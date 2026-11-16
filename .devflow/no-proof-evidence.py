#!/usr/bin/env python3
"""Retain this Epic's isolated HTTP assertion on actual base/head, not old proofs."""

import hashlib
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
BASE = 'c7bf3287a5231e12b15dca45a9f6ff9eaeda32a7'
TEST = 'tests/test_404_count_http.py'
METHOD = 'test_404_requests_do_not_increment_stats'


def run_regression(tree, out, label):
    report = out / f'{label}.xml'
    report.unlink(missing_ok=True)
    command = ['bash', '.devflow/test.sh']
    proc = subprocess.run(command, cwd=tree, env={**os.environ,
        'DEVFLOW_TEST_ONLY': TEST, 'DEVFLOW_JUNIT': str(report)},
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    (out / f'{label}.log').write_text(proc.stdout)
    (out / f'{label}.exit-code.txt').write_text(str(proc.returncode) + '\n')
    print(f'{label}: exit={proc.returncode}; selector={TEST}::{METHOD}\n{proc.stdout}', flush=True)
    cases = list(ET.parse(report).getroot().iter('testcase'))
    assert len(cases) == 1 and cases[0].get('name') == METHOD, ET.tostring(ET.parse(report).getroot())
    case = cases[0]
    outcome = next((kind for kind in ('error', 'failure', 'skipped')
                    if case.find(kind) is not None), 'passed')
    return {'command': command, 'selector': TEST + '::' + METHOD,
            'test_sha256': hashlib.sha256((tree / TEST).read_bytes()).hexdigest(),
            'exit_code': proc.returncode, 'outcome': outcome,
            'junit': report.name, 'log': f'{label}.log', 'exit_file': f'{label}.exit-code.txt'}


def collect_proof(base, out):
    with tempfile.TemporaryDirectory(prefix='404-count-base-') as temporary:
        tree = Path(temporary)
        archive = subprocess.check_output(['git', 'archive', base], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(tree, filter='data')
        # Exactly the same test bytes and runner entrypoint as the final head.
        for path in (TEST, '.devflow/test.sh'):
            shutil.copyfile(ROOT / path, tree / path)
        before = run_regression(tree, out, 'base')
    after = run_regression(ROOT, out, 'head')
    return before, after


def main():
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    assert os.environ.get('GITHUB_SHA', head) == head, 'checkout/source SHA mismatch'
    base = sys.argv[1] if len(sys.argv) > 1 else BASE
    base = subprocess.check_output(['git', 'rev-parse', '--verify', base + '^{commit}'],
                                   cwd=ROOT, text=True).strip()
    assert base == BASE, 'this Epic requires the original pre-fix base'
    out = Path(os.environ.get('DEVFLOW_EVIDENCE', ROOT / '.devflow/evidence')).resolve() / 'no-proof'
    out.mkdir(parents=True, exist_ok=True)
    # A failed rerun must not leave a previous PASS manifest behind.
    (out / 'NO-PROOF-AC-3.json').unlink(missing_ok=True)
    before, after = collect_proof(base, out)
    passed = (before['exit_code'] == 1 and before['outcome'] == 'failure'
              and after['exit_code'] == 0 and after['outcome'] == 'passed'
              and before['test_sha256'] == after['test_sha256'])
    record = {'id': 'NO-PROOF-AC-3', 'epic': 't_b0023bda', 'lesson_id': 'L-0004',
              'base_sha': base, 'source_sha': head, 'pr_head': head,
              'ref': TEST + '::' + METHOD, 'base': before, 'head': after,
              'run_id': os.environ.get('GITHUB_RUN_ID'),
              'phase': os.environ.get('DEVFLOW_VERIFY_PHASE', 'checkout'),
              'result': 'PASS' if passed else 'FAIL',
              'scope': 'Real existing HTTP endpoints on isolated servers. Base archive overlaid only '
                       'with the head test and test.sh. Canonical PR gate runs separately, unchanged. '
                       'Historical weak exemption/ADV decision is recorded on the card and PR, not simulated here.'}
    (out / 'NO-PROOF-AC-3.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'NO-PROOF-AC-3: {record["result"]}; base={base}; head={head}', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
