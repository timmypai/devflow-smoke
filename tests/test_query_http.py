"""HTTP regression kept self-contained for the lesson gate's base overlay."""

import http.client
import json
import threading
import unittest

from app import Handler, Server


class QueryHTTPTests(unittest.TestCase):
    def start_server(self):
        server = Server(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        return server

    def request(self, server, path):
        connection = http.client.HTTPConnection(*server.server_address, timeout=2)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            connection.close()

    def test_query_routes_preserve_http_content_and_get_counts(self):
        for path in ("/stats", "/version", "/health", "/"):
            with self.subTest(path=path):
                plain, query = self.start_server(), self.start_server()
                for server in (plain, query):
                    for before, status in (("/health", 200), ("/version", 200), ("/nope", 404)):
                        self.assertEqual(self.request(server, before)[0], status)
                expected = self.request(plain, path)
                actual = self.request(query, path + "?x=1")
                self.assertEqual(actual[0], 200)
                self.assertEqual(actual, expected)  # Raw bytes, including dynamic counts.
                if path == "/stats":
                    self.assertEqual(json.loads(actual[2]), {"requests": 3})
                if path == "/":
                    self.assertIn(b'<output id="requests">3</output>', actual[2])
                for server in (plain, query):
                    self.assertEqual(self.request(server, "/nope?x=1")[0], 404)
                    self.assertEqual(json.loads(self.request(server, "/stats")[2]), {"requests": 4})
