"""Reject altered or misclassified terminal RTL in a publication export."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

class PublishedArtifactsTests(unittest.TestCase):
    def load_checker(self):
        path = ROOT / 'experiments/tt100-final/check_artifacts.py'
        self.assertTrue(path.is_file(), 'artifact checker must be provided')
        spec = importlib.util.spec_from_file_location('publication_artifact_check', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self, root):
        (root / 'candidate.v').write_text('module top(input x, output y); assign y=x; endmodule\n')
        (root / 'prompt.txt').write_text('Recover the supplied function.\n')
        row = dict(case='ex200', arm='with_skill', candidate='candidate.v',
                   candidate_sha256=sha(root/'candidate.v'), receipt='receipt.json',
                   input_sha256='a'*64, V=True, H=True, Q=1,
                   prompt='prompt.txt', prompt_sha256=sha(root/'prompt.txt'))
        receipt = dict(case=row['case'], arm=row['arm'], input_sha256=row['input_sha256'],
                       candidate_sha256=row['candidate_sha256'], terminal_candidate_available=True,
                       published_V=True, published_H=True, published_Q=1,
                       prompt_sha256=row['prompt_sha256'], evaluation_target_is_terminal=True)
        (root/'receipt.json').write_text(json.dumps(receipt))
        row['receipt_sha256']=sha(root/'receipt.json')
        pub=dict(case=row['case'],arm=row['arm'],input_sha256=row['input_sha256'],candidate_sha256=row['candidate_sha256'],V='True',H='True',syntax_cost='1')
        return row,pub

    def test_preserves_published_terminal(self):
        checker=self.load_checker()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);row,pub=self.fixture(root)
            checker.check_record(root,row,pub)

    def test_rejects_modified_rtl(self):
        checker=self.load_checker()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);row,pub=self.fixture(root)
            (root/'candidate.v').write_text('incorrect replacement')
            with self.assertRaises(ValueError):checker.check_record(root,row,pub)

    def test_cannot_promote_diagnostic_to_terminal(self):
        checker=self.load_checker()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);row,pub=self.fixture(root)
            pub.update(candidate_sha256='',V='False',H='False',syntax_cost='')
            with self.assertRaises(ValueError):checker.check_record(root,row,pub)

    def test_rejects_swapped_receipt(self):
        checker=self.load_checker()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);row,pub=self.fixture(root)
            receipt=json.loads((root/'receipt.json').read_text());receipt['case']='ex201'
            (root/'receipt.json').write_text(json.dumps(receipt));row['receipt_sha256']=sha(root/'receipt.json')
            with self.assertRaises(ValueError):checker.check_record(root,row,pub)

    def test_rejects_unlisted_terminal(self):
        checker=self.load_checker()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'ex200.v').write_text('published')
            checker.check_inventory(root, {'ex200.v'})
            (root/'ex208.v').write_text('diagnostic only')
            with self.assertRaises(ValueError):
                checker.check_inventory(root, {'ex200.v'})
