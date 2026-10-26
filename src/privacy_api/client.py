"""Synchronous HTTP client for the Privacy.com API."""

from __future__ import annotations

import logging
import os
import random
import time
from importlib.metadata import PackageNotFoundError, version
from types import TracebackType
from typing import Any

import httpx

from privacy_api.errors import (
    AuthError,
    NetworkError,
    PrivacyError,
    from_response,
    parse_retry_after,
)

logger = logging.getLogger(__name__)

PRODUCTION_URL: str = "https://api.privacy.com/v1"
SANDBOX_URL: str = "https://sandbox.privacy.com/v1"
ENV_API_KEY: str = "PRIVACY_API_KEY"

try:
    _VERSION: str = version("privacy-api")
except PackageNotFoundError:  # pragma: no cover - not installed
    _VERSION = "unknown"


def _backoff(retry: int) -> float:
    """Return the delay before retry number ``retry`` (starting at 1).

    Args:
        retry: The retry number, 1 for the first retry.

    Returns:
        Exponential backoff capped at 8 seconds, plus up to 0.25 of jitter.
    """
    return min(0.5 * 2 ** (retry - 1), 8.0) + random.uniform(0, 0.25)


class Client:
    """Client for the Privacy.com virtual card API.

    Example:
        >>> with Client() as client:  # doctest: +SKIP
        ...     client.status()
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        sandbox: bool = False,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            api_key: API key. None falls back to ``PRIVACY_API_KEY``; an
                empty string does not.
            sandbox: Use the sandbox URL instead of production.
            base_url: Explicit base URL; wins over ``sandbox``.
            timeout: Per-request timeout in seconds.
            max_retries: Extra attempts for a failed GET.
            transport: Custom httpx transport, mainly for tests.

        Raises:
            AuthError: If no API key is available or the key is empty.
        """
        if api_key is None:
            api_key = os.environ.get(ENV_API_KEY)
        if not api_key:
            raise AuthError(f"No API key: pass api_key= or set {ENV_API_KEY}")
        if base_url is None:
            base_url = SANDBOX_URL if sandbox else PRODUCTION_URL
        self._max_retries = max(max_retries, 0)
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"api-key {api_key}",
                "Accept": "application/json",
                "User-Agent": f"privacy-api-python/{_VERSION}",
            },
            timeout=timeout,
            transport=transport,
        )

    def status(self) -> str:
        """Return the API status message.

        Returns:
            The ``message`` field of ``GET /status``.
        """
        return self._request("GET", "/status")["message"]

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    def __enter__(self) -> Client:
        """Enter the context manager.

        Returns:
            This client.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the client on context exit.

        Args:
            exc_type: Exception type, if one was raised.
            exc: Exception instance, if one was raised.
            tb: Traceback, if an exception was raised.
        """
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request, retrying idempotent GETs on transient failure.

        Args:
            method: HTTP method. Only GET is retried.
            path: Path relative to the base URL, e.g. ``/cards``.
            params: Query parameters; None values are dropped.
            json: JSON request body.

        Returns:
            The decoded JSON body of the 2xx response.

        Raises:
            PrivacyError: The mapped error of the last failed attempt.
        """
        if params is not None:
            params = {k: v for k, v in params.items() if v is not None}
        attempts = self._max_retries + 1 if method == "GET" else 1
        attempt = 1
        while True:
            retry_after: float | None = None
            try:
                response = self._http.request(
                    method, path, params=params, json=json
                )
            except httpx.TransportError as exc:
                error: PrivacyError = NetworkError(
                    str(exc) or type(exc).__name__
                )
                reason = type(exc).__name__
                retryable = True
            else:
                logger.debug("%s %s -> %s", method, path, response.status_code)
                if response.is_success:
                    return response.json()
                error = from_response(response)
                reason = str(response.status_code)
                retryable = (
                    response.status_code == 429 or response.status_code >= 500
                )
                retry_after = parse_retry_after(response)
            if not retryable or attempt >= attempts:
                raise error
            delay = _backoff(attempt) if retry_after is None else retry_after
            logger.warning(
                "%s %s failed (%s); retrying in %.2fs",
                method,
                path,
                reason,
                delay,
            )
            time.sleep(delay)
            attempt += 1
