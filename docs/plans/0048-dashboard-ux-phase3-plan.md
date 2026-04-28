---
id: PLAN-0048
title: Dashboard UX Phase 3 — Brief Redesign, Alert Detail Deep-Link, TopBar Polish, Predictions Enrichment, Sector Treemap
prd: qa-user-feedback-2026-04-28
status: draft
created: 2026-04-28
updated: 2026-04-28
supersedes: docs/plans/0047-dashboard-ux-phase2-plan.md (absorbs A/B/C/D/E)
---

# PLAN-0048 — Dashboard UX Phase 3

> **Source**: QA report `docs/audits/2026-04-28-qa-plan-0045-user-feedback-report.md`
> **Priority**: HIGH — primary intelligence widgets (brief, alerts, predictions) underdeliver despite PLAN-0045 completion
> **Status**: DRAFT — pending implementation

This plan absorbs PLAN-0047 (which never reached implementation) and adds the user feedback issues identified after PLAN-0045 shipped. Total: 6 waves, 17 tasks.

---

## Pre-Read List

Before implementing, read:
- `docs/audits/2026-04-28-qa-plan-0045-user-feedback-report.md` — root cause analysis for every wave
- `docs/plans/0047-dashboard-ux-phase2-plan.md` — original draft for waves D/E/F (now absorbed here)
- `libs/prompts/src/prompts/briefing/morning.py` (Wave A)
- `services/rag-chat/src/rag_chat/api/schemas.py` and `application/use_cases/generate_briefing.py` (Wave A)
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (Wave A)
- `services/alert/src/alert/application/use_cases/alert_fanout.py` (Wave B)
- `apps/worldview-web/app/(app)/alerts/page.tsx` and `components/alerts/AlertsList.tsx` (Wave B)
- `apps/worldview-web/components/shell/TopBar.tsx` (Wave C)
- `apps/worldview-web/components/dashboard/PortfolioSummary.tsx` (Wave C)
- `services/market-data/src/market_data/api/routers/prediction_markets.py` (Wave D)
- `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx` (Wave D)
- `apps/worldview-web/app/(app)/dashboard/page.tsx` (Wave E)
- `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx` (Wave F)

---

## Wave A — Morning Brief: Two-Tier Output + Top Stories Strip

**Why**: User reports the brief wastes 15% of the page on duplicate "Market Overview" / "Morning Market Briefing" / date headers. They want a compact one-paragraph summary collapsed, structured sections expanded, and clickable links to top stories.

### Task A-1: Update MORNING_BRIEFING prompt to emit `summary:` + `details:` blocks

**Target file**: `libs/prompts/src/prompts/briefing/morning.py`

**Changes**:
1. Restructure prompt to require:
   ```
   ## SUMMARY
   <1-2 sentences capturing today's most important signal across portfolio + market + alerts>

   ---

   ## DETAILS
   ### Market Overview
   ...
   ### Portfolio Impact
   ...
   ### Key News
   ...
   ### Active Alerts & Signals
   ...
   ```
2. Bump prompt version `2.1 → 2.2`.
3. Tighten guidelines: forbid emitting "Date:" or "Morning Briefing" in the body (the card chrome supplies them).

**Validation**:
- [ ] LLM smoke test: brief output begins with `## SUMMARY` and contains `---` separator
- [ ] Snapshot test in `services/rag-chat/tests/unit/` updated

### Task A-2: Add `summary` + `top_stories` fields to BriefingResponse

**Target files**:
- `services/rag-chat/src/rag_chat/api/schemas.py` — `BriefingResponse` adds `summary: str | None` and reuses existing `citations` (top 3 by relevance) as `top_stories`
- `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py` — split LLM output on `---`, populate `summary` from the first half, `narrative` from the second
- `apps/worldview-web/types/api.ts` — extend `BriefingResponse`
- Forward-compatible: both fields default null on legacy responses

**Validation**: rag-chat unit tests updated; gateway typecheck passes.

### Task A-3: MorningBriefCard collapsed = `summary`, expanded = `narrative` + Top Stories strip

**Target file**: `apps/worldview-web/components/dashboard/MorningBriefCard.tsx`

