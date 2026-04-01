# PLAN-0005: Provider Config Externalization — Nested Settings Pattern

> **PRD**: N/A (architectural improvement)
> **Status**: completed
> **Created**: 2026-03-28
> **Updated**: 2026-03-29
> **Owner**: Arnau Rodon

---

## 1. Context & Goal

Several service clients have hardcoded module-level constants for external API base URLs,
page sizes, concurrency caps, rate limits, and HTTP timeouts. These cannot be overridden
without redeploying a new image.

**Pattern adopted (decided 2026-03-28):**

- Operational parameters (base URLs, page sizes, rate limits, timeouts, concurrency caps)
  move into `pydantic-settings` **nested `BaseModel` sub-models** on each service's `Settings`
- True secrets (API keys, DB passwords) remain as **flat fields** on `Settings`, mapped from
  `Kubernetes Secret` env vars
- At the Helm/K8s level, secrets live in `Secret` manifests; operational params live in
  `ConfigMap` manifests — both injected as env vars, both overridable via `helm upgrade`
  (rolling restart only, no image rebuild required)
- In code, clients receive their typed config sub-model at construction — no reading of
  module globals at call time

**Env var naming** (pydantic-settings v2 with `env_nested_delimiter="__"`):
```
CONTENT_INGESTION_EODHD__BASE_URL=https://mock-eodhd/news    # override in test
CONTENT_INGESTION_HTTP_CLIENT__TIMEOUT_SECONDS=60.0           # tune in production
```

---

## 2. Affected Services

| Service | Scope | Hardcoded values |
|---------|-------|-----------------|
| **S4 Content-Ingestion** | Primary | 4 client files (EODHD, Finnhub, NewsAPI, SEC EDGAR) + app.py rate limits + httpx timeout |
| **S2 Market-Ingestion** | Minor | `_BASE_URL` in `eodhd.py` provider adapter |
| All other services | None | Already clean — no action needed |

---

## 3. Dependency Graph

```
Sub-plan A (S4):
  Wave A-1 (config models) ──→ Wave A-2 (clients + wiring + tests + docs)

Sub-plan B (S2):
  Wave B-1 (EODHD URL + adapter) — independent of Sub-plan A
```

Sub-plans A and B touch different services and can be executed in parallel worktrees.

---

## 4. Sub-Plan A: S4 Content-Ingestion

### Wave A-1: Add Nested Provider Settings Models ✅

**Goal**: Define 5 `BaseModel` sub-models and wire them into `Settings` — zero client changes in this wave, only config additions.

**Depends on**: none
**Estimated effort**: 20–35 min
**Architecture layer**: config
**Status**: **DONE** — 2026-03-28 · 13 new tests + 280 unit total pass · ruff + mypy clean

---

#### T-A-1-01: Add nested settings models to `config.py`

**Type**: impl
**depends_on**: none
**blocks**: [T-A-2-01, T-A-2-02, T-A-2-03, T-A-2-04, T-A-2-05]
**Target files**:
- `services/content-ingestion/src/content_ingestion/config.py`

**What to build**:
Add 5 new `BaseModel` subclasses (from `pydantic`) to `config.py` above the `Settings` class.
Wire them as fields on `Settings`. Add `env_nested_delimiter="__"` to `SettingsConfigDict`
so env vars like `CONTENT_INGESTION_EODHD__BASE_URL` map to `settings.eodhd.base_url`.

**Entities / Components**:

- **`EODHDProviderSettings(BaseModel)`**
  - `base_url: str = "https://eodhd.com/api/news"` — EODHD news endpoint
  - `page_size: int = 100` — results per page (was `_PAGE_SIZE` in `eodhd/client.py`)
  - `rate_limit_per_second: float = 10.0` — token-bucket capacity + refill rate (was hardcoded in `app.py:112`)

- **`FinnhubProviderSettings(BaseModel)`**
  - `base_url: str = "https://finnhub.io/api/v1"` — Finnhub API root (was `_BASE_URL` in `finnhub/client.py`)
  - `rate_limit_per_minute: int = 55` — token-bucket capacity (was hardcoded in `app.py:121`)

