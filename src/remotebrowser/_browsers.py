from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any, Literal, TypedDict, Unpack
from urllib.parse import quote, urlsplit, urlunsplit

if TYPE_CHECKING:
    from ._client import RemoteBrowser, RequestOptions

__all__ = [
    "Browser",
    "BrowserConfig",
    "BrowserStatus",
    "BrowserStatusResponse",
    "Browsers",
    "Config",
]

BrowserStatus = Literal["starting", "running", "suspended", "error", "terminated"]


class BrowserStatusResponse(TypedDict):
    browser_id: str
    status: BrowserStatus


class Browser(TypedDict):
    browser_id: str
    status: BrowserStatus
    description: str
    os: str
    creation_timestamp: int | None
    """Milliseconds since the Unix epoch."""


class BrowserConfig(TypedDict):
    browser_id: str
    proxy: str | None


def _browser_path(browser_id: str, suffix: str = "") -> str:
    if not browser_id:
        raise ValueError("A browser id is required")
    return f"/api/v1/browsers/{quote(browser_id, safe='')}{suffix}"


class Config:
    """The settings of a browser that can change while it runs: `client.browsers.config`."""

    def __init__(self, client: RemoteBrowser) -> None:
        self._client = client

    def retrieve(self, browser_id: str, **options: Unpack[RequestOptions]) -> BrowserConfig:
        return self._client.get(_browser_path(browser_id, "/config"), **options)

    def update(self, browser_id: str, *, proxy: str | None, **options: Unpack[RequestOptions]) -> BrowserConfig:
        """Set the proxy, or None to connect directly. This closes all open connections of the browser."""
        return self._client.patch(_browser_path(browser_id, "/config"), body={"proxy": proxy}, **options)


class Browsers:
    """The browsers of the API key's workspace: `client.browsers`."""

    def __init__(self, client: RemoteBrowser) -> None:
        self._client = client
        self.config = Config(client)

    def create(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        os: Literal["debian-13", "ubuntu-26.04", "fedora-44", "windows-11"] | str | None = None,
        browser: Literal["chromium", "chrome"] | None = None,
        screen_resolution: Literal["full-hd", "wuxga", "qhd", "4k"] | None = None,
        screen_scale: Literal[100, 125, 150, 175, 200] | None = None,
        proxy: str | None = None,
        **options: Unpack[RequestOptions],
    ) -> BrowserStatusResponse:
        """Launch a browser. It is still starting when this returns.

        Every setting is optional; one left as None takes the server's default.

        Args:
            name: 1-80 characters. A random name is used if omitted.
            description: Up to 140 characters.
            os: The guest OS. Default debian-13.
            browser: Default chromium.
            screen_resolution: Default full-hd.
            screen_scale: In percent. Default 150.
            proxy: An http://, socks4:// or socks5:// URL. Default none.
        """
        params: dict[str, Any] = {
            "name": name,
            "description": description,
            "os": os,
            "browser": browser,
            "screen_resolution": screen_resolution,
            "screen_scale": screen_scale,
            "proxy": proxy,
        }
        body = {key: value for key, value in params.items() if value is not None}
        return self._client.post("/api/v1/browsers", body=body, **options)

    def retrieve(self, browser_id: str, **options: Unpack[RequestOptions]) -> Browser:
        return self._client.get(_browser_path(browser_id), **options)

    def list(self, **options: Unpack[RequestOptions]) -> builtins.list[str]:
        """IDs of the starting and running browsers in the workspace."""
        return self._client.get("/api/v1/browsers", **options)

    def delete(self, browser_id: str, **options: Unpack[RequestOptions]) -> BrowserStatusResponse:
        """Terminate a browser. This cannot be undone."""
        return self._client.delete(_browser_path(browser_id), **options)

    def suspend(self, browser_id: str, **options: Unpack[RequestOptions]) -> BrowserStatusResponse:
        return self._client.post(_browser_path(browser_id, "/suspend"), **options)

    def resume(self, browser_id: str, **options: Unpack[RequestOptions]) -> BrowserStatusResponse:
        return self._client.post(_browser_path(browser_id, "/resume"), **options)

    def connect_url(self, browser_id: str) -> str:
        """WebSocket URL of the CDP endpoint.

        The connection needs the API key in the Authorization header, see `client.auth_headers`.
        """
        url = urlsplit(self._client.base_url + _browser_path(browser_id, "/cdp"))
        scheme = "wss" if url.scheme == "https" else "ws"
        return urlunsplit(url._replace(scheme=scheme))
