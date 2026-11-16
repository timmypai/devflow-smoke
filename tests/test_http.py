import http.client
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
from pathlib import Path
import select
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from app import Handler, Server
from smoke import check


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ))
        os.environ.pop("DEVFLOW_REVISION", None)

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)

    def request(self, path):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            connection.close()

    def test_health(self):
        self.assertEqual(self.request("/health"), (200, "application/json", b'{"status":"ok"}'))

    def test_stats_first_and_consecutive_requests(self):
        for expected in (1, 2, 3):
            status, content_type, body = self.request("/stats")
            self.assertEqual((status, content_type), (200, "application/json"))
            payload = json.loads(body)
            self.assertEqual(payload, {"requests": expected})
            self.assertIs(type(payload["requests"]), int)

    def test_root(self):
        status, content_type, body = self.request("/")
        self.assertEqual((status, content_type), (200, "text/html; charset=utf-8"))
        html = body.decode("utf-8")
        self.assertIn("<!doctype html>", html)
        self.assertIn("hello devflow", html)
        self.assertIn("目前請求數", html)
        self.assertEqual(re.search(r'<output[^>]*>([0-9]+)</output>', html)[1], "1")

    def test_only_successful_gets_count_and_home_uses_same_snapshot(self):
        self.assertEqual(json.loads(self.request("/stats")[2]), {"requests": 1})
        for path in ("/health", "/version", "/missing"):
            self.request(path)
        html = self.request("/")[2].decode("utf-8")
        self.assertEqual(re.search(r'<output[^>]*>([0-9]+)</output>', html)[1], "4")
        self.assertEqual(json.loads(self.request("/stats")[2]), {"requests": 5})

    def test_concurrent_gets_do_not_lose_counts(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            responses = list(pool.map(self.request, ["/stats"] * 120))
        self.assertTrue(all(status == 200 and kind == "application/json" for status, kind, _ in responses))
        self.assertEqual(sorted(json.loads(body)["requests"] for _, _, body in responses), list(range(1, 121)))
        self.assertEqual(json.loads(self.request("/stats")[2]), {"requests": 121})

    def test_new_server_instances_are_isolated_and_reset(self):
        self.request("/health")
        for _ in range(2):
            with Server(("127.0.0.1", 0), Handler) as other:
                thread = threading.Thread(target=other.serve_forever)
                thread.start()
                try:
                    connection = http.client.HTTPConnection(*other.server_address, timeout=2)
                    try:
                        connection.request("GET", "/stats")
                        self.assertEqual(json.loads(connection.getresponse().read()), {"requests": 1})
                    finally:
                        connection.close()
                finally:
                    other.shutdown()
                    thread.join()
        self.assertEqual(json.loads(self.request("/stats")[2]), {"requests": 2})

    def test_unknown_paths(self):
        for path in ("/missing", "/health/", "/nope?x=1"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_health_with_extra_query(self):
        self.assertEqual(self.request("/health?extra=1"), (200, "application/json", b'{"status":"ok"}'))

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

    def test_process_restart_resets_counter_and_keeps_environments_isolated(self):
        def start(revision):
            process = subprocess.Popen(
                [sys.executable, "app.py"], cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, "PORT": "0", "DEVFLOW_REVISION": revision},
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            def stop():
                process.terminate()
                process.wait(timeout=5)
                process.stdout.close()
            self.addCleanup(stop)
            self.assertTrue(select.select([process.stdout], [], [], 5)[0])
            port = int(process.stdout.readline().strip().rsplit(":", 1)[1])
            return process, port

        def get(port, path):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                return json.loads(response.read())
            finally:
                connection.close()

        first, port = start("first")
        _, other = start("second")
        self.assertEqual(get(port, "/stats"), {"requests": 1})
        self.assertEqual(get(port, "/version"), {"revision": "first"})
        self.assertEqual(get(other, "/stats"), {"requests": 1})
        self.assertEqual(get(other, "/version"), {"revision": "second"})
        first.terminate()
        first.wait(timeout=5)
        _, restarted = start("restarted")
        self.assertEqual(get(restarted, "/stats"), {"requests": 1})
        self.assertEqual(get(restarted, "/version"), {"revision": "restarted"})
        self.assertEqual(get(other, "/stats"), {"requests": 3})


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

        with Server(("127.0.0.1", 0), VersionHandler) as server:
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

    def test_stats_rejects_non_integer_extra_keys_and_stale_snapshots(self):
        class StatsHandler(Handler):
            body = None

            def do_GET(self):
                if self.path != "/stats":
                    return super().do_GET()
                count = self.server.count_request()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                body = self.body if self.body is not None else f' {{ "requests" : {count} }} \n'.encode()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with Server(("127.0.0.1", 0), StatsHandler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_port}"
                check(base_url)  # Whitespace is not part of the JSON contract.
                for body in (b'{"requests":true}', b'{"requests":1.0}', b'{"requests":"1"}',
                             b'{"requests":-1}', b'{"requests":null}', b'{"requests":1,"extra":0}',
                             b'{}', b'[]', b'bad JSON', b'\xff', b'{"requests":0}'):
                    with self.subTest(body=body):
                        StatsHandler.body = body
                        with self.assertRaisesRegex(ValueError, "HTTP contract mismatch for /stats"):
                            check(base_url)
            finally:
                server.shutdown()
                thread.join()

    def test_rejects_wrong_status_type_and_body_on_each_endpoint(self):
        class BrokenHandler(Handler):
            broken_path = "/health"
            fault = "status"

            def do_GET(self):
                if self.path != self.broken_path:
                    return super().do_GET()
                content_type, body = {
                    "/health": ("application/json", b'{"status":"ok"}'),
                    "/stats": ("application/json", b'{"requests":1}'),
                    "/": ("text/html; charset=utf-8", '<!doctype html><h1>hello devflow</h1><label for="requests">目前請求數</label><output id="requests">2</output>'.encode()),
                }[self.path]
                self.send_response(503 if self.fault == "status" else 200)
                self.send_header("Content-Type", "text/plain" if self.fault == "type" else content_type)
                self.end_headers()
                self.wfile.write(b"invalid body" if self.fault == "body" else body)

            def log_message(self, *args):
                pass

        with Server(("127.0.0.1", 0), BrokenHandler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                for path in ("/health", "/", "/stats"):
                    for fault in ("status", "type", "body"):
                        with self.subTest(path=path, fault=fault):
                            BrokenHandler.broken_path, BrokenHandler.fault = path, fault
                            with self.assertRaisesRegex(ValueError, f"HTTP contract mismatch for {path}"):
                                check(f"http://127.0.0.1:{server.server_port}")
            finally:
                server.shutdown()
                thread.join()
