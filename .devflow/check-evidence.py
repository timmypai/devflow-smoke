"""Fail closed: verification cannot pass without fresh real browser evidence."""
import json
from pathlib import Path
import re
import struct
import sys


def check(directory):
    root = Path(directory)
    contract = (root / 'contract.txt').read_text().strip()
    if contract not in ('stats', 'legacy'):
        raise ValueError('unknown evidence contract')
    modern = contract == 'stats'
    screenshot = 'AC-2.png' if modern else 'legacy-home.png'
    required = ['source-sha.txt', 'expected-revision.txt', 'runner.txt', 'phase.txt', 'http.log',
                'browser.log', screenshot, 'playwright.json', 'playwright-report/index.html', 'journeys.log']
    required += ['AC-1.log', 'AC-2.log', 'AC-2-http-dom.json'] if modern else ['legacy.txt', 'legacy-http.log', 'legacy-browser.log']
    for name in required:
        file = root / name
        if not file.is_file() or file.stat().st_size == 0:
            raise ValueError(f'missing required evidence: {name}')
    for name in ('source-sha.txt', 'expected-revision.txt'):
        if not re.fullmatch(r'[0-9a-f]{40}\n?', (root / name).read_text()):
            raise ValueError(f'invalid SHA evidence: {name}')
    phase = (root / 'phase.txt').read_text().strip()
    if phase not in ('candidate', 'rollback') or (not modern and phase != 'rollback'):
        raise ValueError('invalid evidence phase')
    png = (root / screenshot).read_bytes()
    if (len(png) < 45 or not png.startswith(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')
            or not all(struct.unpack('>II', png[16:24])) or png[-8:] != b'IEND\xaeB`\x82'):
        raise ValueError('invalid PNG evidence')
    report = json.loads((root / 'playwright.json').read_text())
    stats = report['stats']
    if stats['expected'] != 1 or any(stats[key] for key in ('unexpected', 'skipped', 'flaky')):
        raise ValueError(f'browser did not pass exactly one journey: {stats}')
    def titles(suites):
        for suite in suites:
            yield from (spec['title'] for spec in suite.get('specs', []))
            yield from titles(suite.get('suites', []))
    expected_title = ('AC-2 visible shared request count increases on refresh' if modern
                      else 'legacy rollback plain-text homepage (not stats ACs)')
    if list(titles(report.get('suites', []))) != [expected_title]:
        raise ValueError('wrong browser journey report')
    if modern:
        records = json.loads((root / 'AC-2-http-dom.json').read_text())
        snapshots = records[-1]['snapshots']
        counts = [snapshots[key] for key in ('before', 'first', 'middle', 'refreshed', 'after')]
        if not all(type(n) is int and n >= 0 for n in counts) or not all(a < b for a, b in zip(counts, counts[1:])):
            raise ValueError('invalid shared counter snapshots')
        if len([record for record in records if 'url' in record]) != 5 or len([record for record in records if 'dom' in record]) != 2:
            raise ValueError('missing HTTP/DOM observations')


if __name__ == '__main__':
    check(sys.argv[1])
