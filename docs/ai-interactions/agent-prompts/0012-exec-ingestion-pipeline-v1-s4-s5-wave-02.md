# Execution Prompt 0012 — Ingestion Pipeline v1: S4+S5 Wave 02

**Wave:** 02 of 07
**Date issued:** 2026-03-22
**Service:** S4 Content Ingestion — Source Adapters
**Execution model:** 4 agents in parallel (one per adapter)
**Prerequisite:** Wave 01 complete and merged (T-S4-001 domain entities and T-S4-004 MinIO adapter interface must exist)

---

## Context (read first)

- Planning prompt: `docs/ai-interactions/agent-prompts/0012-ingestion-pipeline-v1-s4-s5-plan.md`
- Planning response: `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md`

---

## Assigned agent profile(s)

- `docs/agents/backend-engineer.md`
- `docs/agents/data-platform-engineer.md`

---

## Mandatory pre-read

Before writing any code, read in full:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/services/content-ingestion.md`
4. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md`
5. `docs/ai-interactions/agent-responses/0012-response-20260322-ingestion-pipeline-v1-s4-s5.md`
6. Wave 01 output files — confirm these exist before proceeding:
   - `services/content-ingestion/src/content_ingestion/domain/entities.py`
   - `services/content-ingestion/src/content_ingestion/infrastructure/storage/minio_bronze.py`
   - `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/fetch_log.py`
7. `services/content-ingestion/pyproject.toml` — verify `aiohttp`, `uuid6`, `structlog` are present.
8. `docs/libs/common.md` — UUIDv7 (`new_uuid7`), UTC time (`utc_now`), cross-service types (`DocumentId`, `EntityId`, `UrlHash`, `MinIOKey`)
9. **`docs/STANDARDS.md`** — engineering standards and anti-patterns: canonical library usage, config conventions, observability setup, testing rules

---

## Objective

Implement all four source adapters for S4 Content Ingestion. Each adapter fetches raw content from its respective external API, applies URL-based deduplication, enforces rate limits, retries on transient failures, and routes to DLQ after exhausting retries. The four adapters are entirely independent of each other — they share only the `SourceAdapter` abstract base class and the domain entities from Wave 01.

---

## Task scope for this wave

**All 4 tasks run in parallel:**

| Task ID | Description | Owner |
|---------|-------------|-------|
| T-S4-005 | EODHD source adapter (paginated fetch, sha256(url) dedup, rate limiter, 3-retry + DLQ) | Agent A |
| T-S4-006 | SEC EDGAR adapter (EFTS search, filing HTML+XBRL, 8 req/sec rate limit) | Agent B |
| T-S4-007 | Finnhub adapter (company-news + transcripts, 55/min token bucket, minute-boundary backoff) | Agent C |
| T-S4-008 | NewsAPI adapter (paginated everything, daily Valkey quota counter, halt on exhaustion) | Agent D |

---

## Why this chunk

All four adapters depend only on T-S4-001 (domain entities, `TokenBucket`, `SourceType`, `FetchResult`) and T-S4-004 (MinIO adapter interface) — both complete from Wave 01. The adapters are completely independent of each other (different external APIs, different rate-limiting strategies, different modules). Running all four in parallel keeps S4 on the critical path toward Wave 03 (scheduler + use-case). The adapter layer is the widest parallelizable chunk in the S4 build.

---

## Implementation instructions

### Shared prerequisite: SourceAdapter base class

**Before starting any individual adapter**, one agent must create the shared base (the first to start should claim it):

Create `services/content-ingestion/src/content_ingestion/infrastructure/adapters/base.py`:
```python
from abc import ABC, abstractmethod
from content_ingestion.domain.entities import Source, FetchResult

class SourceAdapter(ABC):
    @abstractmethod
    async def fetch(self, source: Source) -> list[FetchResult]:
        """Fetch raw content from the external source.

        Args:
            source: The source configuration including API credentials in source.config.

        Returns:
            List of FetchResult objects. Empty list if no new content.

        Must do:
            - Apply deduplication (skip already-fetched url_hash).
            - Apply rate limiting before each request.
            - Retry transient failures up to 3 times with exponential backoff.
            - Route to DLQ after 3 failed retries.
            - Never raise unhandled exceptions — log and return partial results.
        """
        ...
```

