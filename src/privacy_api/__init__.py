"""Python client for the Privacy.com virtual card API."""

__version__ = "0.1.0"

from privacy_api.client import Client
from privacy_api.errors import (
    AuthError,
    BadRequestError,
    NetworkError,
    NotFoundError,
    PrivacyError,
    RateLimitError,
    ServerError,
)
from privacy_api.models import (
    Card,
    Event,
    Funding,
    FundingSource,
    Merchant,
    Page,
    Transaction,
)

__all__ = [
    "AuthError",
    "BadRequestError",
    "Card",
    "Client",
    "Event",
    "Funding",
    "FundingSource",
    "Merchant",
    "NetworkError",
    "NotFoundError",
    "Page",
    "PrivacyError",
    "RateLimitError",
    "ServerError",
    "Transaction",
    "__version__",
]
