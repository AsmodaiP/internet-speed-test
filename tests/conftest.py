"""A small local HTTP server so tests never touch the internet."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest


@dataclass
class RequestRecord:
    path: str
    headers: dict[str, str]
    client_port: int
    started: float
    finished: float = 0.0


@dataclass
class ServerState:
    records: list[RequestRecord] = field(default_factory=list)
    hits: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # so keep-alive is possible
    server: LocalServer

    def log_message(self, *args: Any) -> None:  # keep pytest output clean
        pass

    def do_GET(self) -> None:
        state = self.server.state
        record = RequestRecord(
            path=self.path,
            headers=dict(self.headers),
            client_port=self.client_address[1],
            started=perf_counter(),
        )
        with state.lock:
            state.hits += 1
            hit = state.hits
            state.records.append(record)  # visible before any byte reaches the client

        parts = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        route = parts.path

        if route == "/file":
            time.sleep(float(query.get("delay", 0)))
            self._send_body(b"x" * int(query.get("size", 1000)))
        elif route == "/chunked":
            self._send_chunked(b"a" * 300, b"b" * 200, terminate=True)
        elif route == "/chunked-truncated":
            # One chunk, then hang up without the terminating 0-chunk.
            self._send_chunked(b"a" * 300, terminate=False)
            self.close_connection = True
        elif route == "/slow":
            # 1000 bytes in 10 pieces with a pause between them: slow but never idle.
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            for _ in range(10):
                self.wfile.write(b"s" * 100)
                self.wfile.flush()
                time.sleep(float(query.get("interval", 0.05)))
        elif route == "/redirect":
            self._redirect("/file?size=500")
        elif route == "/redirect-loop":
            self._redirect("/redirect-loop")
        elif route == "/redirect-nowhere":
            self.send_response(302)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif route.startswith("/status/"):
            self._send_body(b"error body", status=int(route.rsplit("/", 1)[1]))
        elif route == "/flaky":
            # Fails with HTTP 500 on exactly one hit, given by ?fail_on=N.
            if hit == int(query.get("fail_on", 0)):
                self._send_body(b"boom", status=500)
            else:
                self._send_body(b"y" * 100)
        elif route == "/truncated":
            # Announce 1000 bytes, send 400, hang up.
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"z" * 400)
            self.wfile.flush()
            self.close_connection = True
        else:
            self._send_body(b"not found", status=404)

        record.finished = perf_counter()

    def _send_body(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_chunked(self, *pieces: bytes, terminate: bool) -> None:
        self.send_response(200)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for piece in pieces:
            self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
        if terminate:
            self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False  # do not wait for handlers still sleeping in timeout tests
    allow_reuse_address = True

    scheme = "http"

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.state = ServerState()

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A client that timed out and left is expected in some tests; anything
        # else is a bug in a route and should be visible.
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)

    def url(self, path: str) -> str:
        host, port = self.server_address[:2]
        return f"{self.scheme}://{host}:{port}{path}"

    @property
    def records(self) -> list[RequestRecord]:
        with self.state.lock:
            return list(self.state.records)


@pytest.fixture
def server() -> Iterator[LocalServer]:
    srv = LocalServer()
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
