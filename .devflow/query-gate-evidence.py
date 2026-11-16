#!/usr/bin/env python3
"""Additive AC-3 proof: run the unchanged gate and retain real base/head JUnit."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TEST = 'tests/test_query_http.py'
METHOD = 'test_query_routes_preserve_http_content_and_get_counts'


def run_tests(cwd, out, label):
    report = out / f'{label}.xml'
    env = {**os.environ, 'DEVFLOW_TEST_ONLY': TEST, 'DEVFLOW_JUNIT': str(report)}
    command = ['bash', '.devflow/test.sh']
    proc = subprocess.run(command, cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    (out / f'{label}.log').write_text(proc.stdout)
    cases = list(ET.parse(report).getroot().iter('testcase'))
    outcomes = [{'name': case.get('name'),
                 'outcome': next((kind for kind in ('error', 'failure', 'skipped')
                                  if case.find(kind) is not None), 'passed')}
                for case in cases]
    assert len(outcomes) == 4 and all(case['name'].startswith(METHOD + '[') for case in outcomes), outcomes
    return {'command': command, 'env': {key: env[key] for key in ('DEVFLOW_TEST_ONLY', 'DEVFLOW_JUNIT')},
            'exit_code': proc.returncode, 'junit': report.name, 'log': f'{label}.log', 'outcomes': outcomes}


def main():
    os.chdir(ROOT)
    base = sys.argv[1]
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    assert os.environ.get('GITHUB_SHA', head) == head
    # Canonicalize and validate the supplied commit via Git, not a guessed revision.
    base = subprocess.check_output(['git', 'rev-parse', '--verify', base + '^{commit}'], text=True).strip()
    out = Path(os.environ.get('DEVFLOW_EVIDENCE', ROOT / '.devflow/evidence')).resolve() / 'lesson-gate-query'
    out.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '.devflow/check.py', '--pr', base]
    gate = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    (out / 'gate.log').write_text(gate.stdout)
    print(gate.stdout, end='')
    with tempfile.TemporaryDirectory(prefix='query-base-') as temporary:
        tree = Path(temporary)
        archive = subprocess.check_output(['git', 'archive', base])
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(tree, filter='data')
        for path in (TEST, '.devflow/test.sh'):
            shutil.copyfile(ROOT / path, tree / path)
        before = run_tests(tree, out, 'base')
    after = run_tests(ROOT, out, 'head')
    passed = (gate.returncode == 0 and before['exit_code'] == 1 and after['exit_code'] == 0
              and {case['outcome'] for case in before['outcomes']} == {'failure'}
              and {case['outcome'] for case in after['outcomes']} == {'passed'})
    run_id = os.environ.get('GITHUB_RUN_ID')
    run_url = f'https://github.com/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{run_id}' if run_id else None
    record = {'id': 'LESSON-GATE-AC-3', 'epic': 't_32d348de', 'base_sha': base,
        'source_sha': head, 'pr_head': head, 'lesson_id': 'L-0003', 'ref': TEST + '::' + METHOD,
        'run_id': run_id, 'run_url': run_url,
        'gate': {'command': command, 'exit_code': gate.returncode, 'log': 'gate.log',
                 'PR_TITLE': os.environ['PR_TITLE'], 'PR_BODY': os.environ['PR_BODY']},
        'base': before, 'head': after, 'result': 'PASS' if passed else 'FAIL',
        'scope': 'Actual unchanged P2 gate plus independent archive of base with only the test file and test.sh overlaid; raw XML/logs retained. Check job log is provided by Actions.'}
    (out / 'LESSON-GATE-AC-3.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'LESSON-GATE-AC-3: {record["result"]}; base={base}; head={head}')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
