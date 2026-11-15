"""Verify the HTTP contract from the host, without third-party dependencies."""

import argparse
import http.client
import time
from urllib.parse import urlsplit


def check(base_url, timeout=30):
    url = urlsplit(base_url)
    if url.scheme != "http" or not url.hostname or url.path not in ("", "/"):
        raise ValueError("expected an http://host:port base URL")
    deadline = time.monotonic() + timeout
    for path, expected_type, expected_body in (
        ("/health", "application/json", b'{"status":"ok"}'),
        ("/", "text/plain; charset=utf-8", b"hello devflow"),
    ):
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
        if (status, content_type, body) != (200, expected_type, expected_body):
            raise ValueError(f"HTTP contract mismatch for {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    args = parser.parse_args()
    check(args.base_url)
