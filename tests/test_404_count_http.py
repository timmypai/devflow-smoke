"""Black-box 404 counting regression, independently selectable on base and head."""

import http.client
import json
import threading
import unittest

from app import Handler, Server


class NotFoundCountHTTPTests(unittest.TestCase):
    def test_404_requests_do_not_increment_stats(self):
        server = Server(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        def get(path, expected_status):
            connection = http.client.HTTPConnection(*server.server_address, timeout=2)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                body = response.read()
                self.assertEqual(response.status, expected_status)
                return body
            finally:
                connection.close()

        before = json.loads(get("/stats", 200))["requests"]
        get("/nope", 404)
        get("/nope?x=1", 404)
        after = json.loads(get("/stats", 200))["requests"]
        # The second successful /stats request counts itself; neither 404 does.
        self.assertEqual(after, before + 1)
