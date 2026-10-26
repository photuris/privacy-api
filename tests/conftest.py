"""Shared sample payloads from the Privacy.com docs."""

from typing import Any

import pytest

JsonDict = dict[str, Any]


@pytest.fixture
def funding_source_json() -> JsonDict:
    """Return a fresh funding source payload."""
    return {
        "created": "2020-07-08 17:57:36",
        "token": "b0f0d91a-3697-46d8-85f3-20f0a585cbea",
        "type": "DEPOSITORY_CHECKING",
        "state": "ENABLED",
        "nickname": "",
        "account_name": "Sandbox",
        "last_four": "5263",
    }


@pytest.fixture
def card_json(funding_source_json: JsonDict) -> JsonDict:
    """Return a fresh single-card payload, including pan and cvv."""
    return {
        "created": "2021-06-28T22:53:15Z",
        "token": "7ef7d65c-9023-4da3-b113-3b8583fd7951",
        "last_four": "4142",
        "hostname": "",
        "memo": "New Card",
        "type": "SINGLE_USE",
        "spend_limit": 1000,
        "spend_limit_duration": "TRANSACTION",
        "state": "OPEN",
        "funding": funding_source_json,
        "pan": "4111111289144142",
        "cvv": "776",
        "exp_month": "06",
        "exp_year": "2027",
    }


@pytest.fixture
def transaction_json(card_json: JsonDict) -> JsonDict:
    """Return a fresh transaction payload with a list-style card."""
    card = {
        k: v
        for k, v in card_json.items()
        if k not in ("pan", "cvv", "exp_month", "exp_year")
    }
    return {
        "card": card,
        "amount": -7666,
        "authorization_amount": -7666,
        "merchant_amount": -7666,
        "merchant_authorization_amount": -7666,
        "merchant_currency": "USD",
        "acquirer_fee": 0,
        "created": "2020-07-15T19:17:22Z",
        "events": [
            {
                "amount": 7666,
                "created": "2020-07-15T19:17:22Z",
                "result": "APPROVED",
                "type": "RETURN",
                "token": "6a885bcb-89f6-4fcb-a0ce-7f0233ae20a0",
            }
        ],
        "funding": [
            {
                "amount": -7666,
                "token": "b0f0d91a-3697-46d8-85f3-20f0a585cbea",
                "type": "DEPOSITORY_CHECKING",
            }
        ],
        "merchant": {
            "acceptor_id": "174030075991",
            "city": "NEW YORK",
            "country": "USA",
            "descriptor": "RESTAURANT ABC",
            "mcc": "5812",
            "state": "NY",
        },
        "result": "APPROVED",
        "settled_amount": -7666,
        "status": "SETTLING",
        "token": "764fa5a3-2371-40f0-8cbb-9a2e1230d955",
        "authorization_code": "123456",
    }
