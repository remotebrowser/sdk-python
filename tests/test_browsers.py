from __future__ import annotations

import pytest
from conftest import FakeServer

from remotebrowser import RemoteBrowser


def test_maps_each_method_to_its_endpoint(server: FakeServer) -> None:
    client = RemoteBrowser(api_key="sk", base_url=server.url + "/")
    client.browsers.create()
    client.browsers.list()
    client.browsers.retrieve("B1")
    client.browsers.delete("B1")
    client.browsers.suspend("B1")
    client.browsers.resume("B1")
    client.browsers.config.retrieve("B1")
    client.browsers.config.update("B1", proxy=None)

    base = "/api/v1/browsers"
    assert [f"{r.method} {r.path}" for r in server.requests] == [
        f"POST {base}",
        f"GET {base}",
        f"GET {base}/B1",
        f"DELETE {base}/B1",
        f"POST {base}/B1/suspend",
        f"POST {base}/B1/resume",
        f"GET {base}/B1/config",
        f"PATCH {base}/B1/config",
    ]
    assert server.requests[0].body == b"{}"
    assert server.requests[4].body == b""
    assert server.requests[7].body == b'{"proxy": null}'


def test_create_sends_only_the_given_settings(server: FakeServer) -> None:
    client = RemoteBrowser(api_key="sk", base_url=server.url)
    client.browsers.create(name="qa", screen_scale=125, proxy="http://p:8080")
    assert server.requests[0].body == b'{"name": "qa", "screen_scale": 125, "proxy": "http://p:8080"}'


def test_escapes_browser_ids(server: FakeServer) -> None:
    client = RemoteBrowser(api_key="sk", base_url=server.url)
    client.browsers.retrieve("a/b")
    assert server.requests[0].path == "/api/v1/browsers/a%2Fb"


def test_rejects_a_missing_browser_id() -> None:
    client = RemoteBrowser(api_key="sk", base_url="http://h")
    with pytest.raises(ValueError, match="browser id"):
        client.browsers.retrieve("")


def test_builds_the_cdp_websocket_url() -> None:
    client = RemoteBrowser(api_key="sk", base_url="https://rb.example/")
    assert client.browsers.connect_url("B1") == "wss://rb.example/api/v1/browsers/B1/cdp"
    local = RemoteBrowser(api_key="sk", base_url="http://localhost:3000")
    assert local.browsers.connect_url("B1") == "ws://localhost:3000/api/v1/browsers/B1/cdp"
    assert local.auth_headers == {"Authorization": "Bearer sk"}
