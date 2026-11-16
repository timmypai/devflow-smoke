"""Real subprocess fixtures for the unittest/P2 contract (no app behavior changes)."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_SHA256 = '8b0a26427f1e86c11dd3aae3ae0baf20f3e267149a688e77181236fa58864e73'
TEMPLATE = Path('/opt/data/devflow/templates/repo/.devflow/check.py')


def load_gate():
    spec = importlib.util.spec_from_file_location('lesson_gate_probe', ROOT / '.devflow/check.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class UnittestContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / '.devflow').mkdir()
        (self.root / 'tests').mkdir()
        for name in ('test.sh', 'unittest-runner.py'):
            shutil.copyfile(ROOT / '.devflow' / name, self.root / '.devflow' / name)
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ('DEVFLOW_TEST_ONLY', 'DEVFLOW_JUNIT')}

    def fixture(self, name, body):
        path = self.root / 'tests' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('import unittest\nfrom pathlib import Path\nclass Probe(unittest.TestCase):\n' + body)
        return 'tests/' + name

    def run_fixture(self, label, selector=None, junit=True):
        env = dict(self.env)
        if selector is not None:
            env['DEVFLOW_TEST_ONLY'] = selector
        report = self.root / 'reports' / (label + '.xml')
        if junit:
            env['DEVFLOW_JUNIT'] = str(report)
        proc = subprocess.run(['bash', '.devflow/test.sh'], cwd=self.root, env=env,
                              text=True, capture_output=True, timeout=30)
        output = os.environ.get('LESSON_GATE_FIXTURE_OUTPUT')
        if output:
            out = Path(output) / self._testMethodName / label
            out.mkdir(parents=True, exist_ok=True)
            (out / 'stdout.log').write_text(proc.stdout)
            (out / 'stderr.log').write_text(proc.stderr)
            (out / 'exit-code.txt').write_text(str(proc.returncode) + '\n')
            if report.exists():
                shutil.copyfile(report, out / 'junit.xml')
        cases = list(ET.parse(report).getroot().iter('testcase')) if report.exists() else []
        return proc, cases

    def test_selector_runs_only_exact_file_and_method_names_match_gate(self):
        selected = self.fixture('test_selected.py', '    def test_target(self):\n        Path("selected").touch()\n')
        self.fixture('test_other.py', '    def test_other(self):\n        Path("other").touch()\n        self.fail("must not execute")\n')
        self.fixture('nested/test_selected.py', '    def test_nested(self):\n        self.fail("wrong file")\n')
        proc, cases = self.run_fixture('selected', selected)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.root / 'selected').exists())
        self.assertFalse((self.root / 'other').exists())
        self.assertEqual([c.get('name') for c in cases], ['test_target'])
        self.assertEqual(cases[0].get('file'), selected)
        self.assertEqual(list(cases[0]), [])
        outcomes, err = load_gate().run_test_file(self.root, selected, 'test_target')
        self.assertEqual((outcomes, err), (['passed'], ''))

    def test_success_assertion_error_and_skip_have_distinct_xml_and_exit_codes(self):
        fixtures = (
            ('success', '        self.assertEqual(2, 2)\n', None, 0),
            ('assertion', '        self.assertEqual(1, 2)\n', 'failure', 1),
            ('exception', '        raise RuntimeError("fixture error")\n', 'error', 1),
            ('skipped', '        getattr(self, "skipTest")("fixture skipped")\n', 'skipped', 0),
        )
        for label, body, kind, rc in fixtures:
            with self.subTest(outcome=label):
                path = self.fixture('test_' + label + '.py', '    def test_probe(self):\n' + body)
                proc, cases = self.run_fixture(label, path)
                self.assertEqual(proc.returncode, rc, proc.stderr)
                self.assertEqual([c.get('name') for c in cases], ['test_probe'])
                self.assertEqual([child.tag for child in cases[0]], [] if kind is None else [kind])
                if kind in ('failure', 'error'):
                    node = cases[0].find(kind)
                    assert node is not None
                    self.assertIn('Traceback', node.text or '')
                outcomes, err = load_gate().run_test_file(self.root, path, 'test_probe')
                self.assertEqual((outcomes, err), ([kind or 'passed'], ''))

    def test_full_discovery_with_and_without_report_preserves_failures(self):
        self.fixture('test_one.py', '    def test_one(self):\n        Path("one").touch()\n')
        self.fixture('test_two.py', '    def test_two(self):\n        Path("two").touch()\n        self.fail("full suite failure")\n')
        for junit in (False, True):
            with self.subTest(junit=junit):
                proc, cases = self.run_fixture('all-' + str(junit), junit=junit)
                self.assertEqual(proc.returncode, 1, proc.stderr)
                self.assertTrue((self.root / 'one').exists())
                self.assertTrue((self.root / 'two').exists())
                if junit:
                    self.assertEqual({c.get('name') for c in cases}, {'test_one', 'test_two'})
                    self.assertEqual(len([c for c in cases if c.find('failure') is not None]), 1)

    def test_full_discovery_success_with_and_without_report(self):
        self.fixture('test_one.py', '    def test_one(self):\n        pass\n')
        self.fixture('test_two.py', '    def test_two(self):\n        pass\n')
        for junit in (False, True):
            proc, cases = self.run_fixture('pass-' + str(junit), junit=junit)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            if junit:
                self.assertEqual(len(cases), 2)
                self.assertTrue(all(not list(c) for c in cases))

    def test_import_and_class_setup_errors_are_not_named_assertion_failures(self):
        path = self.fixture('test_broken.py', '    def test_probe(self):\n        pass\n')
        (self.root / path).write_text('raise ImportError("fixture collection error")\n')
        proc, cases = self.run_fixture('import', path)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any(c.find('error') is not None for c in cases))
        self.assertFalse(any(c.get('name') == 'test_probe' for c in cases))
        (self.root / path).write_text('import unittest\nclass Probe(unittest.TestCase):\n'
            '    @classmethod\n    def setUpClass(cls):\n        raise RuntimeError("setup")\n'
            '    def test_probe(self):\n        pass\n')
        proc, cases = self.run_fixture('class-setup', path)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any(c.find('error') is not None for c in cases))
        self.assertFalse(any(c.get('name') == 'test_probe' for c in cases))

    def test_subtest_failure_and_error_are_not_reported_as_passed(self):
        path = self.fixture('test_sub.py', '    def test_probe(self):\n'
            '        with self.subTest(case="assertion"):\n            self.assertEqual(1, 2)\n'
            '        with self.subTest(case="exception"):\n            raise RuntimeError("subtest")\n')
        proc, cases = self.run_fixture('subtests', path)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual({child.tag for c in cases for child in c}, {'failure', 'error'})
        self.assertTrue(all(c.get('name', '').startswith('test_probe[') for c in cases))
        self.assertTrue(all(list(c) for c in cases))

    def test_invalid_selector_and_empty_suite_fail_closed(self):
        self.fixture('test_valid.py', '    def test_valid(self):\n        pass\n')
        for selector in ('tests/missing.py', '../outside.py', 'tests/test_*.py'):
            proc, _ = self.run_fixture('invalid-' + str(len(selector)), selector)
            self.assertNotEqual(proc.returncode, 0)
        (self.root / 'tests/test_valid.py').unlink()
        proc, _ = self.run_fixture('empty')
        self.assertNotEqual(proc.returncode, 0)


class LessonGateWorkflowTests(unittest.TestCase):
    def test_check_file_matches_pinned_current_template(self):
        actual = (ROOT / '.devflow/check.py').read_bytes()
        self.assertEqual(hashlib.sha256(actual).hexdigest(), TEMPLATE_SHA256)
        if TEMPLATE.exists():
            self.assertEqual(actual, TEMPLATE.read_bytes())

    def test_pr_gate_metadata_history_event_and_existing_guards(self):
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('types: [opened, synchronize, reopened, edited]', ci)
        check = ci.split('  check:', 1)[1].split('  test:', 1)[0]
        self.assertIn('fetch-depth: 0', check)
        self.assertIn("if: github.event_name == 'pull_request'", check)
        self.assertIn('PR_TITLE: ${{ github.event.pull_request.title }}', check)
        self.assertIn('PR_BODY: ${{ github.event.pull_request.body }}', check)
        self.assertIn('PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}', check)
        self.assertIn('python3 .devflow/check.py --pr "$PR_BASE_SHA"', check)
        for line in check.splitlines():
            if 'github.event.pull_request.' in line and any(x in line for x in ('.title', '.body', '.base.sha')):
                self.assertTrue(line.lstrip().startswith(('PR_TITLE:', 'PR_BODY:', 'PR_BASE_SHA:')), line)
        self.assertIn('bash .devflow/check.sh', check)
        self.assertIn('python3 .devflow/contract-evidence.py', check)
        self.assertIn('python3 .devflow/lesson-gate-evidence.py', check)
        self.assertIn('runner: [ubuntu-latest, ubuntu-24.04-arm]', ci)
        self.assertIn('"label":"x64"', ci)
        self.assertIn('"label":"arm64"', ci)
        self.assertIn('needs: [check, test, verify]', ci)
        self.assertIn('python3 .devflow/lesson-gate-evidence.py', (ROOT / '.devflow/verify.sh').read_text())


class PRGateCliTests(unittest.TestCase):
    def test_real_base_overlay_accepts_assertion_only_not_error_skip_or_false_proof(self):
        # The helper is deliberately committed in BASE: the unmodified gate
        # overlays only test.sh and the cited test, never this helper.
        variants = (
            ('assertion', 'self.assertEqual(subject.VALUE, 2)', 0, '0 problem(s)'),
            ('error', 'self.assertEqual(subject.NEW_VALUE, 2)', 1, 'BASE): error'),
            ('skip', 'getattr(self, "skipTest")("fixture") if subject.VALUE == 1 else None', 1, 'BASE): skipped'),
            ('already-pass', 'self.assertGreater(subject.VALUE, 0)', 1, 'BASE): passed'),
        )
        for label, assertion, rc, message in variants:
            with self.subTest(proof=label), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / '.devflow/lessons').mkdir(parents=True)
                (root / 'tests').mkdir()
                for name in ('test.sh', 'unittest-runner.py', 'check.py'):
                    shutil.copyfile(ROOT / '.devflow' / name, root / '.devflow' / name)
                (root / 'subject.py').write_text('VALUE = 1\n')
                def git(*args):
                    return subprocess.check_output(['git', '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', *args], cwd=root, text=True).strip()
                git('init', '-q')
                git('add', '.')
                git('commit', '-qm', 'base with helper')
                base = git('rev-parse', 'HEAD')
                (root / 'subject.py').write_text('VALUE = 2\nNEW_VALUE = 2\n')
                (root / 'tests/test_regression.py').write_text(
                    'import unittest\nimport subject\nclass Regression(unittest.TestCase):\n'
                    '    def test_regression(self):\n        ' + assertion + '\n')
                (root / '.devflow/lessons/L-0002.toml').write_text(
                    'id = "L-0002"\ntitle = "Fixture"\nevent = "Fixture"\nroot_cause = "Fixture"\n'
                    'category = "verification"\n[enforcement]\nkind = "test"\n'
                    'ref = "tests/test_regression.py::test_regression"\n')
                git('add', '.')
                git('commit', '-qm', 'fix fixture')
                proc = subprocess.run([sys.executable, '.devflow/check.py', '--pr', base], cwd=root,
                    env={**os.environ, 'PR_TITLE': 'fix: fixture', 'PR_BODY': 'Lesson: L-0002'},
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(proc.returncode, rc, proc.stdout + proc.stderr)
                self.assertIn(message, proc.stdout)
                self.assertEqual(len(git('worktree', 'list', '--porcelain').split('worktree ')) - 1, 1)
                output = os.environ.get('LESSON_GATE_FIXTURE_OUTPUT')
                if output:
                    out = Path(output) / self._testMethodName / label
                    out.mkdir(parents=True, exist_ok=True)
                    (out / 'stdout.log').write_text(proc.stdout)
                    (out / 'stderr.log').write_text(proc.stderr)
                    (out / 'exit-code.txt').write_text(str(proc.returncode) + '\n')

    def test_fix_requires_lesson_and_non_fix_passes_without_one(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.devflow').mkdir()
            shutil.copyfile(ROOT / '.devflow/check.py', root / '.devflow/check.py')
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                            'commit', '--allow-empty', '-qm', 'base'], cwd=root, check=True)
            for title, body, rc in (
                ('ci: upgrade contract', '', 0),
                ('fix: regression', '', 1),
                ('revert: regression', '', 1),
                ('fix: regression', 'No-lesson: isolated fixture with no recurring cause', 0),
                ('fix: regression', 'Lesson: L-9999', 1),
                ('ci: literal $(touch injected)', 'metadata; $(touch injected)', 0),
            ):
                with self.subTest(title=title, body=body):
                    proc = subprocess.run([sys.executable, '.devflow/check.py', '--pr', 'HEAD'],
                        cwd=root, env={**os.environ, 'PR_TITLE': title, 'PR_BODY': body},
                        text=True, capture_output=True, timeout=30)
                    self.assertEqual(proc.returncode, rc, proc.stdout + proc.stderr)
                    self.assertFalse((root / 'injected').exists())


if __name__ == '__main__':
    unittest.main()