- **`NewsAPIProviderSettings(BaseModel)`**
  - `base_url: str = "https://newsapi.org/v2/everything"` — NewsAPI endpoint (was `_BASE_URL` in `newsapi/client.py`)
  - `page_size: int = 100` — results per page (was `_PAGE_SIZE`)
  - `quota_ttl_seconds: int = 86400` — daily quota key TTL in Valkey (was `_QUOTA_TTL_SECONDS`)

- **`SECEdgarProviderSettings(BaseModel)`**
  - `efts_url: str = "https://efts.sec.gov/LATEST/search-index"` — EFTS search endpoint (was `_EFTS_URL`)
  - `filing_base_url: str = "https://www.sec.gov/Archives/edgar/data"` — filing document base (was `_FILING_BASE_URL`)
  - `default_forms: str = "10-K,10-Q,8-K,DEF14A"` — comma-separated form types (was `_DEFAULT_FORMS`)
  - `max_concurrent: int = 8` — asyncio semaphore size (was `_MAX_CONCURRENT`)

- **`HTTPClientSettings(BaseModel)`**
  - `timeout_seconds: float = 30.0` — httpx total timeout (was `httpx.Timeout(30.0, ...)` in `app.py:286`)
  - `connect_timeout_seconds: float = 5.0` — httpx connect timeout (was hardcoded 5.0)
  - `max_retries: int = 3` — default retry count (was `DEFAULT_MAX_RETRIES` in `base.py`)

**Logic & Behavior**:
- Import `BaseModel` from `pydantic` (already a transitive dep via `pydantic-settings`)
- Add `env_nested_delimiter="__"` to the existing `SettingsConfigDict` call
- Add 5 fields on `Settings` with field names matching their nested env var prefix segment:
  ```python
  eodhd: EODHDProviderSettings = EODHDProviderSettings()
  finnhub: FinnhubProviderSettings = FinnhubProviderSettings()
  newsapi: NewsAPIProviderSettings = NewsAPIProviderSettings()
  sec_edgar: SECEdgarProviderSettings = SECEdgarProviderSettings()
  http_client: HTTPClientSettings = HTTPClientSettings()
  ```
- The existing flat fields (`eodhd_api_key`, `finnhub_api_key`, `newsapi_key`,
  `sec_edgar_user_agent`, `newsapi_daily_limit`) remain **unchanged** — secrets stay flat
- Note: `newsapi_daily_limit` already exists as a flat field on `Settings` and is used by
  `NewsAPIClient` — leave it in place; the new `newsapi.page_size` and `newsapi.quota_ttl_seconds`
  are additive

**Acceptance criteria**:
- [x] All 5 nested model classes defined with correct field names, types, and defaults
- [x] `env_nested_delimiter="__"` added to `SettingsConfigDict`
- [x] 5 fields added to `Settings` with default factory constructors
- [x] `ruff check` and `mypy` pass on `config.py`
- [x] Existing `Settings()` instantiation still works with no env vars set

---

#### T-A-1-02: Write unit tests for new config models

