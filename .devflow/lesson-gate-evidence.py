#!/usr/bin/env python3
"""LESSON-GATE-AC-1 evidence; never certify merge/deploy or reuse app/CONTRACT IDs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path('/opt/data/devflow/templates/repo/.devflow/check.py')
TEMPLATE_SHA256 = '8b0a26427f1e86c11dd3aae3ae0baf20f3e267149a688e77181236fa58864e73'


def main():
    os.chdir(ROOT)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if os.environ.get('GITHUB_SHA', head) != head:
        raise ValueError('lesson gate evidence checkout/source SHA mismatch')
    out = Path(os.environ.get('DEVFLOW_EVIDENCE', ROOT / '.devflow/evidence')) / 'lesson-gate'
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = out / 'probes.xml'
    report.unlink(missing_ok=True)
    files = ('.devflow/check.py', '.devflow/check.sh', '.devflow/test.sh', '.devflow/unittest-runner.py',
             '.devflow/lesson-gate-evidence.py', '.devflow/verify.sh', '.devflow/contract-evidence.py',
             '.github/workflows/ci.yml', 'tests/test_lesson_gate.py', 'tests/test_contract.py')
    digests = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in files}
    command = ['bash', '.devflow/test.sh']
    proc = subprocess.run(command, env={**os.environ,
        'DEVFLOW_TEST_ONLY': 'tests/test_lesson_gate.py', 'DEVFLOW_JUNIT': str(report),
        'LESSON_GATE_FIXTURE_OUTPUT': str(out / 'fixtures')},
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    (out / 'probes.log').write_text(proc.stdout)
    cases = list(ET.parse(report).getroot().iter('testcase')) if report.exists() else []
    outcomes = [{'name': case.get('name'), 'outcomes': [child.tag for child in case] or ['passed']}
                for case in cases]
    matched = digests['.devflow/check.py'] == TEMPLATE_SHA256
    local_comparison = ((ROOT / '.devflow/check.py').read_bytes() == TEMPLATE.read_bytes()) if TEMPLATE.exists() else None
    passed = (proc.returncode == 0 and bool(cases) and all(not list(c) for c in cases)
              and matched and local_comparison is not False)
    record = {'id': 'LESSON-GATE-AC-1', 'epic': 't_32d348de', 'epic_ac': 'AC-1',
        'source_sha': head, 'run_id': os.environ.get('GITHUB_RUN_ID'),
        'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'), 'phase': os.environ.get('DEVFLOW_VERIFY_PHASE', 'checkout'),
        'runner_arch': os.environ.get('RUNNER_ARCH'), 'result': 'PASS' if passed else 'FAIL',
        'scope': 'Checkout contract/workflow + real selector/JUnit and PR gate fixtures; CI conclusion, merge and health verified separately',
        'template_comparison': {'template_path': str(TEMPLATE), 'expected_sha256': TEMPLATE_SHA256,
            'actual_sha256': digests['.devflow/check.py'], 'matches_pinned_template': matched,
            'local_template_byte_comparison': local_comparison,
            'note': 'Hosted runners compare pinned template digest; local template bytes also compared when available'},
        'workflow_conditions': ['pull_request edited', 'exact head + full history', 'PR-only gate',
            'PR metadata in env, not shell interpolation', 'check.sh + contract-evidence preserved',
            'x64/ARM64 matrix + strict check/test/verify aggregation'],
        'command': command, 'env': {'DEVFLOW_TEST_ONLY': 'tests/test_lesson_gate.py', 'DEVFLOW_JUNIT': 'probes.xml'},
        'probe_exit_code': proc.returncode, 'tests': outcomes, 'sha256': digests,
        'evidence': ['probes.log', 'probes.xml', 'fixtures/'],
        'application_journeys': 'AC-1 / AC-2 unchanged; previous CONTRACT-* evidence stays separate'}
    (out / 'LESSON-GATE-AC-1.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'LESSON-GATE-AC-1: {record["result"]}; source={head}; fixture suite exit={proc.returncode}')
    if not passed:
        print(proc.stdout)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
