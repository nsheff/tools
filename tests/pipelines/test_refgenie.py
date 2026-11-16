"""Tests covering the refgenie integration code"""

import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from nf_core.pipelines.refgenie import update_config


class TestRefgenie(unittest.TestCase):
    """Class for refgenie tests"""

    def setUp(self):
        """
        Prepare a refgenie database
        """
        self.tmp_dir = Path(tempfile.TemporaryDirectory().name)
        self.NXF_HOME = self.tmp_dir / ".nextflow"
        self.NXF_REFGENIE_PATH = self.NXF_HOME / "nf-core" / "refgenie_genomes.config"
        self.REFGENIE_HOME_PATH = self.tmp_dir / "refgenie"
        self.translation_file = self.REFGENIE_HOME_PATH / "genomes" / "alias_translations.yaml"

        # Run refgenie with its home and NXF_HOME in the current tmpdir
        # avoids adding includeConfig statement to config file outside the current tmpdir
        self.env = dict(os.environ, NXF_HOME=str(self.NXF_HOME), REFGENIE_HOME_PATH=str(self.REFGENIE_HOME_PATH))
        self.env.pop("REFGENIE", None)

        # create NXF_HOME and nf-core directories
        nf_core_dir = self.NXF_HOME / "nf-core"
        nf_core_dir.mkdir(parents=True, exist_ok=True)

        # Initialize a refgenie database
        self.refgenie("init")

        # Set the nextflow config path for the nf-core refgenie plugin
        self.refgenie(f"plugins set nf-core-refgenie nextflow_config={self.NXF_REFGENIE_PATH}")

        # Add an alias translation to YAML file
        with open(self.translation_file, "a") as fh:
            fh.write("bwa_index: bwa\n")

    def refgenie(self, args):
        """Run a refgenie command"""
        return subprocess.check_output(["refgenie", *shlex.split(args)], stderr=subprocess.STDOUT, env=self.env)

    def test_update_refgenie_genomes_config(self):
        """Test that pulling an asset updates the genomes config"""
        # Populate the config with a genome
        self.refgenie("pull rCRSd/fasta")

        out = self.NXF_REFGENIE_PATH.read_text()
        assert "'rCRSd' {" in out
        assert "      fasta                = " in out
        assert f"includeConfig '{self.NXF_REFGENIE_PATH}'" in (self.NXF_HOME / "config").read_text()

    def test_asset_alias_translation(self):
        """Test that asset aliases are translated correctly"""
        # Populate the config with a genome
        self.refgenie("pull rCRSd/bwa_index")
        out = self.NXF_REFGENIE_PATH.read_text()
        assert "      bwa                  = " in out
        assert "      bwa_index            = " not in out


def test_legacy_refgenie_is_skipped():
    """Test that refgenie < 1.0, which calls the plugin with one argument, does not fail"""
    assert update_config(object()) is False
