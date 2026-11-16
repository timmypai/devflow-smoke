"""Exercise the actual proof, including refusal to certify an already-green base."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class NoProofEvidenceTests(unittest.TestCase):
    def test_actual_http_assertion_proof_and_green_base_rejection(self):
        spec = importlib.util.spec_from_file_location('no_proof_evidence', ROOT / '.devflow/no-proof-evidence.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            with patch.dict(os.environ, {'DEVFLOW_EVIDENCE': str(out), 'GITHUB_SHA': head}):
                with patch.object(sys, 'argv', ['no-proof-evidence.py']):
                    self.assertEqual(module.main(), 0)
                proof = out / 'no-proof'
                record = json.loads((proof / 'NO-PROOF-AC-3.json').read_text())
                self.assertEqual(record['result'], 'PASS')
                self.assertEqual(record['lesson_id'], 'L-0004')
                self.assertEqual((record['base']['exit_code'], record['head']['exit_code']), (1, 0))
                self.assertIn('AssertionError: 4 != 2', (proof / 'base.log').read_text())
                self.assertIn('<failure', (proof / 'base.xml').read_text())
                self.assertEqual(record['base']['test_sha256'], record['head']['test_sha256'])
                # A base that already contains the fix cannot prove a regression.
                with patch.object(module, 'BASE', head), patch.object(sys, 'argv', ['no-proof-evidence.py']):
                    self.assertEqual(module.main(), 1)
                rejected = json.loads((proof / 'NO-PROOF-AC-3.json').read_text())
                self.assertEqual(rejected['result'], 'FAIL')
                self.assertEqual(rejected['base']['outcome'], 'passed')
                self.assertEqual(rejected['head']['outcome'], 'passed')
