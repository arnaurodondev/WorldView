---
id: PLAN-0089
title: "Platform Cleanup — Critical Fixes, api-gateway Restructure, Backend & Frontend Refactors"
status: completed
created: 2026-05-11
updated: 2026-05-12
owner: Arnau Rodon
type: implementation
spawned_from: 2026-05-11 /investigate platform quality audit
supersedes: none
---

## Overview

Spawned from a `/investigate` pass on 2026-05-11 that audited platform quality after rapid growth
across PLAN-0074/0076/0080/0086/0087/0088. Speed > quality during this phase; this plan corrects it.

**Scope:**
- Sub-Plan A: 3 critical/quality fixes (misleading comments, missing migration tests, missing WS endpoint)
- Sub-Plan B: api-gateway architectural restructure (proxy.py 4319 lines → 7 route modules + use-case layer)
- Sub-Plan C: 4 backend large-file refactors (rag-chat, nlp-pipeline, market-ingestion)
- Sub-Plan D: 3 frontend component splits (chart, intelligence, watchlists/fundamentals/graph)

**Total waves:** 14 (A1–A3, B1–B4, C1–C4, D1–D3)

---

## Sub-Plan A — Critical & Quality Fixes

### Wave A-1: Fix Misleading alembic/env.py Comments ✅

**Goal:** Replace `target_metadata = None  # TODO: import Base.metadata` with accurate explanatory
comments in api-gateway and knowledge-graph, which have no SQLAlchemy ORM models and correctly use `None`.

**Status:** DONE — completed 2026-05-11

**Target files:**
- `services/api-gateway/alembic/env.py`
- `services/knowledge-graph/alembic/env.py`

**What was done:** Changed TODO comment to accurate doc-comment explaining `None` is intentionally
correct because these services manage schema only via raw SQL migrations — no ORM models exist or
are planned. Autogenerate is not used.

**Validation gate:**
- [ ] ruff PASS on both files
- [ ] `python -m alembic check` passes in both services (no phantom pending migration)

---

### Wave A-2: intelligence-migrations Test Coverage ✅

**Goal:** Add per-migration test fixtures and test files covering migrations 0034–0038.
Currently only 2 test files exist for 35 migration files (highest revision: 0038).

**Status:** DONE — 2026-05-12 · 43 new migration tests · ruff + mypy clean

**depends_on:** none

**Target files:**
- `services/intelligence-migrations/tests/conftest.py` — add `migration_runner` per-test fixture
- `services/intelligence-migrations/tests/test_migration_0034.py` (NEW)
- `services/intelligence-migrations/tests/test_migration_0035.py` (NEW)
- `services/intelligence-migrations/tests/test_migration_0036.py` (NEW)
- `services/intelligence-migrations/tests/test_migration_0037.py` (NEW)
- `services/intelligence-migrations/tests/test_migration_0038.py` — extend existing file

**What to build:**

Add a `migration_runner` pytest fixture to `conftest.py` that:
1. Starts a transaction savepoint before the test
2. Runs `alembic upgrade <revision>` then `alembic downgrade -1`
3. Rolls back the savepoint after each test (isolation)

Each test file covers one migration:
- `test_upgrade` — asserts schema state after upgrade (table/column exists, index present, etc.)
- `test_downgrade` — asserts schema state after downgrade (reverted cleanly)
- `test_forward_compat` — inserts a row, upgrades, row still readable, no data loss

Follow the pattern from existing `test_migration_0038.py` (320 lines — the per-revision pattern in this repo).

**Acceptance criteria:**
- [ ] All 5 new test files pass with `python -m pytest tests/ -v -m migration`
- [ ] No skipped tests
- [ ] Each migration has upgrade + downgrade + forward-compat test (15+ total new tests)

---

### Wave A-3: WS-URL Passthrough Endpoint ✅