**Changes**:
1. Remove `stripBriefPreamble()` helper (no longer needed).
2. Collapsed view: render `brief.summary` (1-2 sentences) at full readability — no `line-clamp-3`.
3. Expanded view: render `brief.narrative` (the structured `## DETAILS` block) as before.
4. New "Top Stories" strip below summary in BOTH collapsed and expanded views: 3 chip-style `<Link>`s using `brief.citations[:3]` showing source + truncated title.
5. Header bar unchanged: `[date]` left · `MORNING BRIEFING` middle · `[Read more →]` right.

**Validation**:
- [ ] `pnpm typecheck` — 0 errors
- [ ] `pnpm test` — all pass
- [ ] Live: collapsed card shows 1-paragraph summary + 3 story chips; expanded shows full sections.

---

## Wave B — Alerts: Payload Enrichment + Detail Deep-Link

### Task B-1: Backend signal-alert payload enrichment

**Target files**:
- `services/alert/src/alert/application/ports/entity_resolver.py` (new) — `EntityNameResolverPort` ABC
- `services/alert/src/alert/infrastructure/clients/s7_entity_resolver.py` (new) — calls S7 `/entities/{id}` (read replica) with Valkey-cached lookup (15-min TTL)
- `services/alert/src/alert/application/use_cases/alert_fanout.py` — inject `entity_name`, `ticker`, `signal_label` (derived from `claim_type` + `polarity`) into payload before persist
- `services/alert/src/alert/application/dependencies.py` — wire new port

**Signal label derivation** (no LLM call needed):
```
(claim_type=forward_guidance, polarity=positive) → "Bullish guidance"
(claim_type=forward_guidance, polarity=negative) → "Bearish guidance"
(claim_type=factual,         polarity=positive) → "Positive factual"
(claim_type=projection,       polarity=negative) → "Bearish projection"
... etc.
```

**Validation**:
- [ ] alert-service unit tests cover the new port
- [ ] Live: `GET /v1/alerts/pending` returns `payload.entity_name`, `payload.ticker`, `payload.signal_label`

### Task B-2: Simplify RecentAlerts + AlertsList rendering

**Target files**: `apps/worldview-web/components/dashboard/RecentAlerts.tsx`, `apps/worldview-web/components/alerts/AlertsList.tsx`

**Changes**:
1. Remove the multi-fallback IIFE in RecentAlerts.tsx:77-99.
2. New rendering: `{payload.ticker || payload.entity_name}: {payload.signal_label}` — fallback to `${severity} alert` only when payload is empty.

### Task B-3: Alert detail deep-link via `/alerts?selected={alert_id}`

**Target files**:
- `apps/worldview-web/app/(app)/alerts/page.tsx` — read `?selected=` query param; pass selectedId down
- `apps/worldview-web/components/alerts/AlertDetailSheet.tsx` (new) — shadcn `<Sheet>` showing alert payload, source event id, related entity link, ack/snooze
- `apps/worldview-web/components/alerts/AlertsList.tsx` — clicking row updates URL `?selected={id}` (instead of navigating to `/instruments`)
- `apps/worldview-web/components/dashboard/RecentAlerts.tsx` — Link `href={"/alerts?selected=" + alert.id}` instead of bare `/alerts`

**Validation**:
- [ ] Live: clicking a dashboard alert opens `/alerts?selected=…` with sheet open
- [ ] Closing the sheet returns to `/alerts` (no selected param)
- [ ] Direct navigation to `/alerts?selected={id}` opens sheet on page load

---

## Wave C — TopBar + PortfolioSummary: Layout Polish, Explicit Labels

### Task C-1: Flex TopBar (no absolute centering) with explicit label slots

**Target file**: `apps/worldview-web/components/shell/TopBar.tsx`

**Changes**:
1. Remove `absolute left-1/2 -translate-x-1/2` on IndexTicker container; restructure into flex row:
   `[logo + search]   [IndexTicker — flex-1, max-width clamp]   [UtcClock | MarketStatusPill | Portfolio block | Bell | Avatar]`
2. Portfolio block — three labeled values with explicit `min-w` slots and `whitespace-nowrap`:
   ```
   PORT   $1.2M
   Day P&L  +$3.4K
   Total P&L  +$45.6K
   ```
