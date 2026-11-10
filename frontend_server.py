"""Serve the tracker UI separately from its Flask API backend."""

from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "5500"))
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "5051"))


class FrontendHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/config.js":
            body = f"window.DOC_TRACKER_API_BASE = 'http://127.0.0.1:{BACKEND_PORT}';\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path in {"/", "/index.html"}:
            self.path = "/templates/index.html"
        super().do_GET()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", FRONTEND_PORT), FrontendHandler)
    print(f"Document Tracker frontend: http://127.0.0.1:{FRONTEND_PORT}")
    server.serve_forever()