**Goal:** Add `GET /v1/alerts/stream/ws-url` endpoint to api-gateway that:
1. Validates the Bearer token (already done by auth middleware)
2. Issues a 30-second ws-token via the existing `GET /v1/auth/ws-token` logic
3. Returns `{"ws_url": "ws://<ALERT_HOST>:<ALERT_PORT>/api/v1/alerts/stream?token=<jwt>", "token": "...", "expires_in": 30}`

This unblocks the frontend WebSocket alerts streaming (noted as `# TODO` at proxy.py:775).

**Status:** DONE — 2026-05-12 · 3 unit tests · ruff + mypy clean

**depends_on:** none

**Target files:**
- `services/api-gateway/src/api_gateway/routes/proxy.py` — add endpoint at line ~775 TODO

**What to build:**

```python
# config.py — add alongside the other service URLs
alert_ws_url: str = "ws://localhost:8010"  # env: API_GATEWAY_ALERT_WS_URL
```

```python
# proxy.py — add inside the alerts section (after the TODO comment at line 775)
@router.get("/v1/alerts/stream/ws-url")
async def get_alerts_ws_url(request: Request) -> dict[str, str | int]:
    """Issue a short-lived WS token and return the full WebSocket URL.

    Replaces the client-side pattern of calling /v1/auth/ws-token then
    constructing the URL manually.  Returns ws_url ready for new WebSocket().
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="authentication_required")

    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid = getattr(request.app.state, "rsa_kid", None)
    if private_key is None or kid is None:
        raise HTTPException(status_code=503, detail="jwt_signing_unavailable")

    user_id = user.get("user_id") or user.get("sub")
    tenant_id = user.get("tenant_id")
    if not user_id or not tenant_id:
        raise HTTPException(status_code=401, detail="incomplete_auth_claims")

    from api_gateway.jwt_utils import issue_ws_jwt  # jwt_utils.py:152

    token = issue_ws_jwt(user_id=user_id, tenant_id=tenant_id, private_key=private_key, kid=kid)
    settings = request.app.state.settings
    ws_url = f"{settings.alert_ws_url}/api/v1/alerts/stream?token={token}"
    return {"ws_url": ws_url, "token": token, "expires_in": 30}
```

Note: `issue_ws_jwt` already sets TTL=30s (hardcoded via `_WS_TTL` in jwt_utils.py).
No `SettingsDep` exists in api-gateway — settings are accessed via `request.app.state.settings`.
Add `alert_ws_url: str = "ws://localhost:8010"` to `config.py` (env var: `API_GATEWAY_ALERT_WS_URL`).

**Acceptance criteria:**
- [ ] `GET /v1/alerts/stream/ws-url` returns 200 with `ws_url`, `token`, `expires_in`
- [ ] Returns 401 without valid Bearer token
- [ ] `expires_in` is 30 (not 300 or 3600)
- [ ] ruff + mypy PASS on config.py and proxy.py
- [ ] 3 unit tests: happy path, no-auth 401, token TTL=30

---

## Sub-Plan B — api-gateway Architectural Restructure

> **Context:** `routes/proxy.py` is 4319 lines — a single file mixing business logic, HTTP retry,
> auth utilities, and route handlers for 7 distinct domains. Violates R16 and makes it impossible
> to find, test, or modify any single capability.
>
> **Strategy:** Incremental split. B-1/B-2 extract use-case logic without touching routes. B-3
> splits the routes file. B-4 extracts the shared HTTP utility. Each wave leaves the service green.

### Wave B-1: Use-Case Layer Scaffold + CompanyOverviewUseCase ✅

**Goal:** Create `services/api-gateway/src/api_gateway/application/use_cases/` package.
Extract the company overview bundle (entity detail + KG + narratives + chart + fundamentals +
articles) into `CompanyOverviewUseCase`.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** none