3. Rename `Daily` → `Day P&L`, `Unrlzd` → `Total P&L`. Increase font-size from `text-[10px]` → `text-[11px]` to give the user the requested "more space".
4. Verify on viewport widths 1280 / 1440 / 1920 — center IndexTicker truncates if needed (it already supports overflow-hidden).

### Task C-2: PortfolioSummary value + P&L on one flex row

**Target file**: `apps/worldview-web/components/dashboard/PortfolioSummary.tsx:274-320`

**Changes**:
1. Convert the value+P&L stack into a single flex row:
   ```
   [value $X.XM (text-xl, flex-1)]   [+$Y.YK (+Z.Z%) (text-sm, right-aligned, nowrap)]
   ```
2. Both children get `whitespace-nowrap tabular-nums` so they cannot wrap into each other.
3. The `~` approximation indicator stays inline with the value.

**Validation**:
- [ ] `pnpm typecheck` — 0 errors
- [ ] Visual: at simulated `+1234.56%` the value and P&L still fit on one line at 1280px width.

---

## Wave D — Prediction Markets: Volume Fix + Content Enrichment — DONE 2026-04-28

### Task D-1: S3 list endpoint returns latest snapshot volume_24h — DONE

**Target files**:
- `services/market-data/src/market_data/infrastructure/db/repositories/prediction_market_repo.py` — `list_markets()` adds `LEFT JOIN LATERAL` (or `DISTINCT ON`) to `prediction_market_snapshots` for latest `volume_24h` and `snapshot_at`
- `services/market-data/src/market_data/api/routers/prediction_markets.py:87,157` — remove hardcoded `volume_24h=None`

**Validation**:
- [ ] market-data unit tests: list endpoint returns non-null `volume_24h` for markets with snapshots
- [ ] Live: `/v1/signals/prediction-markets?status=open` shows real volumes

### Task D-2: PredictionMarketsWidget — add Δ24h, close countdown, sparkline, category badge — DONE

**Target file**: `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx`

**Changes per market row** (within existing 2-line layout):
1. **Line 1 (title row)**: append `[macro]` / `[politics]` / `[sports]` chip — derived client-side from existing `ECON_KEYWORDS`-style sets.
2. **Line 2 (data row)**: add `Δ +5.2pp` (24h change) — fetched via the existing history endpoint (last 2 snapshots) — and replace plain close-time with `closes today` / `closes in 3d` countdown.
3. **Optional sparkline (right-aligned, 60px)**: 7-day yes-probability trend using a tiny SVG sparkline (no library — inline path commands).

**Validation**:
- [ ] Live: prediction rows show 24h Δ, real volume, close countdown, sparkline
- [ ] Frontend tests: snapshot of widget with sample data

---

## Wave E — Dashboard Layout Reorganisation

### Task E-1: Drop PortfolioGainersLosers; restructure Row 2 + Row 3

**Target file**: `apps/worldview-web/app/(app)/dashboard/page.tsx`

**New layout**:
| Row | Cells |
|-----|-------|
| Row 1 | MorningBriefCard (col-12) |
| Row 2 | MarketSnapshot (col-3) · SectorHeatmap (col-4 — now treemap) · WatchlistMovers (col-5) |
| Row 3 | PortfolioSummary (col-4) · PredictionMarkets (col-4) · TopMovers (col-4) |
| Row 4 | EconCalendar (col-3) · Earnings (col-3) · PortfolioNews (col-3) · RecentAlerts (col-3) |

