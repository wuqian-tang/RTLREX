"""Portable tool selection must honor explicit choices and fail closed."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/circuit-reverse-rtl/scripts"))
from verify.tooling import artifact_path, resolve_tool


class ToolDiscovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = {}
        for label in ["explicit", "environment", "configured", "bin"]:
            folder = self.root / label
            folder.mkdir()
            exe = folder / "yosys"
            exe.write_text("#!/bin/sh\nexit 0\n")
            exe.chmod(0o755)
            self.paths[label] = exe

    def tearDown(self):
        self.temp.cleanup()

    def test_explicit_environment_config_and_path_precedence(self):
        with patch.dict(os.environ, {"PATH": str(self.paths["bin"].parent)}, clear=True):
            self.assertEqual(resolve_tool("YOSYS"), self.paths["bin"])
            config = {"YOSYS": str(self.paths["configured"])}
            self.assertEqual(resolve_tool("YOSYS", config=config), self.paths["configured"])
            os.environ["YOSYS"] = str(self.paths["environment"])
            self.assertEqual(resolve_tool("YOSYS", config=config), self.paths["environment"])
            self.assertEqual(resolve_tool("YOSYS", explicit=self.paths["explicit"], config=config),
                             self.paths["explicit"])

    def test_invalid_explicit_and_environment_do_not_fall_back(self):
        with patch.dict(os.environ, {"PATH": str(self.paths["bin"].parent)}, clear=True):
            with self.assertRaises(ValueError):
                resolve_tool("YOSYS", explicit=self.root / "missing")
            os.environ["YOSYS"] = str(self.root / "missing")
            with self.assertRaises(ValueError):
                resolve_tool("YOSYS")

    def test_config_relative_to_config_file(self):
        with patch.dict(os.environ, {"PATH": ""}, clear=True):
            actual = resolve_tool("YOSYS", config={"YOSYS": "./configured/yosys"},
                                  config_path=self.root / "tools.env")
            self.assertEqual(actual, self.paths["configured"])

    def test_abc_distribution_alias(self):
        abc = self.paths["bin"].with_name("berkeley-abc")
        abc.write_text("#!/bin/sh\nexit 0\n")
        abc.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(abc.parent)}, clear=True):
            self.assertEqual(resolve_tool("ABC"), abc)

    def test_explicit_symlink_name_preserved(self):
        alias = self.root / "yosys-alias"
        alias.symlink_to(self.paths["explicit"])
        self.assertEqual(resolve_tool("YOSYS", explicit=alias), alias)

    def test_artifacts_use_explicit_base(self):
        self.assertEqual(artifact_path("proof/result.json", self.root),
                         self.root / "proof/result.json")


if __name__ == "__main__":
    unittest.main()