---

### T-S4-005 — EODHD Source Adapter

1. **Create `services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/client.py`**:
   ```python
   import aiohttp
   import hashlib
   from datetime import date

   class EodhdClient:
       BASE_URL = "https://eodhd.com/api/news"

       async def get_news(
           self,
           api_token: str,
           symbol: str | None,
           from_date: date,
           to_date: date,
           offset: int,
           limit: int = 100,
       ) -> list[dict]:
           params = {
               "api_token": api_token,
               "from": from_date.isoformat(),
               "to": to_date.isoformat(),
               "offset": offset,
               "limit": limit,
               "fmt": "json",
           }
           if symbol:
               params["s"] = symbol
           async with aiohttp.ClientSession() as session:
               async with session.get(self.BASE_URL, params=params) as resp:
                   resp.raise_for_status()
                   return await resp.json()
   ```

2. **Create `services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/adapter.py`**:
   - Class `EodhdAdapter(SourceAdapter)`.
   - Constructor takes `client: EodhdClient`, `fetch_log_repo: FetchLogRepository`, `outbox_repo: OutboxRepository`.
   - `async def fetch(self, source: Source) -> list[FetchResult]`:
     a. Extract from `source.config`: `api_token`, `symbols: list[str]` (default `[None]`), `from_date: date`, `to_date: date`, `max_pages: int = 100`.
     b. Create `TokenBucket(capacity=10, tokens=10, refill_rate=10, last_refill=now())`.
     c. For each symbol: paginate with `offset=0`, incrementing by `limit=100` per page until empty page or `max_pages` reached.
     d. For each article in page: compute `url_hash = hashlib.sha256(article['url'].encode()).hexdigest()`; skip if `await fetch_log_repo.exists_by_url_hash(url_hash)`.
     e. Before each HTTP request: `while not bucket.consume(): await asyncio.sleep(bucket.wait_time())`.
     f. Retry loop (max 3, backoff 1s/2s/4s): call `client.get_news()`; on `aiohttp.ClientResponseError` or `asyncio.TimeoutError` retry; on third failure call `await outbox_repo.move_to_dlq(...)` with synthetic event id and log error; continue to next page.
     g. Construct `FetchResult(source_id=source.id, url=article['url'], url_hash=url_hash, raw_bytes=json.dumps(article).encode(), fetched_at=now(), http_status=200, content_type='application/json')`.
   - Return accumulated `list[FetchResult]`.
   - Log at INFO: `source=eodhd fetched=N skipped=M failed=K` using `structlog`.

3. **Write unit tests** at `services/content-ingestion/tests/unit/test_eodhd_adapter.py`:
   - `test_pagination_stops_on_empty_page` — mock client returns 100 items then empty list; assert 2 pages fetched.
   - `test_dedup_skips_known_url_hash` — mock repo returns True for url_hash; assert fetch_result NOT created.
   - `test_retry_on_client_error` — mock client raises on first 2 calls, succeeds on 3rd; assert 1 result returned.
   - `test_dlq_after_three_failures` — mock client raises 3 times; assert `move_to_dlq` called; assert empty result list.
   - `test_rate_limiter_wait_applied` — mock bucket that always returns False on first call; assert `asyncio.sleep` called.

4. **Run:** `cd services/content-ingestion && make test`, `ruff check`, `mypy`.

---

### T-S4-006 — SEC EDGAR Adapter

