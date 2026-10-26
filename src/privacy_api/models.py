"""Pydantic models for Privacy.com API payloads."""

from datetime import UTC, datetime
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _as_utc(value: datetime | None) -> datetime | None:
    """Return ``value`` with UTC attached when it is naive.

    Args:
        value: A parsed datetime or None.

    Returns:
        None for None, the same instant tagged UTC for a naive value,
        otherwise ``value`` unchanged.
    """
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class _Model(BaseModel):
    """Base model: unknown fields are kept and round-trip on dump."""

    model_config = ConfigDict(extra="allow")


class FundingSource(_Model):
    """A funding source (bank account) backing cards."""

    token: str
    type: str
    state: str
    created: datetime | None = None
    nickname: str | None = None
    account_name: str | None = None
    last_four: str | None = None

    @field_validator("created", mode="after")
    @classmethod
    def _created_utc(cls, value: datetime | None) -> datetime | None:
        """Treat a naive ``created`` as UTC."""
        return _as_utc(value)


class Card(_Model):
    """A virtual card; ``pan`` and ``cvv`` appear only on some responses."""

    token: str
    created: datetime
    type: str
    state: str
    last_four: str
    spend_limit: int
    spend_limit_duration: str
    memo: str | None = None
    hostname: str | None = None
    funding: FundingSource | None = None
    exp_month: str | None = None
    exp_year: str | None = None
    pan: str | None = None
    cvv: str | None = None

    @field_validator("created", mode="after")
    @classmethod
    def _created_utc(cls, value: datetime) -> datetime:
        """Treat a naive ``created`` as UTC."""
        return _as_utc(value)


class Merchant(_Model):
    """The merchant a transaction was made with."""

    acceptor_id: str | None = None
    city: str | None = None
    country: str | None = None
    descriptor: str | None = None
    mcc: str | None = None
    state: str | None = None


class Event(_Model):
    """A lifecycle event on a transaction."""

    token: str
    type: str
    result: str
    amount: int
    created: datetime

    @field_validator("created", mode="after")
    @classmethod
    def _created_utc(cls, value: datetime) -> datetime:
        """Treat a naive ``created`` as UTC."""
        return _as_utc(value)


class Funding(_Model):
    """One funding movement attached to a transaction."""

    amount: int
    type: str
    token: str | None = None


class Transaction(_Model):
    """A card transaction."""

    token: str
    created: datetime
    status: str
    result: str
    amount: int
    card_token: str | None = None
    card: Card | None = None
    authorization_amount: int | None = None
    merchant_amount: int | None = None
    merchant_authorization_amount: int | None = None
    merchant_currency: str | None = None
    acquirer_fee: int | None = None
    settled_amount: int | None = None
    authorization_code: str | None = None
    merchant: Merchant | None = None
    events: list[Event] = Field(default_factory=list)
    funding: list[Funding] = Field(default_factory=list)

    @field_validator("created", mode="after")
    @classmethod
    def _created_utc(cls, value: datetime) -> datetime:
        """Treat a naive ``created`` as UTC."""
        return _as_utc(value)

    @model_validator(mode="after")
    def _derive_card_token(self) -> Self:
        """Fill a missing or null ``card_token`` from ``card.token``."""
        if self.card_token is None and self.card is not None:
            self.card_token = self.card.token
        return self


class Page[T](_Model):
    """One page of a list response."""

    data: list[T]
    page: int
    total_entries: int
    total_pages: int