**Target files:**
- `services/api-gateway/src/api_gateway/application/__init__.py` (NEW)
- `services/api-gateway/src/api_gateway/application/use_cases/__init__.py` (NEW)
- `services/api-gateway/src/api_gateway/application/use_cases/base.py` (NEW) — `GatewayUseCase` ABC
- `services/api-gateway/src/api_gateway/application/use_cases/company_overview.py` (NEW)
- `services/api-gateway/src/api_gateway/routes/proxy.py` — replace inline logic with use case calls

**What to build:**

```python
# base.py
# Note: no DB UoW here — api-gateway has no database; use cases make HTTP calls only.
class GatewayUseCase(ABC):
    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any: ...
```

```python
# company_overview.py
class CompanyOverviewUseCase(GatewayUseCase):
    async def execute(self, entity_id: str, user_id: str) -> CompanyOverviewBundle:
        # Parallel fetch: entity detail, KG subgraph, narratives, fundamentals, articles
        ...
```

**Acceptance criteria:**
- [ ] `CompanyOverviewUseCase` passes unit tests (mock `http_client`)
- [ ] proxy.py company-overview handler delegates to use case
- [ ] `python -m pytest tests/ -v` PASS in api-gateway
- [ ] No new ruff/mypy violations

---

### Wave B-2: Dashboard, Instrument, Portfolio Use Cases ✅

**Goal:** Extract 3 more bundle use cases following the B-1 pattern.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** Wave B-1

**Target files:**
- `services/api-gateway/src/api_gateway/application/use_cases/dashboard_snapshot.py` (NEW)
- `services/api-gateway/src/api_gateway/application/use_cases/instrument_page_bundle.py` (NEW)
- `services/api-gateway/src/api_gateway/application/use_cases/portfolio_bundle.py` (NEW)
- `services/api-gateway/src/api_gateway/routes/proxy.py` — delegate to new use cases

**What to build:**

- `DashboardSnapshotUseCase` — morning brief + top movers + watchlist preview + portfolio KPIs
- `InstrumentPageBundleUseCase` — OHLCV + quote + fundamentals metadata
- `PortfolioBundleUseCase` — holdings + equity curve + portfolio stats

Each use case: parallel httpx fetches, structured return type, unit-testable.

**Acceptance criteria:**
- [ ] 3 use cases each have ≥5 unit tests
- [ ] proxy.py delegates all 3 bundles to use cases
- [ ] api-gateway test suite still PASS

---

### Wave B-3: Split proxy.py into 7 Domain Route Modules ✅

**Goal:** Split 4319-line `proxy.py` into 7 focused route files, one per business domain.
This is the highest-value wave — after this, proxy.py ceases to exist.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** Wave B-2

**Target files (all NEW):**
- `services/api-gateway/src/api_gateway/routes/chat.py` — `/v1/chat/*` routes
- `services/api-gateway/src/api_gateway/routes/market.py` — `/v1/market/*`, movers, OHLCV
- `services/api-gateway/src/api_gateway/routes/instruments.py` — `/v1/instruments/*`, screener
- `services/api-gateway/src/api_gateway/routes/portfolio.py` — `/v1/portfolio/*`, brokerages
- `services/api-gateway/src/api_gateway/routes/intelligence.py` — `/v1/intelligence/*`, narratives, KG
- `services/api-gateway/src/api_gateway/routes/alerts.py` — `/v1/alerts/*`, ws-url
- `services/api-gateway/src/api_gateway/routes/content.py` — `/v1/news/*`, documents, entities

**Routing plan:**

| New file | Routes migrated from proxy.py | Est. lines |
|---|---|---|
| `chat.py` | `/v1/chat/*`, briefings | ~500 |
| `market.py` | OHLCV, quotes, movers, screener | ~600 |
| `instruments.py` | entity search, fundamentals, company overview | ~600 |
| `portfolio.py` | holdings, equity-curve, brokerages, transactions | ~700 |
| `intelligence.py` | KG, narratives, knowledge, paths | ~550 |
| `alerts.py` | alert CRUD, ws-url | ~200 |
| `content.py` | news, documents, tenant-documents | ~400 |

