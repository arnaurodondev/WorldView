# PLAN-0049 — Frontend & Backend Stabilization (Phase 1)

**Status**: draft
**PRD source**: `docs/audits/2026-04-28-qa-frontend-design-roadmap.md` (PART D, Phase 1)
**Created**: 2026-04-28
**Owner**: Worldview platform
**Estimated effort**: 2 weeks (≈80h)
**Critical path**: yes — blocks PLAN-0050 (depends on structured AI brief schema + batch endpoints) and PLAN-0051 (depends on alert schema migration)

## Goal

Close every BLOCKING and CRITICAL defect surfaced by the 2026-04-28 frontend QA audit. Land the schema, endpoint, and shared-component foundation that Phases 2-5 build on. After this plan: zero BLOCKING, zero CRITICAL, and 4 cross-cutting shared components (`<MarkdownContent>`, `<DashboardEmptyState>`, `<PeriodSelector>`, `<DataTimestamp>`) extracted.

## Scope

| Severity | Findings closed |
|----------|----------------|
| BLOCKING | F-B-001 / F-P-009 (SnapTrade v4), F-I-001 (instruments landing), F-X-101/F-X-102 (workspace baseline — deferred to PLAN-0051) |
| CRITICAL | F-D-002 (sector overflow), F-D-006 / F-X-201 / F-B-002 / F-B-006 (alert title schema + fallback), F-P-001 (black panel holdings), F-P-008 (black panel watchlist), F-P-010 (DIV $0), F-I-003 / F-I-013 (EPS/Beta/Volume backfill — kicks off here, completes in PLAN-0050), F-I-002 (chart toolbar — kicks off, completes in PLAN-0050) |
| MAJOR | F-B-009 (batch OHLCV), F-B-010 (structured AI brief JSON), F-B-007 / F-B-008 (watchlist insights, predictions category — endpoint contracts only) |

## Codebase State Verification (Phase 0.5 — Mandatory)

| PRD Reference | Type | Service | Actual current state | Expected state | Delta |
|--------------|------|---------|---------------------|----------------|-------|
| `alerts` table | DB | alert | columns: alert_id, entity_id, alert_type, source_event_id, source_topic, payload (JSONB), dedup_key, created_at, severity (from migration 0004) | + title VARCHAR(255), ticker VARCHAR(20), entity_name VARCHAR(500), signal_label VARCHAR(200) | new migration `0005_add_alert_enrichment_columns.py`; head = `0004_add_severity_to_alerts` |
| `AlertFanoutUseCase._derive_signal_label` | code | alert | `services/alert/src/alert/application/use_cases/alert_fanout.py:105-125` — fallback `f"{severity} signal"` | populate alert.title from signal_label/entity_name; log warning on fallback | Modify use case + persistence path |
| Brokerage callback guard | code | worldview-web | `apps/worldview-web/app/(app)/portfolio/brokerage/callback/page.tsx:93` — `if (!connectionId || !authorizationId || !userId || !sessionId)` | `if (!connectionId || (!authorizationId && !connection_id_snap))` | One-line guard relaxation + v4 read |
| `EquityCurveChart` empty state | code | worldview-web | `components/portfolio/PortfolioAnalyticsSection.tsx:81` — `min-h-[200px] bg-card` unconditional | conditional `min-h` only when data present | Wrap render in branch |
| Watchlist tab empty | code | worldview-web | `components/portfolio/WatchlistsTabPanel.tsx:187-190` — no guard for `watchlists.length === 0` | render `<InlineEmptyState>` with create CTA | Add guard branch |
| Sector heatmap overflow | code | worldview-web | `components/dashboard/SectorHeatmapWidget.tsx:294-310` — GAP_PX=4 + p-1 → flex-basis cumulative rounding overflow | GAP_PX=2, `px-0.5 py-0`, container `overflow-hidden` | Constants + class change |
| `/v1/quotes/bars/batch` | endpoint | api-gateway | does not exist | new POST endpoint accepting `{symbols, interval, from, to}` | New route + market-data fan-out |
| AI brief response | API | rag-chat | returns `{narrative: string}` (raw markdown) | returns `{headline, sections:[{title,bullets:string[]}], citations:[{title,url,article_id}]}` (structured) | Schema change + prompt structuring |
| `MorningBriefCard` rendering | code | worldview-web | `components/dashboard/MorningBriefCard.tsx:305-352` — ReactMarkdown direct on string | use `<MarkdownContent>` shared component OR structured renderer | Refactor + shared component |
| `InstrumentAISubheader` rendering | code | worldview-web | `components/instrument/InstrumentAISubheader.tsx:188` — `<p>` plain text | use `<MarkdownContent>` (or structured renderer) | Refactor |
| `PortfolioSummary` "+X more" | code | worldview-web | `components/dashboard/PortfolioSummary.tsx:427-434` — no truncate | add `truncate px-2` | Class change |
| Holdings page 1S/1W/1M buttons | code | worldview-web | TBD — find header period buttons (separate from EquityCurveChart toggle) | remove per user request | Identify file + delete element |
| Brokerage callback test | test | worldview-web | `__tests__/brokerage-callback.test.tsx:107-112` — VALID_CALLBACK_PARAMS includes 4 params (false-PASS) | add v4 case (only connectionId + connection_id_snap) | Add test case |
| `<MarkdownContent>` | component | worldview-web | does not exist | new shared component in `components/ui/markdown-content.tsx` | New component |
| `<DashboardEmptyState>` | component | worldview-web | does not exist | new in `components/ui/dashboard-empty-state.tsx` | New component |
| `<PeriodSelector>` | component | worldview-web | does not exist | new in `components/ui/period-selector.tsx` | New component |
| `<DataTimestamp>` | component | worldview-web | does not exist | new in `components/ui/data-timestamp.tsx` | New component |

**All deltas have tasks below.** No PRD references are unverified.

---

## Dependency Graph

