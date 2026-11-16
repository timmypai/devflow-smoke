"""Execute the historical-proof CI step; do not replace the evidence script."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_BASE = 'c7bf3287a5231e12b15dca45a9f6ff9eaeda32a7'
FIXED_BASE = 'c18fbe0cf7820078aea601b556d2dc5db8491d12'


def proof_step():
    ci = (ROOT / '.github/workflows/ci.yml').read_text()
    step = ci.split('      - name: retain NO-PROOF-AC-3', 1)[1].split('      - ', 1)[0]
    condition = re.search(r'^        if: (.+)$', step, re.M).group(1)
    run = step.split('        run: ', 1)[1]
    command = textwrap.dedent(run[2:]) if run.startswith('|\n') else run.strip()
    return condition, command


class NoProofScopeTests(unittest.TestCase):
    def run_step(self, base, out, source=None):
        _, command = proof_step()
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', command], cwd=ROOT,
            env={**os.environ, 'PR_BASE_SHA': base, 'SOURCE_SHA': source or head,
                 'DEVFLOW_EVIDENCE': str(out)}, capture_output=True, text=True, timeout=30)

    def test_other_base_skips_historical_proof_without_pass_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = self.run_step(FIXED_BASE, temporary)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn('SKIP', proc.stdout)
            self.assertIn('actual=' + FIXED_BASE, proc.stdout)
            self.assertIn('expected=' + ORIGINAL_BASE, proc.stdout)
            self.assertNotIn('PASS', proc.stdout)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_original_base_executes_real_http_assertion_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = self.run_step(ORIGINAL_BASE, temporary)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotIn('SKIP', proc.stdout)
            out = Path(temporary) / 'no-proof'
            proof = json.loads((out / 'NO-PROOF-AC-3.json').read_text())
            self.assertEqual(proof['result'], 'PASS')
            self.assertEqual(proof['base_sha'], ORIGINAL_BASE)
            self.assertEqual(proof['base']['outcome'], 'failure')
            self.assertEqual(proof['base']['exit_code'], 1)
            self.assertIn('AssertionError: 4 != 2', (out / 'base.log').read_text())
            self.assertEqual(proof['head']['outcome'], 'passed')
            self.assertEqual(proof['head']['exit_code'], 0)
            self.assertEqual(proof['base']['test_sha256'], proof['head']['test_sha256'])

    def test_real_evidence_failure_propagates_to_ci_step(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = self.run_step(ORIGINAL_BASE, temporary, source=ORIGINAL_BASE)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('checkout/source SHA mismatch', proc.stderr)
            self.assertNotIn('SKIP', proc.stdout)
            self.assertNotIn('PASS', proc.stdout)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_non_pr_events_excluded_by_workflow_condition(self):
        condition, _ = proof_step()
        # GitHub owns expression evaluation. Pin the guard, not a fake Actions runner.
        self.assertEqual(condition, "github.event_name == 'pull_request'")
