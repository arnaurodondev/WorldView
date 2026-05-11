# PLAN-0081 — Catalog Tools (Briefs, Compare, Screen, Movers, Calendars)

> **PRD**: derived from `/investigate` 2026-05-07 — issue A-4 (full Bloomberg-grade tool catalog)
> **Status**: completed
> **Created**: 2026-05-07
> **Last revised**: 2026-05-09
> **Owner**: TBD
> **Estimated effort**: ~3 dev-days (2 waves, ~14 tasks)
> **Hard dependencies**:
>   - PLAN-0067 W11-3 **MUST BE COMPLETE** — provides `ToolExecutorFactory`, `ToolExecutor`, `EntityContext`.
>   - PLAN-0066 **COMPLETE** — `user_briefs` table and `BriefArchivePort` Protocol are already in the codebase. `_fetch_brief_seed` (retrieval_orchestrator.py:635) also exists and was NOT deleted by W11-3.
>   - PLAN-0080 **MUST BE COMPLETE** — establishes manifest v2 conventions that this plan extends to v3.

---

## §0 Why this plan exists

For a Bloomberg-competitor LLM, the 8 tools in PLAN-0067 (search/graph/portfolio) plus the 4 in PLAN-0080 (intelligence layer) are still too narrow. Users expect to ask "compare AAPL and MSFT" or "show me the top movers this week" and get a structured answer. This plan adds 6 catalog tools that wrap existing services without new endpoints.

---

## §1 BP-405 Name Verification

The following names were mechanically verified via `grep` against the current codebase on 2026-05-07.
Items tagged **NEW** do not exist yet and will be created by the indicated plan/wave.

| Name | Type | Exists now? | Source |
|------|------|-------------|--------|
| `get_morning_brief` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `compare_entities` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `screen_universe` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `get_market_movers` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `get_economic_calendar` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `get_earnings_calendar` | tool name (manifest + handler) | NO — NEW (this plan Wave A) | — |
| `user_briefs` table | DB table | YES — Alembic `0004_add_user_briefs_and_feedback.py` (shipped by PLAN-0066) | existing |
| `BriefArchivePort` | Protocol port | YES — `application/ports/brief_archive.py:71` (shipped by PLAN-0066) | existing |
| `_fetch_brief_seed` | module-level function | YES — `retrieval_orchestrator.py:635` (shipped by PLAN-0066 Sub-Plan B; **NOT deleted by W11-3**) | existing |
| `S9 GET /v1/market/top-movers` | S9 gateway route | YES — `top_movers` route in `api_gateway/routes/proxy.py:3378` | existing |
| `S9 POST /v1/fundamentals/screen` | S9 gateway route | YES — `screen_instruments` route in `proxy.py:557` — **POST with JSON body** | existing |
| `S3 GET /api/v1/market/period-movers` | S3 market-data route | YES — `market.py:43` | existing |
| `S9 GET /v1/fundamentals/earnings-calendar` | S9 gateway route | YES — `proxy.py:1623` | existing |
| `S9 GET /v1/fundamentals/economic-calendar` | S9 gateway route | YES — `proxy.py:1592` | existing |
| S3 screener endpoint | S3 route | YES (PRD-0017) | existing |
| `S3Port` | Protocol port | YES | `upstream_clients.py:218` |
| `S6Port` | Protocol port | YES | `upstream_clients.py:141` |
| `S7Port` | Protocol port | YES | `upstream_clients.py:154` |
| `S3BriefPort` (or reuse S3Port) | NEW Protocol extension for screener + movers + calendars | NO — NEW (this plan Wave A) | — |

**Note on `_fetch_brief_seed`**: `_fetch_brief_seed` exists at `retrieval_orchestrator.py:635` and was **not** deleted by PLAN-0067 W11-3. W11-3 deleted `IntentClassifier`, `RetrievalPlanBuilder`, and `ParallelRetrievalOrchestrator` only. The two mechanisms serve different purposes: `_fetch_brief_seed` is a **pipeline-internal** function that auto-injects brief citations as high-trust `RetrievedItem` objects on every request; `get_morning_brief` (this plan) is an **LLM-callable tool** that the model explicitly invokes when the user asks for their brief. They coexist — `get_morning_brief` is an additive surface, not a replacement.

---

## 2. Tools

| Tool | Purpose | Backed by |
|---|---|---|
| `get_morning_brief` (NEW — Wave A) | LLM-callable tool: explicitly surfaces today's brief for a user when they ask for it. Complements (does not replace) the pipeline-internal `_fetch_brief_seed` which auto-injects brief context on every request. | `user_briefs` table (existing) via `BriefArchivePort` Protocol (existing) |
| `compare_entities` (NEW — Wave A) | Side-by-side fundamentals + price + sentiment + KG-overlap for 2–4 entities; parameter: `entity_tickers: list[str]` (2–4 elements) | composes S3Port (fundamentals) + S6Port (chunk search) + S7Port (graph) — ALL via Protocol ports |
| `screen_universe` (NEW — Wave A) | Quantitative screener (filters: market_cap, pe_ratio, sector, region, etc.) | S9 `POST /v1/fundamentals/screen` (existing, **POST with JSON body**) via `S3BriefPort.screen_instruments(filters: dict)` |
| `get_market_movers` (NEW — Wave A) | Top gainers / losers / most-active over a timeframe | S9 `GET /v1/market/top-movers` (existing, `proxy.py:3378`) via `S3BriefPort.get_top_movers(...)` |
| `get_economic_calendar` (NEW — Wave A) | Upcoming/past macro events (CPI, FOMC, GDP) for region | S9 `GET /v1/fundamentals/economic-calendar` (existing, `proxy.py:1592`) via `S3BriefPort.get_economic_calendar(...)` |
| `get_earnings_calendar` (NEW — Wave A) | Earnings release dates ± actuals/estimates for a date range | S9 `GET /v1/fundamentals/earnings-calendar` (existing, `proxy.py:1623`) via `S3BriefPort.get_earnings_calendar(...)` |

