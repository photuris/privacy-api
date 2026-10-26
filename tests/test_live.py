"""Read-only live smoke tests; skipped without PRIVACY_API_KEY."""

import os

import pytest

from privacy_api import Client, Page, Transaction

pytestmark = pytest.mark.skipif(
    not os.environ.get("PRIVACY_API_KEY"),
    reason="PRIVACY_API_KEY not set",
)


def test_status() -> None:
    """GET /status returns a non-empty message."""
    with Client() as client:
        message = client.status()

    assert isinstance(message, str)
    assert message


def test_transactions_list() -> None:
    """GET /transactions returns a typed first page."""
    with Client() as client:
        page = client.transactions.list(page_size=1)

    assert isinstance(page, Page)
    assert page.page == 1
    assert len(page.data) <= 1
    assert all(isinstance(tx, Transaction) for tx in page.data)
