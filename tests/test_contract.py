"""Contract probes. Docker test doubles prove boundaries, NOT Actions execution."""
import importlib.util
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copytree(ROOT / '.devflow/rules', self.root / '.devflow/rules')
        shutil.copytree(ROOT / '.devflow/lessons', self.root / '.devflow/lessons')
        for name in ('check.py', 'check.sh'):
            shutil.copy(ROOT / '.devflow' / name, self.root / '.devflow' / name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def check(self, expected=0, contains=''):
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        p = subprocess.run(['bash', '.devflow/check.sh'], cwd=self.root,
                           text=True, capture_output=True)
        self.assertEqual(p.returncode, expected, p.stdout + p.stderr)
        self.assertIn(contains, p.stdout)
        return p.stdout

    def test_current_rules_self_test_and_lesson_pass(self):
        self.check(contains='3 rule(s), 1 lesson(s), 0 baselined, 0 new')

    def test_new_tracked_violations_fail_all_rules(self):
        # Construct source snippets to avoid confusing the scanner with its probes.
        for name, text, rule in (
                ('worker.py', 'time.' + 'sleep(2)', 'no-sleep-fix'),
                ('test_api.py', '@unittest.' + 'skip("later")', 'no-skip-test'),
                ('worker.py', 'x = 1  # ' + 'noqa', 'no-suppress'),
                ('.devflow/ui/probe.js', 'await page.' + 'waitForTimeout(1000)', 'no-sleep-fix')):
            with self.subTest(rule=rule, path=name):
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                self.check(1, f'[{rule}]')
                path.unlink()

    def test_exemption_requires_existing_lesson(self):
        path = self.root / 'worker.py'
        path.write_text('time.' + 'sleep(0.2)  # devflow: allow no-sleep-fix L-9999')
        self.check(1, 'missing lesson L-9999')
        path.write_text(path.read_text().replace('L-9999', 'L-0001'))
        self.check()

    def test_lesson_format_and_enforcement_refs_fail(self):
        path = self.root / '.devflow/lessons/L-0001.toml'
        original = path.read_text()
        cases = (
            (original.replace('category = "verification"', 'category = "unknown"'), 'category must'),
            (original.replace('ref = "no-sleep-fix"', 'ref = "absent-rule"'), 'names no rule'),
            (original.replace('kind = "rule"', 'kind = "test"').replace('ref = "no-sleep-fix"', 'ref = "missing.py::test_it"'), 'file not found'),
            (original.replace('kind = "rule"', 'kind = "test"').replace('ref = "no-sleep-fix"', 'ref = ".devflow/check.py::nonexistent_test_name"'), 'not found in'),
            (original.replace('root_cause =', 'unused ='), 'root_cause is required'),
        )
        for text, message in cases:
            with self.subTest(message=message):
                path.write_text(text)
                self.check(1, message)
        path.write_text(original)
        self.check()

    def test_empty_rules_and_broad_exclusion_cannot_pass(self):
        path = self.root / '.devflow/rules/no-sleep-fix.toml'
        path.write_text(path.read_text().replace('patterns = [', 'exclude = ["**"]\npatterns = ['))
        self.check(1, 'did not fire on')
        for path in (self.root / '.devflow/rules').glob('*.toml'):
            path.unlink()
        self.check(2, 'at least one rule is required')


class ContractWorkflowTests(unittest.TestCase):
    def test_check_exact_head_and_strict_gate(self):
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        check = ci.split('  check:', 1)[1].split('  test:', 1)[0]
        self.assertIn('ref: ${{ env.SOURCE_SHA }}', check)
        self.assertIn('bash .devflow/check.sh', check)
        self.assertIn('test "$(git rev-parse HEAD)" = "$SOURCE_SHA"', check)
        gate = ci.split('  devflow-ci:', 1)[1]
        self.assertIn('needs: [check, test, verify]', gate)
        self.assertIn('if: always()', gate)
        command = next(line.split('run: ', 1)[1] for line in gate.splitlines() if 'run: ' in line)
        for states in itertools.product(('success', 'failure', 'skipped', 'cancelled', ''), repeat=3):
            result = subprocess.run(['bash', '-c', command], env={**os.environ,
                **dict(zip(('CHECK_RESULT', 'TEST_RESULT', 'VERIFY_RESULT'), states))})
            self.assertEqual(result.returncode == 0, states == ('success',) * 3)

    def test_quality_hosted_readonly_pinned_and_not_required(self):
        quality = (ROOT / '.github/workflows/quality.yml').read_text()
        self.assertIn('runs-on: ubuntu-latest', quality)
        self.assertIn('contents: read', quality)
        self.assertNotIn('self-hosted', quality)
        self.assertNotIn('secrets.', quality)
        self.assertIn('continue-on-error: true', quality)
        self.assertIn('bash .devflow/quality.sh', quality)
        self.assertEqual(len(re.findall(r'(?:crapper|dryer|mutator):[0-9a-f]{40}', quality)), 3)
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertNotIn('quality', ci)

    def test_repro_matches_real_interfaces_and_always_cleanup_upload(self):
        repro = (ROOT / '.github/workflows/repro.yml').read_text()
        self.assertNotRegex(repro, r'(?m)^\s+inputs:')
        for unsupported in ('DEVFLOW_ONLY', 'DEVFLOW_TRACE', 'ci-${DEVFLOW_APP}'):
            self.assertNotIn(unsupported, repro)
        for script in ('prepare-evidence.sh', 'up.sh', 'verify.sh', 'cleanup.sh', 'capture.sh'):
            self.assertIn(script, repro)
        self.assertIn('capture.sh "$DEVFLOW_VERIFY_PROJECT" repro', repro)
        self.assertLess(repro.index('capture.sh'), repro.index('cleanup.sh'))
        self.assertIn('if: always()', repro.split('uses: actions/upload-artifact@v4')[1])
        self.assertIn('ref: ${{ env.SOURCE_SHA }}', repro)

    def test_cleanup_refuses_foreign_projects_without_calling_docker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(ROOT / '.devflow', root / '.devflow',
                            ignore=shutil.ignore_patterns('evidence', 'diagnostics', 'node_modules', '__pycache__'))
            for foreign in ('devflow-devflow-smoke', 'devflow-verify-99-1-x64', '../elsewhere'):
                p = subprocess.run(['bash', '.devflow/cleanup.sh'], cwd=root,
                    env={**os.environ, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                         'RUNNER_ARCH': 'X64', 'DEVFLOW_VERIFY_PROJECT': foreign}, capture_output=True)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn(b'refusing foreign project', p.stderr)


# Synthetic secrets only. No daemon used here; real Docker diagnostics are in Actions.
CAPTURE_DOCKER = r'''
import json, sys
from pathlib import Path
args = sys.argv[1:]
with open('docker.jsonl', 'a') as f:
    f.write(json.dumps(args) + '\n')
secret = 'synthetic-literal-Secret-123'
if args[0] == 'ps':
    assert '--filter' in args
    assert args[args.index('--filter') + 1] == 'label=com.docker.compose.project=devflow-verify-123-1-x64'
    print('a' * 64 if '-aq' in args else json.dumps({'Status': secret}))
elif args[0] == 'inspect':
    assert '.Config.Env' not in args[2]
    print(json.dumps({'state': {'ExitCode': 7, 'OOMKilled': True, 'Health': {'Log': secret}}, 'restart_count': 2}))
elif args[0] == 'logs':
    print('Authorization: Bearer syntheticBearer123')
    print('password=syntheticPassword123')
    print(secret)
else:
    raise SystemExit('unexpected command')
'''


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / '.devflow').mkdir()
        (self.root / 'deploy').mkdir()
        (self.root / 'bin').mkdir()
        for name in ('capture.sh', 'redact.py'):
            shutil.copy(ROOT / '.devflow' / name, self.root / '.devflow' / name)
        (self.root / '.devflow/config.env').write_text('DEVFLOW_PORT=0\nDEVFLOW_HEALTH_PATH=\n')
        (self.root / 'deploy/.env').write_text('EXAMPLE=synthetic-literal-Secret-123\nSHORT=xyz\n')
        docker = self.root / 'bin/docker'
        docker.write_text(f'#!{sys.executable}\n' + CAPTURE_DOCKER)
        docker.chmod(0o755)
        self.env = {**os.environ, 'PATH': f'{self.root}/bin:' + os.environ['PATH'], 'GITHUB_SHA': 'a' * 40}

    def capture(self, label='candidate'):
        p = subprocess.run(['bash', '.devflow/capture.sh', 'devflow-verify-123-1-x64', label],
                           cwd=self.root, env=self.env, text=True, capture_output=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('synthetic-literal-Secret-123', p.stdout + p.stderr)
        return self.root / '.devflow/diagnostics' / label

    def test_all_diagnostic_files_redacted_and_repeated_capture_is_scoped(self):
        outside = self.root / 'outside'
        outside.write_text('do not delete')
        for _ in range(2):
            out = self.capture()
            payload = '\n'.join(p.read_text() for p in out.rglob('*') if p.is_file())
            for secret in ('synthetic-literal-Secret-123', 'syntheticBearer123', 'syntheticPassword123'):
                self.assertNotIn(secret, payload)
            self.assertIn('<REDACTED>', payload)
            state = json.loads((out / 'state.jsonl').read_text())
            self.assertEqual(state['state']['ExitCode'], 7)
            self.assertTrue(state['state']['OOMKilled'])
            self.assertEqual(state['restart_count'], 2)
            self.assertEqual(json.loads((out / 'manifest.json').read_text())['project'], 'devflow-verify-123-1-x64')
            self.assertEqual(outside.read_text(), 'do not delete')
            self.assertEqual(list((self.root / '.devflow').glob('.capture-*')), [])

    def test_redactor_failure_removes_every_payload_and_stale_success(self):
        self.capture()
        (self.root / '.devflow/redact.py').write_text('raise SystemExit(9)')
        out = self.capture()
        self.assertEqual([p.name for p in out.iterdir()], ['errors.txt'])
        self.assertIn('fail closed', (out / 'errors.txt').read_text())
        self.assertEqual(list((self.root / '.devflow').glob('.capture-*')), [])

    def test_traversal_and_symlink_output_cannot_delete_outside(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'keep').write_text('safe')
        self.capture('../outside')
        root = self.root / '.devflow/diagnostics'
        root.mkdir(exist_ok=True)
        (root / 'candidate').symlink_to(outside, target_is_directory=True)
        self.capture()
        self.assertEqual((outside / 'keep').read_text(), 'safe')
        self.assertFalse((self.root / 'docker.jsonl').exists())

    def test_literal_short_secrets_and_common_credential_patterns(self):
        spec = importlib.util.spec_from_file_location('redact_probe', ROOT / '.devflow/redact.py')
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = ('xyz synthetic-literal-Secret-123 Bearer syntheticBearer123 '
                'https://user:syntheticURL123@example.com Cookie: syntheticCookie123\n'
                '-----BEGIN PRIVATE KEY-----\nsyntheticPrivate123\n-----END PRIVATE KEY-----')
        result = mod.redact(text, mod.env_literals(self.root / 'deploy/.env'))
        for value in ('xyz', 'synthetic-literal-Secret-123', 'syntheticBearer123',
                      'syntheticURL123', 'syntheticCookie123', 'syntheticPrivate123'):
            self.assertNotIn(value, result)
        self.assertLess(len(mod.redact('x' * 5000, [])), 4100)
        with self.assertRaises(ValueError):
            mod.env_literals(self.root / 'missing.env')
        (self.root / 'bad.env').write_text('KEY="unterminated\n')
        with self.assertRaises(ValueError):
            mod.env_literals(self.root / 'bad.env')


if __name__ == '__main__':
    unittest.main()
