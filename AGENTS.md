# privacy-api

Python client library for the Privacy.com virtual card API
(https://developers.privacy.com). Sync only, httpx + pydantic.

- Layout: `src/privacy_api/` (client, errors, models, resources),
  tests in `tests/`. Python 3.13, uv, ruff at 79 columns.
- Design spec: `docs/superpowers/specs/2026-10-26-privacy-api-design.md`.
  Read it before changing the public surface.
- Run checks: `uv run pytest -q` and `uv run ruff check . && uv run ruff format --check .`.
- Live tests need `PRIVACY_API_KEY`; they skip without it.
- All HTTP goes through `Client._request`. Resources never call httpx.