**Type**: test
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `services/content-ingestion/tests/unit/test_config.py` (new file)

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_eodhd_defaults` | `Settings().eodhd.base_url == "https://eodhd.com/api/news"` and `page_size == 100` | unit |
| `test_finnhub_defaults` | `Settings().finnhub.base_url == "https://finnhub.io/api/v1"` and `rate_limit_per_minute == 55` | unit |
| `test_newsapi_defaults` | `Settings().newsapi.base_url`, `page_size == 100`, `quota_ttl_seconds == 86400` | unit |
| `test_sec_edgar_defaults` | All 4 SEC EDGAR fields have correct defaults | unit |
| `test_http_client_defaults` | `timeout_seconds == 30.0`, `connect_timeout_seconds == 5.0`, `max_retries == 3` | unit |
| `test_eodhd_base_url_env_override` | `monkeypatch.setenv("CONTENT_INGESTION_EODHD__BASE_URL", "http://mock")` → `Settings().eodhd.base_url == "http://mock"` | unit |
| `test_finnhub_rate_limit_env_override` | `monkeypatch.setenv("CONTENT_INGESTION_FINNHUB__RATE_LIMIT_PER_MINUTE", "30")` → `Settings().finnhub.rate_limit_per_minute == 30` | unit |
| `test_sec_edgar_max_concurrent_env_override` | `monkeypatch.setenv("CONTENT_INGESTION_SEC_EDGAR__MAX_CONCURRENT", "4")` → `Settings().sec_edgar.max_concurrent == 4` | unit |
| `test_http_timeout_env_override` | `monkeypatch.setenv("CONTENT_INGESTION_HTTP_CLIENT__TIMEOUT_SECONDS", "60.0")` → `Settings().http_client.timeout_seconds == 60.0` | unit |
| `test_flat_secrets_unaffected` | `eodhd_api_key`, `finnhub_api_key`, `newsapi_key` still work from their existing flat env vars | unit |

- Minimum test count: 10
- Use `monkeypatch` to set env vars (avoids `.env` file loading side effects)
- Force `env_file=None` or use `model_config` override in test to avoid reading local `.env`

**Acceptance criteria**:
- [x] 10+ tests in `test_config.py` (13 written)
- [x] All tests pass (`python -m pytest tests/unit/test_config.py -v`)
- [x] `ruff check` and `mypy` pass on test file

---

#### Pre-read (agent must read before starting Wave A-1)
- `services/content-ingestion/src/content_ingestion/config.py` — current Settings structure
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/client.py` — to confirm exact defaults to replicate
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/client.py` — same
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/client.py` — same
- `services/content-ingestion/src/content_ingestion/app.py` lines 110–130 and 280–290 — to confirm token-bucket and timeout values

#### Validation Gate
- [x] `ruff check services/content-ingestion/src/content_ingestion/config.py` passes
- [x] `mypy services/content-ingestion/src/content_ingestion/config.py` passes
- [x] `python -m pytest services/content-ingestion/tests/unit/test_config.py -v` — 13 tests pass
- [x] `Settings()` instantiation (no env vars) produces objects with all expected defaults

---

### Wave A-2: Refactor Clients + Update app.py Wiring + Tests + Docs ✅

**Goal**: Remove all module-level globals from 4 client files; update constructor signatures to accept provider settings; update `app.py` to pass settings at construction; update existing client unit tests; add docs update.

**Depends on**: Wave A-1
**Estimated effort**: 60–90 min
**Architecture layer**: infrastructure + wiring
**Status**: **DONE** — 2026-03-29 · 291 unit tests pass · ruff + mypy clean

---

#### T-A-2-01: Refactor `EODHDClient` — remove globals, inject provider settings

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-2-05]
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/client.py`

**What to build**:
Remove module-level `_BASE_URL = ...` and `_PAGE_SIZE = ...`. Update `__init__` to accept
`provider_cfg: EODHDProviderSettings`. Store values as instance attributes.

**Logic & Behavior**:
- New constructor signature:
  ```python
  def __init__(
      self,
      http_client: httpx.AsyncClient,
      api_key: str,
      provider_cfg: EODHDProviderSettings,
  ) -> None:
      self._http = http_client
      self._api_key = api_key
      self._base_url = provider_cfg.base_url
      self._page_size = provider_cfg.page_size
  ```
- Replace all uses of `_BASE_URL` with `self._base_url`
- Replace all uses of `_PAGE_SIZE` with `self._page_size`
- Import `EODHDProviderSettings` from `content_ingestion.config`
- Delete the two module-level constant lines

**Acceptance criteria**:
- [x] No `_BASE_URL` or `_PAGE_SIZE` module-level names remain in the file
- [x] Constructor accepts `provider_cfg: EODHDProviderSettings`
- [x] `ruff check` and `mypy` pass on the file

---

#### T-A-2-02: Refactor `FinnhubClient` — remove globals, inject provider settings

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-2-05]
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/client.py`

