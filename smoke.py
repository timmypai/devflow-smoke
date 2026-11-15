"""Verify the HTTP contract from the host, without third-party dependencies."""

import argparse
import http.client
import json
import time
from urllib.parse import urlsplit


def check(base_url, timeout=30, expected_revision=None):
    url = urlsplit(base_url)
    if url.scheme != "http" or not url.hostname or url.path not in ("", "/"):
        raise ValueError("expected an http://host:port base URL")
    deadline = time.monotonic() + timeout
    endpoints = [
        ("/health", "application/json", b'{"status":"ok"}'),
        ("/", "text/plain; charset=utf-8", b"hello devflow"),
    ]
    if expected_revision is not None:
        endpoints.append(("/version", "application/json", {"revision": expected_revision}))
    for path, expected_type, expected_body in endpoints:
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
                time.sleep(0.2)
            finally:
                connection.close()
        print(f"GET {path}: status={status} content-type={content_type!r} body={body!r}", flush=True)
        if path == "/version":
            try:
                body = json.loads(body)
            except (ValueError, UnicodeError) as error:
                raise ValueError(f"HTTP contract mismatch for {path}: invalid JSON") from error
        if (status, content_type, body) != (200, expected_type, expected_body):
            raise ValueError(f"HTTP contract mismatch for {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--expected-revision")
    args = parser.parse_args()
    check(args.base_url, expected_revision=args.expected_revision)
