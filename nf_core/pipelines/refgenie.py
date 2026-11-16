"""
Update a nextflow.config file with refgenie genomes
"""

import logging
import os
import re
from pathlib import Path
from textwrap import dedent

import rich
import rich.traceback
import yaml

import nf_core.utils

# Set up logging
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# # Setup rich traceback
stderr = rich.console.Console(stderr=True, force_terminal=nf_core.utils.rich_force_colors())
rich.traceback.install(console=stderr, width=200, word_wrap=True, extra_lines=1)

NF_CFG_TEMPLATE = """
// This is a read-only config file managed by refgenie. Manual changes to this file will be overwritten
// To make changes here, use refgenie to update the reference genome data
params {{
  genomes {{
{content}
  }}
}}
"""

# Name of the refgenie plugin entry point in pyproject.toml.
# Refgenie stores this plugin's settings under the same name.
PLUGIN_NAME = "nf-core-refgenie"


def _print_nf_config(rg):
    """
    Generate a nextflow config file with the genomes
    from the local refgenie database
    Adapted from: https://github.com/refgenie/refgenie_nfcore

    Takes a refgenie.Refgenie object as argument
    """
    # Imported here, so that importing this module does not require refgenie
    from refgenie.exceptions import RefgenieError
    from refgenie.models import AssetRegistryPathComponents

    paths = rg.paths()
    genomes_str = ""
    alias_translations = _get_alias_translation_file(rg)
    # Genome aliases, and the asset groups that have a default asset
    for genome in paths:
        genomes_str += f"    '{genome}' {{\n"
        for asset in paths[genome]:
            try:
                pth = rg.asset.seek_components(AssetRegistryPathComponents(genome=genome, asset_group=asset))
            except RefgenieError:
                log.warning(f"{genome}/{asset} is incomplete, ignoring...")
            else:
                # Translate an alias name to the alias used in the pipeline
                if asset in alias_translations:
                    log.info(f"Translating refgenie asset alias {asset} to {alias_translations[asset]}.")
                    asset = alias_translations[asset]
                genomes_str += f'      {asset.ljust(20, " ")} = "{pth}"\n'
        genomes_str += "    }\n"

    return NF_CFG_TEMPLATE.format(content=genomes_str)


def _update_nextflow_home_config(refgenie_genomes_config_file, nxf_home):
    """
    Update the $NXF_HOME/config file by adding a includeConfig statement to it
    for the 'refgenie_genomes_config_file' if not already defined
    """
    # Check if NXF_HOME/config exists and has a
    refgenie_config_path = Path(refgenie_genomes_config_file).resolve()
    include_config_string = dedent(
        f"""
        ///// >>> nf-core + RefGenie >>> /////
        // !! Contents within this block are managed by 'nf-core/tools' !!
        // Includes auto-generated config file with RefGenie genome assets
        includeConfig '{refgenie_config_path}'
        ///// <<< nf-core + RefGenie <<< /////
        """
    )
    nxf_home_config = Path(nxf_home) / "config"
    if nxf_home_config.exists():
        # look for include statement in config
        has_include_statement = False
        with open(nxf_home_config) as fh:
            lines = fh.readlines()
            for line in lines:
                if re.match(rf"\s*includeConfig\s*'{re.escape(str(refgenie_config_path))}'", line):
                    has_include_statement = True
                    break

        # if include statement is missing, add it to the last line
        if not has_include_statement:
            with open(nxf_home_config, "a") as fh:
                fh.write(include_config_string)

            log.info(f"Included refgenie_genomes.config to {nxf_home_config}")

    else:
        # create new config and add include statement
        with open(nxf_home_config, "w") as fh:
            fh.write(include_config_string)
            log.info(f"Created new nextflow config file: {nxf_home_config}")


def _get_alias_translation_file(rg):
    """
    Read a file containing alias translations.

    Alias translation file should be located in the refgenie genome folder
    (by default `~/.refgenie/genomes`).
    Alias translation file should be named `alias_translations.yaml`

    Input file contains the name of refgenie asset groups as keys and the name of the respective nf-core pipeline aliases as values.
    Such as:
    ensembl_gtf: gtf
    star_index: star
    """
    translations = {}

    try:
        with open(Path(rg.genome_folder) / "alias_translations.yaml") as yaml_file:
            translations = yaml.load(yaml_file, Loader=yaml.Loader)
    except FileNotFoundError:
        pass

    return translations


def update_config(rg, event=None):
    """
    Update the genomes.config file after a local refgenie database has been updated

    Refgenie (1.0 or later) runs this function as a 'post_update' plugin after any command
    that changes local assets, such as 'refgenie pull <genome>/<asset>'.
    The local refgenie assets are transformed into a nextflow.config file, which is used to
    overwrite the 'refgenie_genomes.config' file.
    The path to the target  config file is inferred from the following options, in order:

    - the 'nextflow_config' plugin setting, set with:
      refgenie plugins set nf-core-refgenie nextflow_config=/path/to/refgenie_genomes.config
    - the NXF_REFGENIE_PATH environment variable
    - otherwise defaults to: $NXF_HOME/nf-core/refgenie_genomes.config

    Additionally, an 'includeConfig' statement is added to the file $NXF_HOME/config
    """

    # refgenie < 1.0 calls plugins with one argument and does not catch their errors
    if event is None:
        log.warning("The nf-core refgenie integration needs refgenie 1.0 or later. Not updating the genomes config.")
        return False

    # Compile nextflow refgenie_genomes.config from the local refgenie assets
    refgenie_genomes = _print_nf_config(rg)

    # Get the path to NXF_HOME
    # If NXF_HOME is not set, create it at $HOME/.nextflow
    # If $HOME is not set, set nxf_home to false
    nxf_home = os.environ.get("NXF_HOME")
    if not nxf_home:
        try:
            nxf_home = Path.home() / ".nextflow"
            if not nxf_home.exists():
                log.info(f"Creating NXF_HOME directory at {nxf_home}")
                nxf_home.mkdir(parents=True, exist_ok=True)
        except RuntimeError:
            nxf_home = False

    # Get the path for storing the updated refgenie_genomes.config
    plugin_settings = rg.plugins.settings(PLUGIN_NAME)
    if "nextflow_config" in plugin_settings:
        refgenie_genomes_config_file = plugin_settings["nextflow_config"]
    elif "NXF_REFGENIE_PATH" in os.environ:
        refgenie_genomes_config_file = os.environ.get("NXF_REFGENIE_PATH")
    elif nxf_home:
        refgenie_genomes_config_file = Path(nxf_home) / "nf-core/refgenie_genomes.config"
    else:
        log.info("Could not determine path to 'refgenie_genomes.config' file.")
        return False

    if refgenie_genomes_config_file is None:
        log.info("Could not determine path to 'refgenie_genomes.config' file.")
        return False

    # Save the updated genome config
    try:
        with open(refgenie_genomes_config_file, "w+") as fh:
            fh.write(refgenie_genomes)
        log.info(f"Updated nf-core genomes config: {refgenie_genomes_config_file}")
    except FileNotFoundError:
        log.info(f"Could not write to {refgenie_genomes_config_file}")
        return False

    # Add include statement to NXF_HOME/config
    if nxf_home:
        _update_nextflow_home_config(refgenie_genomes_config_file, nxf_home)

    return True