1. **Create `services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/client.py`**:
   ```python
   import aiohttp
   from datetime import date

   class SecEdgarClient:
       EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
       ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar"

       def __init__(self, user_agent: str):
           if not user_agent:
               raise ConfigurationError("SEC_EDGAR_USER_AGENT must not be empty")
           self._headers = {"User-Agent": user_agent}

       async def search_filings(
           self,
           query: str,
           date_range: tuple[date, date],
           form_types: list[str],
           from_: int,
           size: int,
       ) -> dict:
           params = {
               "q": query,
               "dateRange": "custom",
               "startdt": date_range[0].isoformat(),
               "enddt": date_range[1].isoformat(),
               "forms": ",".join(form_types),
               "from": from_,
               "hits.hits.total.value": size,
           }
           async with aiohttp.ClientSession(headers=self._headers) as session:
               async with session.get(self.EFTS_URL, params=params) as resp:
                   resp.raise_for_status()
                   return await resp.json(content_type=None)

       async def get_filing_document(self, url: str) -> bytes:
           async with aiohttp.ClientSession(headers=self._headers) as session:
               async with session.get(url) as resp:
                   resp.raise_for_status()
                   return await resp.read()
   ```

2. **Create `services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/adapter.py`**:
   - Class `SecEdgarAdapter(SourceAdapter)`.
   - Rate limiter: `self._semaphore = asyncio.Semaphore(8)` — acquire before EVERY HTTP request.
   - Also maintain a request-per-second counter; sleep to stay at ≤ 8 req/sec (sliding window or leaky bucket).
   - `async def fetch(self, source: Source) -> list[FetchResult]`:
     a. Extract from `source.config`: `query`, `form_types` (e.g., `["8-K", "10-K"]`), `date_range`, `max_pages=10`, `page_size=20`.
     b. Paginate EFTS search; for each hit: extract `_source.file_date`, `_source.period_of_report`, document URL from filing index.
     c. For each document: `url_hash = hashlib.sha256((accession_number + filename).encode()).hexdigest()`; skip if already fetched.
     d. Fetch primary HTML document + XBRL file (if present) — each under the semaphore.
     e. 3-retry (backoff 1s/2s/4s) per document fetch; DLQ on exhaustion.
     f. Construct `FetchResult` with `content_type='text/html'` for HTML, `'application/xml'` for XBRL.

3. **Write unit tests** at `services/content-ingestion/tests/unit/test_sec_edgar_adapter.py`:
   - `test_user_agent_required` — construct `SecEdgarClient("")` → assert `ConfigurationError`.
   - `test_pagination_over_efts` — mock search returns 2 pages; assert both fetched.
   - `test_rate_limiter_semaphore_acquired` — assert semaphore acquired for each HTTP call.
   - `test_dedup_skips_known_hash`.
   - `test_dlq_on_three_document_fetch_failures`.

4. **Run:** `cd services/content-ingestion && make test`, `ruff check`, `mypy`.

---

### T-S4-007 — Finnhub Adapter

1. **Create `services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/client.py`**:
   ```python
   import aiohttp
   from datetime import date

   class FinnhubClient:
       BASE_URL = "https://finnhub.io/api/v1"

       def __init__(self, api_key: str):
           self._api_key = api_key

       async def get_company_news(self, symbol: str, from_date: date, to_date: date) -> list[dict]:
           params = {"symbol": symbol, "from": from_date.isoformat(), "to": to_date.isoformat(), "token": self._api_key}
           async with aiohttp.ClientSession() as session:
               async with session.get(f"{self.BASE_URL}/company-news", params=params) as resp:
                   if resp.status == 429:
                       raise RateLimitError("Finnhub 429")
                   resp.raise_for_status()
                   return await resp.json()

       async def get_transcripts_list(self, symbol: str) -> list[dict]:
           params = {"symbol": symbol, "token": self._api_key}
           async with aiohttp.ClientSession() as session:
               async with session.get(f"{self.BASE_URL}/stock/transcripts/list", params=params) as resp:
                   if resp.status == 429:
                       raise RateLimitError("Finnhub 429")
                   resp.raise_for_status()
                   data = await resp.json()
                   return data.get("transcripts", [])
   ```
   - Define `RateLimitError(Exception)` at module level.