**Rationale** (matches user request "move predictions there instead"):
- PortfolioGainersLosers deleted (its data is duplicated in PortfolioSummary's holdings table).
- WatchlistMovers replaces PreMarketMovers in Row 2 col-5 (wider — better for showing absolute prices).
- PredictionMarkets moves to Row 3 col-4 (where PortfolioGainersLosers was).
- TopMovers (now sector-filterable, see F-2) takes the remaining Row 3 col-4.

### Task E-2: Implement WatchlistMoversWidget

**Target file**: `apps/worldview-web/components/dashboard/WatchlistMoversWidget.tsx` (new)

Implementation per PLAN-0047 Wave A. Reuses `getWatchlists()`, `getWatchlistMembers(id)`, `getBatchQuotes(ids)`, with sector filter pills (Task F-2).

### Task E-3: Delete PortfolioGainersLosers component

Remove the file and its import from `dashboard/page.tsx`.

**Validation**:
- [ ] `pnpm typecheck` clean
- [ ] `pnpm test` (no test imports the deleted component)
- [ ] Live: dashboard renders 4-row layout per spec; no orphan widgets

---

## Wave F — Sector Heatmap Treemap + Top Movers Sector Filter

### Task F-1: Replace SectorHeatmapWidget 2-column list with CSS flex treemap

**Target file**: `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx`

**Changes**:
1. Replace `<SectorRow compact />` list with a flex-wrap container of `<button>` tiles.
2. Tile width: proportional to `Math.max(0.05, abs(change_pct) / sumOfAbsChange)`.
3. Tile fill color: `bg-positive/N` or `bg-negative/N` where N scales with magnitude.
4. Each tile shows `{abbreviation}\n{+1.23%}`.
5. Click tile → opens shadcn `<Popover>` with the top 3 movers in that sector (filtered from `getTopMovers('all', 50)` by `companyOverview.sector === tile.name`).

### Task F-2: WatchlistMovers + TopMovers sector filter pills

**Target files**: `apps/worldview-web/components/dashboard/WatchlistMoversWidget.tsx`, `apps/worldview-web/components/dashboard/PreMarketMoversWidget.tsx` (rename to TopMoversWidget post-restructure)

**Changes**: Add a horizontal scrollable sector pill row at top of widget (`All`, `Tech`, `Health`, `Financials`, ...). Selecting filters client-side via `companyOverview.sector`. Default `All`.

**Validation**:
- [ ] Live: clicking sector pill in TopMovers filters the rows
- [ ] Live: clicking a treemap tile opens popover with sector top movers

---

## Validation Gates Summary

| Gate | Wave |
|------|------|
| rag-chat unit tests | A |
| Frontend typecheck | A, B, C, D, E, F |
| Frontend unit tests | A, B, C, D, E, F |
| alert unit tests | B |
| market-data unit tests | D |
| Live: brief shows 1-paragraph summary + 3 story chips collapsed | A |
| Live: alerts show ticker + signal_label, click opens sheet | B |
| Live: TopBar values do not overlap; labels read "Day P&L" / "Total P&L" | C |
| Live: prediction volumes non-null; Δ24h + countdown visible | D |
| Live: dashboard reflects 4-row Phase-3 layout | E |
| Live: sector treemap visible; click → top movers popover | F |

---

## Task Status

| Task | Status |
|------|--------|
| A-1: MORNING_BRIEFING prompt v2.2 (summary + details) | pending |
| A-2: BriefingResponse adds summary + top_stories | pending |
| A-3: MorningBriefCard two-tier render + Top Stories strip | pending |
| B-1: Alert payload enrichment (entity_name, ticker, signal_label) | pending |
| B-2: Simplify RecentAlerts + AlertsList rendering | pending |
| B-3: AlertDetailSheet on `/alerts?selected={id}` | pending |
| C-1: TopBar flex layout + Day P&L / Total P&L labels | pending |
| C-2: PortfolioSummary value+P&L flex row | pending |
| D-1: S3 list endpoint returns volume_24h via JOIN | pending |
| D-2: PredictionMarkets — Δ24h + countdown + sparkline + category | pending |
| E-1: Dashboard 4-row Phase-3 layout | pending |
| E-2: WatchlistMoversWidget implementation | pending |
| E-3: Delete PortfolioGainersLosers | pending |
| F-1: SectorHeatmap CSS-flex treemap + popover | pending |
| F-2: TopMovers sector filter pills | pending |

---

## Open Questions

- Sparkline (D-2): inline SVG vs. tiny chart library? Recommend inline SVG (no dependency cost).
- Brief summary length cap: hard 240 chars or soft "1-2 sentences"? Recommend soft via prompt + a 280-char fence in code.
- Alert detail sheet: include source-article preview? If so, add S6 doc-link field; defer if it requires a new endpoint — sheet without article preview is still a strict improvement.