**What to build**:
Remove `_BASE_URL = "https://finnhub.io/api/v1"`. Update `__init__` to accept
`provider_cfg: FinnhubProviderSettings`. Store `self._base_url = provider_cfg.base_url`.

**Logic & Behavior**:
- New constructor signature:
  ```python
  def __init__(
      self,
      http_client: httpx.AsyncClient,
      api_key: str,
      provider_cfg: FinnhubProviderSettings,
  ) -> None:
      self._http = http_client
      self._api_key = api_key
      self._base_url = provider_cfg.base_url
  ```
- Replace `_BASE_URL` usages (3 occurrences in `fetch_company_news`, `fetch_transcript_list`,
  `fetch_transcript`) with `self._base_url`
- Delete the module-level constant line
- Import `FinnhubProviderSettings` from `content_ingestion.config`

**Acceptance criteria**:
- [x] No `_BASE_URL` module-level name remains in the file
- [x] Constructor accepts `provider_cfg: FinnhubProviderSettings`
- [x] `ruff check` and `mypy` pass

---

#### T-A-2-03: Refactor `NewsAPIClient` — remove globals, inject provider settings

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-2-05]
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/client.py`

**What to build**:
Remove `_BASE_URL`, `_PAGE_SIZE`, `_QUOTA_TTL_SECONDS` module-level constants. Update `__init__`
to accept `provider_cfg: NewsAPIProviderSettings`. Store values as instance attributes.

**Logic & Behavior**:
- New constructor signature:
  ```python
  def __init__(
      self,
      http_client: httpx.AsyncClient,
      api_key: str,
      provider_cfg: NewsAPIProviderSettings,
      valkey: ValkeyClient | None = None,
      daily_limit: int = 100,
  ) -> None:
      self._http = http_client
      self._api_key = api_key
      self._base_url = provider_cfg.base_url
      self._page_size = provider_cfg.page_size
      self._quota_ttl_seconds = provider_cfg.quota_ttl_seconds
      self._valkey = valkey
      self._daily_limit = daily_limit
  ```
- Replace `_BASE_URL` with `self._base_url`, `_PAGE_SIZE` with `self._page_size`,
  `_QUOTA_TTL_SECONDS` with `self._quota_ttl_seconds`
- `daily_limit` parameter stays in place — it continues to come from
  `settings.newsapi_daily_limit` (flat field) in the wiring in `app.py`
- Import `NewsAPIProviderSettings` from `content_ingestion.config`

**Acceptance criteria**:
- [x] No `_BASE_URL`, `_PAGE_SIZE`, `_QUOTA_TTL_SECONDS` module-level names remain
- [x] Constructor accepts `provider_cfg: NewsAPIProviderSettings`
- [x] `ruff check` and `mypy` pass

---

#### T-A-2-04: Refactor `SECEdgarClient` + `base.py` — remove globals, inject provider settings

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-2-05]
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/base.py`

**What to build**:

*`sec_edgar/client.py`*: Remove 4 module-level constants. Update `__init__` to accept
`provider_cfg: SECEdgarProviderSettings`. Store values as instance attributes.

*`base.py`*: `DEFAULT_MAX_RETRIES` and `DEFAULT_BACKOFF_FACTORS` remain as module-level
constants (they are used as `RetryConfig` field defaults and the backoff sequence is not
user-tunable). No change needed to `base.py` — the `max_retries` from `HTTPClientSettings`
will be applied in `app.py` by building a `RetryConfig` and storing it on each adapter.
See T-A-2-05 for how `max_retries` flows from settings → `RetryConfig`.

**Logic & Behavior for `sec_edgar/client.py`**:
- New constructor signature:
  ```python
  def __init__(
      self,
      http_client: httpx.AsyncClient,
      user_agent: str,
      provider_cfg: SECEdgarProviderSettings,
  ) -> None:
      if not user_agent or not user_agent.strip():
          msg = "SEC EDGAR requires a User-Agent header. Set SEC_EDGAR_USER_AGENT."
          raise ConfigurationError(msg)
      self._http = http_client
      self._user_agent = user_agent
      self._efts_url = provider_cfg.efts_url
      self._filing_base_url = provider_cfg.filing_base_url
      self._default_forms = provider_cfg.default_forms
      self._semaphore = asyncio.Semaphore(provider_cfg.max_concurrent)
  ```
