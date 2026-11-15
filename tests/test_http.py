import http.client
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from app import Handler
from smoke import check


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ))
        os.environ.pop("DEVFLOW_REVISION", None)

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def request(self, path):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        self.addCleanup(connection.close)
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.getheader("Content-Type"), response.read()

    def test_health(self):
        self.assertEqual(self.request("/health"), (200, "application/json", b'{"status":"ok"}'))

    def test_root(self):
        self.assertEqual(self.request("/"), (200, "text/plain; charset=utf-8", b"hello devflow"))

    def test_unknown_paths(self):
        for path in ("/missing", "/health/", "/health?extra=1"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_smoke(self):
        check(f"http://127.0.0.1:{self.server.server_port}")

    def assert_version(self, expected):
        status, content_type, body = self.request("/version")
        self.assertEqual((status, content_type), (200, "application/json"))
        self.assertEqual(json.loads(body), {"revision": expected})

    def test_version_environment_value(self):
        os.environ["DEVFLOW_REVISION"] = "a" * 40
        self.assert_version("a" * 40)

    def test_version_missing_environment(self):
        self.assert_version("unknown")

    def test_version_empty_environment(self):
        os.environ["DEVFLOW_REVISION"] = ""
        self.assert_version("")

    def test_version_json_escaping(self):
        revision = '引號"、反斜線\\、換行\n\t\r'
        os.environ["DEVFLOW_REVISION"] = revision
        self.assert_version(revision)

    def test_version_smoke_and_cli(self):
        base_url = f"http://127.0.0.1:{self.server.server_port}"
        for revision in ("a" * 40, "", '測試"\\\n'):
            with self.subTest(revision=revision):
                os.environ["DEVFLOW_REVISION"] = revision
                check(base_url, 2, expected_revision=revision)
                result = subprocess.run(
                    [sys.executable, "smoke.py", base_url, "--expected-revision", revision],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            [sys.executable, "smoke.py", base_url, "--expected-revision", "wrong"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTP contract mismatch for /version", result.stderr)

    def test_port_environment_in_real_process(self):
        process = subprocess.Popen(
            [sys.executable, "app.py"],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "PORT": "0"},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0], "server did not start")
            address = process.stdout.readline().strip()
            self.assertTrue(address.startswith("Listening on 0.0.0.0:"), address)
            port = int(address.rsplit(":", 1)[1])
            self.assertGreater(port, 0)
            check(f"http://127.0.0.1:{port}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()


class SmokeTests(unittest.TestCase):
    def test_version_contract_and_legacy_compatibility(self):
        class VersionHandler(Handler):
            status = 200
            content_type = "application/json"
            body = b'{"revision":"expected"}'
            version_requests = 0

            def do_GET(self):
                if self.path != "/version":
                    return super().do_GET()
                type(self).version_requests += 1
                self.send_response(self.status)
                self.send_header("Content-Type", self.content_type)
                self.end_headers()
                self.wfile.write(self.body)

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), VersionHandler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_port}"
                check(base_url, expected_revision="expected")
                # JSON formatting is not part of the /version contract.
                VersionHandler.body = b'{ "revision" : "expected" }\n'
                check(base_url, expected_revision="expected")
                for status, content_type, body in (
                    (201, "application/json", b'{"revision":"expected"}'),
                    (404, "application/json", b'{"revision":"expected"}'),
                    (200, "text/plain", b'{"revision":"expected"}'),
                    (200, "application/json", b'{"revision":"wrong"}'),
                    (200, "application/json", b'{}'),
                    (200, "application/json", b'{"revision":"expected","extra":1}'),
                    (200, "application/json", b'{"revision":null}'),
                    (200, "application/json", b'[]'),
                    (200, "application/json", b'not JSON'),
                    (200, "application/json", b'\xff'),
                ):
                    with self.subTest(status=status, content_type=content_type, body=body):
                        VersionHandler.status, VersionHandler.content_type, VersionHandler.body = status, content_type, body
                        with self.assertRaisesRegex(ValueError, "HTTP contract mismatch for /version"):
                            check(base_url, expected_revision="expected")
                VersionHandler.status = 404
                before = VersionHandler.version_requests
                check(base_url)
                self.assertEqual(VersionHandler.version_requests, before)
            finally:
                server.shutdown()
                thread.join()

    def test_rejects_wrong_status_type_and_body_on_each_endpoint(self):
        class BrokenHandler(BaseHTTPRequestHandler):
            broken_path = "/health"
            fault = "status"

            def do_GET(self):
                content_type, body = (
                    ("application/json", b'{"status":"ok"}') if self.path == "/health"
                    else ("text/plain; charset=utf-8", b"hello devflow")
                )
                broken = self.path == self.broken_path
                self.send_response(503 if broken and self.fault == "status" else 200)
                self.send_header("Content-Type", "text/html" if broken and self.fault == "type" else content_type)
                self.end_headers()
                self.wfile.write(body + b"\n" if broken and self.fault == "body" else body)

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), BrokenHandler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                for path in ("/health", "/"):
                    for fault in ("status", "type", "body"):
                        with self.subTest(path=path, fault=fault):
                            BrokenHandler.broken_path, BrokenHandler.fault = path, fault
                            with self.assertRaisesRegex(ValueError, "HTTP contract mismatch"):
                                check(f"http://127.0.0.1:{server.server_port}")
            finally:
                server.shutdown()
                thread.join()