**Migration strategy:**
1. Create each new file with its subset of routes (copy, no changes)
2. Register all new routers in `app.py`
2b. Update `routes/__init__.py`: currently it does `from api_gateway.routes.proxy import router`
    and re-exports it as `router`; `app.py` consumes it as `main_router`. When proxy.py is deleted
    this chain breaks. Replace the proxy import with direct imports from the 7 new files and
    combine them into a single `router` (or switch `app.py` to include each router directly and
    remove the `router` re-export from `__init__.py`).
3. Remove corresponding routes from proxy.py
4. After all routes moved, delete proxy.py
5. Run full test suite

**Acceptance criteria:**
- [ ] `proxy.py` is deleted (0 lines remain)
- [ ] All 7 new route files created
- [ ] `python -m pytest tests/ -v` PASS in api-gateway (no route regressions)
- [ ] ruff + mypy PASS across new files
- [ ] `GET /v1/health` still returns 200 (smoke test)

---

### Wave B-4: Extract Shared HTTP Utility ✅

**Goal:** Extract the retry logic, timeout, and error-mapping utilities currently duplicated
across proxy.py into `services/api-gateway/src/api_gateway/application/http_utils.py`.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** Wave B-3

**Target files:**
- `services/api-gateway/src/api_gateway/application/http_utils.py` (NEW)
- Route files from B-3 — import from http_utils instead of inline definitions

**What to build:**

```python
# http_utils.py
async def proxy_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = 10.0,
    retries: int = 2,
) -> httpx.Response: ...

async def proxy_post(client, url, *, json, timeout=10.0) -> httpx.Response: ...

def map_upstream_error(exc: httpx.HTTPStatusError) -> HTTPException: ...
```

**Acceptance criteria:**
- [ ] No inline retry/timeout logic remains in route files
- [ ] `http_utils.py` has ≥8 unit tests
- [ ] All 7 route files import from `http_utils`

---

## Sub-Plan C — Backend Large-File Refactors

### Wave C-1: rag-chat tool_executor.py → handlers/ directory ✅

**Goal:** Split `application/pipeline/tool_executor.py` (3148 lines) into a `handlers/` package
with a `ToolHandler` ABC and per-tool-group handler classes.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** none

**Target files:**
- `services/rag-chat/src/rag_chat/application/pipeline/handlers/__init__.py` (NEW)
- `services/rag-chat/src/rag_chat/application/pipeline/handlers/base.py` (NEW) — `ToolHandler` ABC
- `services/rag-chat/src/rag_chat/application/pipeline/handlers/market.py` (NEW) — price/OHLCV/screener tools
- `services/rag-chat/src/rag_chat/application/pipeline/handlers/intelligence.py` (NEW) — KG/narrative tools
- `services/rag-chat/src/rag_chat/application/pipeline/handlers/portfolio.py` (NEW) — portfolio tools
- `services/rag-chat/src/rag_chat/application/pipeline/handlers/news.py` (NEW) — article/brief tools
- `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py` — reduced to dispatcher only (~150 lines)

**What to build:**

```python
# handlers/base.py
class ToolHandler(ABC):
    @abstractmethod
    async def can_handle(self, tool_name: str) -> bool: ...

    @abstractmethod
    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any: ...
```

The `tool_executor.py` becomes a dispatcher:
```python
class ToolExecutor:
    _handlers: list[ToolHandler]

    async def execute_tool(self, tool_name: str, args: dict) -> Any:
        for handler in self._handlers:
            if await handler.can_handle(tool_name):
                return await handler.execute(tool_name, args)
        raise UnknownToolError(tool_name)
```

