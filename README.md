<img src="assets/icon.svg" width="64" height="64" alt="">

# privacy-api

A small, typed, synchronous Python client for the
[Privacy.com developer API](https://developers.privacy.com). Built on
`httpx` and `pydantic` v2; requires Python 3.13.

A paid Privacy plan is required to get an API key. Free accounts cannot
use the API.

## Install

From a git source (this repo is private):

```bash
uv add "privacy-api @ git+ssh://git@github.com/<owner>/privacy-api.git"
```

For local development, run `uv sync`.

## Authentication

Pass `api_key=` or set `PRIVACY_API_KEY`. Omitting `api_key` falls back
to the environment variable; an explicit empty string does not. A missing
key raises `AuthError`.

```python
from privacy_api import Client

client = Client(api_key="...")  # or Client() with PRIVACY_API_KEY set
sandbox = Client(sandbox=True)  # https://sandbox.privacy.com/v1
```

Failed `GET` requests (429, 5xx, network errors) are retried with
exponential backoff, honoring `Retry-After`. `max_retries` (default 3)
controls this. `POST` and `PATCH` are never retried.

## Quickstart

```python
from datetime import date

from privacy_api import Client, PrivacyError, Card, Transaction, Page

with Client() as client:                 # key from PRIVACY_API_KEY
    client.status()                      # -> str (the "message")
    page = client.transactions.list(begin=date(2026, 1, 1), page_size=100)
    for tx in client.transactions.iter(card_token="..."):
        ...
    card = client.cards.get("token")
    card = client.cards.create(type="SINGLE_USE", memo="x", spend_limit=1000)
    card = client.cards.update("token", state="PAUSED")
    card = client.cards.share("token", recipient_email="a@b.c")
    for fs in client.funding_sources.iter():
        ...
```

Amounts are integers in cents. `begin` and `end` accept a `date`, a
`datetime` (converted to UTC; naive means UTC), or a ready-made string.

## Pagination

`cards.list()` and `transactions.list()` return one `Page` (`data`,
`page`, `total_entries`, `total_pages`) and take `page` and `page_size`
(default 50, maximum 100).

`cards.iter()` and `transactions.iter()` are lazy generators: they
request one page at a time, only as you consume items, and stop after
the last page. They default to `page_size=100`.

Funding sources are not paginated. `funding_sources.list()` is one
request and `funding_sources.iter()` yields its items.

## Errors

Every error derives from `PrivacyError`, which carries `status_code` and
`debugging_request_id`.

| Exception | When |
| --- | --- |
| `BadRequestError` | 400, 422 |
| `AuthError` | 401, 403, or no API key |
| `NotFoundError` | 404 |
| `RateLimitError` | 429 (`retry_after` attribute) |
| `ServerError` | 5xx |
| `NetworkError` | transport failure |

```python
from privacy_api import Client, NotFoundError

with Client() as client:
    try:
        client.cards.get("missing")
    except NotFoundError:
        ...
```

## Tests

```bash
uv run pytest -q
```

`tests/test_live.py` makes read-only calls against production and is
skipped unless `PRIVACY_API_KEY` is set.
