"""Tests for privacy_api.resources via httpx.MockTransport."""

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from privacy_api import (
    Card,
    Client,
    FundingSource,
    NotFoundError,
    Page,
    Transaction,
)
from privacy_api.resources import _fmt_date

JsonDict = dict[str, Any]
Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler) -> tuple[Client, list[httpx.Request]]:
    """Build a client whose transport records requests and calls handler.

    Args:
        handler: Produces the response for each request.

    Returns:
        The client and the list that records every request sent.
    """
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = Client(api_key="k", transport=httpx.MockTransport(record))
    return client, requests


def page_body(
    data: list[JsonDict], *, page: int = 1, total_pages: int = 1
) -> JsonDict:
    """Build a list response body.

    Args:
        data: The items.
        page: The page number reported.
        total_pages: The total pages reported.

    Returns:
        A Privacy.com list response.
    """
    return {
        "data": data,
        "page": page,
        "total_entries": len(data),
        "total_pages": total_pages,
    }


def static_client(body: Any) -> tuple[Client, list[httpx.Request]]:
    """Build a client that answers every request with ``body``.

    Args:
        body: The JSON body of the 200 response.

    Returns:
        The client and its request log.
    """
    return make_client(lambda request: httpx.Response(200, json=body))


@dataclass
class Kind:
    """A paginated resource under test."""

    name: str
    path: str
    model: type
    sample: JsonDict

    def item(self, token: str) -> JsonDict:
        """Return the sample payload with a replaced token.

        Args:
            token: The token to set.

        Returns:
            A copy of the sample.
        """
        item = copy.deepcopy(self.sample)
        item["token"] = token
        return item

    def paged_client(
        self, pages: dict[int, list[str]], total_pages: int
    ) -> tuple[Client, list[httpx.Request]]:
        """Build a client serving ``pages`` keyed by the page query.

        Args:
            pages: Item tokens to serve for each page number.
            total_pages: The total_pages reported on every page.

        Returns:
            The client and its request log.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            number = int(request.url.params["page"])
            items = [self.item(t) for t in pages.get(number, [])]
            return httpx.Response(
                200,
                json=page_body(items, page=number, total_pages=total_pages),
            )

        return make_client(handler)

    def resource(self, client: Client) -> Any:
        """Return this kind's resource on ``client``.

        Args:
            client: The client.

        Returns:
            ``client.cards`` or ``client.transactions``.
        """
        return getattr(client, self.name)


@pytest.fixture(params=["cards", "transactions"])
def kind(
    request: pytest.FixtureRequest,
    card_json: JsonDict,
    transaction_json: JsonDict,
) -> Kind:
    """Return each paginated resource in turn."""
    if request.param == "cards":
        return Kind("cards", "/cards", Card, card_json)
    return Kind("transactions", "/transactions", Transaction, transaction_json)


def query(request: httpx.Request) -> dict[str, str]:
    """Return a request's query string as a dict.

    Args:
        request: The recorded request.

    Returns:
        The query parameters.
    """
    return dict(request.url.params)


def tokens(items: list[Any]) -> list[str]:
    """Return the token of each model.

    Args:
        items: Parsed models.

    Returns:
        Their tokens in order.
    """
    return [i.token for i in items]


# ── 1. _fmt_date ─────────────────────────────────────────────────────────────


def test_fmt_date() -> None:
    """_fmt_date handles None, str, date, and datetime inputs."""
    utc_minus_5 = timezone(timedelta(hours=-5))

    assert _fmt_date(None) is None
    assert _fmt_date("2026-01-02") == "2026-01-02"
    assert _fmt_date(date(2026, 1, 2)) == "2026-01-02"
    assert (
        _fmt_date(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
        == "2026-01-02T03:04:05Z"
    )
    assert _fmt_date(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05Z"
    assert (
        _fmt_date(datetime(2026, 1, 2, 3, 4, 5, tzinfo=utc_minus_5))
        == "2026-01-02T08:04:05Z"
    )


# ── 2-3. transactions.list ───────────────────────────────────────────────────


def test_transactions_list_all_params(transaction_json: JsonDict) -> None:
    """All five filters reach the query string; items are parsed."""
    client, requests = static_client(page_body([transaction_json], page=2))

    page = client.transactions.list(
        card_token="t",
        result="APPROVED",
        begin=date(2026, 1, 1),
        page=2,
        page_size=10,
    )

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path.endswith("/transactions")
    assert query(requests[0]) == {
        "card_token": "t",
        "result": "APPROVED",
        "begin": "2026-01-01",
        "page": "2",
        "page_size": "10",
    }
    assert isinstance(page, Page)
    assert page.page == 2
    assert isinstance(page.data[0], Transaction)
    assert page.data[0].token == transaction_json["token"]


def test_transactions_list_defaults(transaction_json: JsonDict) -> None:
    """With no filters only page and page_size are sent."""
    client, requests = static_client(page_body([transaction_json]))

    client.transactions.list()

    assert requests[0].method == "GET"
    assert query(requests[0]) == {"page": "1", "page_size": "50"}


# ── 4-7. iter, shared by cards and transactions ──────────────────────────────


def test_iter_walks_pages(kind: Kind) -> None:
    """iter yields every page in order, requesting 1..N at page_size 100."""
    client, requests = kind.paged_client(
        {1: ["p1-0"], 2: ["p2-0"], 3: ["p3-0"]}, total_pages=3
    )

    items = list(kind.resource(client).iter())

    assert tokens(items) == ["p1-0", "p2-0", "p3-0"]
    assert all(isinstance(i, kind.model) for i in items)
    assert len(requests) == 3
    assert [query(r)["page"] for r in requests] == ["1", "2", "3"]
    assert all(query(r)["page_size"] == "100" for r in requests)


def test_iter_stops_at_total_pages(kind: Kind) -> None:
    """iter makes one request per page and no more."""
    client, requests = kind.paged_client({1: ["p1-0", "p1-1"]}, total_pages=1)
    assert tokens(list(kind.resource(client).iter())) == ["p1-0", "p1-1"]
    assert len(requests) == 1

    client, requests = kind.paged_client(
        {1: ["p1-0", "p1-1"], 2: ["p2-0"]}, total_pages=2
    )
    assert tokens(list(kind.resource(client).iter())) == [
        "p1-0",
        "p1-1",
        "p2-0",
    ]
    assert len(requests) == 2


def test_iter_stops_on_empty_later_page(kind: Kind) -> None:
    """An empty page ends iteration even if total_pages says more."""
    client, requests = kind.paged_client(
        {1: ["p1-0", "p1-1"], 2: []}, total_pages=3
    )

    items = list(kind.resource(client).iter())

    assert tokens(items) == ["p1-0", "p1-1"]
    assert [query(r)["page"] for r in requests] == ["1", "2"]


def test_iter_empty(kind: Kind) -> None:
    """total_pages=0 with no data yields nothing after one request."""
    client, requests = kind.paged_client({1: []}, total_pages=0)

    assert list(kind.resource(client).iter()) == []
    assert len(requests) == 1


def test_iter_empty_first_page_with_more_pages(kind: Kind) -> None:
    """An empty first page stops iteration despite total_pages=5."""
    client, requests = kind.paged_client({1: []}, total_pages=5)

    assert list(kind.resource(client).iter()) == []
    assert len(requests) == 1


def test_iter_is_lazy(kind: Kind) -> None:
    """No request until the first next(); one request per page pulled."""
    client, requests = kind.paged_client(
        {1: ["p1-0", "p1-1"], 2: ["p2-0", "p2-1"], 3: ["p3-0", "p3-1"]},
        total_pages=3,
    )

    it = kind.resource(client).iter()
    assert len(requests) == 0

    assert next(it).token == "p1-0"
    assert next(it).token == "p1-1"
    assert len(requests) == 1

    assert next(it).token == "p2-0"
    assert len(requests) == 2


def test_transactions_iter_passes_filters(
    transaction_json: JsonDict,
) -> None:
    """Every request carries the same filters and page_size."""
    kind = Kind("transactions", "/transactions", Transaction, transaction_json)
    client, requests = kind.paged_client({1: ["a"], 2: ["b"]}, total_pages=2)

    items = list(
        client.transactions.iter(
            card_token="t",
            result="APPROVED",
            begin=date(2026, 1, 1),
            end=date(2026, 2, 1),
            page_size=7,
        )
    )

    assert tokens(items) == ["a", "b"]
    assert [query(r) for r in requests] == [
        {
            "card_token": "t",
            "result": "APPROVED",
            "begin": "2026-01-01",
            "end": "2026-02-01",
            "page_size": "7",
            "page": str(n),
        }
        for n in (1, 2)
    ]


def test_cards_iter_passes_filters(card_json: JsonDict) -> None:
    """Every request carries the same date filters and page_size."""
    kind = Kind("cards", "/cards", Card, card_json)
    client, requests = kind.paged_client({1: ["a"], 2: ["b"]}, total_pages=2)

    items = list(
        client.cards.iter(
            begin=date(2026, 1, 1), end=date(2026, 2, 1), page_size=7
        )
    )

    assert tokens(items) == ["a", "b"]
    assert [query(r) for r in requests] == [
        {
            "begin": "2026-01-01",
            "end": "2026-02-01",
            "page_size": "7",
            "page": str(n),
        }
        for n in (1, 2)
    ]


# ── 8-13. cards and funding sources ──────────────────────────────────────────


def test_cards_get(card_json: JsonDict) -> None:
    """get fetches one card and keeps pan."""
    client, requests = static_client(card_json)

    card = client.cards.get("tok")

    assert requests[0].method == "GET"
    assert requests[0].url.path.endswith("/cards/tok")
    assert isinstance(card, Card)
    assert card.pan == card_json["pan"]


def test_cards_create_omits_none(card_json: JsonDict) -> None:
    """create sends only the arguments given."""
    client, requests = static_client(card_json)

    card = client.cards.create(type="SINGLE_USE", memo="x", spend_limit=1000)

    assert requests[0].method == "POST"
    assert requests[0].url.path.endswith("/cards")
    assert json.loads(requests[0].content) == {
        "type": "SINGLE_USE",
        "memo": "x",
        "spend_limit": 1000,
    }
    assert isinstance(card, Card)


def test_cards_create_sends_falsy_values(card_json: JsonDict) -> None:
    """create sends empty and zero values and every optional field."""
    client, requests = static_client(card_json)

    client.cards.create(
        type="MERCHANT_LOCKED",
        memo="",
        spend_limit=0,
        funding_token="f",
        spend_limit_duration="MONTHLY",
        state="PAUSED",
        exp_month="06",
        exp_year="2027",
    )

    assert json.loads(requests[0].content) == {
        "type": "MERCHANT_LOCKED",
        "memo": "",
        "spend_limit": 0,
        "funding_token": "f",
        "spend_limit_duration": "MONTHLY",
        "state": "PAUSED",
        "exp_month": "06",
        "exp_year": "2027",
    }


def test_cards_update(card_json: JsonDict) -> None:
    """update PATCHes only the arguments given, including falsy ones."""
    client, requests = static_client(card_json)

    card = client.cards.update("tok", state="PAUSED")
    client.cards.update(
        "tok", memo="", spend_limit=0, spend_limit_duration="FOREVER"
    )

    assert isinstance(card, Card)
    assert [r.method for r in requests] == ["PATCH", "PATCH"]
    assert all(r.url.path.endswith("/cards/tok") for r in requests)
    assert json.loads(requests[0].content) == {"state": "PAUSED"}
    assert json.loads(requests[1].content) == {
        "memo": "",
        "spend_limit": 0,
        "spend_limit_duration": "FOREVER",
    }


def test_cards_share(card_json: JsonDict) -> None:
    """share POSTs the recipient and optional theme."""
    client, requests = static_client(card_json)

    card = client.cards.share("tok", recipient_email="a@b.c")
    client.cards.share("tok", recipient_email="a@b.c", theme="CONFETTI")

    assert isinstance(card, Card)
    assert [r.method for r in requests] == ["POST", "POST"]
    assert all(r.url.path.endswith("/cards/tok/share") for r in requests)
    assert json.loads(requests[0].content) == {"recipient_email": "a@b.c"}
    assert json.loads(requests[1].content) == {
        "recipient_email": "a@b.c",
        "theme": "CONFETTI",
    }


def test_cards_list_string_date(card_json: JsonDict) -> None:
    """A string begin is sent unchanged with default paging."""
    client, requests = static_client(page_body([card_json]))

    page = client.cards.list(begin="2026-01-01")

    assert requests[0].method == "GET"
    assert requests[0].url.path.endswith("/cards")
    assert query(requests[0]) == {
        "begin": "2026-01-01",
        "page": "1",
        "page_size": "50",
    }
    assert isinstance(page.data[0], Card)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_funding_sources_unpaginated(
    count: int, funding_source_json: JsonDict
) -> None:
    """funding_sources sends no query and iter makes one request."""
    items = [{**funding_source_json, "token": f"fs-{n}"} for n in range(count)]
    client, requests = static_client(page_body(items))

    page = client.funding_sources.list()

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path.endswith("/funding_sources")
    assert requests[0].url.query == b""
    assert isinstance(page, Page)
    assert tokens(page.data) == [f"fs-{n}" for n in range(count)]

    client, requests = static_client(page_body(items))

    yielded = list(client.funding_sources.iter())

    assert len(requests) == 1
    assert all(isinstance(f, FundingSource) for f in yielded)
    assert tokens(yielded) == [f"fs-{n}" for n in range(count)]


def test_not_found_propagates() -> None:
    """A 404 surfaces as NotFoundError."""
    client, _ = make_client(
        lambda request: httpx.Response(
            404, json={"message": "no such card", "debugging_request_id": "r"}
        )
    )

    with pytest.raises(NotFoundError, match="no such card"):
        client.cards.get("tok")
