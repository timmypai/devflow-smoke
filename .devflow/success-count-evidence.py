#!/usr/bin/env python3
"""Exact live HTTP counter observations; shared by PR and deployment journeys."""

import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.request import urlopen


def get(base, path, status, content_type=None):
    try:
        response = urlopen(base.rstrip('/') + path, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        body = response.read().decode('utf-8')
        observation = {'path': path, 'status': response.status,
                       'content_type': response.headers.get('Content-Type'), 'body': body}
    assert observation['status'] == status, observation
    if content_type:
        assert observation['content_type'] == content_type, observation
    return observation


def main():
    out = Path(os.environ['DEVFLOW_EVIDENCE']) / 'no-proof'
    out.mkdir(parents=True, exist_ok=True)
    base = os.environ['DEVFLOW_BASE_URL']
    record = {'id': 'NO-PROOF-AC-1', 'covers': ['AC-1', 'AC-4'], 'epic': 't_b0023bda',
              'source_sha': os.environ['GITHUB_SHA'],
              'expected_revision': os.environ['DEVFLOW_EXPECTED_REVISION'],
              'run_id': os.environ.get('GITHUB_RUN_ID'),
              'phase': os.environ.get('DEVFLOW_VERIFY_PHASE'), 'base_url': base,
              'attempts': [], 'result': 'FAIL',
              'criterion': 'root = before + 1; after = before + 2; three 404s add zero. '
                           'Concurrent successful requests can only increase the deltas; '
                           'retry at most 20 windows, never loosen equality or stop healthchecks.'}
    try:
        revision = get(base, '/version', 200, 'application/json')
        record['version'] = revision
        assert json.loads(revision['body']) == {'revision': record['expected_revision']}, revision
        for _ in range(20):
            observations = []
            record['attempts'].append({'observations': observations})
            for path, status, kind in (
                ('/stats', 200, 'application/json'),
                ('/nope', 404, None), ('/nope?x=1', 404, None), ('/health/?x=1', 404, None),
                ('/', 200, 'text/html; charset=utf-8'), ('/stats', 200, 'application/json'),
            ):
                observations.append(get(base, path, status, kind))
            before, after = (json.loads(observations[i]['body']) for i in (0, -1))
            for payload in (before, after):
                assert set(payload) == {'requests'} and type(payload['requests']) is int, payload
            html = observations[-2]['body']
            assert 'hello devflow' in html and '目前請求數' in html, html
            match = re.search(r'<output id="requests">([0-9]+)</output>', html)
            assert match is not None, html
            counts = [before['requests'], int(match[1]), after['requests']]
            record['attempts'][-1]['snapshots'] = counts
            if counts[1] == counts[0] + 1 and counts[2] == counts[0] + 2:
                record['result'] = 'PASS'
                break
        assert record['result'] == 'PASS', record
    finally:
        (out / 'NO-PROOF-AC-1.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(f'NO-PROOF-AC-1: PASS; source={record["source_sha"]}; snapshots={counts}; '
          f'windows={len(record["attempts"])}')


if __name__ == '__main__':
    main()
