"""Verify the HTTP contract from the host, without third-party dependencies."""

import argparse
import http.client
import json
import re
import time
from urllib.parse import urlsplit


def check(base_url, timeout=30, expected_revision=None, legacy_home=False):
    url = urlsplit(base_url)
    if url.scheme != "http" or not url.hostname or url.path not in ("", "/"):
        raise ValueError("expected an http://host:port base URL")
    deadline = time.monotonic() + timeout

    def get(path, expected_type):
        while True:
            connection = http.client.HTTPConnection(url.hostname, url.port, timeout=2)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                status = response.status
                content_type = response.getheader("Content-Type")
                body = response.read()
                break
            except (OSError, http.client.HTTPException):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)  # devflow: allow no-sleep-fix L-0001
            finally:
                connection.close()
        print(f"GET {path}: status={status} content-type={content_type!r} body={body!r}", flush=True)
        if (status, content_type) != (200, expected_type):
            raise ValueError(f"HTTP contract mismatch for {path}")
        return body

    def stats():
        body = get("/stats", "application/json")
        try:
            payload = json.loads(body)
            valid = (isinstance(payload, dict) and set(payload) == {"requests"}
                     and type(payload["requests"]) is int and payload["requests"] >= 0)
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            raise ValueError("HTTP contract mismatch for /stats")
        return payload["requests"]

    before = None if legacy_home else stats()
    if get("/health", "application/json") != b'{"status":"ok"}':
        raise ValueError("HTTP contract mismatch for /health")
    if legacy_home:
        if get("/", "text/plain; charset=utf-8") != b"hello devflow":
            raise ValueError("HTTP contract mismatch for /")
    else:
        html = get("/", "text/html; charset=utf-8").decode("utf-8")
        count = re.search(r'<output id="requests">([0-9]+)</output>', html)
        if (not html.startswith("<!doctype html>") or '<h1>hello devflow</h1>' not in html
                or '<label for="requests">目前請求數</label>' not in html or count is None):
            raise ValueError("HTTP contract mismatch for /")
        home = int(count[1])
        after = stats()
        if not before < home < after:
            raise ValueError("HTTP contract mismatch for /stats: snapshots did not increase")
        print(f"Shared counter snapshots: stats={before} < home={home} < stats={after}", flush=True)
    if expected_revision is not None:
        try:
            version = json.loads(get("/version", "application/json"))
        except (ValueError, UnicodeError) as error:
            raise ValueError("HTTP contract mismatch for /version: invalid JSON") from error
        if version != {"revision": expected_revision}:
            raise ValueError("HTTP contract mismatch for /version")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--expected-revision")
    parser.add_argument("--legacy-home", action="store_true", help="explicit old-image rollback only")
    args = parser.parse_args()
    check(args.base_url, expected_revision=args.expected_revision, legacy_home=args.legacy_home)