2. **Create `services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/adapter.py`**:
   - Class `FinnhubAdapter(SourceAdapter)`.
   - Token bucket: `TokenBucket(capacity=55, tokens=55, refill_rate=55/60, last_refill=now())`.
   - `async def fetch(self, source: Source) -> list[FetchResult]`:
     a. Extract from `source.config`: `symbols: list[str]`, `from_date: date`, `to_date: date`.
     b. For each symbol, fetch news AND transcripts list.
     c. Before each API call: `wait = bucket.wait_time(); if wait > 0: await asyncio.sleep(wait); bucket.consume()`.
     d. On `RateLimitError` (HTTP 429): compute seconds until start of next minute: `sleep_secs = 60 - datetime.now().second`; `await asyncio.sleep(sleep_secs)`; retry.
     e. URL hash for news: `sha256(str(article['id']).encode()).hexdigest()`.
     f. URL hash for transcript: `sha256(str(transcript['id']).encode()).hexdigest()`.
     g. 3-retry on non-429 errors; DLQ on exhaustion.
     h. Construct `FetchResult` with `content_type='application/json'`.

3. **Write unit tests** at `services/content-ingestion/tests/unit/test_finnhub_adapter.py`:
   - `test_token_bucket_sleep_applied_when_insufficient`.
   - `test_429_triggers_minute_boundary_sleep` — mock client raises `RateLimitError`; assert `asyncio.sleep` called with value 0–60.
   - `test_news_and_transcripts_both_fetched_per_symbol`.
   - `test_dedup_skips_known_article_id_hash`.
   - `test_dlq_after_three_non_429_failures`.

4. **Run:** `cd services/content-ingestion && make test`, `ruff check`, `mypy`.

---

### T-S4-008 — NewsAPI Adapter

1. **Create `services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/client.py`**:
   ```python
   import aiohttp
   from datetime import date

   class NewsApiClient:
       BASE_URL = "https://newsapi.org/v2/everything"

       def __init__(self, api_key: str):
           self._api_key = api_key

       async def everything(
           self, query: str, from_date: date, to_date: date, page: int, page_size: int = 100
       ) -> dict:
           # Pass API key in header (not query param — avoids URL logging)
           headers = {"X-Api-Key": self._api_key}
           params = {
               "q": query,
               "from": from_date.isoformat(),
               "to": to_date.isoformat(),
               "page": page,
               "pageSize": page_size,
               "sortBy": "publishedAt",
               "language": "en",
           }
           async with aiohttp.ClientSession(headers=headers) as session:
               async with session.get(self.BASE_URL, params=params) as resp:
                   resp.raise_for_status()
                   return await resp.json()
   ```

2. **Create `services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/adapter.py`**:
   - Class `NewsApiAdapter(SourceAdapter)`.
   - Constructor takes `client: NewsApiClient`, `fetch_log_repo: FetchLogRepository`, `outbox_repo: OutboxRepository`, `valkey_client`, `settings`.
   - Quota key pattern: `newsapi:daily_requests:{YYYY-MM-DD}` where date is UTC today.
   - `async def _check_and_increment_quota(self) -> None`: `count = await valkey_client.incr(quota_key)`; `await valkey_client.expire(quota_key, 86400)` (set only if count == 1 to avoid resetting TTL); if `count > settings.NEWSAPI_DAILY_LIMIT`: raise `QuotaExhaustedError("NewsAPI daily quota exhausted")`.
   - `async def fetch(self, source: Source) -> list[FetchResult]`:
     a. Extract from `source.config`: `query`, `from_date`, `to_date`, `max_pages=10`.
     b. Paginate: page=1 to max_pages; for each page:
        - Call `_check_and_increment_quota()` — if `QuotaExhaustedError`: log warning, return accumulated results immediately.
        - Call `client.everything(query, from_date, to_date, page)`.
        - If `response['totalResults'] == 0` or articles empty: break.
        - Dedup each article via `sha256(article['url'].encode()).hexdigest()`.
        - Construct `FetchResult` with `content_type='application/json'`.
     c. 3-retry on `aiohttp.ClientResponseError` (non-429, non-quota); DLQ on exhaustion.
     d. Do NOT retry on `QuotaExhaustedError` — halt immediately.