## 3. Scope

| Wave | Title | Layer | Status |
|------|-------|-------|--------|
| A | Manifest entries (6 tools, `since: v3`); `S3BriefPort` Protocol port extension (NEW — Wave A) for screener/movers/calendars (POST screener + 3 GETs); 6 handlers; add `s3_brief: S3BriefPort \| None = None` to `ToolExecutorFactory.__init__()` and DI wiring in `app.py`; add 6 tool names to `build_default_registry()` `_catalog_tool_names` list; tests; 10 golden-eval queries | libs + S8 | ✅ **DONE — 2026-05-09 · 31 tests pass · ruff + mypy clean** |
| B | Cross-tool composition test: query "compare AAPL and MSFT and show me the top movers" forces multi-tool LLM behaviour | tests | ✅ **DONE — 2026-05-09 · 5 tests pass · ruff + mypy clean** |

## 4. Hard Constraints

- **ABC/Protocol port requirement (R25)**: ALL 6 tool handlers MUST go through Protocol ports defined in `application/ports/upstream_clients.py`. No handler may import from `infrastructure/clients/` directly. Specifically:
  - `get_morning_brief` → `BriefArchivePort` Protocol (existing — `application/ports/brief_archive.py:71`)
  - `compare_entities` → `S3Port` + `S6Port` + `S7Port` (all existing)
  - `screen_universe`, `get_market_movers`, `get_economic_calendar`, `get_earnings_calendar` → `S3BriefPort` Protocol (NEW — this plan Wave A). Method signatures:
    - `screen_instruments(filters: dict) -> dict` — issues `POST /v1/fundamentals/screen` with JSON body (**POST**, not GET)
    - `get_top_movers(mover_type: str, limit: int, period: str) -> dict` — issues `GET /v1/market/top-movers`
    - `get_economic_calendar(from_date: str | None, to_date: str | None, region: str | None) -> list[dict]` — issues `GET /v1/fundamentals/economic-calendar`
    - `get_earnings_calendar(from_date: str | None, to_date: str | None) -> list[dict]` — issues `GET /v1/fundamentals/earnings-calendar`
- **ReadOnlyUoW for reads (R27)**: all 6 tools are read-only. Their handlers MUST NOT acquire `UnitOfWork`. The `get_morning_brief` handler reads `user_briefs` via `BriefArchivePort` which is backed by `ReadOnlyUnitOfWork` (R27). This must be explicitly specified in the Wave A task.
- **`compare_entities` parameter schema**: `entity_tickers: list[str]` (required, 2–4 elements, e.g. `["AAPL", "MSFT"]`). Consistent with `search_documents` which also uses `entity_tickers` from the LLM. This is a wire contract once published to `capability_manifest.yaml` — must not be renamed later without a deprecation entry.
- **EntityContext respected for `compare_entities`**: when scope is set to one entity, the second arg (target entity) is the user-provided one; the scoped entity is auto-injected as the first arg.
- **`get_morning_brief` is additive**: `_fetch_brief_seed` (retrieval_orchestrator.py:635) still exists and handles implicit brief injection on every request. The `get_morning_brief` tool adds an explicit LLM surface so the model can retrieve and present the brief on demand. No I-4 "migration" is needed — both coexist.
- **R29 compliance**: `capability_manifest.yaml` updated atomically with handler registration. Each entry needs `name`, `description`, `parameters`, `since: "v3"`, and at least 2 `example_queries`. `tests/architecture/test_tool_manifest_sync.py` (created in Wave A) is the CI gate: it asserts every tool name in `capability_manifest.yaml` appears in `build_default_registry()`'s `_new_tool_names` list. Without this test file, the guard is phantom.
- **`ToolExecutorFactory` DI wiring**: Wave A adds `S3BriefPort` as a new Protocol port. `ToolExecutorFactory.__init__()` must gain a new parameter `s3_brief: S3BriefPort | None = None`. The DI container in `services/rag-chat/src/rag_chat/api/dependencies.py` must construct and inject the concrete `S3BriefClient` adapter.
- **`build_default_registry()` update**: `tool_executor.py:1172` must include all 6 new tool names in the `_new_tool_names` list (same pattern as the existing 8 names). Omitting them causes `unknown_tool_name` warnings for every tool call at runtime.
- **Manifest version**: all entries `since: "v3"`. Top-level `version: "v3"` in the same Wave A commit.
- **UUIDs**: `common.ids.new_uuid7()` (R10). No `uuid.uuid4()`.
- **Timestamps**: `common.time.utc_now()` (R11). No naive datetimes.
- **structlog only**: all handlers use `structlog.get_logger()`, never stdlib `logging`.
- **Forward-compatible schemas (R11 / R5)**: tool parameter schemas added with defaults; never remove or rename existing parameters once published (manifest entries are treated as wire contracts).

## 5. Out of scope

- Action-tools (read-only here; alerts read/create are PLAN-0082).
- Options flow, prediction markets, social sentiment — defer until upstream services mature.

---

*Stub generated 2026-05-07. BP-405 audit 2026-05-07.*