- Replace `_EFTS_URL` with `self._efts_url`, `_FILING_BASE_URL` with `self._filing_base_url`
- `search_filings` method has `forms: str = _DEFAULT_FORMS` as default param — change to:
  ```python
  async def search_filings(self, *, from_date: str = "", to_date: str = "", forms: str = "") -> ...:
      actual_forms = forms or self._default_forms
      # use actual_forms instead of forms below
  ```
- `fetch_filing_document` builds URL with `_FILING_BASE_URL` → use `self._filing_base_url`
- Import `SECEdgarProviderSettings` from `content_ingestion.config`
- Delete all 4 module-level constant lines

**Acceptance criteria**:
- [x] No `_EFTS_URL`, `_FILING_BASE_URL`, `_DEFAULT_FORMS`, `_MAX_CONCURRENT` remain in `sec_edgar/client.py`
- [x] Constructor accepts `provider_cfg: SECEdgarProviderSettings`
- [x] `search_filings` uses `forms or self._default_forms` pattern
- [x] `ruff check` and `mypy` pass on both files

---

#### T-A-2-05: Update `app.py` wiring — pass settings at client construction

**Type**: impl
**depends_on**: [T-A-2-01, T-A-2-02, T-A-2-03, T-A-2-04]
**blocks**: [T-A-2-06]
**Target files**:
- `services/content-ingestion/src/content_ingestion/app.py`

**What to build**:
Update the `lifespan` function and `_run_fetch_cycle` function to pass nested settings
sub-models at client construction and to use config values for httpx timeout and TokenBucket.

**Logic & Behavior**:

*httpx client (in `lifespan`, lines ~284–287)*:
```python
http_client = httpx.AsyncClient(
    transport=SSRFSafeTransport(),
    timeout=httpx.Timeout(
        settings.http_client.timeout_seconds,
        connect=settings.http_client.connect_timeout_seconds,
    ),
)
```

*Client construction (in `_run_fetch_cycle`, lines ~112–128)*:
```python
# EODHD branch
rate_limiter = TokenBucket(
    capacity=settings.eodhd.rate_limit_per_second,
    tokens=settings.eodhd.rate_limit_per_second,
    refill_rate=settings.eodhd.rate_limit_per_second,
    last_refill=now,
)
client = EODHDClient(
    http_client=http_client,
    api_key=settings.eodhd_api_key,
    provider_cfg=settings.eodhd,
)

# Finnhub branch
rate_per_second = settings.finnhub.rate_limit_per_minute / 60.0
rate_limiter = TokenBucket(
    capacity=settings.finnhub.rate_limit_per_minute,
    tokens=float(settings.finnhub.rate_limit_per_minute),
    refill_rate=rate_per_second,
    last_refill=now,
)
client = FinnhubClient(
    http_client=http_client,
    api_key=settings.finnhub_api_key,
    provider_cfg=settings.finnhub,
)

# SEC EDGAR branch
client = SECEdgarClient(
    http_client=http_client,
    user_agent=settings.sec_edgar_user_agent,
    provider_cfg=settings.sec_edgar,
)

# NewsAPI branch
client = NewsAPIClient(
    http_client=http_client,
    api_key=settings.newsapi_key,
    provider_cfg=settings.newsapi,
    valkey=valkey,
    daily_limit=settings.newsapi_daily_limit,
)
```

**Acceptance criteria**:
- [x] No hardcoded `httpx.Timeout(30.0, ...)` — values come from `settings.http_client`
- [x] No hardcoded `TokenBucket(capacity=10, ...)` or `TokenBucket(capacity=55, ...)` — values from `settings.eodhd` / `settings.finnhub`
- [x] All 4 client constructors pass their respective `provider_cfg` argument
- [x] `ruff check` and `mypy` pass on `app.py`