3. **Write unit tests** at `services/content-ingestion/tests/unit/test_newsapi_adapter.py`:
   - `test_quota_halt_when_counter_exceeds_limit` — mock Valkey `incr` returns `NEWSAPI_DAILY_LIMIT + 1`; assert `QuotaExhaustedError` raised; assert no more pages fetched.
   - `test_quota_increment_on_each_page`.
   - `test_pagination_stops_on_empty_articles`.
   - `test_api_key_in_header_not_query_param` — assert client sends `X-Api-Key` header (not `apiKey` param).
   - `test_dedup_skips_known_url_hash`.
   - `test_dlq_after_three_non_quota_failures`.

4. **Run:** `cd services/content-ingestion && make test`, `ruff check`, `mypy`.

---

## Constraints

- Do NOT implement any code outside T-S4-005, T-S4-006, T-S4-007, T-S4-008.
- Do NOT implement the scheduler, use-case, admin API, or tests beyond unit tests — those are future waves.
- No `print()` statements — `structlog` only.
- All datetimes UTC only.
- All four adapters MUST implement `SourceAdapter.fetch()` — no alternate signatures.
- `content_type` in `FetchResult` must be set correctly per adapter:
  - EODHD → `application/json`
  - SEC EDGAR HTML → `text/html`; XBRL → `application/xml`
  - Finnhub → `application/json`
  - NewsAPI → `application/json`
- `raw_bytes` in `FetchResult` for JSON-returning APIs must be `json.dumps(article).encode('utf-8')`.
- NEVER import between adapter modules (EODHD must not import from Finnhub, etc.).
- **`common.ids.new_uuid7()` mandatory** — all entity, document, fetch-log, and outbox primary keys must use `common.ids.new_uuid7()`. Never call `common.ids.new_uuid7()` directly in service code; `uuid6` must not appear in service-layer imports.
- **`common.time.utc_now()` mandatory** — all timestamp generation uses `common.time.utc_now()`. Never call `datetime.now(UTC)` or `datetime.utcnow()` directly in service code.
- **`common.types` for cross-service IDs** — use `DocumentId` (from `common.types`) for canonical document primary keys; `UrlHash` for sha256(url) values; `MinIOKey` for MinIO object key strings.

---

## Scope & token budget

**Write paths:**

```
services/content-ingestion/src/content_ingestion/infrastructure/adapters/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/base.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/adapter.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/client.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/adapter.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/client.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/adapter.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/finnhub/client.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/__init__.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/adapter.py
services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/client.py
services/content-ingestion/tests/unit/test_eodhd_adapter.py
services/content-ingestion/tests/unit/test_sec_edgar_adapter.py
services/content-ingestion/tests/unit/test_finnhub_adapter.py
services/content-ingestion/tests/unit/test_newsapi_adapter.py
services/content-ingestion/pyproject.toml
services/content-store/pyproject.toml
```

**Max exploration:** Read at most 8 files outside write paths (Wave 01 domain + repository files, pyproject.toml, base adapter).

**Stop condition:** All 4 adapters implemented with passing tests, zero ruff violations, zero mypy errors.

---

## Required tests

```bash
cd services/content-ingestion && make test
ruff check services/content-ingestion/src/
mypy services/content-ingestion/src/
```

**Pass criteria:** All tests green; `ruff` exits 0; `mypy` exits 0.