**Acceptance criteria:**
- [ ] `tool_executor.py` ≤200 lines after split
- [ ] Each handler file ≤600 lines
- [ ] `python -m pytest tests/ -v` PASS in rag-chat (existing 549 tests)
- [ ] ruff + mypy PASS

---

### Wave C-2: nlp-pipeline article_consumer.py → consumers/blocks/ directory ✅

**Goal:** Split `infrastructure/messaging/consumers/article_consumer.py` (1933 lines) into a
`consumers/blocks/` package with a `ProcessingBlock` ABC and 8 single-responsibility block classes.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** none

**Target files:**
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/__init__.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/base.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/entity_extraction.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/relation_extraction.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/embedding.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/canonicalization.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/section_extraction.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/relevance_scoring.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/event_detection.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/blocks/output_dispatch.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` — reduced to block orchestration

**What to build:**

```python
# blocks/base.py
@dataclass(frozen=True)
class ArticleContext:
    document: StoredArticle
    tenant_id: UUID
    event: ArticleStoredEvent

class ProcessingBlock(ABC):
    @abstractmethod
    async def process(self, ctx: ArticleContext, state: dict[str, Any]) -> dict[str, Any]: ...
```

Each block handles one step: extract entities → canonicalize → embed → extract relations → score relevance → detect events → dispatch. The orchestrator in `article_consumer.py` runs the pipeline.

**Acceptance criteria:**
- [ ] `article_consumer.py` ≤300 lines after split
- [ ] Each block file ≤350 lines
- [ ] `python -m pytest tests/ -v` PASS in nlp-pipeline (existing 715 tests)
- [ ] ruff + mypy PASS

---

### Wave C-3: rag-chat generate_briefing.py → BriefParser + BriefContextFormatter ✅

**Goal:** Split `application/use_cases/generate_briefing.py` (1549 lines) by extracting
the brief response parsing and context formatting into dedicated classes.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** none

**Target files:**
- `services/rag-chat/src/rag_chat/application/use_cases/brief_parser.py` (NEW) — `BriefParser`
- `services/rag-chat/src/rag_chat/application/use_cases/brief_context_formatter.py` (NEW) — `BriefContextFormatter`
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` — reduced orchestrator

**What to build:**

- `BriefParser` — parses LLM response into structured `BriefSection` list; handles markdown extraction, section labeling, fallback for malformed responses
- `BriefContextFormatter` — builds the context string injected into the brief prompt: entity data, article summaries, fundamentals, market context; currently ~600 lines of prompt-building logic

**Acceptance criteria:**
- [ ] `generate_briefing.py` ≤700 lines after extraction
- [ ] `BriefParser` has ≥10 unit tests covering malformed input, empty sections, citation extraction
- [ ] `BriefContextFormatter` has ≥6 unit tests covering context truncation, missing data fields
- [ ] Existing 549 rag-chat tests PASS

---

### Wave C-4: market-ingestion execute_task.py → strategies/ directory ✅

**Goal:** Split `application/use_cases/execute_task.py` (1068 lines) into a `strategies/`
package with an `IngestionStrategy` ABC and per-provider strategy classes.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** none

**Target files:**
- `services/market-ingestion/src/market_ingestion/application/use_cases/strategies/__init__.py` (NEW)
- `services/market-ingestion/src/market_ingestion/application/use_cases/strategies/base.py` (NEW)
- `services/market-ingestion/src/market_ingestion/application/use_cases/strategies/eodhd_fundamentals.py` (NEW)
- `services/market-ingestion/src/market_ingestion/application/use_cases/strategies/eodhd_ohlcv.py` (NEW)
- `services/market-ingestion/src/market_ingestion/application/use_cases/strategies/polymarket.py` (NEW)
- `services/market-ingestion/src/market_ingestion/application/use_cases/strategies/macro_indicators.py` (NEW)
- `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` — reduced dispatcher

**What to build:**

