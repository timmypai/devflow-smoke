"""Minimal standard-library HTTP service."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            content_type, body = "application/json", b'{"status":"ok"}'
        elif self.path == "/version":
            content_type = "application/json"
            body = json.dumps({"revision": os.environ.get("DEVFLOW_REVISION", "unknown")}).encode("utf-8")
        elif self.path == "/":
            content_type, body = "text/plain; charset=utf-8", b"hello devflow"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    with ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler) as server:
        print(f"Listening on {server.server_address[0]}:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
