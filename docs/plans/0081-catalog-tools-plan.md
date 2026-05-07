# PLAN-0081 — Catalog Tools (Briefs, Compare, Screen, Movers, Calendars)

> **PRD**: derived from `/investigate` 2026-05-07 — issue A-4 (full Bloomberg-grade tool catalog)
> **Status**: stub
> **Created**: 2026-05-07
> **Last revised**: 2026-05-07 (BP-405 name-verification + architecture compliance audit)
> **Owner**: TBD
> **Estimated effort**: ~3 dev-days (2 waves, ~14 tasks)
> **Hard dependencies**:
>   - PLAN-0067 W11-3 **MUST BE COMPLETE** — provides `ToolExecutorFactory`, `ToolExecutor`, `EntityContext`.
>   - PLAN-0066 Sub-Plan A **MUST BE COMPLETE** — provides `user_briefs` table (NEW in PLAN-0066 Sub-Plan A) and `BriefArchivePort` Protocol (NEW in PLAN-0066 Sub-Plan A) needed for `get_morning_brief`. Without Sub-Plan A, there is no brief archive to query.
>   - PLAN-0066 Sub-Plan B **MUST BE COMPLETE** — creates `RetrievalOrchestrator._fetch_brief_seed` (NEW in PLAN-0066 Sub-Plan B). PLAN-0067 W11-3 then **deletes** `_fetch_brief_seed` when `RetrievalOrchestrator` is removed. This plan's `get_morning_brief` tool is the replacement.
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
| `user_briefs` table | DB table | NO — NEW (PLAN-0066 Sub-Plan A) | — |
| `BriefArchivePort` | Protocol port | NO — NEW (PLAN-0066 Sub-Plan A) | — |
| `RetrievalOrchestrator._fetch_brief_seed` | method | NO — does not exist in current codebase; it is a FUTURE item in PLAN-0066 Sub-Plan B, then deleted by PLAN-0067 W11-3 | — |
| `S9 GET /v1/market/movers` | S9 gateway route | YES — `top_movers` route in `api_gateway/routes/proxy.py:2836` | existing |
| `S3 GET /api/v1/market/period-movers` | S3 market-data route | YES — `market.py:43` | existing |
| `S9 GET /v1/fundamentals/earnings-calendar` | S9 gateway route | YES — `proxy.py:1492` | existing |
| `S9 GET /v1/fundamentals/economic-calendar` | S9 gateway route | YES — `proxy.py:1466` | existing |
| S3 screener endpoint | S3 route | YES (PRD-0017) | existing |
| `S3Port` | Protocol port | YES | `upstream_clients.py:218` |
| `S6Port` | Protocol port | YES | `upstream_clients.py:141` |
| `S7Port` | Protocol port | YES | `upstream_clients.py:154` |
| `S3BriefPort` (or reuse S3Port) | NEW Protocol extension for screener + movers + calendars | NO — NEW (this plan Wave A) | — |

**Critical note on `_fetch_brief_seed`**: The plan references this method as something being "deleted from PLAN-0066 Sub-Plan B." Clarification: `_fetch_brief_seed` does NOT exist in the codebase today. It will be created in PLAN-0066 Sub-Plan B, and then removed by PLAN-0067 W11-3. This plan's `get_morning_brief` tool is specified as the W11-3 replacement. The implementation ordering constraint is: PLAN-0066 Sub-Plan B → PLAN-0067 W11-3 → this plan.

---

## 2. Tools

| Tool | Purpose | Backed by |
|---|---|---|
| `get_morning_brief` (NEW — Wave A) | Today's brief for an entity (or user-wide); replaces `RetrievalOrchestrator._fetch_brief_seed` (deleted by PLAN-0067 W11-3) | PLAN-0066 Sub-Plan A `user_briefs` table via `BriefArchivePort` Protocol |
| `compare_entities` (NEW — Wave A) | Side-by-side fundamentals + price + sentiment + KG-overlap for 2–4 entities | composes S3Port (fundamentals) + S6Port (chunk search) + S7Port (graph) — ALL via Protocol ports |
| `screen_universe` (NEW — Wave A) | Quantitative screener (filters: market_cap, pe_ratio, sector, region, etc.) | S9 → S3 screener (PRD-0017) via S3BriefPort Protocol |
| `get_market_movers` (NEW — Wave A) | Top gainers / losers / most-active over a timeframe | S9 `GET /v1/market/movers` (existing) via S3BriefPort Protocol |
| `get_economic_calendar` (NEW — Wave A) | Upcoming/past macro events (CPI, FOMC, GDP) for region | S9 `GET /v1/fundamentals/economic-calendar` (existing) via S3BriefPort Protocol |
| `get_earnings_calendar` (NEW — Wave A) | Earnings release dates ± actuals/estimates for a date range | S9 `GET /v1/fundamentals/earnings-calendar` (existing) via S3BriefPort Protocol |

## 3. Scope

| Wave | Title | Layer | Effort |
|------|-------|-------|--------|
| A | Manifest entries (6 tools, `since: v3`); `S3BriefPort` Protocol port extension (NEW — Wave A) for screener/movers/calendars; handlers; tests; 10 golden-eval queries added to PLAN-0067 W11-4 | libs + S8 | 1.5 dev-days |
| B | Cross-tool composition test: query "compare AAPL and MSFT and show me the top movers" forces multi-tool LLM behaviour | tests | 1.5 dev-days |

## 4. Hard Constraints

- **ABC/Protocol port requirement (R25)**: ALL 6 tool handlers MUST go through Protocol ports defined in `application/ports/upstream_clients.py`. No handler may import from `infrastructure/clients/` directly. Specifically:
  - `get_morning_brief` → `BriefArchivePort` Protocol (NEW in PLAN-0066 Sub-Plan A)
  - `compare_entities` → `S3Port` + `S6Port` + `S7Port` (all existing)
  - `screen_universe`, `get_market_movers`, `get_economic_calendar`, `get_earnings_calendar` → `S3BriefPort` Protocol (NEW — this plan Wave A)
- **ReadOnlyUoW for reads (R27)**: all 6 tools are read-only. Their handlers MUST NOT acquire `UnitOfWork`. The `get_morning_brief` handler reads `user_briefs` via `BriefArchivePort` which is backed by `ReadOnlyUnitOfWork` (R27). This must be explicitly specified in the Wave A task.
- **EntityContext respected for `compare_entities`**: when scope is set to one entity, the second arg (target entity) is the user-provided one; the scoped entity is auto-injected as the first arg.
- **`get_morning_brief` doubles as the I-4 migration target** (from PLAN-0067 §0): when `RetrievalOrchestrator._fetch_brief_seed` is deleted by PLAN-0067 W11-3, the `get_morning_brief` tool auto-called when same-day brief exists is the direct replacement. This auto-call logic is implemented in the W11-3 orchestrator wiring, not inside this plan.
- **R29 compliance**: `capability_manifest.yaml` updated atomically with handler registration. Each entry needs `name`, `description`, `parameters`, `since: "v3"`, and at least 2 `example_queries`.
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
