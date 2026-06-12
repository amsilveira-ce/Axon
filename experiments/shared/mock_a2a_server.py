"""
Reusable mock A2A HTTP server for experiments.

Usage:
    server = MockA2AServer(port=18041, card=some_dict)
    server.start()
    ...
    server.stop()

Or as a context manager:
    with MockA2AServer(port=18041, card=some_dict) as server:
        url = server.url
        ...
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

CARD_PATHS = ("/.well-known/agent-card.json", "/.well-known/agent.json")


class MockA2AServer:
    def __init__(self, port: int, card: dict) -> None:
        self.port = port
        self.card = card
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        card = self.card

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path in CARD_PATHS:
                    body = json.dumps(card).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

        self._server = HTTPServer(("127.0.0.1", self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()   # libera a porta — permite restart no mesmo port
            self._server = None

    def __enter__(self) -> "MockA2AServer":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()