---

#### T-A-2-06: Update existing client unit tests + add env-override integration test + update docs

**Type**: test + docs
**depends_on**: [T-A-2-01, T-A-2-02, T-A-2-03, T-A-2-04, T-A-2-05]
**blocks**: none
**Target files**:
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_eodhd_client.py`
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_finnhub_client.py`
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_newsapi_client.py`
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_sec_edgar_client.py`
- `services/content-ingestion/tests/unit/test_app_fetch_cycle.py` (may need updates)
- `docs/services/content-ingestion.md` — update Configuration section

**What to build**:
Update all 4 client test files to pass `provider_cfg=<ModelName>()` (using defaults) to the
client constructors. Add a new "custom URL" test to each to verify the env-override path works.
Update the service doc's configuration section to document the new nested settings.

**Tests to write** (additions per client test file):

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_eodhd_client_custom_base_url` | Constructing with `EODHDProviderSettings(base_url="http://mock/news")` makes requests to the mock URL | unit |
| `test_eodhd_client_custom_page_size` | `page_size=10` stops pagination after a single short page | unit |
| `test_finnhub_client_custom_base_url` | Requests go to overridden base URL | unit |
| `test_newsapi_client_custom_quota_ttl` | TTL value passed to `valkey.expire` matches `quota_ttl_seconds` | unit |
| `test_sec_edgar_client_custom_urls` | EFTS and filing base URLs are configurable | unit |
| `test_sec_edgar_custom_max_concurrent` | Semaphore size matches `max_concurrent` | unit |

**Downstream test impact**:
- `test_app_fetch_cycle.py` — may construct clients or mock them; review and update if
  client constructors are called directly
- `test_app_robustness.py` — same review needed
- `test_scheduler.py` — check if it instantiates clients directly

**Doc update** (`docs/services/content-ingestion.md`):
In the Configuration section, add a sub-section "Nested Provider Settings" documenting:
- The 5 nested models with their fields, defaults, and corresponding env var names
- Example Helm `ConfigMap` snippet for overriding EODHD base URL
- Note that API keys remain as flat fields (Kubernetes `Secret`)

**Acceptance criteria**:
- [x] All 4 client test files updated — existing tests pass with `provider_cfg` arg added
- [x] 6+ new tests covering custom URL/config overrides (10 added: 2 EODHD + 1 Finnhub + 1 NewsAPI + 4 SEC EDGAR + 2 forms override)
- [x] `test_app_fetch_cycle.py` / `test_app_robustness.py` / `test_scheduler.py` reviewed and updated if needed (test_newsapi.py + test_sec_edgar.py downstream updated)
- [x] `python -m pytest services/content-ingestion/tests/unit/ -v` — all tests pass (291 pass)
- [x] `docs/services/content-ingestion.md` updated

---

#### Pre-read (agent must read before starting Wave A-2)
- `services/content-ingestion/src/content_ingestion/config.py` — confirm nested models from Wave A-1
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/client.py`
- `services/content-ingestion/src/content_ingestion/app.py` (full file)
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_eodhd_client.py`
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_finnhub_client.py`
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_newsapi_client.py`
- `services/content-ingestion/tests/unit/infrastructure/adapters/test_sec_edgar_client.py`
- `services/content-ingestion/tests/unit/test_app_fetch_cycle.py`
- `docs/services/content-ingestion.md`

#### Validation Gate
- [x] `ruff check services/content-ingestion/src/` passes
- [x] `mypy services/content-ingestion/src/` passes (pre-existing import-not-found only)
- [x] `python -m pytest services/content-ingestion/tests/unit/ -v` — all tests pass (291 pass, 0 failures)
- [x] No module-level `_BASE_URL`, `_PAGE_SIZE`, `_QUOTA_TTL_SECONDS`, `_EFTS_URL`, `_FILING_BASE_URL`, `_DEFAULT_FORMS`, `_MAX_CONCURRENT` remain in any adapter file
- [x] `docs/services/content-ingestion.md` updated

#### Regression Guardrails
- **BP-023** (pre-commit ruff-format sync): Run `uvx ruff format services/content-ingestion/` before committing — ensure no AM/MM staged Python files
- Watch for circular imports: `config.py` imports `BaseModel` from pydantic (fine); client files import from `config.py` — ensure no circular dependency via `domain/` or `application/`

---

## 5. Sub-Plan B: S2 Market-Ingestion

### Wave B-1: Externalize EODHD Base URL ✅

**Goal**: Add `eodhd_base_url` to market-ingestion `Settings`; inject it into `EODHDProviderAdapter` at construction; remove `_BASE_URL` module-level constant.

**Depends on**: none (independent of Sub-plan A)
**Estimated effort**: 20–30 min
**Architecture layer**: config + infrastructure
**Status**: **DONE** — 2026-03-29 · 374 unit tests pass · ruff + mypy clean

---

#### T-B-1-01: Add `eodhd_base_url` to market-ingestion `Settings` + inject into adapter

**Type**: impl
**depends_on**: none
**blocks**: [T-B-1-02]
**Target files**:
- `services/market-ingestion/src/market_ingestion/config.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py`
- Wiring file that instantiates `EODHDProviderAdapter` (likely in `app.py` or a factory — read before editing)

**What to build**:

*`config.py`*: Add one flat field to the existing `Settings` class, in the "Provider API keys"
section (it is not a secret, so no nested model needed — market-ingestion's config is already
flat and this one URL doesn't justify a structural change):
```python
# Provider base URLs (operational — overridable without image rebuild)
eodhd_base_url: str = "https://eodhd.com/api"
```

*`eodhd.py`*: Remove `_BASE_URL = "https://eodhd.com/api"`. Update `__init__` to accept
`base_url: str`:
```python
def __init__(self, api_key: str, client: httpx.AsyncClient, base_url: str = "https://eodhd.com/api") -> None:
    self._api_key = api_key
    self._client = client
    self._base_url = base_url
