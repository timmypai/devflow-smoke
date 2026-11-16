#!/usr/bin/env python3
"""Real-Docker synthetic failure probe. Execute ONLY on GitHub-hosted temporary projects."""
import json
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    assert os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'hosted-only probe'
    expected = 'devflow-verify-{}-{}-{}'.format(os.environ['GITHUB_RUN_ID'],
        os.environ['GITHUB_RUN_ATTEMPT'], os.environ['RUNNER_ARCH'].lower())
    assert os.environ['DEVFLOW_VERIFY_PROJECT'] == expected, 'foreign project'
    env_file = Path('deploy/.env')
    assert env_file.is_file() and not env_file.is_symlink() and not env_file.read_bytes(), 'requires empty, non-production env'
    # up starts the service but does not wait for HTTP readiness. Use the actual
    # deadline-bounded smoke condition, not a fixed startup delay.
    subprocess.run(['python3', 'smoke.py', os.environ['DEVFLOW_BASE_URL'],
                    '--expected-revision', os.environ['GITHUB_SHA']],
                   check=True, capture_output=True, timeout=45)
    name = 'devflow-diag-' + uuid.uuid4().hex
    literal = 'synthetic-Diagnostic-Literal-123'
    bearer = 'syntheticBearerCredential123'
    command = f'print("{literal}"); print("Authorization: Bearer {bearer}"); raise SystemExit(7)'
    env_file.write_text(f'SYNTHETIC_LITERAL={literal}\n')
    try:
        # Same exact temporary project, separate exited container. Never production.
        p = subprocess.run(['docker', 'run', '--name', name,
            '--label', f'com.docker.compose.project={expected}',
            '--label', 'com.docker.compose.service=diagnostic-probe',
            os.environ['DEVFLOW_IMAGE'], 'python3', '-c', command], capture_output=True, timeout=60)
        assert p.returncode == 7, 'synthetic container did not fail as intended'
        subprocess.run(['bash', '.devflow/capture.sh', expected, 'synthetic-failure'], check=True, timeout=120)
        root = Path('.devflow/diagnostics/synthetic-failure')
        payload = '\n'.join(p.read_text() for p in root.rglob('*') if p.is_file())
        assert literal not in payload and bearer not in payload, 'synthetic secret escaped redaction'
        states = [json.loads(line) for line in (root / 'state.jsonl').read_text().splitlines()]
        probe = next(s for s in states if s['service'] == 'diagnostic-probe')
        assert probe['state']['ExitCode'] == 7, 'missing actual failure State'
        logs = list((root / 'logs').glob('*.log'))
        assert logs and any('<REDACTED>' in p.read_text() for p in logs), 'missing masked logs'
        assert json.loads((root / 'health.json').read_text())['http_code'] == '200', 'wrong project health URL'
        record = {'source_sha': os.environ['GITHUB_SHA'], 'project': expected,
                  'runner_environment': os.environ['RUNNER_ENVIRONMENT'], 'result': 'PASS',
                  'actual_exit_code': 7, 'literal_redacted': True, 'bearer_redacted': True,
                  'health_code': 200, 'diagnostics': 'synthetic-failure/'}
        Path('.devflow/evidence/diagnostics-probe.json').write_text(json.dumps(record, indent=2) + '\n')
    finally:
        # Exact probe container only; cleanup.sh handles only this run's compose project.
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        env_file.write_text('')


if __name__ == '__main__':
    main()