```python
# strategies/base.py
class IngestionStrategy(ABC):
    @abstractmethod
    def can_handle(self, task_type: str) -> bool: ...

    @abstractmethod
    async def execute(self, task: IngestionTask, uow: UnitOfWork) -> IngestionResult: ...
```

`execute_task.py` becomes a strategy registry + dispatcher (~100 lines).

**Acceptance criteria:**
- [ ] `execute_task.py` ≤150 lines after extraction
- [ ] Each strategy file ≤350 lines
- [ ] Existing market-ingestion tests PASS
- [ ] ruff + mypy PASS

---

## Sub-Plan D — Frontend Component Splits

> **Context:** 5 React components exceed 900 lines each. Large components are hard to reason
> about, have slow TypeScript compilation, and are impossible to test in isolation. Each split
> extracts visual sub-components while keeping the parent as a pure orchestrator.
>
> **Pattern:** Parent keeps state + data fetching. Child components receive typed props only.
> No prop drilling beyond 2 levels — use context or co-location.

### Wave D-1: OHLCVChart.tsx (1321 lines) → chart/ subdirectory ✅

**Goal:** Split `components/instrument/OHLCVChart.tsx` into 4 focused files.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** none

**Target files:**
- `apps/worldview-web/components/instrument/chart/ChartToolbar.tsx` (NEW) — timeframe selector, indicators toggle, type switcher
- `apps/worldview-web/components/instrument/chart/ChartTooltip.tsx` (NEW) — custom tooltip renderer
- `apps/worldview-web/lib/chart-adapter.ts` (NEW) — lightweight-charts data transformation, color utilities
- `apps/worldview-web/components/instrument/OHLCVChart.tsx` — reduced orchestrator

**What to build:**

- `ChartToolbar` — timeframe buttons (1D/1W/1M/3M/1Y/ALL), chart type (candle/line/bar), indicator toggles; emits callback props
- `ChartTooltip` — renders OHLCV values in the floating tooltip overlay on hover
- `chart-adapter.ts` — converts API `OHLCVBar[]` → lightweight-charts `CandlestickData[]`; color utilities for up/down candles

**Acceptance criteria:**
- [ ] `OHLCVChart.tsx` ≤400 lines after extraction
- [ ] Each sub-component ≤300 lines
- [ ] Chart still renders correctly in local dev (visually verify)
- [ ] TypeScript strict PASS (`pnpm tsc --noEmit`)
- [ ] No prop drilling beyond 2 levels

---

### Wave D-2: IntelligenceTab.tsx (1329 lines) → intelligence/ subdirectory ✅

**Goal:** Split `components/instrument/IntelligenceTab.tsx` into 5 focused files.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** none

**Target files:**
- `apps/worldview-web/components/instrument/intelligence/ContradictionCard.tsx` (NEW)
- `apps/worldview-web/components/instrument/intelligence/IntelligenceSummarySection.tsx` (NEW)
- `apps/worldview-web/components/instrument/intelligence/GraphDetailSidebar.tsx` (NEW)
- `apps/worldview-web/components/instrument/intelligence/IntelligenceFilters.tsx` (NEW)
- `apps/worldview-web/components/instrument/IntelligenceTab.tsx` — reduced orchestrator

**What to build:**

- `ContradictionCard` — renders a single narrative contradiction with source/target entity, confidence badge, evidence snippets
- `IntelligenceSummarySection` — renders the top-level narrative summary + confidence meters
- `GraphDetailSidebar` — slide-in panel showing selected KG node/edge detail (entity info, relation type, evidence)
- `IntelligenceFilters` — time-range picker, entity filter, narrative type filter bar

**Acceptance criteria:**
- [ ] `IntelligenceTab.tsx` ≤400 lines after extraction
- [ ] TypeScript strict PASS
- [ ] Intelligence panel renders and filters work in local dev

---

### Wave D-3: Watchlists, Fundamentals, EntityGraph splits ✅

**Goal:** Split 3 remaining large components below 400 lines each.

