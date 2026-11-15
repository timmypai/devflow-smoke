"""Fail closed: verification cannot pass without fresh real browser evidence."""
import json
from pathlib import Path
import sys


def check(directory):
    root = Path(directory)
    for name in ('source-sha.txt', 'expected-revision.txt', 'runner.txt', 'http.log',
                 'browser.log', 'baseline-home.png', 'playwright.json', 'playwright-report/index.html'):
        file = root / name
        if not file.is_file() or file.stat().st_size == 0:
            raise ValueError(f'missing required evidence: {name}')
    if not (root / 'baseline-home.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('invalid PNG evidence')
    report = json.loads((root / 'playwright.json').read_text())
    stats = report['stats']
    if stats['expected'] != 1 or any(stats[key] for key in ('unexpected', 'skipped', 'flaky')):
        raise ValueError(f'browser did not pass exactly one baseline journey: {stats}')


if __name__ == '__main__':
    check(sys.argv[1])
