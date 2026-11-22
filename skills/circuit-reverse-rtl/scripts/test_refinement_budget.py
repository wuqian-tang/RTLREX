#!/usr/bin/env python3
"""Durable refinement limits, with actual fixed-frontend checkpoint controls."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from reverse import recover_truth as recovery
from reverse.refinement_budget import RefinementBudget, budget_path
from test_fixed_point_compact import write_words


def args(truth, output, candidate=None, **kwargs):
    values = dict(truth=truth, output=output, candidate=candidate, state_dir=None,
                  budget_seconds=30, max_cost_proposals=None, refinement_seconds=None,
                  max_non_improvements=None, engine_timeout=20, allow_boolean_fallback=False,
                  allowed_syntax=None, cost_csv=SCRIPTS/'cost/syntax_cost.csv', yosys=None)
    values.update(kwargs)
    return argparse.Namespace(**values)


class CheckpointControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def initial(self, n=12, **kwargs):
        h=n//2; mask=(1<<h)-1
        truth=self.base/'oracle.truth'; output=self.base/'final.v'; first=self.base/'initial.v'
        write_words(truth,n,n,[(x&mask)*(x>>h) for x in range(1<<n)])
        first.write_text(f'module top(input [{n-1}:0] x, output [{n-1}:0] y); assign y = (x[{h-1}:0] * x[{n-1}:{h}]) + 0 + 0; endmodule\n')
        result=recovery.recover(args(truth,output,first,**kwargs))
        self.assertEqual(result['status'],'promoted',result)
        self.assertEqual(result['verification']['status'],'pass')
        self.assertEqual(result['verification']['verification_method'],'complete-domain interleaved Icarus Verilog replay')
        self.assertEqual(result['verification']['interleaved_replay']['workers'],1 if n<12 else 4)
        return truth,output,result

    def test_parallel_cross_call_improvement_and_proposal_limit(self):
        truth,output,first=self.initial()
        proposal=self.base/'better.v'
        proposal.write_text('module top(input [11:0] x, output [11:0] y); assign y=x[5:0]*x[11:6]; endmodule\n')
        better=recovery.recover(args(truth,output,proposal))
        self.assertEqual(better['status'],'promoted',better)
        self.assertLess(better['cost'],first['cost'])
        self.assertEqual(better['first_checkpoint'],first['first_checkpoint'])
        self.assertEqual(better['verification']['interleaved_replay']['workers'],4)
        selected=output.read_bytes(); receipt=Path(better['selected_checkpoint']['receipt_path']).read_bytes()
        repeated=recovery.recover(args(truth,output,proposal))
        self.assertEqual(repeated['status'],'retained_lower_or_equal_cost',repeated)
        # Changing state directories with copied, intact receipts cannot reset
        # the canonical output-bound counter.
        alt=self.base/'alternative_state'; alt.mkdir()
        shutil.copyfile(better['selected_checkpoint']['receipt_path'],alt/'best.json')
        with patch.object(recovery,'execute',side_effect=AssertionError('expensive work started')):
            rejected=recovery.recover(args(truth,output,proposal,state_dir=alt))
        self.assertEqual(rejected['reason'],'proposal_limit')
        self.assertEqual(rejected['refinement_budget']['proposals_started'],2)
        self.assertEqual(output.read_bytes(),selected)
        self.assertEqual(Path(better['selected_checkpoint']['receipt_path']).read_bytes(),receipt)

    def test_small_domain_failed_proposals_preserve_best(self):
        truth,output,first=self.initial(4)
        saved=output.read_bytes(); proposal=self.base/'bad.v'
        proposal.write_text('module top(input [3:0] x, output [3:0] y); assign y=0; endmodule\n')
        failed=recovery.recover(args(truth,output,proposal))
        self.assertEqual(failed['status'],'verification_failed',failed)
        failed2=recovery.recover(args(truth,output,proposal))
        self.assertEqual(failed2['refinement_budget']['consecutive_non_improvements'],2)
        rejected=recovery.recover(args(truth,output,proposal))
        self.assertEqual(rejected['status'],'refinement_limit_reached')
        self.assertEqual(output.read_bytes(),saved)
        self.assertEqual(rejected['first_checkpoint'],first['first_checkpoint'])

    def test_missing_candidate_counts_and_missing_journal_fails_closed(self):
        truth,output,first=self.initial(4)
        with self.assertRaises(FileNotFoundError):
            recovery.recover(args(truth,output,self.base/'missing.v'))
        journal=json.loads(budget_path(output).read_text())
        self.assertEqual(journal['proposals_started'],1)
        self.assertEqual(journal['events'][0]['status'],'attempt_exception')
        saved=output.read_bytes(); budget_path(output).unlink()
        with self.assertRaisesRegex(ValueError,'budget is missing'):
            recovery.recover(args(truth,output))
        self.assertEqual(output.read_bytes(),saved)

    def test_interrupted_reservation_and_pending_parallel_promotion_repair(self):
        truth,output,first=self.initial()
        state=Path(first['selected_checkpoint']['receipt_path']).parent
        receipt=json.loads((state/'best.json').read_text())
        metadata=receipt['first_checkpoint']; first_receipt=json.loads(Path(metadata['receipt_path']).read_text())
        anchor=RefinementBudget.anchor_for(output,first_receipt,Path(metadata['receipt_path']))
        budget=RefinementBudget(budget_path(output),anchor,recovery.atomic_json,args(truth,output))
        budget.load(); budget.reserve(receipt,time.monotonic()+10)
        # Simulate a killed refinement before any promotion: the next call
        # consumes the orphan and can only reserve the remaining proposal.
        again=recovery.recover(args(truth,output,self.base/'initial.v'))
        self.assertEqual(again['status'],'retained_lower_or_equal_cost',again)
        self.assertEqual(again['refinement_budget']['events'][0]['status'],'interrupted')
        # Genuine pending journal repair must still bind all four partitions.
        recovery.atomic_json(state/'pending.json',receipt)
        (state/'best.json').unlink()
        final=recovery.recover(args(truth,output,self.base/'initial.v'))
        self.assertEqual(final['status'],'refinement_limit_reached',final)
        self.assertTrue((state/'best.json').is_file())
        self.assertFalse((state/'pending.json').exists())

    def test_native_verifier_timeout_counts_without_overwriting_best(self):
        truth,output,first=self.initial()
        saved=output.read_bytes(); proposal=self.base/'better.v'
        proposal.write_text('module top(input [11:0] x, output [11:0] y); assign y=x[5:0]*x[11:6]; endmodule\n')
        original_execute=recovery.execute
        def run(command,directory,stem,deadline):
            if stem=='cost':
                return {'status':'completed','returncode':0,'value':[{'cost':0}]}
            # This launches the real native proof worker in a process group,
            # then forces its outer deadline; there is no synthetic PASS.
            return original_execute(command,directory,stem,min(deadline,time.monotonic()+0.001))
        with patch.object(recovery,'execute',side_effect=run):
            failed=recovery.recover(args(truth,output,proposal))
        self.assertEqual(failed['status'],'budget_exhausted',failed)
        self.assertEqual(failed['refinement_budget']['proposals_started'],1)
        self.assertEqual(failed['refinement_budget']['consecutive_non_improvements'],1)
        self.assertEqual(output.read_bytes(),saved)

    def test_shrunken_policy_and_elapsed_window_reject_before_work(self):
        truth,output,_=self.initial(4,refinement_seconds=0)
        with patch.object(recovery,'execute',side_effect=AssertionError('expensive work started')):
            rejected=recovery.recover(args(truth,output))
        self.assertEqual(rejected['reason'],'refinement_time_limit')
        with self.assertRaisesRegex(ValueError,'cannot be changed'):
            recovery.recover(args(truth,output,refinement_seconds=120))

    def test_brief_report_keeps_receipts_and_checkpoint_hashes(self):
        truth,output,result=self.initial(4)
        selected=Path(result['selected_checkpoint']['receipt_path'])
        first=Path(result['first_checkpoint']['receipt_path'])
        hashes=(recovery.sha(output),recovery.sha(selected),recovery.sha(first))
        original=json.dumps(result,sort_keys=True)
        brief=recovery.brief_report(result)
        self.assertEqual(json.dumps(result,sort_keys=True),original)
        self.assertEqual((recovery.sha(output),recovery.sha(selected),recovery.sha(first)),hashes)
        self.assertEqual(brief['first_checkpoint'],result['first_checkpoint'])
        self.assertEqual(brief['selected_checkpoint']['receipt_sha256'],hashes[1])
        self.assertNotIn('verification_context',brief)
        self.assertNotIn('interleaved_replay',brief['verification'])
        self.assertEqual(brief['verification']['replay_workers'],1)
        self.assertLess(len(json.dumps(brief)),len(original)/3)
        full=json.loads(Path(brief['report_path']).read_text())
        self.assertEqual(full['verification']['vectors'],16)
        self.assertIn('interleaved_replay',full['verification'])

    def test_policy_and_timestamp_changes_cannot_contradict_first_receipt(self):
        truth,output,_=self.initial(4,max_cost_proposals=0,refinement_seconds=1)
        original=json.loads(budget_path(output).read_text())
        changed=json.loads(json.dumps(original))
        changed['policy'].update(max_proposals=2,refinement_seconds=120)
        changed['refinement_deadline_wall_ns']=changed['published_wall_ns']+120_000_000_000
        recovery.atomic_json(budget_path(output),changed)
        with self.assertRaisesRegex(ValueError,'contradicts the first checkpoint'):
            recovery.recover(args(truth,output))
        shifted=json.loads(json.dumps(original))
        for key in ('published_wall_ns','refinement_deadline_wall_ns','last_seen_wall_ns'):
            shifted[key]+=100_000_000_000
        recovery.atomic_json(budget_path(output),shifted)
        with self.assertRaisesRegex(ValueError,'contradicts the first checkpoint'):
            recovery.recover(args(truth,output))

    def test_tampered_counter_history_fails_closed(self):
        truth,output,_=self.initial(4)
        value=json.loads(budget_path(output).read_text())
        value['proposals_started']=1
        recovery.atomic_json(budget_path(output),value)
        with self.assertRaisesRegex(ValueError,'history is incomplete'):
            recovery.recover(args(truth,output))


if __name__=='__main__':
    unittest.main()
