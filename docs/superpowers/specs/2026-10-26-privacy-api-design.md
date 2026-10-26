# privacy-api design

Date: 2026-10-26. Status: approved in chat, implemented by overseer run
`2026-10-26-privacy-api`.

## Goal

A small, typed, synchronous Python client for the Privacy.com developer
API, published as a private GitHub repo and consumed by
`context-pipeline/extractors/personal-finance` through a git source.

## API facts (from https://developers.privacy.com, 2026-10-26)

- Base URLs: production `https://api.privacy.com/v1`, sandbox
  `https://sandbox.privacy.com/v1`.
- Auth header: `Authorization: api-key <KEY>`. A paid plan is required.
- Endpoints: `GET /cards`, `POST /cards`, `GET /cards/{token}`,
  `PATCH /cards/{token}`, `POST /cards/{token}/share`,
  `GET /funding_sources`, `GET /transactions`, `GET /status`.
- List responses: `{"data": [...], "page": int, "total_entries": int,
  "total_pages": int}`. Query `page` (default 1) and `page_size`
  (default 50, max 100 per the OpenAPI spec).
- Date filters `begin` and `end` are strings. The OpenAPI spec says
  ISO 8601 date-time in UTC; the transactions guide says `YYYY-MM-DD`.
  Both are accepted server-side as far as the docs show.
- Error body: `{"message": str, "debugging_request_id": str}` on
  400, 401, 404, 422, 429. No rate-limit headers are documented; the
  rate-limits page is a 404.
- Amounts are integers in the currency's smallest unit (cents).
- `created` on cards and transactions is `2021-06-28T22:53:15Z`;
  on funding sources it is `2020-07-08 17:57:36` (space, no zone) and
  may be null. All times are UTC.
- A transaction in a list response carries a nested `card` object;
  the OpenAPI schema lists `card_token`. Treat both as optional and
  derive `card_token` from `card.token` when absent.
- `pan` and `cvv` are documented for single-card responses (get,
  create, update, share). The guide says they are absent from list
  responses, but the transactions reference example embeds them in the
  nested `card`. Treat both as optional everywhere and preserve them
  whenever present.
- `GET /funding_sources` is not paginated: its only query parameter is
  `account_token`, and the response's `page` and `total_pages` are
  documented as always 1. Sending `page` or `page_size` is unsupported.

## Package

- Name `privacy-api`, import `privacy_api`, Python 3.13, uv,
  hatchling, src layout. Dependencies: `httpx`, `pydantic` v2. Dev:
  `pytest`, `ruff` (79 columns).
- Files: `src/privacy_api/{__init__,client,errors,models,resources}.py`,
  `py.typed`, `tests/{conftest,test_client,test_models,test_resources,test_live}.py`.
- No CLI, no async client, no webhook receiver, no pydantic-settings.

## Public surface

```python
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

### `client.py`

```python
PRODUCTION_URL = "https://api.privacy.com/v1"
SANDBOX_URL = "https://sandbox.privacy.com/v1"
ENV_API_KEY = "PRIVACY_API_KEY"

class Client:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        sandbox: bool = False,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None
    def status(self) -> str
    def close(self) -> None
    def __enter__(self) -> Client; def __exit__(...) -> None
    def _request(self, method: str, path: str, *,
                 params: dict[str, Any] | None = None,
                 json: dict[str, Any] | None = None) -> Any
