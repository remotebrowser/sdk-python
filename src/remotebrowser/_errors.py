from __future__ import annotations

import json
from email.message import Message
from typing import Any, cast

__all__ = [
    "APIConnectionError",
    "APIConnectionTimeoutError",
    "APIError",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "InternalServerError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "RemoteBrowserError",
    "UnprocessableEntityError",
]


class RemoteBrowserError(Exception):
    """Base class of every error the SDK raises."""


class APIError(RemoteBrowserError):
    """A failed API call.

    Attributes:
        status: The HTTP status code, or None when no response arrived.
        body: The parsed response body: a dict for a JSON body, a str otherwise, or None.
        headers: The response headers, or None when no response arrived.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        status: int | None = None,
        body: Any = None,
        headers: Message | None = None,
    ) -> None:
        super().__init__(_make_message(status, body, message))
        self.status = status
        self.body = body
        self.headers = headers


class APIConnectionError(APIError):
    """The request did not get a response, for example because the server is down."""

    def __init__(self, message: str = "Connection error.") -> None:
        super().__init__(message)


class APIConnectionTimeoutError(APIConnectionError):
    """The request timed out."""

    def __init__(self, message: str = "Request timed out.") -> None:
        super().__init__(message)


class BadRequestError(APIError):
    pass


class AuthenticationError(APIError):
    pass


class PermissionDeniedError(APIError):
    pass


class NotFoundError(APIError):
    pass


class ConflictError(APIError):
    """The browser is in the wrong state for the action."""


class UnprocessableEntityError(APIError):
    pass


class RateLimitError(APIError):
    pass


class InternalServerError(APIError):
    pass


_STATUS_ERRORS: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def make_status_error(status: int, body: Any, headers: Message | None) -> APIError:
    error_class = _STATUS_ERRORS.get(status) or (InternalServerError if status >= 500 else APIError)
    return error_class(status=status, body=body, headers=headers)


def _make_message(status: int | None, body: Any, message: str | None) -> str:
    detail = _detail(body)
    if status and detail:
        return f"{status} {detail}"
    if status:
        return f"{status} status code (no body)"
    return message or detail or "(no status code or body)"


def _detail(body: Any) -> str:
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        fields = cast(dict[str, Any], body)
        for key in ("error", "message"):
            value = fields.get(key)
            if isinstance(value, str) and value:
                return value
    return json.dumps(body) if body else ""