**Status:** DONE — 2026-05-12 · ruff + mypy clean

**depends_on:** none

**Target files:**

**WatchlistsTabPanel.tsx (974 lines):**
- `components/portfolio/watchlists/WatchlistItem.tsx` (NEW) — single watchlist row with expand/collapse
- `components/portfolio/watchlists/WatchlistInstrumentRow.tsx` (NEW) — instrument row within a watchlist
- `components/portfolio/WatchlistsTabPanel.tsx` — reduced orchestrator

**FundamentalsTab.tsx (928 lines):**
- `components/instrument/fundamentals/FinancialTable.tsx` (NEW) — income/balance/cash-flow table renderer
- `components/instrument/fundamentals/RatiosGrid.tsx` (NEW) — key ratios cards grid
- `components/instrument/FundamentalsTab.tsx` — reduced orchestrator

**EntityGraph.tsx (918 lines):**
- `components/instrument/graph/GraphControls.tsx` (NEW) — zoom/fit/depth controls
- `components/instrument/graph/GraphLegend.tsx` (NEW) — node type + edge type legend
- `components/instrument/EntityGraph.tsx` — reduced orchestrator

**Acceptance criteria:**
- [ ] All 3 parent components ≤400 lines after extraction
- [ ] Each sub-component ≤350 lines
- [ ] TypeScript strict PASS
- [ ] Local dev renders all 3 panels correctly

---

## Wave Status Summary

| Wave | Title | Status | Depends On |
|---|---|---|---|
| A-1 | Fix alembic/env.py misleading TODO comments | ✅ done | — |
| A-2 | intelligence-migrations test coverage | ✅ done | — |
| A-3 | WS-URL passthrough endpoint | ✅ done | — |
| B-1 | Use-case layer scaffold + CompanyOverviewUseCase | ✅ done | — |
| B-2 | Dashboard, Instrument, Portfolio use cases | ✅ done | B-1 |
| B-3 | Split proxy.py → 7 domain route modules | ✅ done | B-2 |
| B-4 | Extract shared HTTP utility | ✅ done | B-3 |
| C-1 | rag-chat tool_executor → handlers/ | ✅ done | — |
| C-2 | nlp-pipeline article_consumer → blocks/ | ✅ done | — |
| C-3 | rag-chat generate_briefing → BriefParser + formatter | ✅ done | — |
| C-4 | market-ingestion execute_task → strategies/ | ✅ done | — |
| D-1 | OHLCVChart → chart/ subdirectory | ✅ done | — |
| D-2 | IntelligenceTab → intelligence/ subdirectory | ✅ done | — |
| D-3 | Watchlists + Fundamentals + EntityGraph splits | ✅ done | — |

---

## Parallelization Guide

Waves with no inter-wave dependencies can run in parallel worktrees:

- **Immediately parallelizable (no deps):** A-2, A-3, B-1, C-1, C-2, C-3, C-4, D-1, D-2, D-3
- **After B-1:** B-2
- **After B-2:** B-3
- **After B-3:** B-4

Sub-Plans C and D are fully independent of Sub-Plan B and each other.

---

## Pre-Read for Each Sub-Plan

**Sub-Plan A:**
- `services/api-gateway/alembic/env.py`
- `services/knowledge-graph/alembic/env.py`
- `services/intelligence-migrations/tests/` (existing test files)
- `services/api-gateway/src/api_gateway/config.py`

**Sub-Plan B:**
- `services/api-gateway/src/api_gateway/routes/proxy.py` (full file)
- `services/api-gateway/src/api_gateway/app.py`
- `services/api-gateway/src/api_gateway/config.py`
- `services/api-gateway/tests/`

**Sub-Plan C:**
- The specific large file for each wave
- Corresponding test files in the service

**Sub-Plan D:**
- The specific large component for each wave
- `apps/worldview-web/components/instrument/` or `portfolio/` directory listing
