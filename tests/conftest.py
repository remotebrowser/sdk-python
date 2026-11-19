from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from remotebrowser import _client


@dataclass
class Request:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Response:
    status: int = 200
    body: Any = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0
    raw: bytes | None = None


class FakeServer:
    """An HTTP server that answers with queued responses and records the requests."""

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.responses: list[Response] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def handle_request(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                server.requests.append(
                    Request(self.command, self.path, dict(self.headers.items()), self.rfile.read(length))
                )
                response = server.responses.pop(0) if server.responses else Response()
                time.sleep(response.delay)
                data = response.raw if response.raw is not None else json.dumps(response.body).encode()
                try:
                    self.send_response(response.status)
                    for name, value in response.headers.items():
                        self.send_header(name, value)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # The client gave up, as a timeout test wants.

            do_GET = do_POST = do_PATCH = do_DELETE = handle_request

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def respond(self, status: int = 200, body: Any = None, **kwargs: Any) -> None:
        self.responses.append(Response(status, {} if body is None else body, **kwargs))

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server() -> Iterator[FakeServer]:
    fake = FakeServer()
    yield fake
    fake.close()


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Skip the waits between retries, and record them."""
    recorded: list[float] = []
    monkeypatch.setattr(_client, "_sleep", recorded.append)
    return recorded


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REMOTEBROWSER_API_KEY", raising=False)
    monkeypatch.delenv("REMOTEBROWSER_URL", raising=False)