---

## Incremental quality gates (mandatory)

Per-task, in order, no deferred fixes:

1. **T-S4-005**: write EODHD adapter → `make test` (EODHD tests) → `ruff check` → `mypy` → all green → DONE.
2. **T-S4-006**: write SEC EDGAR adapter → `make test` → `ruff check` → `mypy` → all green → DONE.
3. **T-S4-007**: write Finnhub adapter → `make test` → `ruff check` → `mypy` → all green → DONE.
4. **T-S4-008**: write NewsAPI adapter → `make test` → `ruff check` → `mypy` → all green → DONE.

**Each gate must pass before starting the next adapter** (if tasks run sequentially) or before declaring the wave complete (if parallel).

---

## Documentation requirements

**Files impacted:**

| File | Update condition | Required update |
|------|-----------------|-----------------|
| `docs/services/content-ingestion.md` | Source adapters section | Add table: adapter name → external API → rate limit strategy → dedup method → DLQ trigger condition |

**Documentation quality criteria:**

1. Accuracy — rate limits match implementation (EODHD: 10 req/sec; SEC: 8 req/sec; Finnhub: 55/min; NewsAPI: daily quota). ✓
2. Diagrams — no multi-component flows in adapter layer. N/A.
3. Realistic code examples — show `source.config` dict structure expected by each adapter. ✓ required.
4. Abstract methods — `SourceAdapter.fetch()` docstring specifies: when called, must do, returns. ✓ required.
5. Common pitfalls — add ≥3 to service doc: (a) SEC EDGAR User-Agent empty → blocked by SEC; (b) Finnhub `id` field is numeric — must `str(id)` before sha256; (c) NewsAPI quota is a hard daily limit — do not retry on `QuotaExhaustedError`; (d) EODHD `offset` pagination — empty page signals end, not `totalResults`.
6. Lib docs — N/A (aiohttp, fastavro already documented in Wave 01 service doc update).
7. Service docs — update `docs/services/content-ingestion.md` adapters section. ✓
8. No orphan documentation — N/A.

---

## Required handoff evidence

1. **Changed files list** (git diff --name-only from wave start).
2. **Test results:** `make test` output — all green.
3. **Ruff:** `ruff check services/content-ingestion/src/` — exit 0.
4. **Mypy:** `mypy services/content-ingestion/src/` — 0 errors.
5. **Docs changed:** confirm `docs/services/content-ingestion.md` adapter table added.
6. **Validation ledger:**

| Task | Tests | Ruff | Mypy | Docs |
|------|-------|------|------|------|
| T-S4-005 | PASS | PASS | PASS | N/A |
| T-S4-006 | PASS | PASS | PASS | N/A |
| T-S4-007 | PASS | PASS | PASS | N/A |
| T-S4-008 | PASS | PASS | PASS | N/A |
| Wave docs | — | — | — | UPDATED |

7. **Commit message proposal:**

```
feat(s4): add source adapters — EODHD, SEC EDGAR, Finnhub, NewsAPI

Implements all four S4 source adapters with paginated fetch, sha256 URL deduplication,
per-adapter rate limiting (token bucket + semaphore + daily Valkey quota), 3-retry
exponential backoff, and DLQ routing on exhaustion.

Co-authored-by: <agent>
```

---

## Definition of done

Wave 02 is complete when ALL of the following are true:

