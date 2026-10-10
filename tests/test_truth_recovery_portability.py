"""Truth recovery uses installed tools and the published pricing contract."""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/circuit-reverse-rtl/scripts'
sys.path.insert(0, str(SCRIPTS))
from cost.RTL_cost_calculator import load_operator_costs
from verify.tooling import resolve_tool
from verify.truth_parallel import run_one
from verify.truth_yosys import default_yosys, executable


class TruthToolPortability(unittest.TestCase):
    def test_configured_yosys_keeps_symlink_and_rejects_missing_path(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            target = directory / 'tool'
            target.write_text('#!/bin/sh\nexit 0\n')
            target.chmod(0o755)
            alias = directory / 'yosys-alias'
            alias.symlink_to(target)
            with patch.dict(os.environ, {'YOSYS': str(alias)}):
                self.assertEqual(default_yosys(), alias)
                self.assertEqual(executable(alias), alias)
            with patch.dict(os.environ, {'YOSYS': str(directory / 'missing')}):
                with self.assertRaises(ValueError):
                    default_yosys()

    def test_icarus_environment_paths_work_without_path_discovery(self):
        compiler = resolve_tool('IVERILOG')
        runtime = resolve_tool('VVP')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            truth, rtl = directory / 'projection.truth', directory / 'projection.v'
            truth.write_text('10101010\n')
            rtl.write_text('module top(input [2:0] i, output y); assign y=i[0]; endmodule\n')
            with patch.dict(os.environ, {'IVERILOG': str(compiler), 'VVP': str(runtime)}), \
                    patch('verify.truth_parallel.shutil.which', return_value=None):
                result = run_one(truth, rtl, 'i', 'y', 30, 30, workers=2)
            self.assertEqual(result['status'], 'pass', result)
            self.assertEqual(result['vectors'], 8)
            self.assertTrue(result['coverage']['coverage_valid'])

    def test_annotated_and_minimal_cost_csv_have_identical_weights(self):
        published = SCRIPTS / 'cost/syntax_cost.csv'
        with published.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        with tempfile.TemporaryDirectory() as directory:
            annotated = Path(directory) / 'annotated.csv'
            with annotated.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['key', 'cost', 'unit', 'description'])
                writer.writeheader()
                for row in rows:
                    writer.writerow({'key': row['key'], 'cost': row['cost'],
                                     'unit': 'per_operator', 'description': 'Documentation only'})
            self.assertEqual(load_operator_costs(str(published)), load_operator_costs(str(annotated)))


if __name__ == '__main__':
    unittest.main()
