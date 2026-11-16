#!/usr/bin/env python3
"""Executable contract journeys, separate namespace from app stats/home ACs.

Runs on PR exact-head CI and again on merged main before deployment/repro.
A passing file proves checkout contract/probes only, not a future CI conclusion,
merge, production health, or a repro dispatch not yet executed.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if head != os.environ.get('GITHUB_SHA', head):
        raise ValueError('contract evidence checkout SHA mismatch')
    out = ROOT / '.devflow/evidence/contracts'
    out.mkdir(parents=True, exist_ok=True)
    groups = (
        ('CONTRACT-AC-1', 'Epic AC-1: exact-head check + strict devflow-ci needs; CI conclusion verified separately',
         [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_contract.py', '-k', 'ContractWorkflowTests', '-v']),
        ('CONTRACT-AC-2', 'Epic AC-2: rules, self-tests, lesson/ref validation and negative probes; no baseline',
         [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_contract.py', '-k', 'RuleTests', '-v']),
        ('CONTRACT-AC-3', 'Epic AC-3: quality/repro/capture/redact files and synthetic diagnostics security probes',
         [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_contract.py', '-k', 'DiagnosticTests', '-v']),
    )
    files = ['.github/workflows/ci.yml', '.github/workflows/quality.yml', '.github/workflows/repro.yml',
             '.devflow/capture.sh', '.devflow/redact.py', '.devflow/check.py', '.devflow/check.sh',
             '.devflow/lessons/L-0001.toml', '.devflow/quality.sh', 'tests/test_contract.py']
    files += [str(p) for p in sorted(Path('.devflow/rules').glob('*.toml'))]
    digests = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in files}
    result = subprocess.run(['bash', '.devflow/check.sh'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (out / 'check.log').write_text(result.stdout)
    passed = result.returncode == 0
    mapping = []
    for ac, description, command in groups:
        probe = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (out / f'{ac}.log').write_text(probe.stdout)
        ok = result.returncode == 0 and probe.returncode == 0
        record = {'id': ac, 'description': description, 'source_sha': head,
                  'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
                  'result': 'PASS' if ok else 'FAIL', 'check_exit_code': result.returncode,
                  'probe_exit_code': probe.returncode, 'command': command, 'sha256': digests,
                  'evidence': ['check.log', f'{ac}.log']}
        (out / f'{ac}.json').write_text(json.dumps(record, indent=2) + '\n')
        mapping.append({'epic_ac': ac.replace('CONTRACT-', ''), 'evidence': f'{ac}.json', 'result': record['result']})
        print(f'{ac}: {record["result"]}')
        if not ok:
            print(result.stdout + probe.stdout)
        passed = passed and ok
    (out / 'mapping.json').write_text(json.dumps({'source_sha': head, 'epic': 't_97e7e941',
        'acceptance': mapping, 'application_journeys': 'AC-1 stats / AC-2 homepage remain separate in attempt-*'}, indent=2) + '\n')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