- [ ] `SourceAdapter` abstract base class created and documented.
- [ ] T-S4-005 (EODHD): pagination, dedup, rate limiter, retry, DLQ tested. `ruff`/`mypy` clean.
- [ ] T-S4-006 (SEC EDGAR): EFTS search, HTML+XBRL fetch, 8 req/sec semaphore, dedup, retry, DLQ tested. `ConfigurationError` on empty User-Agent. `ruff`/`mypy` clean.
- [ ] T-S4-007 (Finnhub): news + transcripts, token bucket, minute-boundary 429 backoff, dedup, retry, DLQ tested. `ruff`/`mypy` clean.
- [ ] T-S4-008 (NewsAPI): pagination, Valkey quota counter, halt on exhaustion, dedup, retry, DLQ tested. API key in header. `ruff`/`mypy` clean.
- [ ] `make test` exit 0 on full test suite.
- [ ] `ruff check` exit 0.
- [ ] `mypy` exit 0.
- [ ] `docs/services/content-ingestion.md` adapter table added with rate limits + dedup methods + common pitfalls.
- [ ] Documentation quality gate: all 8 criteria ✓ or N/A justified.
- [ ] Commit message proposal provided.
- [ ] All four adapters populate `FetchResult.published_at` from the source API response (see backfill requirements below).
- [ ] All four adapters propagate `settings.BACKFILL_ENABLED` → `FetchResult.is_backfill`.

---

## Backfill requirements for adapters (added 2026-03-23)

These are **mandatory** additions to every adapter built in this wave.  See PRD §2.4 for the full
backfill architecture rationale.

### 1. Extract `published_at` from every API response

Each adapter must parse the source-reported editorial publication date and populate
`FetchResult.published_at` (nullable).  This field flows downstream to
`relation_evidence.evidence_date` in S7.  **Failure to extract it means all backfilled
documents appear as fresh evidence and corrupt the temporal decay formula.**

| Adapter | Source field | Parse notes |
|---------|-------------|-------------|
| EODHD | `article['date']` | `datetime.fromisoformat(article['date']).replace(tzinfo=timezone.utc)` |
| SEC EDGAR | `_source.period_of_report` or `_source.file_date` | Prefer `period_of_report`; fall back to `file_date`. `datetime.strptime(..., "%Y-%m-%d").replace(tzinfo=timezone.utc)`. |
| Finnhub | `article['datetime']` (Unix timestamp) | `datetime.fromtimestamp(article['datetime'], tz=timezone.utc)` |
| NewsAPI | `article['publishedAt']` (ISO-8601) | `datetime.fromisoformat(article['publishedAt'].replace("Z", "+00:00"))` |

If the field is absent or unparseable: log a warning, set `published_at = None`.
Never raise on missing `published_at` — return the `FetchResult` with `published_at=None`.

### 2. `is_backfill` flag propagation

In each adapter's `fetch()` method, read `self._settings.BACKFILL_ENABLED` (or pass it via
constructor) and set `is_backfill=settings.BACKFILL_ENABLED` on every `FetchResult` produced.

Steady-state polling always passes `is_backfill=False`.  The backfill boot phase passes
`is_backfill=True` (controlled by the `BACKFILL_ENABLED` env var set on the caller).

### 3. Historical date range support

All adapters already accept `from_date` / `to_date` from `source.config`.  During a backfill
run the scheduler will pass `BACKFILL_FROM_DATE` and `BACKFILL_TO_DATE` from settings instead
of the rolling watermark window.  No adapter code change is required here — the scheduler (Wave
03) handles the date selection and passes it into `source.config`.

### 4. Rate limiting during backfill

During backfill, insert `await asyncio.sleep(settings.BACKFILL_BATCH_DELAY_SECONDS)` between
paginated requests.  This replaces the steady-state token bucket during a backfill run to avoid
API rate bans from bulk historical queries.  Steady-state rate limiting (token bucket/semaphore)
remains in place for non-backfill calls.

### 5. Unit test additions per adapter

Add the following tests to each adapter's test file:

- `test_published_at_extracted` — mock API returning an article with known date; assert `FetchResult.published_at` matches expected `datetime`.
- `test_published_at_none_on_missing_date_field` — mock API returning article without date field; assert `FetchResult.published_at is None`; assert no exception raised.
- `test_is_backfill_set_from_settings` — construct adapter with `BACKFILL_ENABLED=True`; assert `FetchResult.is_backfill is True`.