```

- `api_key` None falls back to `os.environ.get(ENV_API_KEY)`. Only
  None triggers the fallback: an explicit `""` does not. If the chosen
  value is None or `""`, raise `AuthError("No API key: pass api_key=
  or set PRIVACY_API_KEY")`.
- `base_url` wins over `sandbox`; `sandbox=True` selects `SANDBOX_URL`;
  default `PRODUCTION_URL`. Trailing slash stripped.
- One `httpx.Client` built in `__init__` with headers
  `Authorization: api-key <key>`, `Accept: application/json`,
  `User-Agent: privacy-api-python/<__version__>`, the timeout, and
  the `transport` when given (tests pass `httpx.MockTransport`).
- `params` entries whose value is `None` are dropped before sending.
- `_request` is the only place httpx is called. It returns
  `response.json()` for 2xx. For non-2xx it raises the error from
  `errors.from_response`.
- Retries apply only when `method == "GET"`. Retryable failures are
  a `429` response, any `5xx` response, and `httpx.TransportError`.
  The initial request is attempt 0 and is sent immediately with no
  sleep. Total attempts are `max_retries + 1`; `max_retries=0` means
  one request and no sleep. After a retryable failure, if another
  attempt remains, sleep then retry; retry number `r` (r starting at
  1) sleeps `min(0.5 * 2 ** (r - 1), 8.0) + random.uniform(0, 0.25)`
  seconds, so with zero jitter the sequence is 0.5, 1, 2, 4, 8, 8.
  When the failed response (429 or 5xx alike) carries a `Retry-After`
  header whose value parses with `float()` to a finite number >= 0,
  that number replaces the whole delay, jitter included; any other
  value (absent, non-numeric, negative, NaN, inf) uses the backoff.
  Sleep via `time.sleep` and jitter via `random.uniform`, both looked
  up on the modules at call time (tests monkeypatch
  `privacy_api.client.time.sleep` and `privacy_api.client.random.uniform`).
  Never sleep after the last attempt. Log each retry at WARNING with
  method, path, status or exception class, and delay. When attempts
  are exhausted raise the mapped error of the last failure. Non-GET
  methods (POST, PATCH, and any other) make exactly one request and
  raise on the first failure, for responses and transport errors alike.
- `status()` calls `GET /status` and returns `data["message"]`.
- Module logger `logging.getLogger(__name__)`; DEBUG line per request
  with method, path, status.

### `errors.py`

```python
class PrivacyError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None,
                 debugging_request_id: str | None = None) -> None
class NetworkError(PrivacyError)      # wraps httpx.TransportError
class BadRequestError(PrivacyError)   # 400, 422
class AuthError(PrivacyError)         # 401, 403, missing key
class NotFoundError(PrivacyError)     # 404
class RateLimitError(PrivacyError)    # 429; extra attr retry_after: float | None
class ServerError(PrivacyError)       # >= 500

def from_response(response: httpx.Response) -> PrivacyError
```

- `from_response` decodes the body as JSON. If the result is a dict,
  each field is taken independently: `message` is the body's
  `message` when that is a str, else `"HTTP <status>"`;
  `debugging_request_id` is the body's `debugging_request_id` when
  that is a str, else None. If the body is not valid JSON or decodes
  to a non-dict (list, null, string, number), `message` is
  `"HTTP <status>"` and the id is None. Any status not listed above
  maps to `PrivacyError`. `str(err)` is the message.
  `RateLimitError.retry_after` is the `Retry-After` header parsed with
  `float()` when that yields a finite number >= 0, else None.

### `models.py`

All models, `Page` included, subclass `_Model(BaseModel)` with
`model_config = ConfigDict(extra="allow")`, so unknown fields survive
`model_dump()`. Enum-valued fields are plain `str` so an unknown value
from the API never breaks parsing. Datetimes: a `field_validator`
(mode "after") on every `datetime` and `datetime | None` field in
every model sets `tzinfo=UTC` when the parsed value is naive and
leaves None as None. Pydantic parses `"2020-07-08 17:57:36"` as a
naive datetime without help.

```python
class FundingSource(_Model):
    token: str; type: str; state: str
    created: datetime | None = None
    nickname: str | None = None; account_name: str | None = None
    last_four: str | None = None

class Card(_Model):
    token: str; created: datetime; type: str; state: str
    last_four: str; spend_limit: int; spend_limit_duration: str
    memo: str | None = None; hostname: str | None = None
    funding: FundingSource | None = None
    exp_month: str | None = None; exp_year: str | None = None
    pan: str | None = None; cvv: str | None = None

class Merchant(_Model):
    acceptor_id: str | None = None; city: str | None = None
    country: str | None = None; descriptor: str | None = None
    mcc: str | None = None; state: str | None = None

class Event(_Model):
    token: str; type: str; result: str; amount: int; created: datetime

class Funding(_Model):
    amount: int; type: str; token: str | None = None

class Transaction(_Model):
    token: str; created: datetime; status: str; result: str; amount: int
    card_token: str | None = None; card: Card | None = None
    authorization_amount: int | None = None
    merchant_amount: int | None = None
    merchant_authorization_amount: int | None = None
    merchant_currency: str | None = None
    acquirer_fee: int | None = None
    settled_amount: int | None = None
    authorization_code: str | None = None
    merchant: Merchant | None = None
    events: list[Event] = []
    funding: list[Funding] = []
    # model_validator(mode="after"): if card_token is None (missing or
    # explicit null) and card is not None, set card_token = card.token.
    # Any other explicit card_token value is kept even when it differs
    # from card.token.

class Page(_Model, Generic[T]):
    data: list[T]; page: int; total_entries: int; total_pages: int
```

### `resources.py`

Each resource holds a `Client` and calls `client._request` only.

```python
DateLike = date | datetime | str
def _fmt_date(value: DateLike | None) -> str | None
    # None -> None; str -> unchanged; datetime -> UTC, "%Y-%m-%dT%H:%M:%SZ"
    # (naive treated as UTC); date -> "YYYY-MM-DD"

class Cards:
    def list(self, *, begin: DateLike | None = None, end: DateLike | None = None,
             page: int = 1, page_size: int = 50) -> Page[Card]
    def iter(self, *, begin=None, end=None, page_size: int = 100) -> Iterator[Card]
    def get(self, token: str) -> Card
    def create(self, *, type: str, memo: str | None = None,
               funding_token: str | None = None, spend_limit: int | None = None,
               spend_limit_duration: str | None = None, state: str | None = None,
               exp_month: str | None = None, exp_year: str | None = None) -> Card
    def update(self, token: str, *, memo: str | None = None,
               spend_limit: int | None = None, spend_limit_duration: str | None = None,
               state: str | None = None) -> Card
    def share(self, token: str, *, recipient_email: str,
              theme: str | None = None) -> Card

class FundingSources:
    def list(self) -> Page[FundingSource]      # one GET, no query params
    def iter(self) -> Iterator[FundingSource]  # yields from list().data

class Transactions:
    def list(self, *, card_token: str | None = None, result: str | None = None,
             begin: DateLike | None = None, end: DateLike | None = None,
             page: int = 1, page_size: int = 50) -> Page[Transaction]
    def iter(self, *, card_token=None, result=None, begin=None, end=None,
             page_size: int = 100) -> Iterator[Transaction]
```

- `create`, `update`, `share` send every keyword argument whose value
  is not None in the JSON body, falsy values included (`spend_limit=0`
  and `memo=""` are sent); `type` and `recipient_email` always.
- `Cards.iter` and `Transactions.iter` are generators: no request is
  made until the first item is pulled. They fetch page 1 with the
  supplied filters and `page_size`, yield every item of `data` in
  order, and then, while the page just fetched has `page <
  total_pages`, fetch the next page with the same filters and
  `page_size` and yield its items. A page whose `data` is empty ends
  the iteration immediately, whatever `total_pages` says. One request
  per page; nothing is prefetched. `FundingSources.iter` yields the
  items of the single `list()` call.
- `Client.__init__` attaches `self.cards = Cards(self)`,
  `self.funding_sources = FundingSources(self)`,
  `self.transactions = Transactions(self)`.
- `__init__.py` exports `Client`, `Page`, every model, every error,
  and `__version__`.

## Testing

- Unit tests use `httpx.MockTransport` passed as `transport=`. Sample
  payloads are the ones from the docs, held in `tests/conftest.py`
  as fixtures (`card_json`, `funding_source_json`, `transaction_json`).
- `tests/test_live.py` is skipped unless `PRIVACY_API_KEY` is set
  (`pytest.mark.skipif`). It calls `status()` and
  `transactions.list(page_size=1)` against production and asserts
  types only. Read-only; it never creates or updates a card.

## Out of scope

Async client, CLI, webhook signature helper, wiring into pfin.
Each is a separate request if ever needed.
