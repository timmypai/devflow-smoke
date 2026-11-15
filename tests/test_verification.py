"""Failure-path orchestration probes; fixture files are NOT browser evidence."""
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from app import Handler

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Path(self.enterContext(tempfile.TemporaryDirectory(dir=ROOT)))
        (self.workspace / '.devflow').mkdir()
        for name in ('verify.sh', 'check-evidence.py'):
            shutil.copy(ROOT / '.devflow' / name, self.workspace / '.devflow' / name)
        shutil.copy(ROOT / 'smoke.py', self.workspace / 'smoke.py')
        self.enterContext(patch.dict(os.environ, DEVFLOW_REVISION=SHA))
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{server.server_port}'

    def verify(self, browser_body, **env):
        browser = self.workspace / '.devflow/playwright.sh'
        browser.write_text('#!/usr/bin/env bash\n' + browser_body)
        browser.chmod(0o755)
        return subprocess.run(['bash', '.devflow/verify.sh'], cwd=self.workspace,
                              env={**os.environ, 'GITHUB_SHA': SHA, 'DEVFLOW_BASE_URL': self.url, **env},
                              text=True, capture_output=True, timeout=10)

    def test_empty_legacy_marker_does_not_reenable_version(self):
        result = self.verify('test "$DEVFLOW_VERSION_ENDPOINT" = "" || exit 99; exit 7\n',
                             DEVFLOW_VERSION_ENDPOINT='')
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        attempt = next((self.workspace / '.devflow/evidence').glob('attempt-*'))
        self.assertNotIn('GET /version', (attempt / 'http.log').read_text())
        self.assertTrue((attempt / 'legacy.txt').exists())

    def test_browser_nonzero_is_fatal_and_retains_failure_evidence(self):
        result = self.verify('echo actual-browser-failure; exit 7\n')
        self.assertNotEqual(result.returncode, 0)
        attempts = list((self.workspace / '.devflow/evidence').glob('attempt-*'))
        self.assertEqual(len(attempts), 1)
        self.assertEqual((attempts[0] / 'exit-code.txt').read_text().strip(), '7')
        self.assertIn('actual-browser-failure', (attempts[0] / 'browser.log').read_text())
        self.assertEqual((attempts[0] / 'source-sha.txt').read_text().strip(), SHA)
        self.assertFalse((attempts[0] / 'result.txt').exists())

    def test_missing_browser_evidence_and_stale_pass_cannot_succeed(self):
        old = self.workspace / '.devflow/evidence/attempt-old'
        old.mkdir(parents=True)
        (old / 'result.txt').write_text('stale PASS')
        for _ in range(2):
            result = self.verify('echo no-real-evidence; exit 0\n')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('missing required evidence', result.stderr)
        attempts = list((self.workspace / '.devflow/evidence').glob('attempt-*'))
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sum((d / 'result.txt').exists() for d in attempts), 1)

    def test_evidence_validator_rejects_skipped_report(self):
        spec = importlib.util.spec_from_file_location('evidence', ROOT / '.devflow/check-evidence.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in ('source-sha.txt', 'expected-revision.txt', 'runner.txt', 'http.log', 'browser.log',
                     'baseline-home.png', 'playwright.json', 'playwright-report/index.html'):
            file = self.workspace / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('unit-test fixture')
        (self.workspace / 'baseline-home.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        (self.workspace / 'playwright.json').write_text(json.dumps({'stats': {
            'expected': 0, 'unexpected': 0, 'skipped': 1, 'flaky': 0}}))
        with self.assertRaisesRegex(ValueError, 'did not pass'):
            module.check(self.workspace)


class WorkflowTests(unittest.TestCase):
    def test_compose_project_accepts_github_uppercase_runner_arch(self):
        script = (ROOT / '.devflow/up.sh').read_text()
        assignment = next(line for line in script.splitlines() if line.startswith('project='))
        for arch in ('X64', 'ARM64'):
            project = subprocess.check_output(['bash', '-eu', '-c', assignment + '; printf %s "$project"'],
                env={**os.environ, 'RUNNER_ARCH': arch, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'},
                text=True)
            self.assertRegex(project, r'^[a-z0-9][a-z0-9_-]+$')

    def test_aggregator_accepts_only_both_success(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        gate = workflow.split('  devflow-ci:', 1)[1]
        self.assertIn('needs: [test, verify]', gate)
        self.assertIn('if: always()', gate)
        command = next(line.split('run: ', 1)[1] for line in gate.splitlines() if 'run: ' in line)
        states = ('success', 'failure', 'cancelled', 'skipped', '')
        for test, verify in itertools.product(states, repeat=2):
            with self.subTest(test=test, verify=verify):
                result = subprocess.run(['bash', '-c', command], env={
                    **os.environ, 'TEST_RESULT': test, 'VERIFY_RESULT': verify})
                self.assertEqual(result.returncode == 0, test == verify == 'success')

    def test_both_workflows_preserve_evidence_on_failure(self):
        for filename in ('ci.yml', 'deploy.yml'):
            content = (ROOT / '.github/workflows' / filename).read_text()
            self.assertIn('run: .devflow/prepare-evidence.sh', content)
            upload = content.split('uses: actions/upload-artifact@v4', 1)[1]
            self.assertIn('if: always()', upload)
            self.assertIn('if-no-files-found: error', upload)
            self.assertIn('path: .devflow/evidence/', upload)
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('runner: [ubuntu-latest, ubuntu-24.04-arm]', ci)
        self.assertIn('run: .devflow/verify.sh', ci)
        self.assertIn('ref: ${{ env.GITHUB_SHA }}', ci)
        self.assertIn('.devflow/container-smoke.sh', ci)
        deploy = (ROOT / '.github/workflows/deploy.yml').read_text()
        self.assertIn("if: github.ref == 'refs/heads/main'", deploy)
        self.assertIn('shell: bash', deploy)
        self.assertIn('runs-on: [self-hosted, Linux, ARM64, devflow, oracle]', deploy)
