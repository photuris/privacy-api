"""Exception hierarchy for the Privacy.com API client."""

import math
from typing import Any

import httpx


class PrivacyError(Exception):
    """Base class for every error raised by this library.

    Attributes:
        message: Human-readable description; also ``str(err)``.
        status_code: HTTP status of the failed response, if any.
        debugging_request_id: Request id reported by the API, if any.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        debugging_request_id: str | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable description.
            status_code: HTTP status of the failed response, if any.
            debugging_request_id: Request id reported by the API.
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.debugging_request_id = debugging_request_id


class NetworkError(PrivacyError):
    """The request never produced a response (wraps httpx.TransportError)."""


class BadRequestError(PrivacyError):
    """The API rejected the request (HTTP 400 or 422)."""


class AuthError(PrivacyError):
    """Missing or rejected credentials (HTTP 401, 403, or no API key)."""


class NotFoundError(PrivacyError):
    """The resource does not exist (HTTP 404)."""


class RateLimitError(PrivacyError):
    """Too many requests (HTTP 429).

    Attributes:
        retry_after: Seconds from the ``Retry-After`` header, if valid.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        debugging_request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable description.
            status_code: HTTP status of the failed response, if any.
            debugging_request_id: Request id reported by the API.
            retry_after: Seconds the server asked the caller to wait.
        """
        super().__init__(
            message,
            status_code=status_code,
            debugging_request_id=debugging_request_id,
        )
        self.retry_after = retry_after


class ServerError(PrivacyError):
    """The API failed to handle the request (HTTP 5xx)."""


def parse_retry_after(response: httpx.Response) -> float | None:
    """Parse the ``Retry-After`` header of a response.

    Args:
        response: The response to inspect.

    Returns:
        The delay in seconds when the header is a finite number >= 0,
        otherwise None.
    """
    try:
        value = float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None

    return value if math.isfinite(value) and value >= 0 else None


def from_response(response: httpx.Response) -> PrivacyError:
    """Build the error that matches a non-2xx response.

    Args:
        response: The failed response.

    Returns:
        The mapped ``PrivacyError`` subclass instance (not raised).
    """
    status = response.status_code
    message = f"HTTP {status}"
    request_id = None
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        if isinstance(body.get("message"), str):
            message = body["message"]
        if isinstance(body.get("debugging_request_id"), str):
            request_id = body["debugging_request_id"]
    kwargs: dict[str, Any] = {
        "status_code": status,
        "debugging_request_id": request_id,
    }
    if status in (400, 422):
        return BadRequestError(message, **kwargs)
    if status in (401, 403):
        return AuthError(message, **kwargs)
    if status == 404:
        return NotFoundError(message, **kwargs)
    if status == 429:
        return RateLimitError(
            message, retry_after=parse_retry_after(response), **kwargs
        )
    if status >= 500:
        return ServerError(message, **kwargs)

    return PrivacyError(message, **kwargs)
