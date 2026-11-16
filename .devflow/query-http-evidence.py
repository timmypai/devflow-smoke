#!/usr/bin/env python3
"""Real query journeys shared by PR CI and Oracle post-deploy verification."""

import http.client
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


def main():
    evidence_id = sys.argv[1]
    if evidence_id not in ('LESSON-GATE-AC-2', 'LESSON-GATE-AC-4'):
        raise ValueError('unknown query journey')
    out = Path(os.environ['DEVFLOW_EVIDENCE']) / 'lesson-gate'
    out.mkdir(parents=True, exist_ok=True)
    base = urlsplit(os.environ['DEVFLOW_BASE_URL'])
    observations = []
    record = {'id': evidence_id, 'epic': 't_32d348de',
        'source_sha': os.environ['GITHUB_SHA'],
        'expected_revision': os.environ['DEVFLOW_EXPECTED_REVISION'],
        'run_id': os.environ.get('GITHUB_RUN_ID'),
        'phase': os.environ.get('DEVFLOW_VERIFY_PHASE'),
        'base_url': os.environ['DEVFLOW_BASE_URL'], 'observations': observations,
        'content_equivalence': 'Raw bytes and Content-Type compared on isolated real servers by tests/test_query_http.py',
        'counter_semantics': 'Each GET counts, including errors; live snapshots strictly increase (other clients may interleave).',
        'result': 'FAIL'}

    def get(path, status=200, content_type=None):
        cls = http.client.HTTPSConnection if base.scheme == 'https' else http.client.HTTPConnection
        connection = cls(base.hostname, base.port, timeout=5)
        try:
            connection.request('GET', base.path.rstrip('/') + path)
            response = connection.getresponse()
            body = response.read()
            kind = response.getheader('Content-Type')
            observations.append({'path': path, 'status': response.status,
                                 'content_type': kind, 'body': body.decode('utf-8')})
            assert response.status == status, observations[-1]
            if content_type:
                assert kind == content_type, observations[-1]
            return body
        finally:
            connection.close()

    def count(path):
        payload = json.loads(get(path, content_type='application/json'))
        assert set(payload) == {'requests'}, payload
        value = payload['requests']
        assert type(value) is int and value > 0, payload
        return value

    try:
        before = count('/stats')
        query = count('/stats?x=1')
        for path in ('/version', '/version?x=1'):
            assert json.loads(get(path, content_type='application/json')) == {
                'revision': record['expected_revision']}
        for path in ('/health', '/health?x=1'):
            assert get(path, content_type='application/json') == b'{"status":"ok"}'
        snapshots = [before, query]
        for path in ('/', '/?x=1'):
            body = get(path, content_type='text/html; charset=utf-8')
            assert b'hello devflow' in body
            match = re.search(rb'<output id="requests">([0-9]+)</output>', body)
            assert match is not None, body
            snapshots.append(int(match[1]))
        get('/nope?x=1', 404)
        get('/health/?x=1', 404)
        snapshots.append(count('/stats'))
        assert all(a < b for a, b in zip(snapshots, snapshots[1:])), snapshots
        record['snapshots'] = snapshots
        record['result'] = 'PASS'
    finally:
        (out / f'{evidence_id}.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'{evidence_id}: PASS; source={record["source_sha"]}; snapshots={snapshots}')


if __name__ == '__main__':
    main()
