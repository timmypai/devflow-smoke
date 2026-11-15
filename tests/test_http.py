import http.client
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import Handler
from smoke import check


class HTTPTests(unittest.TestCase):
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
