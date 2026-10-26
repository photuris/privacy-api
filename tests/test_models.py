"""Tests for privacy_api.models."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from privacy_api.models import (
    Card,
    Event,
    FundingSource,
    Page,
    Transaction,
)

JsonDict = dict[str, Any]


def test_funding_source_space_separated_created(
    funding_source_json: JsonDict,
) -> None:
    """1: zone-less space-separated created becomes UTC-aware."""
    fs = FundingSource.model_validate(funding_source_json)
    assert fs.created == datetime(2020, 7, 8, 17, 57, 36, tzinfo=UTC)
    assert fs.created.tzinfo is not None


def test_funding_source_nulls(funding_source_json: JsonDict) -> None:
    """2: null created and last_four parse as None."""
    funding_source_json.update(created=None, last_four=None)
    fs = FundingSource.model_validate(funding_source_json)
    assert fs.created is None
    assert fs.last_four is None


@pytest.mark.parametrize(
    ("model", "fixture", "created"),
    [
        (FundingSource, "funding_source_json", "2020-07-08 17:57:36"),
        (Card, "card_json", "2021-06-28T22:53:15"),
        (Transaction, "transaction_json", "2020-07-15T19:17:22"),
        (Event, "event_json", "2020-07-15T19:17:22"),
    ],
)
def test_naive_created_becomes_utc(
    request: pytest.FixtureRequest,
    model: type[Any],
    fixture: str,
    created: str,
) -> None:
    """2b: a naive created is tagged UTC on every model."""
    if fixture == "event_json":
        payload = request.getfixturevalue("transaction_json")["events"][0]
    else:
        payload = request.getfixturevalue(fixture)
    payload["created"] = created
    obj = model.model_validate(payload)
    assert obj.created.tzinfo is not None
    assert obj.created.utcoffset() == timedelta(0)


def test_card_full(card_json: JsonDict) -> None:
    """3: a full card parses with funding, pan and cvv."""
    card = Card.model_validate(card_json)
    assert card.created == datetime(2021, 6, 28, 22, 53, 15, tzinfo=UTC)
    assert isinstance(card.funding, FundingSource)
    assert card.pan == "4111111289144142"
    assert card.cvv == "776"


def test_card_list_style(card_json: JsonDict) -> None:
    """4: a list-style card has no pan, cvv, exp_month, exp_year."""
    for key in ("pan", "cvv", "exp_month", "exp_year"):
        del card_json[key]
    card = Card.model_validate(card_json)
    assert card.pan is None
    assert card.cvv is None
    assert card.exp_month is None
    assert card.exp_year is None


def test_unknown_field_survives(card_json: JsonDict) -> None:
    """5: unknown fields round-trip through model_dump."""
    card = Card.model_validate({**card_json, "new_field": 1})
    assert card.model_dump()["new_field"] == 1


def test_unknown_enum_value(card_json: JsonDict) -> None:
    """6: an unknown state does not raise."""
    card = Card.model_validate({**card_json, "state": "SOMETHING_NEW"})
    assert card.state == "SOMETHING_NEW"


def test_transaction_full(transaction_json: JsonDict) -> None:
    """7: a full transaction parses and derives card_token."""
    tx = Transaction.model_validate(transaction_json)
    assert tx.amount == -7666
    assert len(tx.events) == 1
    assert tx.events[0].type == "RETURN"
    assert tx.merchant is not None
    assert tx.merchant.mcc == "5812"
    assert len(tx.funding) == 1
    assert tx.card is not None
    assert tx.card_token == tx.card.token


def test_transaction_nested_card_keeps_pan_cvv(
    transaction_json: JsonDict,
) -> None:
    """7b: pan and cvv on a nested card are preserved."""
    transaction_json["card"].update(pan="4111111289144142", cvv="776")
    tx = Transaction.model_validate(transaction_json)
    assert tx.card is not None
    assert tx.card.pan == "4111111289144142"
    assert tx.card.cvv == "776"


_ABSENT = object()


@pytest.mark.parametrize(
    ("card_token", "has_card", "expected"),
    [
        ("explicit", True, "explicit"),
        (None, True, "nested"),
        ("abc", False, "abc"),
        (None, False, None),
        (_ABSENT, False, None),
    ],
)
def test_card_token_precedence(
    transaction_json: JsonDict,
    card_token: object,
    has_card: bool,
    expected: str | None,
) -> None:
    """8: an explicit card_token wins; null or absent derives or stays None."""
    if has_card:
        transaction_json["card"]["token"] = "nested"
    else:
        del transaction_json["card"]
    if card_token is not _ABSENT:
        transaction_json["card_token"] = card_token
    tx = Transaction.model_validate(transaction_json)
    assert tx.card_token == expected


def test_page_of_transactions(transaction_json: JsonDict) -> None:
    """9: Page[Transaction] parses items and keeps unknown fields."""
    page = Page[Transaction].model_validate(
        {
            "data": [transaction_json],
            "page": 1,
            "total_entries": 1,
            "total_pages": 1,
            "next_cursor": "x",
        }
    )
    assert isinstance(page.data[0], Transaction)
    assert page.total_pages == 1
    assert page.model_dump()["next_cursor"] == "x"


def test_transaction_optional_lists_default_empty(
    transaction_json: JsonDict,
) -> None:
    """10: absent events and funding give independent empty lists."""
    del transaction_json["events"]
    del transaction_json["funding"]
    a = Transaction.model_validate(transaction_json)
    b = Transaction.model_validate(transaction_json)
    assert a.events == []
    assert a.funding == []
    assert a.events is not b.events
    assert a.funding is not b.funding
