#!/usr/bin/env python3
"""Portable checkpoint durability controls over a synthetic full truth domain.

All initial/promoted candidates use the actual configured frontend/replay.
Timeout control bounds the real worker; no synthetic verification PASS is used.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from reverse import recover_truth as recovery
from reverse.refinement_budget import RefinementBudget, budget_path


def arguments(truth, output, candidate=None, **changes):
    values = dict(truth=truth, output=output, candidate=candidate, state_dir=None,
                  budget_seconds=30, max_cost_proposals=None, refinement_seconds=None,
                  max_non_improvements=None, engine_timeout=20, allow_boolean_fallback=False,
                  allowed_syntax=None, cost_csv=SCRIPTS / 'cost/syntax_cost.csv', yosys=None,
                  check_checkpoint=False)
    values.update(changes)
    return argparse.Namespace(**values)


def write_truth(path):
    words = [(x & 3) * (x >> 2) for x in range(16)]
    path.write_text('\n'.join(''.join(str((words[index ^ 15] >> bit) & 1)
                                    for index in range(16)) for bit in range(4)) + '\n')


class ProtectedCheckpointTests(unittest.TestCase):
    def setUp(self):
        # Every recovery/CLI child inherits this, including verification workers.
        environment = patch.dict(os.environ, {'PYTHONDONTWRITEBYTECODE': '1'})
        environment.start()
        self.addCleanup(environment.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.truth, self.output = self.base / 'oracle.truth', self.base / 'final.v'
        write_truth(self.truth)
        self.initial = self.base / 'initial.v'
        self.initial.write_text('module top(input [3:0] x, output [3:0] y); '
                                'assign y=(x[1:0]*x[3:2])+0+0; endmodule\n')
        self.better = self.base / 'better.v'
        self.better.write_text('module top(input [3:0] x, output [3:0] y); '
                               'assign y=x[1:0]*x[3:2]; endmodule\n')
        self.first = recovery.recover(arguments(self.truth, self.output, self.initial))
        self.assertEqual(self.first['status'], 'promoted', self.first)
        self.assertEqual(self.first['verification']['status'], 'pass')
        self.assertEqual(self.first['verification']['vectors'], 16)
        self.assertEqual(self.first['verification']['frontend'], 'pass')
        self.receipt = Path(self.first['selected_checkpoint']['receipt_path'])
        self.first_receipt = Path(self.first['first_checkpoint']['receipt_path'])
        self.assert_sealed()

    def tearDown(self):
        self.temporary.cleanup()

    def assert_sealed(self):
        mode = stat.S_IMODE(self.output.stat().st_mode)
        self.assertEqual(mode & 0o222, 0)
        self.assertTrue(mode & stat.S_IRUSR)

    def final_check(self):
        return recovery.recover(arguments(self.truth, self.output, check_checkpoint=True))

    def assert_rejected_without_work(self):
        with patch.object(recovery, 'execute', side_effect=AssertionError('worker must not start')):
            try:
                result = self.final_check()
            except (OSError, ValueError):
                return
        self.assertNotIn(result['status'], {'checkpoint_validated', 'promoted',
                                           'retained_lower_or_equal_cost'}, result)

    def test_ordinary_copy_blocked_but_verified_atomic_promotion_works(self):
        saved, inode = self.output.read_bytes(), self.output.stat().st_ino
        options = {}
        if os.geteuid() == 0:
            # Root can bypass mode bits; test the intended ordinary user instead.
            self.base.chmod(0o755)
            self.better.chmod(0o644)
            def ordinary_user():
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
            options['preexec_fn'] = ordinary_user
        copied = subprocess.run(['cp', '--', str(self.better), str(self.output)],
                                capture_output=True, text=True, **options)
        self.assertNotEqual(copied.returncode, 0, copied.stderr)
        self.assertEqual(self.output.read_bytes(), saved)
        self.assert_sealed()
        improved = recovery.recover(arguments(self.truth, self.output, self.better))
        self.assertEqual(improved['status'], 'promoted', improved)
        self.assertLess(improved['cost'], self.first['cost'])
        self.assertEqual(improved['verification']['status'], 'pass')
        self.assertEqual(self.output.read_bytes(), self.better.read_bytes())
        self.assertNotEqual(self.output.stat().st_ino, inode)
        self.assertEqual(improved['first_checkpoint'], self.first['first_checkpoint'])
        self.assert_sealed()

    def test_equal_candidate_retains_sealed_source_without_replay(self):
        saved, receipt = self.output.read_bytes(), self.receipt.read_bytes()
        execute = recovery.execute
        def no_replay(command, directory, stem, deadline):
            self.assertEqual(stem, 'cost', 'equal-cost candidate must not enter proof')
            return execute(command, directory, stem, deadline)
        with patch.object(recovery, 'execute', side_effect=no_replay):
            result = recovery.recover(arguments(self.truth, self.output, self.initial))
        self.assertEqual(result['status'], 'retained_lower_or_equal_cost', result)
        self.assertEqual(self.output.read_bytes(), saved)
        self.assertEqual(self.receipt.read_bytes(), receipt)
        self.assert_sealed()

    def test_bad_lower_cost_candidate_never_overwrites_checkpoint(self):
        bad = self.base / 'bad.v'
        bad.write_text('module top(input [3:0] x, output [3:0] y); assign y=0; endmodule\n')
        saved, receipt = self.output.read_bytes(), self.receipt.read_bytes()
        result = recovery.recover(arguments(self.truth, self.output, bad))
        self.assertEqual(result['status'], 'verification_failed', result)
        self.assertEqual(self.output.read_bytes(), saved)
        self.assertEqual(self.receipt.read_bytes(), receipt)
        self.assertEqual(result['refinement_budget']['proposals_started'], 1)
        self.assert_sealed()

    def test_real_worker_timeout_preserves_sealed_checkpoint(self):
        saved, receipt = self.output.read_bytes(), self.receipt.read_bytes()
        execute = recovery.execute
        def bounded(command, directory, stem, deadline):
            return execute(command, directory, stem,
                           min(deadline, time.monotonic() + 0.001) if stem == 'verify' else deadline)
        with patch.object(recovery, 'execute', side_effect=bounded):
            result = recovery.recover(arguments(self.truth, self.output, self.better))
        self.assertEqual(result['status'], 'budget_exhausted', result)
        self.assertEqual(result['refinement_budget']['proposals_started'], 1)
        self.assertEqual(self.output.read_bytes(), saved)
        self.assertEqual(self.receipt.read_bytes(), receipt)
        self.assert_sealed()

    def test_final_check_reseals_without_workers_proposals_or_budget_reset(self):
        # An owner can chmod; a valid final check should restore protection only.
        self.output.chmod(0o644)
        saved = {p: p.read_bytes() for p in (self.output, self.receipt, self.first_receipt,
                                            budget_path(self.output))}
        attempts = set(self.receipt.parent.glob('attempt_*'))
        with (patch.object(recovery, 'execute', side_effect=AssertionError('no worker')),
              patch.object(RefinementBudget, 'reserve', side_effect=AssertionError('no proposal'))):
            result = self.final_check()
        self.assertEqual(result['status'], 'checkpoint_validated', result)
        self.assertEqual(result['selected_checkpoint']['candidate_sha256'], recovery.sha(self.output))
        for path, value in saved.items():
            self.assertEqual(path.read_bytes(), value)
        self.assertEqual(set(self.receipt.parent.glob('attempt_*')), attempts)
        self.assert_sealed()

    def test_truth_and_checker_context_changes_are_refused(self):
        original = self.truth.read_text()
        self.truth.write_text(('1' if original[0] == '0' else '0') + original[1:])
        self.assert_rejected_without_work()
        self.truth.write_text(original)
        context = recovery.verification_context(None)
        context = {**context, 'checkpoint_test_context_mutation': True}
        with patch.object(recovery, 'verification_context', return_value=context):
            self.assert_rejected_without_work()
        self.assert_sealed()

    def test_source_and_best_receipt_tampering_are_refused(self):
        saved = self.output.read_bytes()
        self.output.chmod(0o644)
        self.output.write_bytes(saved + b'// tampered bytes\n')
        changed = self.output.read_bytes()
        self.assert_rejected_without_work()
        self.assertEqual(self.output.read_bytes(), changed, 'must not silently restore bytes')
        self.output.write_bytes(saved)
        self.output.chmod(0o444)
        receipt = json.loads(self.receipt.read_text())
        receipt['verification']['vectors'] = 15
        self.receipt.write_text(json.dumps(receipt))
        self.assert_rejected_without_work()
        self.assertEqual(self.output.read_bytes(), saved)

    def test_first_receipt_and_budget_history_tampering_are_refused(self):
        first = self.first_receipt.read_bytes()
        self.first_receipt.write_bytes(first + b'\n')
        self.assert_rejected_without_work()
        self.first_receipt.write_bytes(first)
        journal = json.loads(budget_path(self.output).read_text())
        journal['proposals_started'] = 1
        budget_path(self.output).write_text(json.dumps(journal))
        self.assert_rejected_without_work()
        self.assert_sealed()

    def test_unresolved_pending_is_not_repaired_by_final_check(self):
        pending = self.receipt.parent / 'pending.json'
        pending.write_bytes(self.receipt.read_bytes())
        saved = {p: p.read_bytes() for p in (pending, self.receipt, self.output, budget_path(self.output))}
        with patch.object(recovery, 'execute', side_effect=AssertionError('no worker')):
            result = self.final_check()
        self.assertEqual(result['status'], 'checkpoint_recovery_required', result)
        for path, value in saved.items():
            self.assertEqual(path.read_bytes(), value)
        self.assert_sealed()

    def test_cli_check_rejects_candidate_or_worker_combination(self):
        for extra in (['--candidate', str(self.better)], ['--worker', 'infer']):
            result = subprocess.run([sys.executable, '-B', str(recovery.__file__),
                                     str(self.truth), str(self.output), '--check-checkpoint', *extra],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
        self.assert_sealed()

    def test_missing_final_or_checkpoint_cannot_be_created_by_check(self):
        self.output.unlink()
        self.assert_rejected_without_work()
        self.assertFalse(self.output.exists())
        fresh = self.base / 'fresh.v'
        with patch.object(recovery, 'execute', side_effect=AssertionError('no worker')):
            try:
                result = recovery.recover(arguments(self.truth, fresh, check_checkpoint=True))
            except (OSError, ValueError):
                result = {'status': 'error'}
        self.assertNotEqual(result['status'], 'checkpoint_validated')
        self.assertFalse(fresh.exists())
        self.assertFalse(budget_path(fresh).exists())


if __name__ == '__main__':
    unittest.main()
