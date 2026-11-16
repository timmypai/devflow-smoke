"""Minimal standard-library HTTP service."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Server(ThreadingHTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests = 0
        self.requests_lock = threading.Lock()

    def count_request(self):
        with self.requests_lock:
            self.requests += 1
            return self.requests


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        requests = self.server.count_request()
        path = self.path.partition("?")[0]
        if path == "/health":
            content_type, body = "application/json", b'{"status":"ok"}'
        elif path == "/version":
            content_type = "application/json"
            body = json.dumps({"revision": os.environ.get("DEVFLOW_REVISION", "unknown")}).encode("utf-8")
        elif path == "/":
            content_type = "text/html; charset=utf-8"
            body = f'''<!doctype html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>hello devflow</title></head>
<body><main><h1>hello devflow</h1>
<p><label for="requests">目前請求數</label>：<output id="requests">{requests}</output></p>
<p>此數字為本次請求的快照，重新整理頁面即可更新。</p>
</main></body></html>'''.encode("utf-8")
        elif path == "/stats":
            content_type = "application/json"
            body = json.dumps({"requests": requests}).encode("utf-8")
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    with Server(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler) as server:
        print(f"Listening on {server.server_address[0]}:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
