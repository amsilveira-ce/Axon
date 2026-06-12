"""
Reusable mock MCP HTTP server for experiments.

It does NOT implement the MCP protocol — it only counts incoming HTTP
requests. Experiment 3 uses it to prove the credential boundary: the GA's
integrity monitor must make ZERO requests to MCP endpoints, so the counter
staying at 0 after a full health cycle is the assertion.

Usage:
    with CountingMockServer(port=18062) as server:
        ...register an MCP resource pointing at server.url...
        run_cycle(paths)
        assert server.hits == 0
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class CountingMockServer:
    def __init__(self, port: int) -> None:
        self.port = port
        self._hits = 0
        self._lock = threading.Lock()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def hits(self) -> int:
        with self._lock:
            return self._hits

    def start(self) -> None:
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _count(self):
                with outer._lock:
                    outer._hits += 1
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            do_GET = do_POST = do_HEAD = _count

        self._server = HTTPServer(("127.0.0.1", self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> "CountingMockServer":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()