```
Replace all uses of `_BASE_URL` with `self._base_url`.

*Wiring*: Find where `EODHDProviderAdapter` is instantiated (search for `EODHDProviderAdapter(`).
Pass `base_url=settings.eodhd_base_url` at construction.

**Acceptance criteria**:
- [x] `_BASE_URL` module-level constant removed from `eodhd.py`
- [x] `eodhd_base_url` field added to market-ingestion `Settings` with correct default
- [x] Wiring passes `base_url=settings.eodhd_base_url` at adapter construction
- [x] `ruff check` and `mypy` pass on all 3 modified files

---

#### T-B-1-02: Add test for URL override + update docs

**Type**: test + docs
**depends_on**: [T-B-1-01]
**blocks**: none
**Target files**:
- `services/market-ingestion/tests/unit/` — find or create appropriate test file for `EODHDProviderAdapter`
- `docs/services/market-ingestion.md` — update Configuration section

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_eodhd_adapter_custom_base_url` | Constructing `EODHDProviderAdapter` with `base_url="http://mock"` makes requests to `http://mock/*` | unit |
| `test_market_ingestion_eodhd_base_url_env_override` | `monkeypatch.setenv("MARKET_INGESTION_EODHD_BASE_URL", "http://mock")` → `Settings().eodhd_base_url == "http://mock"` | unit |

**Acceptance criteria**:
- [x] 2 tests pass
- [x] `docs/services/market-ingestion.md` updated to document `eodhd_base_url`

---

#### Pre-read (agent must read before starting Wave B-1)
- `services/market-ingestion/src/market_ingestion/config.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py`
- Search `services/market-ingestion/src/` for `EODHDProviderAdapter(` to find wiring location
- `docs/services/market-ingestion.md`

#### Validation Gate
- [ ] `ruff check services/market-ingestion/src/` passes
- [ ] `mypy services/market-ingestion/src/` passes
- [ ] Relevant unit tests pass
- [ ] `_BASE_URL` constant absent from `eodhd.py`
- [ ] `docs/services/market-ingestion.md` updated

---

## 6. Cross-Cutting Concerns

### 6.1 Contract Changes
None — no Avro schemas, REST API contracts, or Kafka topics are affected.

### 6.2 Migration Needs
None — no DB schema changes.

### 6.3 Configuration Changes
New env vars introduced (all have safe defaults — no breakage if unset):

**S4 Content-Ingestion** (prefix `CONTENT_INGESTION_`):
```
CONTENT_INGESTION_EODHD__BASE_URL            # default: https://eodhd.com/api/news
CONTENT_INGESTION_EODHD__PAGE_SIZE           # default: 100
CONTENT_INGESTION_EODHD__RATE_LIMIT_PER_SECOND  # default: 10.0
CONTENT_INGESTION_FINNHUB__BASE_URL          # default: https://finnhub.io/api/v1
CONTENT_INGESTION_FINNHUB__RATE_LIMIT_PER_MINUTE  # default: 55
CONTENT_INGESTION_NEWSAPI__BASE_URL          # default: https://newsapi.org/v2/everything
CONTENT_INGESTION_NEWSAPI__PAGE_SIZE         # default: 100
CONTENT_INGESTION_NEWSAPI__QUOTA_TTL_SECONDS  # default: 86400
CONTENT_INGESTION_SEC_EDGAR__EFTS_URL        # default: https://efts.sec.gov/LATEST/search-index
CONTENT_INGESTION_SEC_EDGAR__FILING_BASE_URL  # default: https://www.sec.gov/Archives/edgar/data
CONTENT_INGESTION_SEC_EDGAR__DEFAULT_FORMS   # default: 10-K,10-Q,8-K,DEF14A
CONTENT_INGESTION_SEC_EDGAR__MAX_CONCURRENT  # default: 8
CONTENT_INGESTION_HTTP_CLIENT__TIMEOUT_SECONDS       # default: 30.0
CONTENT_INGESTION_HTTP_CLIENT__CONNECT_TIMEOUT_SECONDS  # default: 5.0
CONTENT_INGESTION_HTTP_CLIENT__MAX_RETRIES   # default: 3
```

**S2 Market-Ingestion**:
```
MARKET_INGESTION_EODHD_BASE_URL              # default: https://eodhd.com/api
```

### 6.4 Documentation Updates
- `docs/services/content-ingestion.md` — Configuration section (Wave A-2)
- `docs/services/market-ingestion.md` — Configuration section (Wave B-1)

---

## 7. Risk Assessment

### Critical Path
Wave A-1 → Wave A-2 is the only dependency chain.
Wave B-1 is independent and can run in parallel.

### Highest Risk
**Wave A-2 (client refactors + test updates)** — touches 4 client files and app.py in one wave.
The risk is that existing tests instantiate clients without `provider_cfg`, causing `TypeError`.
Mitigation: Read all 4 existing test files before editing clients; update tests atomically
with their corresponding client changes.

### Rollback Strategy
All changes are additive (new config fields with defaults) + in-place refactors within one service.
If A-2 fails mid-wave: the new config model from A-1 is harmless (unused). Revert only the
client file changes, and the service continues to work with the old constructor signatures.

### Testing Gaps
Integration tests (test_pipeline.py, test_admin_api.py) start a full app via TestClient.
These are less likely to break (they don't construct clients directly) but should be run
at the wave boundary as a smoke check.

---

## 8. Task Summary

| Wave | Tasks | Type | Est. Effort |
|------|-------|------|-------------|
| A-1 | T-A-1-01, T-A-1-02 | config + test | 20–35 min |
| A-2 | T-A-2-01 to T-A-2-06 | impl + test + docs | 60–90 min |
| B-1 | T-B-1-01, T-B-1-02 | impl + test + docs | 20–30 min |

**Total**: 9 tasks, 3 waves, ~100–155 minutes

---

## 9. Wave Status Tracking

| Wave | Status | Commit |
|------|--------|--------|
| A-1 | pending | — |
| A-2 | pending | — |
| B-1 | pending | — |
