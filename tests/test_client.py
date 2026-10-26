"""Tests for privacy_api.client and privacy_api.errors."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from privacy_api.client import PRODUCTION_URL, SANDBOX_URL, Client
from privacy_api.errors import (
    AuthError,
    BadRequestError,
    NetworkError,
    NotFoundError,
    PrivacyError,
    RateLimitError,
    ServerError,
)

Outcome = httpx.Response | Exception


def make_client(
    outcome: Callable[[int], Outcome], **kwargs: Any
) -> tuple[Client, list[httpx.Request]]:
    """Build a client whose n-th request yields ``outcome(n)``.

    Args:
        outcome: Maps the zero-based request index to a response or an
            exception to raise from the transport.
        **kwargs: Extra ``Client`` arguments.

    Returns:
        The client and the list that records every request sent.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        result = outcome(len(requests) - 1)
        if isinstance(result, Exception):
            raise result

        return result

    transport = httpx.MockTransport(handler)

    return Client("key", transport=transport, **kwargs), requests


def seq(*items: Outcome) -> Callable[[int], Outcome]:
    """Return an outcome function that repeats the last item forever.

    Args:
        *items: Outcomes in request order.

    Returns:
        A function mapping a request index to an outcome.
    """
    return lambda i: items[min(i, len(items) - 1)]


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record sleeps instead of sleeping and zero out the jitter."""
    recorded: list[float] = []
    monkeypatch.setattr("privacy_api.client.time.sleep", recorded.append)
    monkeypatch.setattr("privacy_api.client.random.uniform", lambda a, b: 0.0)

    return recorded


OK = httpx.Response(200, json={"message": "ok"})


# ── 1-4: construction ───────────────────────────────────────────────────────


def test_explicit_key_sets_authorization_header() -> None:
    client, requests = make_client(seq(OK))
    client.status()
    assert requests[0].headers["Authorization"] == "api-key key"


def test_env_key_used_when_no_explicit_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIVACY_API_KEY", "from-env")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)

        return OK

    Client(transport=httpx.MockTransport(handler)).status()
    assert requests[0].headers["Authorization"] == "api-key from-env"


def test_missing_key_raises_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRIVACY_API_KEY", raising=False)
    with pytest.raises(AuthError) as excinfo:
        Client()
    assert str(excinfo.value) == (
        "No API key: pass api_key= or set PRIVACY_API_KEY"
    )


def test_empty_key_does_not_fall_back_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIVACY_API_KEY", "valid")
    with pytest.raises(AuthError):
        Client(api_key="")
    monkeypatch.setenv("PRIVACY_API_KEY", "")
    with pytest.raises(AuthError):
        Client()


def test_base_url_selection() -> None:
    def url_for(**kwargs: Any) -> str:
        client, requests = make_client(seq(OK), **kwargs)
        client.status()

        return str(requests[0].url)

    assert url_for() == f"{PRODUCTION_URL}/status"
    assert url_for(sandbox=True) == f"{SANDBOX_URL}/status"
    custom = url_for(sandbox=True, base_url="http://example.test/v9/")
    assert custom == "http://example.test/v9/status"
    doubled = url_for(base_url="http://example.test/v9//")
    assert doubled == "http://example.test/v9/status"


# ── 5: status ───────────────────────────────────────────────────────────────


def test_status_returns_message() -> None:
    client, _ = make_client(
        seq(httpx.Response(200, json={"message": "All good"}))
    )
    assert client.status() == "All good"


# ── 6-8: error mapping ──────────────────────────────────────────────────────


def test_bad_request_error_fields() -> None:
    body = {"message": "nope", "debugging_request_id": "req-1"}
    client, _ = make_client(seq(httpx.Response(400, json=body)))
    with pytest.raises(BadRequestError) as excinfo:
        client.status()
    err = excinfo.value
    assert err.message == "nope"
    assert err.status_code == 400
    assert err.debugging_request_id == "req-1"
    assert str(err) == "nope"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AuthError),
        (404, NotFoundError),
        (422, BadRequestError),
        (418, PrivacyError),
        (503, ServerError),
    ],
)
def test_status_maps_to_error_class(
    status: int, expected: type[PrivacyError], sleeps: list[float]
) -> None:
    client, _ = make_client(seq(httpx.Response(status)), max_retries=0)
    with pytest.raises(PrivacyError) as excinfo:
        client.status()
    assert type(excinfo.value) is expected


@pytest.mark.parametrize(
    ("content", "message", "request_id"),
    [
        (b"not json", "HTTP 400", None),
        (b'{"message": "bad"}', "bad", None),
        (b'{"debugging_request_id": "r1"}', "HTTP 400", "r1"),
        (b"{}", "HTTP 400", None),
        (b"[]", "HTTP 400", None),
        (b"null", "HTTP 400", None),
    ],
)
def test_error_body_fallbacks(
    content: bytes, message: str, request_id: str | None
) -> None:
    client, _ = make_client(seq(httpx.Response(400, content=content)))
    with pytest.raises(BadRequestError) as excinfo:
        client.status()
    assert excinfo.value.message == message
    assert excinfo.value.debugging_request_id == request_id


# ── 9-13: retries ───────────────────────────────────────────────────────────


def test_get_retries_429_then_succeeds(sleeps: list[float]) -> None:
    r429 = httpx.Response(429)
    client, requests = make_client(seq(r429, r429, OK), max_retries=3)
    assert client.status() == "ok"
    assert len(requests) == 3
    assert sleeps == [0.5, 1.0]


def test_backoff_doubles_and_caps_at_eight(sleeps: list[float]) -> None:
    r429 = httpx.Response(429)
    client, requests = make_client(seq(*[r429] * 6, OK), max_retries=6)
    client.status()
    assert len(requests) == 7
    assert sleeps == [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]


def test_retry_after_replaces_backoff_and_is_exposed(
    sleeps: list[float],
) -> None:
    response = httpx.Response(429, headers={"Retry-After": "2"})
    client, requests = make_client(seq(response), max_retries=2)
    with pytest.raises(RateLimitError) as excinfo:
        client.status()
    assert len(requests) == 3
    assert sleeps == [2.0, 2.0]
    assert excinfo.value.retry_after == 2.0


def test_retry_after_on_5xx_and_non_numeric_fallback(
    sleeps: list[float],
) -> None:
    r503 = httpx.Response(503, headers={"Retry-After": "1"})
    client, requests = make_client(seq(r503, OK), max_retries=1)
    client.status()
    assert len(requests) == 2
    assert sleeps == [1.0]
    sleeps.clear()
    soon = httpx.Response(429, headers={"Retry-After": "soon"})
    client, _ = make_client(seq(soon, OK), max_retries=1)
    client.status()
    assert sleeps == [0.5]


def test_get_retries_500_then_raises_server_error(
    sleeps: list[float],
) -> None:
    client, requests = make_client(seq(httpx.Response(500)), max_retries=2)
    with pytest.raises(ServerError):
        client.status()
    assert len(requests) == 3
    assert sleeps == [0.5, 1.0]


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (httpx.Response(429), RateLimitError),
        (httpx.Response(503), ServerError),
        (httpx.ConnectError("boom"), NetworkError),
    ],
    ids=["429", "503", "connect-error"],
)
def test_zero_retries_makes_one_request(
    outcome: Outcome, expected: type[PrivacyError], sleeps: list[float]
) -> None:
    client, requests = make_client(seq(outcome), max_retries=0)
    with pytest.raises(PrivacyError) as excinfo:
        client.status()
    assert type(excinfo.value) is expected
    assert len(requests) == 1
    assert sleeps == []


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (httpx.Response(500), ServerError),
        (httpx.Response(429), RateLimitError),
        (httpx.ConnectError("boom"), NetworkError),
    ],
    ids=["500", "429", "connect-error"],
)
def test_non_get_never_retries(
    method: str,
    outcome: Outcome,
    expected: type[PrivacyError],
    sleeps: list[float],
) -> None:
    client, requests = make_client(seq(outcome), max_retries=3)
    with pytest.raises(PrivacyError) as excinfo:
        client._request(method, "/cards", json={})
    assert type(excinfo.value) is expected
    assert len(requests) == 1
    assert sleeps == []


def test_get_retries_transport_errors(sleeps: list[float]) -> None:
    client, requests = make_client(
        seq(httpx.ConnectError("boom")), max_retries=2
    )
    with pytest.raises(NetworkError):
        client.status()
    assert len(requests) == 3
    assert sleeps == [0.5, 1.0]


# ── 14: params ──────────────────────────────────────────────────────────────


def test_none_params_are_dropped() -> None:
    client, requests = make_client(seq(OK))
    client._request("GET", "/cards", params={"a": 1, "b": None})
    params = requests[0].url.params
    assert params["a"] == "1"
    assert "b" not in params
