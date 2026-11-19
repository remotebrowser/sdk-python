from __future__ import annotations

import json
import socket

import pytest
from conftest import FakeServer

import remotebrowser
from remotebrowser import (
    APIConnectionError,
    APIConnectionTimeoutError,
    NotFoundError,
    RateLimitError,
    RemoteBrowser,
    RemoteBrowserError,
)


def make_client(server: FakeServer, **kwargs: object) -> RemoteBrowser:
    return RemoteBrowser(api_key="sk-1", base_url=server.url, **kwargs)  # type: ignore[arg-type]


def test_reads_api_key_and_base_url_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMOTEBROWSER_API_KEY", "sk-env")
    monkeypatch.setenv("REMOTEBROWSER_URL", "http://env:3000/")
    client = RemoteBrowser()
    assert client.api_key == "sk-env"
    assert client.base_url == "http://env:3000"


def test_arguments_win_over_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMOTEBROWSER_API_KEY", "sk-env")
    client = RemoteBrowser(api_key="sk-arg", base_url="http://h")
    assert client.api_key == "sk-arg"


def test_requires_api_key_and_base_url() -> None:
    with pytest.raises(RemoteBrowserError, match="REMOTEBROWSER_API_KEY"):
        RemoteBrowser(base_url="http://h")
    with pytest.raises(RemoteBrowserError, match="REMOTEBROWSER_URL"):
        RemoteBrowser(api_key="sk")
    with pytest.raises(RemoteBrowserError, match="REMOTEBROWSER_API_KEY"):
        RemoteBrowser(api_key="", base_url="http://h")


def test_sends_the_bearer_token_and_json_body(server: FakeServer) -> None:
    server.respond(200, {"browser_id": "B1", "status": "starting"})
    client = make_client(server, default_headers={"X-Default": "d"})
    result = client.browsers.create(os="ubuntu-26.04", extra_headers={"X-Extra": "e"})
    assert result == {"browser_id": "B1", "status": "starting"}
    request = server.requests[0]
    assert request.method == "POST"
    assert request.path == "/api/v1/browsers"
    assert request.headers["Authorization"] == "Bearer sk-1"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["X-Default"] == "d"
    assert request.headers["X-Extra"] == "e"
    assert json.loads(request.body) == {"os": "ubuntu-26.04"}


def test_maps_status_codes_to_error_classes(server: FakeServer) -> None:
    client = make_client(server, max_retries=0)
    cases = [
        (400, remotebrowser.BadRequestError),
        (401, remotebrowser.AuthenticationError),
        (403, remotebrowser.PermissionDeniedError),
        (404, remotebrowser.NotFoundError),
        (409, remotebrowser.ConflictError),
        (422, remotebrowser.UnprocessableEntityError),
        (429, remotebrowser.RateLimitError),
        (500, remotebrowser.InternalServerError),
        (503, remotebrowser.InternalServerError),
        (418, remotebrowser.APIError),
    ]
    for status, error_class in cases:
        server.respond(status, {"error": "nope"})
        with pytest.raises(error_class) as info:
            client.browsers.list()
        assert type(info.value) is error_class
        assert info.value.status == status
        assert info.value.body == {"error": "nope"}
        assert str(info.value) == f"{status} nope"


def test_keeps_a_plain_text_error_body(server: FakeServer) -> None:
    server.respond(404, raw=b"Not Found")
    with pytest.raises(NotFoundError, match=r"^404 Not Found$") as info:
        make_client(server).browsers.retrieve("B1")
    assert info.value.body == "Not Found"


def test_conflict_error_has_the_browser_status(server: FakeServer) -> None:
    server.respond(409, {"error": "Only a suspended browser can be resumed.", "browser_id": "B1", "status": "running"})
    with pytest.raises(remotebrowser.ConflictError) as info:
        make_client(server).browsers.resume("B1")
    assert info.value.body["status"] == "running"
    assert len(server.requests) == 1


def test_retries_429_using_retry_after(server: FakeServer, sleeps: list[float]) -> None:
    server.respond(429, {}, headers={"Retry-After": "3"})
    server.respond(200, ["B1"])
    assert make_client(server).browsers.list() == ["B1"]
    assert sleeps == [3.0]
    assert len(server.requests) == 2


def test_retries_5xx_with_backoff_and_gives_up_after_max_retries(server: FakeServer, sleeps: list[float]) -> None:
    for _ in range(3):
        server.respond(503, {"error": "busy"})
    with pytest.raises(remotebrowser.InternalServerError):
        make_client(server).browsers.list()
    assert len(server.requests) == 3
    assert len(sleeps) == 2
    assert 0.375 <= sleeps[0] <= 0.5
    assert 0.75 <= sleeps[1] <= 1.0


def test_max_retries_per_request(server: FakeServer, sleeps: list[float]) -> None:
    server.respond(500)
    with pytest.raises(remotebrowser.InternalServerError):
        make_client(server).browsers.list(max_retries=0)
    assert len(server.requests) == 1


def test_wraps_network_failures(sleeps: list[float]) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = RemoteBrowser(api_key="sk", base_url=f"http://127.0.0.1:{port}")
    with pytest.raises(APIConnectionError, match="Connection error"):
        client.browsers.list()
    assert len(sleeps) == 2


def test_times_out(server: FakeServer, sleeps: list[float]) -> None:
    server.respond(200, [], delay=1)
    with pytest.raises(APIConnectionTimeoutError, match="timed out"):
        make_client(server, max_retries=0).browsers.list(timeout=0.1)


def test_rate_limit_error_is_exported() -> None:
    assert issubclass(RateLimitError, remotebrowser.APIError)
    assert issubclass(remotebrowser.APIError, RemoteBrowserError)
