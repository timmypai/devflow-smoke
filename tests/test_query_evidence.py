"""Exercise evidence producers directly so coverage sees real HTTP/Git execution."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import Handler, Server

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / '.devflow' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QueryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.out = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {
            'GITHUB_SHA': 'a' * 40, 'DEVFLOW_EXPECTED_REVISION': 'a' * 40,
            'DEVFLOW_REVISION': 'a' * 40, 'DEVFLOW_EVIDENCE': str(self.out),
            'DEVFLOW_VERIFY_PHASE': 'candidate'}))

    def start_server(self):
        server = Server(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        os.environ['DEVFLOW_BASE_URL'] = f'http://127.0.0.1:{server.server_port}'

    def test_query_journeys_capture_real_responses_and_reject_wrong_revision(self):
        self.start_server()
        module = load_script('query-http-evidence')
        for ac in ('LESSON-GATE-AC-2', 'LESSON-GATE-AC-4'):
            with patch.object(sys, 'argv', ['query-http-evidence.py', ac]):
                module.main()
            record = json.loads((self.out / 'lesson-gate' / (ac + '.json')).read_text())
            self.assertEqual(record['result'], 'PASS')
            observations = {item['path']: item for item in record['observations']}
            for path in ('/stats?x=1', '/version?x=1', '/health?x=1', '/?x=1'):
                self.assertEqual(observations[path]['status'], 200)
                self.assertTrue(observations[path]['body'])
            self.assertEqual(observations['/nope?x=1']['status'], 404)
            self.assertEqual(observations['/health/?x=1']['status'], 404)
            self.assertTrue(all(a < b for a, b in zip(record['snapshots'], record['snapshots'][1:])))
        os.environ['DEVFLOW_EXPECTED_REVISION'] = 'b' * 40
        with patch.object(sys, 'argv', ['query-http-evidence.py', 'LESSON-GATE-AC-4']):
            with self.assertRaises(AssertionError):
                module.main()
        record = json.loads((self.out / 'lesson-gate/LESSON-GATE-AC-4.json').read_text())
        self.assertEqual(record['result'], 'FAIL')
        self.assertEqual(json.loads(record['observations'][-1]['body']), {'revision': 'a' * 40})

    def test_success_count_journey_records_exact_http_snapshots_and_revision(self):
        self.start_server()
        module = load_script('success-count-evidence')
        module.main()
        record = json.loads((self.out / 'no-proof/NO-PROOF-AC-1.json').read_text())
        self.assertEqual(record['result'], 'PASS')
        self.assertEqual(record['epic'], 't_b0023bda')
        window = record['attempts'][-1]
        self.assertEqual([item['status'] for item in window['observations']],
                         [200, 404, 404, 404, 200, 200])
        before, home, after = window['snapshots']
        self.assertEqual((home - before, after - before), (1, 2))
        os.environ['DEVFLOW_EXPECTED_REVISION'] = 'b' * 40
        with self.assertRaises(AssertionError):
            module.main()
        failed = json.loads((self.out / 'no-proof/NO-PROOF-AC-1.json').read_text())
        self.assertEqual(failed['result'], 'FAIL')
        self.assertEqual(failed['attempts'], [])
        self.assertEqual(json.loads(failed['version']['body']), {'revision': 'a' * 40})

    def test_gate_evidence_runs_real_base_and_head_and_preserves_assertion_junit(self):
        # A separate Git repository avoids touching the Hermes-managed worktree.
        # Use the actual pre-fix app, unchanged gate, and actual regression test.
        tree = self.out / 'repo'
        tree.mkdir()
        for directory in ('.devflow/rules', '.devflow/lessons'):
            shutil.copytree(ROOT / directory, tree / directory)
        (tree / '.devflow/lessons/L-0003.toml').unlink()
        for path in ('.devflow/check.py', '.devflow/check.sh', '.devflow/test.sh',
                     '.devflow/unittest-runner.py', '.devflow/verify.sh'):
            shutil.copyfile(ROOT / path, tree / path)
        # The only product delta under test is stripping query before dispatch.
        fixed = (ROOT / 'app.py').read_text()
        pre_fix = fixed.replace('path = self.path.partition("?")[0]', 'path = self.path')
        self.assertNotEqual(pre_fix, fixed)
        (tree / 'app.py').write_text(pre_fix)
        (tree / 'tests').mkdir()
        (tree / 'tests/__init__.py').write_text('')
        env = {**os.environ, 'GIT_AUTHOR_NAME': 'test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
               'GIT_COMMITTER_NAME': 'test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid'}

        def git(*args):
            return subprocess.check_output(['git', *args], cwd=tree, env=env, text=True).strip()

        git('init', '-q')
        git('add', '.')
        git('commit', '-qm', 'base query routing')
        base = git('rev-parse', 'HEAD')
        (tree / 'app.py').write_text(fixed)
        shutil.copyfile(ROOT / 'tests/test_query_http.py', tree / 'tests/test_query_http.py')
        shutil.copyfile(ROOT / '.devflow/lessons/L-0003.toml', tree / '.devflow/lessons/L-0003.toml')
        git('add', '.')
        git('commit', '-qm', 'fix query routing')
        head = git('rev-parse', 'HEAD')
        module = load_script('query-gate-evidence')
        module.ROOT = tree
        output = self.out / 'proof'
        self.enterContext(patch.dict(os.environ, {'GITHUB_SHA': head, 'DEVFLOW_EVIDENCE': str(output),
            'PR_TITLE': 'fix: query routing', 'PR_BODY': 'Lesson: L-0003'}))
        previous = Path.cwd()
        try:
            with patch.object(sys, 'argv', ['query-gate-evidence.py', base]):
                self.assertEqual(module.main(), 0)
        finally:
            os.chdir(previous)
        proof = output / 'lesson-gate-query'
        record = json.loads((proof / 'LESSON-GATE-AC-3.json').read_text())
        self.assertEqual((record['base_sha'], record['pr_head']), (base, head))
        self.assertEqual(record['result'], 'PASS')
        self.assertEqual(record['gate']['exit_code'], 0)
        self.assertIn('devflow pr gate: 0 problem(s)', (proof / 'gate.log').read_text())
        self.assertEqual(record['base']['exit_code'], 1)
        self.assertEqual(record['head']['exit_code'], 0)
        self.assertEqual([case['outcome'] for case in record['base']['outcomes']], ['failure'] * 4)
        self.assertEqual([case['outcome'] for case in record['head']['outcomes']], ['passed'] * 4)
        # A green base is not proof of a regression: preserve FAIL, never PASS.
        try:
            with patch.object(sys, 'argv', ['query-gate-evidence.py', head]):
                self.assertEqual(module.main(), 1)
        finally:
            os.chdir(previous)
        record = json.loads((proof / 'LESSON-GATE-AC-3.json').read_text())
        self.assertEqual(record['result'], 'FAIL')
        self.assertEqual(record['base']['exit_code'], 0)
        self.assertEqual([case['outcome'] for case in record['base']['outcomes']], ['passed'] * 4)
