"""Resource namespaces: cards, funding sources, and transactions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from privacy_api.models import Card, FundingSource, Page, Transaction

if TYPE_CHECKING:
    from privacy_api.client import Client

DateLike = date | datetime | str


def _fmt_date(value: DateLike | None) -> str | None:
    """Format a date filter for the query string.

    Args:
        value: None, a ready-made string, a date, or a datetime. A naive
            datetime is treated as UTC.

    Returns:
        None for None, the string unchanged, ``YYYY-MM-DDTHH:MM:SSZ``
        (UTC) for a datetime, or ``YYYY-MM-DD`` for a date.
    """
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.isoformat()


def _paginate[T](fetch: Callable[[int], Page[T]]) -> Iterator[T]:
    """Lazily yield every item across pages, one request per page.

    Args:
        fetch: Returns the page with the given 1-based number.

    Yields:
        Each item of each page in order. Iteration ends after the last
        page, or at the first page with no data.
    """
    page_number = 1
    while True:
        page = fetch(page_number)
        if not page.data:
            return
        yield from page.data
        if page.page >= page.total_pages:
            return
        page_number += 1


def _body(**fields: Any) -> dict[str, Any]:
    """Drop None values from a JSON body, keeping falsy ones.

    Args:
        **fields: Candidate body fields.

    Returns:
        The fields whose value is not None.
    """
    return {k: v for k, v in fields.items() if v is not None}


class Cards:
    """The ``/cards`` endpoints."""

    def __init__(self, client: Client) -> None:
        """Bind the resource to a client.

        Args:
            client: The client whose ``_request`` is used.
        """
        self._client = client

    def list(
        self,
        *,
        begin: DateLike | None = None,
        end: DateLike | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Page[Card]:
        """Fetch one page of cards.

        Args:
            begin: Only cards created on or after this time.
            end: Only cards created before this time.
            page: 1-based page number.
            page_size: Items per page (the API maximum is 100).

        Returns:
            The requested page.
        """
        data = self._client._request(
            "GET",
            "/cards",
            params={
                "begin": _fmt_date(begin),
                "end": _fmt_date(end),
                "page": page,
                "page_size": page_size,
            },
        )

        return Page[Card].model_validate(data)

    def iter(
        self,
        *,
        begin: DateLike | None = None,
        end: DateLike | None = None,
        page_size: int = 100,
    ) -> Iterator[Card]:
        """Iterate over all matching cards, fetching pages lazily.

        Args:
            begin: Only cards created on or after this time.
            end: Only cards created before this time.
            page_size: Items per request.

        Yields:
            Each card in API order.
        """
        yield from _paginate(
            lambda page: self.list(
                begin=begin, end=end, page=page, page_size=page_size
            )
        )

    def get(self, token: str) -> Card:
        """Fetch one card.

        Args:
            token: The card token.

        Returns:
            The card, including ``pan`` and ``cvv``.
        """
        return Card.model_validate(
            self._client._request("GET", f"/cards/{token}")
        )

    def create(
        self,
        *,
        type: str,
        memo: str | None = None,
        funding_token: str | None = None,
        spend_limit: int | None = None,
        spend_limit_duration: str | None = None,
        state: str | None = None,
        exp_month: str | None = None,
        exp_year: str | None = None,
    ) -> Card:
        """Create a card.

        Args:
            type: Card type, e.g. ``SINGLE_USE`` or ``MERCHANT_LOCKED``.
            memo: Label for the card.
            funding_token: Funding source to charge.
            spend_limit: Limit in cents.
            spend_limit_duration: e.g. ``TRANSACTION``, ``MONTHLY``.
            state: Initial state, e.g. ``OPEN`` or ``PAUSED``.
            exp_month: Two-digit expiry month.
            exp_year: Four-digit expiry year.

        Returns:
            The new card.
        """
        body = _body(
            type=type,
            memo=memo,
            funding_token=funding_token,
            spend_limit=spend_limit,
            spend_limit_duration=spend_limit_duration,
            state=state,
            exp_month=exp_month,
            exp_year=exp_year,
        )

        return Card.model_validate(
            self._client._request("POST", "/cards", json=body)
        )

    def update(
        self,
        token: str,
        *,
        memo: str | None = None,
        spend_limit: int | None = None,
        spend_limit_duration: str | None = None,
        state: str | None = None,
    ) -> Card:
        """Update a card. Only the arguments given are sent.

        Args:
            token: The card token.
            memo: New label.
            spend_limit: New limit in cents.
            spend_limit_duration: New limit duration.
            state: New state, e.g. ``PAUSED`` or ``CLOSED``.

        Returns:
            The updated card.
        """
        body = _body(
            memo=memo,
            spend_limit=spend_limit,
            spend_limit_duration=spend_limit_duration,
            state=state,
        )

        return Card.model_validate(
            self._client._request("PATCH", f"/cards/{token}", json=body)
        )

    def share(
        self,
        token: str,
        *,
        recipient_email: str,
        theme: str | None = None,
    ) -> Card:
        """Email a card to a recipient.

        Args:
            token: The card token.
            recipient_email: Who receives the card.
            theme: Optional email theme, e.g. ``CONFETTI``.

        Returns:
            The shared card.
        """
        body = _body(recipient_email=recipient_email, theme=theme)

        return Card.model_validate(
            self._client._request("POST", f"/cards/{token}/share", json=body)
        )


class FundingSources:
    """The ``/funding_sources`` endpoint (not paginated)."""

    def __init__(self, client: Client) -> None:
        """Bind the resource to a client.

        Args:
            client: The client whose ``_request`` is used.
        """
        self._client = client

    def list(self) -> Page[FundingSource]:
        """Fetch all funding sources in a single request.

        Returns:
            The (only) page of funding sources.
        """
        data = self._client._request("GET", "/funding_sources")

        return Page[FundingSource].model_validate(data)

    def iter(self) -> Iterator[FundingSource]:
        """Iterate over all funding sources.

        Yields:
            Each funding source in API order.
        """
        yield from self.list().data


class Transactions:
    """The ``/transactions`` endpoint."""

    def __init__(self, client: Client) -> None:
        """Bind the resource to a client.

        Args:
            client: The client whose ``_request`` is used.
        """
        self._client = client

    def list(
        self,
        *,
        card_token: str | None = None,
        result: str | None = None,
        begin: DateLike | None = None,
        end: DateLike | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Page[Transaction]:
        """Fetch one page of transactions.

        Args:
            card_token: Only transactions on this card.
            result: Only this result, e.g. ``APPROVED`` or ``DECLINED``.
            begin: Only transactions created on or after this time.
            end: Only transactions created before this time.
            page: 1-based page number.
            page_size: Items per page (the API maximum is 100).

        Returns:
            The requested page.
        """
        data = self._client._request(
            "GET",
            "/transactions",
            params={
                "card_token": card_token,
                "result": result,
                "begin": _fmt_date(begin),
                "end": _fmt_date(end),
                "page": page,
                "page_size": page_size,
            },
        )

        return Page[Transaction].model_validate(data)

    def iter(
        self,
        *,
        card_token: str | None = None,
        result: str | None = None,
        begin: DateLike | None = None,
        end: DateLike | None = None,
        page_size: int = 100,
    ) -> Iterator[Transaction]:
        """Iterate over all matching transactions, fetching lazily.

        Args:
            card_token: Only transactions on this card.
            result: Only this result, e.g. ``APPROVED`` or ``DECLINED``.
            begin: Only transactions created on or after this time.
            end: Only transactions created before this time.
            page_size: Items per request.

        Yields:
            Each transaction in API order.
        """
        yield from _paginate(
            lambda page: self.list(
                card_token=card_token,
                result=result,
                begin=begin,
                end=end,
                page=page,
                page_size=page_size,
            )
        )
