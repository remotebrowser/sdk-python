from __future__ import annotations

import http.client
import itertools
import json
import os
import random
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from email.message import Message
from typing import Any, TypedDict

from ._browsers import Browsers
from ._errors import (
    APIConnectionError,
    APIConnectionTimeoutError,
    APIError,
    RemoteBrowserError,
    make_status_error,
)
from ._version import __version__

__all__ = ["DEFAULT_MAX_RETRIES", "DEFAULT_TIMEOUT", "RemoteBrowser", "RequestOptions"]

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRY_DELAY = 60.0

# Tests replace this to skip the waits between retries.
_sleep = time.sleep


class RequestOptions(TypedDict, total=False):
    """Options that every API method takes as keyword arguments."""

    timeout: float
    """Seconds to wait for the server, per attempt."""
    max_retries: int
    extra_headers: Mapping[str, str]


class RemoteBrowser:
    """Client for the Remote Browser REST API.

    Args:
        api_key: Defaults to the REMOTEBROWSER_API_KEY environment variable.
        base_url: Defaults to the REMOTEBROWSER_URL environment variable.
        timeout: Seconds to wait for the server, per attempt. Default 60.
        max_retries: How many times to retry a failed request. Default 2.
        default_headers: Headers to send with every request.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: Mapping[str, str] | None = None,
    ) -> None:
        if api_key is None:
            api_key = os.environ.get("REMOTEBROWSER_API_KEY")
        if not api_key:
            raise RemoteBrowserError(
                "The REMOTEBROWSER_API_KEY environment variable is missing or empty; either provide it, "
                "or pass the `api_key` argument to the RemoteBrowser client."
            )
        if base_url is None:
            base_url = os.environ.get("REMOTEBROWSER_URL")
        if not base_url:
            raise RemoteBrowserError(
                "The REMOTEBROWSER_URL environment variable is missing or empty; either provide it, "
                "or pass the `base_url` argument to the RemoteBrowser client."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.default_headers = dict(default_headers or {})

        self.browsers = Browsers(self)

    @property
    def auth_headers(self) -> dict[str, str]:
        """Headers for connections the SDK does not make itself, such as CDP over WebSocket."""
        return {"Authorization": f"Bearer {self.api_key}"}

    def get(self, path: str, *, body: Any = None, **options: Any) -> Any:
        return self.request("GET", path, body=body, **options)

    def post(self, path: str, *, body: Any = None, **options: Any) -> Any:
        return self.request("POST", path, body=body, **options)

    def patch(self, path: str, *, body: Any = None, **options: Any) -> Any:
        return self.request("PATCH", path, body=body, **options)

    def delete(self, path: str, *, body: Any = None, **options: Any) -> Any:
        return self.request("DELETE", path, body=body, **options)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Send a request and return the parsed JSON response.

        A body of None sends no body. Raises an APIError subclass on failure.
        """
        retries = self.max_retries if max_retries is None else max_retries
        for attempt in itertools.count():
            try:
                return self._make_request(
                    method,
                    path,
                    body=body,
                    timeout=self.timeout if timeout is None else timeout,
                    extra_headers=extra_headers,
                )
            except APIError as err:
                if attempt >= retries or not _should_retry(err):
                    raise
                _sleep(_retry_delay(err, attempt))

    def _make_request(
        self,
        method: str,
        path: str,
        *,
        body: Any,
        timeout: float,
        extra_headers: Mapping[str, str] | None,
    ) -> Any:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"remotebrowser-python/{__version__}",
            **self.auth_headers,
            **self.default_headers,
            **(extra_headers or {}),
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()

        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        response_headers: Message | None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status = response.status
                response_headers = response.headers
                raw = response.read()
        except urllib.error.HTTPError as err:
            status = err.code
            response_headers = err.headers
            try:
                raw = err.read()
            except OSError:
                raw = b""
        except TimeoutError as err:
            raise APIConnectionTimeoutError() from err
        except urllib.error.URLError as err:
            if isinstance(err.reason, TimeoutError):
                raise APIConnectionTimeoutError() from err
            raise APIConnectionError() from err
        except (OSError, http.client.HTTPException) as err:
            raise APIConnectionError() from err

        text = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            # Proxies in front of the API may answer with plain text.
            parsed = text

        if status >= 400:
            raise make_status_error(status, parsed, response_headers)
        return parsed


def _should_retry(err: APIError) -> bool:
    if isinstance(err, APIConnectionError):
        return True
    # 409 is a state conflict in this API, so retrying it would not help.
    return err.status is not None and (err.status in (408, 429) or err.status >= 500)


def _retry_delay(err: APIError, attempt: int) -> float:
    retry_after = err.headers.get("retry-after") if err.headers is not None else None
    if retry_after is not None:
        try:
            seconds = float(retry_after)
        except ValueError:
            seconds = -1.0
        if 0 <= seconds <= MAX_RETRY_DELAY:
            return seconds
    base = min(0.5 * 2**attempt, 8.0)
    return base * (1 - random.random() * 0.25)
