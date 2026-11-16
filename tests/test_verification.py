"""Failure-path orchestration probes; fixture files are NOT browser evidence."""
import importlib.util
import base64
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import Handler, Server

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
        class VerificationHandler(Handler):
            legacy = False

            def do_GET(self):
                if self.legacy and self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(b'hello devflow')
                elif self.legacy and self.path in ('/stats', '/version'):
                    self.send_error(404)
                else:
                    super().do_GET()

        self.handler = VerificationHandler
        server = Server(('127.0.0.1', 0), VerificationHandler)
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

    def test_candidate_cannot_disable_stats_or_version(self):
        for env in ({'DEVFLOW_STATS_ENDPOINT': ''}, {'DEVFLOW_VERSION_ENDPOINT': ''},
                    {'DEVFLOW_STATS_ENDPOINT': 'unknown'}):
            result = self.verify('echo browser-must-not-run; exit 99\n', **env)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('browser-must-not-run', result.stdout)

    def test_empty_legacy_marker_does_not_reenable_version(self):
        self.handler.legacy = True
        result = self.verify('test "$DEVFLOW_VERSION_ENDPOINT" = "" || exit 99; exit 7\n',
                             DEVFLOW_VERSION_ENDPOINT='', DEVFLOW_STATS_ENDPOINT='',
                             DEVFLOW_VERIFY_PHASE='rollback')
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        attempt = next((self.workspace / '.devflow/evidence').glob('attempt-*'))
        self.assertNotIn('GET /version', (attempt / 'http.log').read_text())
        self.assertNotIn('GET /stats', (attempt / 'http.log').read_text())
        self.assertIn('AC-1/AC-2 NOT verified', (attempt / 'legacy.txt').read_text())
        self.assertEqual((attempt / 'phase.txt').read_text().strip(), 'rollback')

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

    def test_evidence_validator_rejects_missing_evidence(self):
        spec = importlib.util.spec_from_file_location('evidence', ROOT / '.devflow/check-evidence.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Deliberately incomplete evidence must be rejected, never used as proof.
        (self.workspace / 'contract.txt').write_text('stats')
        with self.assertRaisesRegex(ValueError, 'missing required evidence'):
            module.check(self.workspace)

    def test_evidence_validator_rejects_skipped_report(self):
        spec = importlib.util.spec_from_file_location('evidence', ROOT / '.devflow/check-evidence.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Unit-test fixtures only; never uploaded or reported as browser evidence.
        for name in ('source-sha.txt', 'expected-revision.txt', 'runner.txt', 'phase.txt', 'http.log',
                     'browser.log', 'AC-1.log', 'AC-2.log', 'AC-2-http-dom.json',
                     'playwright.json', 'playwright-report/index.html', 'journeys.log'):
            file = self.workspace / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('unit-test fixture')
        for name in ('source-sha.txt', 'expected-revision.txt'):
            (self.workspace / name).write_text(SHA)
        (self.workspace / 'phase.txt').write_text('candidate')
        (self.workspace / 'contract.txt').write_text('stats')
        (self.workspace / 'AC-2.png').write_bytes(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1cAAAAASUVORK5CYII='))
        for stats in ({'expected': 0, 'unexpected': 0, 'skipped': 1, 'flaky': 0},
                      {'expected': 0, 'unexpected': 1, 'skipped': 0, 'flaky': 0},
                      {'expected': 1, 'unexpected': 0, 'skipped': 0, 'flaky': 1}):
            with self.subTest(stats=stats):
                (self.workspace / 'playwright.json').write_text(json.dumps({'stats': stats}))
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

    def test_aggregator_accepts_only_all_success(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        gate = workflow.split('  devflow-ci:', 1)[1]
        self.assertIn('needs: [check, test, verify]', gate)
        self.assertIn('if: always()', gate)
        command = next(line.split('run: ', 1)[1] for line in gate.splitlines() if 'run: ' in line)
        states = ('success', 'failure', 'cancelled', 'skipped', '')
        for check, test, verify in itertools.product(states, repeat=3):
            with self.subTest(check=check, test=test, verify=verify):
                result = subprocess.run(['bash', '-c', command], env={
                    **os.environ, 'CHECK_RESULT': check, 'TEST_RESULT': test, 'VERIFY_RESULT': verify})
                self.assertEqual(result.returncode == 0, check == test == verify == 'success')

    def test_both_workflows_preserve_evidence_on_failure(self):
        for filename in ('ci.yml', 'deploy.yml'):
            content = (ROOT / '.github/workflows' / filename).read_text()
            self.assertIn('.devflow/prepare-evidence.sh', content)
            upload = content.split('uses: actions/upload-artifact@v4', 1)[1]
            self.assertIn('if: always()', upload)
            self.assertIn('if-no-files-found: error', upload)
            self.assertIn('path: .devflow/evidence/', upload)
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('runner: [ubuntu-latest, ubuntu-24.04-arm]', ci)
        self.assertIn('run: GITHUB_SHA="$SOURCE_SHA" .devflow/verify.sh', ci)
        self.assertIn('run: GITHUB_SHA="$SOURCE_SHA" .devflow/up.sh', ci)
        self.assertNotIn('      GITHUB_SHA:', ci)
        self.assertIn('ref: ${{ env.SOURCE_SHA }}', ci)
        self.assertIn('.devflow/container-smoke.sh', ci)
        deploy = (ROOT / '.github/workflows/deploy.yml').read_text()
        self.assertIn("if: github.ref == 'refs/heads/main'", deploy)
        self.assertIn('shell: bash', deploy)
        self.assertIn('runs-on: [self-hosted, Linux, ARM64, devflow, oracle]', deploy)