```
Wave A (Backend foundation: alert schema + AI brief schema + batch endpoint)
   │
   ├──→ Wave B (Frontend visual fixes: panels, overflow, callback, components)
   │       │
   │       └──→ Wave D (Frontend integration: MorningBriefCard + AlertWidgets + tests)
   │
   └──→ Wave C (Wire structured brief + alert enrichment end-to-end)
           │
           └──→ Wave D
```

**Parallelizable**: Wave A (all backend services) and Wave B (all frontend visual fixes) run in parallel — only dependency is Wave A blocks Wave C+D.

---

## Wave A — Backend Foundation

**Goal**: Migrate alert schema + ship structured AI brief + add batch OHLCV endpoint. Unlocks frontend integration.
**Depends on**: none
**Estimated effort**: 16-20h
**Architecture layer**: schema → infrastructure → application → API

### Tasks

#### T-A-1-01: Alembic migration `0005_add_alert_enrichment_columns.py`

**Type**: schema
**depends_on**: none
**blocks**: T-A-1-02, T-A-1-03, T-D-4-04
**Target files**: `services/alert/alembic/versions/0005_add_alert_enrichment_columns.py` (new)
**PRD reference**: F-B-002, F-B-003, F-D-006

**What to build**: Forward-compatible Alembic migration adding four nullable columns to `alerts` table: `title VARCHAR(255)`, `ticker VARCHAR(20)`, `entity_name VARCHAR(500)`, `signal_label VARCHAR(200)`. All nullable with no `server_default` (forward-compat). Add index on `ticker` (we'll filter by ticker in admin views later).

**Migration body**:
```python
revision = "0005_add_alert_enrichment_columns"
down_revision = "0004_add_severity_to_alerts"

def upgrade() -> None:
    op.add_column("alerts", sa.Column("title", sa.String(length=255), nullable=True))
    op.add_column("alerts", sa.Column("ticker", sa.String(length=20), nullable=True))
    op.add_column("alerts", sa.Column("entity_name", sa.String(length=500), nullable=True))
    op.add_column("alerts", sa.Column("signal_label", sa.String(length=200), nullable=True))
    op.create_index("idx_alerts_ticker", "alerts", ["ticker"], postgresql_where=sa.text("ticker IS NOT NULL"))

def downgrade() -> None:
    op.drop_index("idx_alerts_ticker", table_name="alerts")
    op.drop_column("alerts", "signal_label")
    op.drop_column("alerts", "entity_name")
    op.drop_column("alerts", "ticker")
    op.drop_column("alerts", "title")
```

**Acceptance criteria**:
- [ ] `alembic upgrade head` runs cleanly on fresh DB
- [ ] `alembic downgrade -1` rolls back cleanly
- [ ] All four columns nullable; existing rows have NULL values (no rewrite required)
- [ ] Forward-compat: BP-007 (server_default needed) NOT applicable since columns are nullable

**Downstream test impact**:
- `services/alert/tests/integration/test_alembic.py` — verify head revision tracker
- `services/alert/tests/unit/test_alert_repository.py` — Alert model fixtures need optional defaults

#### T-A-1-02: Extend Alert domain entity + ORM model

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: T-A-1-03
**Target files**: `services/alert/src/alert/domain/entities.py`, `services/alert/src/alert/infrastructure/db/models.py`
**PRD reference**: F-B-002, F-B-003

**What to build**: Add four nullable string fields to the `Alert` frozen dataclass and SQLAlchemy ORM model: `title`, `ticker`, `entity_name`, `signal_label`. All Optional[str] with default None. Update `Alert.from_kwargs()` / repository `to_entity()` mapping.

**Entities**:
- **Alert** (existing dataclass) — add fields:
  - `title: str | None = None` — descriptive subject for UI display
  - `ticker: str | None = None` — denormalized ticker for filtering
  - `entity_name: str | None = None` — denormalized entity name
  - `signal_label: str | None = None` — derived signal label (e.g., "Bullish guidance")

**Acceptance criteria**:
- [ ] Domain entity has 4 new fields with `None` defaults
- [ ] ORM model declares matching nullable columns (`Mapped[str | None]`)
- [ ] Repository `_to_entity()` maps new columns
- [ ] Existing tests pass (no constructor calls broken — fields are optional)

**Downstream test impact**:
- `services/alert/tests/unit/test_alert_repository.py` — verify roundtrip preserves new fields
- `services/alert/tests/unit/test_alert_fanout_use_case.py` — fixture Alert(...) calls still pass (defaults)

#### T-A-1-03: Populate enrichment fields in AlertFanoutUseCase + log fallback

**Type**: impl
**depends_on**: [T-A-1-02]
**blocks**: T-D-4-04
**Target files**: `services/alert/src/alert/application/use_cases/alert_fanout.py`
**PRD reference**: F-B-002, F-B-006, F-D-006, F-X-201

**What to build**: In `AlertFanoutUseCase.execute()`, populate new fields on the Alert before persistence:
- `ticker` ← `payload.ticker` if present
- `entity_name` ← `payload.entity_name` if present
- `signal_label` ← `_derive_signal_label(...)` (existing function)
- `title` ← composed string (priority): `entity_name + ": " + signal_label`, else `ticker + ": " + signal_label`, else `signal_label`, else `f"{alert_type.replace('_',' ').title()} alert"` — **never** bare `f"{severity} signal"`.

When `_derive_signal_label` falls back (claim_type/polarity missing), emit `logger.warning("signal_label_fallback", claim_type=..., polarity=..., severity=..., alert_id=...)`.

**Logic**:
1. Existing logic derives signal_label
2. New: compute title via composition above
3. Update Alert constructor to pass `title=`, `ticker=`, `entity_name=`, `signal_label=`
4. If signal_label was a fallback, structured-log warning

**Tests to write** (inline):
| Test name | Verifies | Type |
|-----------|----------|------|
| `test_fanout_populates_title_from_entity_and_signal` | title = "Apple Inc.: Bullish guidance" when both present | unit |
| `test_fanout_falls_back_to_ticker_title` | title = "AAPL: Bullish guidance" when no entity_name | unit |
| `test_fanout_falls_back_to_signal_only` | title = "Bullish guidance" when neither ticker nor name | unit |
| `test_fanout_uses_alert_type_when_signal_label_empty` | title = "Graph Change Alert" | unit |
| `test_fanout_logs_warning_on_signal_label_fallback` | logger.warning called with claim_type/polarity | unit |
| `test_fanout_never_outputs_bare_severity_signal` | title never equals "LOW signal"/"MEDIUM signal"/etc. | unit |

Min 6 new tests. No existing tests deleted (R19).

**Acceptance criteria**:
- [ ] All 6 new tests pass
- [ ] All existing alert tests still green
- [ ] `mypy` clean on alert_fanout.py
- [ ] No regression in `services/alert/tests/integration/test_outbox_consumer.py`

#### T-A-1-04: Structured AI brief response schema (rag-chat)

**Type**: schema + impl
**depends_on**: none
**blocks**: T-D-4-01, T-D-4-02
**Target files**:
- `services/rag-chat/src/rag_chat/api/schemas/briefing.py`
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py`
- `services/rag-chat/src/rag_chat/prompts/morning_brief.py` (or wherever the prompt lives)
- `libs/contracts/src/contracts/briefing.py` (canonical model — if shared)

**PRD reference**: F-B-010, F-D-001, F-I-004

**What to build**: Replace single `narrative: str` field with structured response. The LLM is instructed (system prompt) to emit valid JSON matching the schema. A post-processor validates and falls back to a single-section structure if JSON parsing fails (graceful degradation — old clients still receive a usable brief).

**New response schema** (Pydantic):
```python
class BriefSection(BaseModel):
    title: str = Field(..., max_length=120)  # e.g., "Drivers", "Implications"
    bullets: list[str] = Field(..., min_length=1, max_length=8)

class BriefCitation(BaseModel):
    title: str
    url: str | None = None
    article_id: str | None = None  # for internal deep-linking

class BriefResponse(BaseModel):
    headline: str = Field(..., max_length=240)
    summary: str | None = None  # 1-2 sentence executive summary
    sections: list[BriefSection] = Field(default_factory=list)
    citations: list[BriefCitation] = Field(default_factory=list)
    narrative: str | None = None  # backwards-compat: original markdown if structured parse failed
    generated_at: datetime
    entity_mentions: list[dict] = Field(default_factory=list)  # existing field preserved
```

**Logic**:
1. Update prompt to instruct: "Respond with a JSON object matching the schema {schema}. No prose outside the JSON."
2. Parse LLM output as JSON; on success → return structured BriefResponse with `narrative=None`
3. On JSON parse failure → log warning + return BriefResponse with `narrative=<raw>` and a single section "Briefing" with the raw markdown as one bullet
4. **Forward-compat**: keep `narrative` field for old frontends; new frontends prefer `sections`

**Tests to write**:
| Test name | Verifies | Type |
|-----------|----------|------|
| `test_briefing_returns_structured_when_llm_emits_json` | sections present, narrative None | unit |
| `test_briefing_falls_back_to_narrative_when_parse_fails` | narrative populated, sections empty | unit |
| `test_briefing_validates_section_max_8_bullets` | Pydantic ValidationError | unit |
| `test_briefing_preserves_entity_mentions` | existing field still emitted | unit |
| `test_briefing_response_serializes_to_json` | round-trip OK | unit |

**Acceptance criteria**:
- [ ] Endpoint contract documented in `docs/services/rag-chat.md` §Briefing API
- [ ] Old `narrative` field still present (forward-compat — BP-019)
- [ ] Pydantic schema in `libs/contracts/` if shared with S9 gateway
- [ ] All briefing tests pass

**Downstream test impact**:
- `services/api-gateway/tests/contract/test_briefing_response.py` — update expected fields
- `apps/worldview-web/__tests__/morning-brief-card.test.tsx` — handled in Wave D

#### T-A-1-05: Batch OHLCV endpoint `POST /v1/quotes/bars/batch`

**Type**: impl
**depends_on**: none
**blocks**: T-A-1-06 (frontend can adopt later)
**Target files**:
- `services/api-gateway/src/api_gateway/routes/quotes.py`
- `services/api-gateway/src/api_gateway/schemas/quotes.py`
- `services/market-data/src/market_data/api/routers/ohlcv.py` (verify batch handler exists)

**PRD reference**: F-B-009

**What to build**: New POST endpoint at `/v1/quotes/bars/batch` that accepts a JSON body with an array of symbol+timeframe specs and returns bars for all in one response. Internally fans out to market-data via `asyncio.gather`. Adds `Cache-Control: max-age=300` (5 min for intraday/daily bars).

**Request schema**:
```python
class BarRequest(BaseModel):
    instrument_id: UUID
    timeframe: Literal["5m", "1h", "1d", "1w", "1M"] = "1d"
    start_date: date | None = None
    end_date: date | None = None
    limit: int = Field(default=200, le=2000)

class BatchBarsRequest(BaseModel):
    requests: list[BarRequest] = Field(..., min_length=1, max_length=50)
```

**Response schema**:
```python
class InstrumentBars(BaseModel):
    instrument_id: UUID
    timeframe: str
    bars: list[OHLCVBar]
    error: str | None = None  # populated if this symbol failed

class BatchBarsResponse(BaseModel):
    results: list[InstrumentBars]
    fetched_at: datetime
```

**Logic**:
1. Validate batch size ≤ 50 symbols (BP-026 — bound external blast radius)
2. Use `asyncio.gather(..., return_exceptions=True)` to parallelize per-symbol fetch
3. Per-symbol exceptions → mark `error` on that result, do not fail the whole batch
4. Set `Cache-Control: max-age=300` on success response (BP-027 — CDN-cacheable for 5 min)

**Tests to write**:
| Test name | Verifies | Type |
|-----------|----------|------|
| `test_batch_bars_returns_results_in_order` | response order matches request order | unit |
| `test_batch_bars_partial_failure_marks_error` | one bad symbol returns error string, others succeed | unit |
| `test_batch_bars_max_50_symbols_enforced` | 51 symbols → 422 ValidationError | unit |
| `test_batch_bars_empty_request_rejected` | 0 symbols → 422 | unit |
| `test_batch_bars_cache_control_header` | response header set | integration |

**Acceptance criteria**:
- [ ] Endpoint in OpenAPI spec
- [ ] mypy + ruff clean
- [ ] 5 new tests pass
- [ ] Documented in `docs/services/api-gateway.md` §Quotes endpoints

**Downstream test impact**:
- `services/api-gateway/tests/contract/test_quotes_routes.py` — add batch route case

### Wave A — Pre-read

- `services/alert/alembic/versions/0004_add_severity_to_alerts.py` (current head)
- `services/alert/src/alert/application/use_cases/alert_fanout.py`
- `services/alert/src/alert/domain/entities.py`
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py`
- `services/api-gateway/src/api_gateway/routes/quotes.py`
- `RULES.md` §11 (forward-compatible schemas), §17 (UoW pattern)
- `docs/BUG_PATTERNS.md` BP-007, BP-019, BP-026, BP-027

### Wave A — Validation Gate

- [ ] `ruff check services/alert services/rag-chat services/api-gateway`
- [ ] `mypy` per-service clean
- [ ] Unit tests pass — minimum 16 new tests across alert + rag-chat + api-gateway
- [ ] `alembic upgrade head` + `alembic downgrade -1` round-trip in alert service
- [ ] Contract test for new `/v1/quotes/bars/batch` route
- [ ] Documentation updated: `docs/services/{alert,rag-chat,api-gateway}.md`
- [ ] Architecture: domain has no infra imports (verify with `python scripts/import_guards/check_import_guards.py`)

### Wave A — Break Impact

| Broken file | Why it breaks | Fix required |
|-------------|---------------|--------------|
| `services/alert/tests/unit/test_alert_repository.py` | Alert entity gains 4 fields | Existing fixtures still work (defaults None); add roundtrip assertion |
| `services/alert/tests/unit/test_alert_fanout_use_case.py` | Alert constructor takes new optional kwargs | No change required (defaults); add new tests per T-A-1-03 |
| `services/api-gateway/tests/contract/test_briefing_response.py` | Brief response schema now has `sections`, `citations` | Update expected payload |
| `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` | Backend may return either `{narrative}` or `{sections}` | Wave D handles — supports both shapes during rollout |
| `apps/worldview-web/components/instrument/InstrumentAISubheader.tsx` | Same | Wave D handles |

### Wave A — Regression Guardrails

- **BP-007**: Adding NOT NULL columns without server_default. **N/A here** — all four new columns nullable. ✓
- **BP-019**: Removing/renaming Avro/contract fields. Mitigated by keeping `narrative` field in BriefResponse. ✓
- **BP-026**: External blast radius. `BatchBarsRequest.requests` capped at 50. ✓
- **BP-027**: Cache-busting writes. Batch endpoint is read-only with 5min cache. ✓
- **BP-122**: Confluent Avro wire format. **N/A** — no Avro changes in this wave.
- **BP-235**: httpx timeout shadowing. Verify `asyncio.gather` in T-A-1-05 wraps `httpx.AsyncClient(timeout=httpx.Timeout(N))` not bare default.

---

## Wave B — Frontend Visual Fixes & Shared Components

**Goal**: Close all CRITICAL frontend visual bugs (black panels, sector overflow, callback) + extract 4 shared components used by Phase 2.
**Depends on**: none (parallel with Wave A)
**Estimated effort**: 14-18h
**Architecture layer**: components + page

### Tasks

#### T-B-2-01: Fix SnapTrade v4 callback guard

**Type**: impl
**depends_on**: none
**blocks**: T-B-2-02
**Target files**: `apps/worldview-web/app/(app)/portfolio/brokerage/callback/page.tsx`
**PRD reference**: F-B-001, F-P-009

**What to build**: Relax the param guard at line 93. Read both `authorizationId` (v3) and `connection_id` (v4 portal). Treat `userId` and `sessionId` as optional with empty-string fallback (matches backend `brokerage_connections.py:152-167`).

**Logic**:
```typescript
const connectionId = searchParams.get("connectionId");
const authorizationId = searchParams.get("authorizationId");
const connectionIdSnap = searchParams.get("connection_id");
const userId = searchParams.get("userId") ?? "";
const sessionId = searchParams.get("sessionId") ?? "";
const authId = authorizationId || connectionIdSnap; // prefer v3, fall back to v4

if (!connectionId || !authId) {
  setError("Missing required callback parameters. Please try connecting your brokerage again.");
  return;
}
// proceed with userId / sessionId possibly empty strings
```

**Acceptance criteria**:
- [ ] v3 callback (4 params) still works (regression-safe)
- [ ] v4 callback (connectionId + connection_id only) succeeds
- [ ] Error message only shown when truly missing critical IDs

#### T-B-2-02: Add v4 callback test case

**Type**: test
**depends_on**: [T-B-2-01]
**blocks**: none
**Target files**: `apps/worldview-web/__tests__/brokerage-callback.test.tsx`
**PRD reference**: F-B-015

**What to build**: New test case `"allows activation when userId and sessionId are absent (v4 portal)"` using URLSearchParams with only `connectionId` and `connection_id` (no `authorizationId`, no `userId`, no `sessionId`). Assert no error rendered, activation request fired.

**Acceptance criteria**:
- [ ] New test passes
- [ ] Existing v3 test still passes (no regression)

#### T-B-2-03: Fix sector heatmap overflow

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx`
**PRD reference**: F-D-002

**What to build**: Reduce `GAP_PX` constant from 4 to 2; change container padding `p-1` → `px-0.5 py-0`; add `overflow-hidden` to outer container so any sub-pixel overflow is clipped. Verify all 11 GICS sectors render within bounds at 1280px, 1440px, and 1920px viewports.

**Acceptance criteria**:
- [ ] No tile crosses widget border at 1280/1440/1920px
- [ ] Sub-pixel rounding doesn't cause row overflow
- [ ] Visual snapshot: tiles still readable (not too cramped at 2px gap)

#### T-B-2-04: Fix EquityCurveChart empty-state black panel

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/PortfolioAnalyticsSection.tsx`
**PRD reference**: F-P-001

**What to build**: Replace unconditional `min-h-[200px] bg-card` with conditional rendering: when data is loading or empty, render a centered `<InlineEmptyState>` inside a smaller container (`min-h-0 h-auto`); when data is present, restore `min-h-[200px]` so the chart has space to draw.

**Logic**:
```tsx
if (isLoading) return <Skeleton className="h-[200px] w-full" />;
if (!data || data.length === 0) {
  return (
    <div className="flex h-auto items-center justify-center py-6 border border-border/40 rounded-[2px]">
      <InlineEmptyState message="No equity history yet — snapshots accumulate over trading days." />
    </div>
  );
}
return (
  <div className="min-h-[200px] bg-card border border-border rounded-[2px] p-2">
    <EquityCurveChart data={data} />
  </div>
);
```

**Acceptance criteria**:
- [ ] Empty portfolio: no large black panel; small centered "No equity history yet" message
- [ ] Loading: skeleton at 200px
- [ ] With data: chart renders at 200px min-height
- [ ] Existing snapshot tests updated

#### T-B-2-05: Fix WatchlistsTabPanel empty-state black panel

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx`
**PRD reference**: F-P-008

**What to build**: Add guard before `<Tabs>` render: if `watchlists.length === 0`, render `<InlineEmptyState>` with "No watchlists yet" + a `<Button>Create watchlist</Button>` CTA. Otherwise existing Tabs path.

**Acceptance criteria**:
- [ ] Empty user: friendly empty state with CTA, no void above tabs
- [ ] User with ≥1 watchlist: normal tabs render
- [ ] CTA opens existing CreateWatchlistDialog

#### T-B-2-06: Fix PortfolioSummary "+X more" overflow

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/dashboard/PortfolioSummary.tsx:427-434`
**PRD reference**: F-D-003

**What to build**: Add `truncate px-2` to the link className. Drop redundant " → View all" suffix (the click target is the entire row).

**Acceptance criteria**:
- [ ] Long counts (e.g., "+46 more") fit within widget bounds
- [ ] Click target unchanged

#### T-B-2-07: Remove 1S/1W/1M buttons from Holdings page header

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/app/(app)/portfolio/page.tsx` (find period buttons, separate from EquityCurveChart toggle)
**PRD reference**: User request (D-4 in audit)

**What to build**: Identify the period selector at the top of the Holdings tab (NOT the EquityCurveChart's internal toggle) and remove. Per user: "On this page we should delete the 1S, 1W and 1M buttons." If the buttons are wired to the `selectedPeriod` state used by KPI strip, leave KPI strip default to "1D" hardcoded.

**Acceptance criteria**:
- [ ] No 1S/1W/1M chips at top of Holdings tab
- [ ] EquityCurveChart period toggle (1W/1M/3M/6M/1Y/All) UNCHANGED
- [ ] No layout gap left behind

#### T-B-2-08: Extract `<MarkdownContent>` shared component

**Type**: impl
**depends_on**: none
**blocks**: T-D-4-01, T-D-4-02, T-D-4-03
**Target files**: `apps/worldview-web/components/ui/markdown-content.tsx` (new)
**PRD reference**: F-D-001, F-D-016, F-D-028, F-I-004

**What to build**: Centralized markdown renderer wrapping ReactMarkdown + remarkGfm with custom component overrides for `<a>`, `<table>`, `<tr>`, `<td>`, `<th>`, `<code>`, `<pre>`, `<h2>`, `<h3>`, `<blockquote>`. Two size variants (`size: "compact" | "comfortable"`) controlling base font (10px / 12px) and spacing.

**Component signature**:
```tsx
interface MarkdownContentProps {
  children: string;
  size?: "compact" | "comfortable";
  className?: string;
}
export function MarkdownContent({ children, size = "comfortable", className }: MarkdownContentProps): JSX.Element;
```

**Acceptance criteria**:
- [ ] Renders headings, lists, tables, code blocks, blockquotes with consistent dark-theme styling
- [ ] Tables get `border-collapse border border-border/40` + zebra-stripe rows
- [ ] Code blocks: `bg-muted/30 rounded-[2px] px-1 font-mono`
- [ ] Storybook-style visual test in `__tests__/markdown-content.test.tsx`

#### T-B-2-09: Extract `<DashboardEmptyState>`, `<PeriodSelector>`, `<DataTimestamp>`

**Type**: impl
**depends_on**: none
**blocks**: T-D-4-04
**Target files**:
- `apps/worldview-web/components/ui/dashboard-empty-state.tsx`
- `apps/worldview-web/components/ui/period-selector.tsx`
- `apps/worldview-web/components/ui/data-timestamp.tsx`

**PRD reference**: F-D-010, F-D-013, F-D-019

**What to build**: Three small shared components:

1. **`<DashboardEmptyState>`** — `{ title, message, cta?: { label, href } }` → centered flex column, primary text + muted secondary + optional link
2. **`<PeriodSelector>`** — `{ periods: string[], selected: string, onSelect: (p) => void, ariaLabel?: string }` → flex row of pill buttons with consistent styling (px-1.5 text-[9px] uppercase, primary/20 active state)
3. **`<DataTimestamp>`** — `{ timestamp: Date | string, format?: "relative" | "absolute" }` → `2m ago` / `1h ago` / `2026-04-28 10:32 UTC`. Color-codes: <5m green, 5-30m amber, >1h muted

**Acceptance criteria**:
- [ ] Each component has a unit test
- [ ] All three exported from `components/ui/index.ts`
- [ ] Storybook-style fixtures committed
- [ ] No external dep additions

### Wave B — Pre-read
- `apps/worldview-web/app/(app)/portfolio/brokerage/callback/page.tsx`
- `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx`
- `apps/worldview-web/components/portfolio/PortfolioAnalyticsSection.tsx`
- `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx`
- `apps/worldview-web/components/portfolio/InlineEmptyState.tsx` (existing pattern to mimic)
- `docs/ui/DESIGN_SYSTEM.md` for shared component conventions

### Wave B — Validation Gate
- [ ] `pnpm lint` clean
- [ ] `pnpm typecheck` clean
- [ ] `pnpm test` green (existing 411+ tests)
- [ ] 5+ new component tests for shared components
- [ ] No Tailwind class regressions (DESIGN_SYSTEM.md compliance)

### Wave B — Break Impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| `__tests__/brokerage-callback.test.tsx` | Guard relaxed | T-B-2-02 adds v4 case |
| `__tests__/sector-heatmap-widget.test.tsx` | GAP_PX changed | Update snapshot |
| `__tests__/portfolio-analytics-section.test.tsx` | Conditional render | Update for empty/loading/data branches |
| Future Wave D consumers | New shared components don't exist yet | Wave D depends on Wave B |

### Wave B — Regression Guardrails
- **BP-026**: Empty array bash. **N/A** (frontend wave).
- **F-303 alert deep-link** — Wave D will backport same pattern to AlarmsPanel; not in scope here.
- DESIGN_SYSTEM.md radius tokens (rounded-[2px]) MUST be respected in new components — no `rounded-md` etc.
- Tailwind: tabular-nums on any new numeric output.

---

## Wave C — Backend Wiring & Universe Coverage Kick-off

**Goal**: Land alert enrichment data flow + start universe expansion + add news limit knob. Lower-criticality backend items.
**Depends on**: Wave A (T-A-1-01..03 for alert enrichment)
**Estimated effort**: 12-16h
**Architecture layer**: application + config + infrastructure

### Tasks

#### T-C-3-01: Backfill alert.title for existing rows (one-shot script)

**Type**: impl + config
**depends_on**: [T-A-1-01, T-A-1-03]
**blocks**: none
**Target files**: `services/alert/scripts/backfill_alert_titles.py` (new)
**PRD reference**: F-B-002

**What to build**: One-shot Python script that iterates rows in `alerts` where `title IS NULL`, derives a title from existing `payload` JSON (using same logic as AlertFanoutUseCase), and updates the row. Idempotent (checks NULL before update). Batched (1000 rows per commit). Logs row count.

**Acceptance criteria**:
- [ ] Idempotent on re-run (no duplicate updates)
- [ ] Logs progress per 10k rows
- [ ] Documented in `docs/services/alert.md` §Migration ops
- [ ] Smoke test on dev DB: every row has non-empty title afterward

#### T-C-3-02: Frontend alert title fallback chain (RecentAlerts + AlarmsPanel)

**Type**: impl
**depends_on**: [T-A-1-03]
**blocks**: none
**Target files**:
- `apps/worldview-web/components/dashboard/RecentAlerts.tsx`
- `apps/worldview-web/components/shell/AlarmsPanel.tsx`

**PRD reference**: F-D-006, F-X-201, F-D-025

**What to build**:
1. Replace severity-based fallback with new chain: `alert.title || alert.signal_label || alert.entity_name || \`${alert.alert_type.replace('_',' ').replace(/\b\w/g, c => c.toUpperCase())} alert\`` — never bare severity.
2. Backport deep-link from RecentAlerts to AlarmsPanel (`router.push('/alerts?selected={id}')`) — closes F-D-025.
3. Update gateway response type `AlertSummary` to include `title`, `ticker`, `entity_name`, `signal_label` from new schema.

**Acceptance criteria**:
- [ ] No "LOW signal" / "MEDIUM signal" / "HIGH signal" / "CRITICAL signal" string can appear in either component (negative regex test)
- [ ] AlarmsPanel deep-link opens AlertDetailSheet (parity with RecentAlerts)
- [ ] Unit test asserts fallback chain priority

#### T-C-3-03: Predictions category filter param

**Type**: impl
**depends_on**: none
**blocks**: PLAN-0050 F-D-005
**Target files**:
- `services/api-gateway/src/api_gateway/routes/predictions.py` (or equivalent)
- Verify content-store schema has `category` column on `prediction_markets` table

**PRD reference**: F-B-008

**What to build**: Add `category: str | None = Query(default=None)` to predictions endpoint. Filter `WHERE category = :category` if provided. Document supported values: `macro`, `politics`, `sports`, `crypto`, `general`.

**Acceptance criteria**:
- [ ] Query param works end-to-end
- [ ] OpenAPI documented
- [ ] Contract test for new param
- [ ] If category column missing, add Alembic migration + seed mapping

#### T-C-3-04: Increase nlp-pipeline news default limit (rag-chat path)

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**: `services/rag-chat/src/rag_chat/application/use_cases/briefing_context_gatherer.py`
**PRD reference**: F-B-005

**What to build**: In `BriefingContextGatherer._fetch_entity_articles()`, explicitly request `limit=30` (max=50) instead of relying on default `limit=10`.

**Acceptance criteria**:
- [ ] Brief generation uses richer article context
- [ ] No new test required (covered by existing brief integration tests)

#### T-C-3-05: Document new endpoint contracts

**Type**: docs
**depends_on**: [T-A-1-04, T-A-1-05]
**blocks**: none
**Target files**:
- `docs/services/api-gateway.md` (new sections: Quotes batch, Predictions category)
- `docs/services/rag-chat.md` (Briefing schema)
- `docs/services/alert.md` (enrichment columns + signal_label fallback contract)

**Acceptance criteria**:
- [ ] All four touched services have updated docs
- [ ] OpenAPI specs regenerated and committed

### Wave C — Pre-read
- `services/api-gateway/src/api_gateway/routes/predictions.py`
- `services/rag-chat/src/rag_chat/application/use_cases/briefing_context_gatherer.py`
- `docs/BUG_PATTERNS.md` BP-126 (NOT NULL column server_default)

### Wave C — Validation Gate
- [ ] All Wave A + B tests still pass
- [ ] New backfill script runs idempotently on dev DB
- [ ] Doc lint clean

### Wave C — Break Impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| `apps/worldview-web/types/api.ts` AlertSummary | New title/ticker/entity_name/signal_label fields | Extend type definition with optional fields |
| `services/api-gateway/tests/contract/test_predictions.py` | New category param | Add test cases |

### Wave C — Regression Guardrails
- **BP-126**: NOT NULL column server_default — N/A (alert columns nullable).
- **BP-019**: Removing fields — N/A (all additive).
- **R19**: No tests deleted; backfill script tested separately.

---

## Wave D — Frontend Integration: Structured Brief + Alert Refactor + Tests

**Goal**: Migrate MorningBriefCard + InstrumentAISubheader + IntelligenceTab to consume structured BriefResponse via shared `<MarkdownContent>`. Add comprehensive Vitest + Playwright coverage for the stabilization work.
**Depends on**: Wave A (T-A-1-04), Wave B (T-B-2-08, T-B-2-09), Wave C (T-C-3-02)
**Estimated effort**: 14-18h
**Architecture layer**: components + integration

### Tasks

#### T-D-4-01: Refactor MorningBriefCard to consume BriefResponse

**Type**: impl
**depends_on**: [T-A-1-04, T-B-2-08]
**blocks**: T-D-4-04
**Target files**: `apps/worldview-web/components/dashboard/MorningBriefCard.tsx`
**PRD reference**: F-D-001, F-B-010

**What to build**: Update component to read `brief.headline`, `brief.summary`, `brief.sections[]`, `brief.citations[]` (preferred path) with fallback to `brief.narrative` (compatibility for unstructured response). Render structured response with section dividers, bullet lists, and styled citation list (numbered, clickable).

**Layout (expanded view)**:
```
┌─────────────────────────────────────────┐
│ HEADLINE (bold, 14px)                   │
│ summary (muted, 11px, 2 lines max)      │
├─────────────────────────────────────────┤
│ Drivers                                  │
│  • bullet 1                              │
│  • bullet 2                              │
│ ─────────                                │
│ Implications                             │
│  • bullet 1                              │
│ ─────────                                │
│ Citations                                │
│  [1] Title — source                      │
│  [2] Title — source                      │
└─────────────────────────────────────────┘
```

**Logic**:
- If `brief.sections.length > 0` → structured render
- Else if `brief.narrative` → render via `<MarkdownContent>`
- Else → empty state via `<DashboardEmptyState>`

**Acceptance criteria**:
- [ ] Both response shapes render cleanly
- [ ] Citations linkable to article URLs / instrument deep-links
- [ ] Snapshot tests for both paths
- [ ] Closes F-D-001 (markdown), F-D-016 (table styling), F-D-028 (code blocks)

#### T-D-4-02: Refactor InstrumentAISubheader to use shared renderer

**Type**: impl
**depends_on**: [T-A-1-04, T-B-2-08]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/InstrumentAISubheader.tsx`
**PRD reference**: F-I-004

**What to build**: Replace plain `<p>{brief.narrative}</p>` at line 188 with `<MarkdownContent size="compact">{brief.narrative ?? brief.summary ?? ""}</MarkdownContent>`. When BriefResponse has structured sections (Phase 2 will deepen this), use compact section renderer.

**Acceptance criteria**:
- [ ] Renders identically to MorningBriefCard collapsed view
- [ ] Closes F-I-004

#### T-D-4-03: Refactor IntelligenceTab brief block

**Type**: impl
**depends_on**: [T-A-1-04, T-B-2-08]
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/IntelligenceTab.tsx:268`
**PRD reference**: F-I-004

**What to build**: Replace inline ReactMarkdown config with `<MarkdownContent size="comfortable">`.

**Acceptance criteria**:
- [ ] Closes F-I-004 last surface
- [ ] All three AI brief surfaces (dashboard, instrument header, intelligence tab) now use the same renderer

#### T-D-4-04: Update RecentAlerts + AlarmsPanel to consume new fields

**Type**: impl
**depends_on**: [T-A-1-03, T-B-2-09, T-C-3-02]
**blocks**: T-D-4-05
**Target files**:
- `apps/worldview-web/components/dashboard/RecentAlerts.tsx`
- `apps/worldview-web/components/shell/AlarmsPanel.tsx`
- `apps/worldview-web/types/api.ts`

**PRD reference**: F-D-006, F-X-201, F-D-025

**What to build**:
1. Extend `AlertSummary` type with `title?: string`, `ticker?: string`, `entity_name?: string`, `signal_label?: string`
2. RecentAlerts row: render `alert.title` as primary text; severity as small chip; ticker as accent
3. AlarmsPanel sidebar: similar layout, monospace ticker
4. Apply fallback chain from T-C-3-02
5. Add `<DataTimestamp timestamp={alert.created_at} format="relative" />` next to each alert

**Acceptance criteria**:
- [ ] No "{SEVERITY} signal" string visible anywhere (regex test)
- [ ] Ticker accent color (text-primary) on alerts that have one
- [ ] DataTimestamp shows green/amber/muted by recency
- [ ] Snapshot tests updated

#### T-D-4-05: Vitest regression tests for stabilization wave

**Type**: test
**depends_on**: [T-D-4-01, T-D-4-04]
**blocks**: T-D-4-06
**Target files**:
- `apps/worldview-web/__tests__/morning-brief-card.test.tsx`
- `apps/worldview-web/__tests__/recent-alerts.test.tsx`
- `apps/worldview-web/__tests__/alarms-panel.test.tsx`
- `apps/worldview-web/__tests__/sector-heatmap-overflow.test.tsx`
- `apps/worldview-web/__tests__/equity-curve-empty-state.test.tsx`

**What to build**: Add ≥12 new tests covering:
- Brief structured rendering with sections/citations
- Brief fallback to narrative
- Alert title fallback chain (4 levels)
- Alert "no severity-only string" assertion (regex)
- Sector heatmap no-overflow at 3 viewport widths
- EquityCurveChart shows InlineEmptyState when no data (no large black panel)
- WatchlistsTabPanel shows CTA when watchlists empty
- AlarmsPanel deep-links to /alerts?selected={id}

**Acceptance criteria**:
- [ ] 12+ new green tests
- [ ] All existing 411+ tests still green

#### T-D-4-06: Playwright E2E for stabilization

**Type**: test
**depends_on**: [T-D-4-05]
**blocks**: none
**Target files**: `apps/worldview-web/e2e/stabilization-phase1.spec.ts` (new)

**What to build**: Three E2E scenarios:
1. Empty user → Holdings tab → no large black panel; Watchlist tab → empty CTA
2. SnapTrade v4 callback simulation (only connectionId + connection_id) → activation succeeds
3. Dashboard load → MorningBriefCard renders structured sections OR narrative fallback (both pass)

**Acceptance criteria**:
- [ ] Playwright spec runs against local dev stack
- [ ] All three scenarios pass

### Wave D — Pre-read
- All Wave A, B, C output
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (current implementation)
- Existing Vitest setup at `apps/worldview-web/vitest.config.ts`
- Existing Playwright config at `apps/worldview-web/playwright.config.ts`

### Wave D — Validation Gate
- [ ] `pnpm lint` clean
- [ ] `pnpm typecheck` clean
- [ ] `pnpm test` — minimum 12 new green tests, total ≥ 423 passing
- [ ] `pnpm exec playwright test` — minimum 3 new specs passing
- [ ] No "LOW signal" / "{SEVERITY} signal" strings anywhere in rendered output (negative regex search)
- [ ] All four shared components used in ≥ 2 places
- [ ] TRACKING.md updated with PLAN-0049 status

### Wave D — Break Impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| `__tests__/morning-brief-card.test.tsx` (existing) | New BriefResponse shape | Rewrite per T-D-4-05 |
| `__tests__/recent-alerts.test.tsx` (existing) | New fallback chain | Rewrite per T-D-4-05 |
| `apps/worldview-web/types/api.ts` AlertSummary | New optional fields | Extend type |
| `apps/worldview-web/types/briefing.ts` (or inline) | New BriefResponse shape | Define matching TS interface |

### Wave D — Regression Guardrails
- **F-303 deep-link parity**: AlarmsPanel must match RecentAlerts pattern (T-D-4-04 does this).
- **R19**: No tests deleted; old tests rewritten to match new component contract (this is allowed — same coverage, updated assertions).
- **BP-249** (alert WS): unchanged in this plan (S10 WS already works); verify not broken by schema migration.
- **DESIGN_SYSTEM.md**: All new components use rounded-[2px], no shadows, gap-px seams.

---

## Cross-Cutting Concerns

### Contracts that change
- **Alert API response** — adds 4 optional string fields (forward-compat ✓)
- **Briefing API response** — adds `headline`, `summary`, `sections`, `citations`; keeps `narrative` (forward-compat ✓)
- **New endpoint** `POST /v1/quotes/bars/batch` — additive, no breaking changes
- **Predictions endpoint** — adds optional `?category=` param (backward-compat ✓)

### Migrations required
- `services/alert/alembic/versions/0005_add_alert_enrichment_columns.py` (new)
- (Optional) Predictions category column if absent — verify in T-C-3-03

### Event/topic changes
- None in Phase 1.

### Configuration changes
- None new env vars required. (PLAN-0050 will add S10 acknowledge endpoints.)

### Documentation
- `docs/services/alert.md` — schema delta, signal_label fallback contract, backfill ops
- `docs/services/rag-chat.md` — BriefResponse schema, structured-vs-narrative fallback
- `docs/services/api-gateway.md` — Quotes batch, Predictions category
- `docs/ui/DESIGN_SYSTEM.md` — 4 new shared components

---

## Risk Assessment

### Critical path
Wave A (alert schema migration + structured brief) is the critical path: every other wave depends on it. Mitigate by parallelizing Wave A tasks (T-A-1-01..05 are independent).

### Highest risk
T-A-1-04 (structured AI brief) — depends on LLM output quality. JSON parse failure rate is unknown. **Mitigation**: graceful fallback to `narrative` field; no UI breakage; log fallback rate to measure success.

### Rollback strategy
- Alembic migration 0005 has clean downgrade path
- Frontend changes preserve all existing functionality (additive)
- BriefResponse keeps `narrative` field — old clients fully compatible
- No service deployment ordering required (all changes forward-compat)

### Testing gaps
- Brief structured-rendering A/B (test runs against both shapes via fixture parametrization)
- v4 callback E2E requires SnapTrade sandbox — mock at the URL level (already done in __tests__)

---

## Compounding Updates

After PLAN-0049 completes, propose adding to `docs/BUG_PATTERNS.md`:
- **BP-265**: Alert/event-rendering UIs must never display severity-only strings (e.g., "LOW signal"). Always provide a meaningful subject. Enforce via negative regex test in component test suite.
- **BP-266**: OAuth callback guards must mirror backend optionality. When backend treats params as optional with empty-string fallback, frontend must do the same. Test both v3 (legacy) and v4 (current) callbacks.
- **BP-267**: AI/LLM responses returning markdown should be structured JSON with a `narrative` fallback field for forward/backward compat during rollout. Frontend renders structured path when available, falls back to narrative otherwise.

Add to `.claude/review/checklists/REVIEW_CHECKLIST.md`:
- "Alert / event display fields never expose internal taxonomy (severity, status enums) without context."
- "OAuth/callback param guards aligned with backend optionality + tested for all supported versions."

Add to `docs/ui/DESIGN_SYSTEM.md`:
- Specs for `<MarkdownContent>`, `<DashboardEmptyState>`, `<PeriodSelector>`, `<DataTimestamp>` (component catalogue extension).

---

## Wave Tracker

| Wave | Status | Tasks | Effort |
|------|--------|-------|--------|
| A — Backend Foundation | pending | 5 | 16-20h |
| B — Frontend Visual Fixes & Shared Components | pending | 9 | 14-18h |
| C — Backend Wiring & Universe Coverage Kick-off | pending | 5 | 12-16h |
| D — Frontend Integration | pending | 6 | 14-18h |
| **Total** | — | **25** | **56-72h ≈ 2 weeks** |

---

**Next**: After Wave A green-lights, kick off `/implement PLAN-0049 Wave A` and `/implement PLAN-0049 Wave B` in parallel worktrees.
