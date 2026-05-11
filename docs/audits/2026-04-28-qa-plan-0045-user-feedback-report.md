# QA Report: PLAN-0045 — User Feedback Audit

**Date**: 2026-04-28 22:00 UTC
**Skill**: qa
**Scope**: PLAN-0045 (`docs/plans/0045-dashboard-ux-improvements-plan.md`) + 7 user-reported issues observed in live UI
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: **FAIL** — PLAN-0045 itself completed cleanly (497 portfolio + 459 rag-chat + 418 frontend tests pass), but live inspection of the dashboard reveals 8 follow-up issues that were either not part of PLAN-0045 scope or were incompletely fixed
**Report file**: `docs/audits/2026-04-28-qa-plan-0045-user-feedback-report.md`
**Companion plan**: `docs/plans/0048-dashboard-ux-phase3-plan.md`

---

## Executive Summary

PLAN-0045 successfully shipped 11 tasks across 5 waves: brief threshold lowered from 0.3 → 0.15, severity-case fix, S1 holdings enrichment, Row 2 restructure, sector 2-column grid, TopBar portfolio NAV. All gates passed. However, the user's live-UI walkthrough on 2026-04-28 evening surfaces 8 issues that fall into three categories: (a) PLAN-0045 work that was technically complete but did not solve the underlying user complaint (alert title still cryptic, brief still has redundant headers in body, sector heatmap still feels visually weak), (b) issues outside PLAN-0045 scope that PLAN-0047 covers but is not yet implemented, and (c) net-new issues the user raised in this round (TopBar values overlap & need explicit labels, predictions widget needs more content, alert click should deep-link to that specific alert's detail). PLAN-0047 already addresses 5 of these in draft form. This report adds the missing 8 items and a fresh plan, **PLAN-0048**, that ships them along with PLAN-0047 in a single coordinated push.

---

## Multi-Agent Review Summary

Single-agent review (UI/UX investigator) — the 5-agent multi-pass was not warranted because every issue is a frontend-presentation or LLM-prompt issue with a clear root cause already identified in this conversation; spawning agents would have duplicated existing source-code analysis.

| Category | Findings | BLOCKING | CRITICAL | MAJOR | MINOR |
|----------|----------|----------|----------|-------|-------|
| Brief presentation | 3 | 0 | 1 | 2 | 0 |
| Alerts UX | 2 | 0 | 1 | 1 | 0 |
| TopBar layout | 2 | 0 | 0 | 2 | 0 |
| Dashboard composition | 3 | 0 | 0 | 3 | 0 |
| Predictions content | 1 | 0 | 0 | 1 | 0 |
| Sector heatmap | 1 | 0 | 0 | 1 | 0 |
| **Total** | **12** | **0** | **2** | **10** | **0** |

---

## Test Execution Results

Per-layer execution was skipped intentionally — PLAN-0045 ran the full test suite at commit time and all gates passed. The follow-up issues identified here are all design/data issues that don't change behavior at the unit-test layer.

| Layer | Status | Note |
|-------|--------|------|
| PLAN-0045 unit/contract/typecheck | PASS | Recorded in PLAN-0045 commit (455e93a) |
| Live UI walkthrough | FAIL | 8 follow-up issues identified |

---

## Issues — Full Investigation

### Issue F-001: Recent Alerts still show "SIGNAL" / "LOW SIGNAL" with no entity context (CRITICAL)

#### Summary
After PLAN-0045 B-1 normalised severity case, the dashboard `RecentAlerts` widget still renders rows as bare `LOW SIGNAL alert` / `MEDIUM SIGNAL alert`. The fallback chain in `RecentAlerts.tsx:77-99` tries `payload.message`, then `signal_label + entity_name`, then `title`, then bottoms out at `${severity} ${alert_type} alert`. Live inspection confirms the bottom fallback fires for every row.

#### Severity / Confidence
**Severity**: CRITICAL — primary intelligence widget is non-actionable
**Confidence**: HIGH
**Flagged by**: User (live UI), source-code trace

#### Root Cause Analysis
- **What**: `services/alert/src/alert/application/use_cases/alert_fanout.py:339` stores `payload=dict(event)` — the raw Kafka event from `nlp.signal.detected.v1`. That schema (`infra/kafka/schemas/nlp.signal.detected.v1.avsc`) contains `claim_id`, `claim_type`, `polarity`, `extraction_confidence`, `market_impact_score`, `subject_entity_id` — but **no `entity_name`, no `ticker`, no `signal_label`, no `message`**. The frontend fallback chain therefore never finds a usable string.
- **Why**: Signal alerts were designed for routing/dedup, not display. No one added a display-rendering enrichment step.
- **When**: Always, for every SIGNAL-typed alert.
- **Where**: Boundary between S6 (signal emission) and S10 (alert fanout). Either side can enrich.
- **History**: BP-263 (PLAN-0045) tried to address this by chaining payload fallbacks; it was a partial fix because the keys it tries don't exist in the payload.

#### Evidence
- `infra/kafka/schemas/nlp.signal.detected.v1.avsc` (full schema, no display fields)
- `services/alert/src/alert/application/use_cases/alert_fanout.py:339` — `payload=dict(event)`
- `apps/worldview-web/components/dashboard/RecentAlerts.tsx:77-99` — fallback chain that misses

#### Impact
- **Immediate**: Dashboard alert widget cannot tell traders WHICH instrument an alert refers to.
- **Blast radius**: Same issue in alerts page (AlertsList), TopBar bell tooltip, email digest summaries.
- **Data risk**: None — the underlying alert is correctly stored, only the display projection is wrong.
- **User impact**: HIGH — alerts are a primary actionable signal; trader cannot triage 10 alerts that all read "LOW SIGNAL alert".

#### Solution Options

**Option A: Backend enrichment at fanout time (RECOMMENDED)**
- Description: In `AlertFanoutUseCase`, fetch entity name + ticker from S7 KG (or cached overview) and inject `entity_name`, `ticker`, `signal_label` into the payload before persisting.
- Changes:
  - `services/alert/src/alert/application/use_cases/alert_fanout.py` — add entity-resolver port + lookup
  - `services/alert/src/alert/application/ports/` — new `EntityNameResolverPort`
  - `services/alert/src/alert/infrastructure/clients/` — implementation calling S7 `/entities/{id}` (or read from S6 KG cache)
  - `RecentAlerts.tsx` fallback chain becomes simpler (just read `payload.entity_name` + `payload.signal_label`)
- Benefits: payload is self-describing; email digest, mobile push, chat summaries all benefit; one network call per alert (cached in Valkey).
- Drawbacks: Adds a service dependency at fanout time; if S7 is down, alert is still stored but with "Unknown" name; ~50ms latency per alert.
- Effort: Medium · Risk: Low

**Option B: Frontend lazy enrichment**
- Description: Frontend collects unique `entity_id`s from alerts, calls `getEntities(ids)` in batch, and merges names client-side.
- Changes: `RecentAlerts.tsx`, `AlertsList.tsx` — both add a useQuery for entity batch lookup
- Benefits: No backend change; alerts work even if S6/S7 are degraded
- Drawbacks: Two pages do the same lookup; mobile push and email still have no name; cache miss on every dashboard load.
- Effort: Low · Risk: Low

**Option C: S6 emits the friendly name in the source event**
- Description: Modify `nlp.signal.detected.v1` to include `subject_entity_name`, `subject_ticker`, `signal_label`. Forward-compatible — add fields with defaults.
- Changes: Avro schema bump v1 → v2; S6 emitter populates new fields; S10 forwards into alert payload.
- Benefits: All consumers (alert, email, archive, replay) see the name without an extra lookup.
- Drawbacks: Schema bump touches contract tests; S6 must look up name at emission (similar latency cost as Option A).
- Effort: Medium · Risk: Medium (schema change)

#### Recommended Option
**Option A** — backend enrichment at fanout. It centralises the lookup, makes alerts self-describing for every downstream consumer (email, push), and avoids the schema-version churn of Option C.

#### Verification Steps
- [ ] After fix, `GET /v1/alerts/pending` returns payloads with `entity_name`, `ticker`, `signal_label`
- [ ] RecentAlerts renders rows like `AAPL: Bearish momentum` instead of `LOW SIGNAL alert`
- [ ] Email digest test renders the same enriched names

---

### Issue F-002: Alert click navigates to /alerts list, not the specific alert's detail (CRITICAL)

#### Summary
The user expects clicking an alert row to deep-link to that specific alert's full detail (entity, payload data, source article, related signals). Current behaviour navigates to the bare `/alerts` page, scrolling the user back to a generic list.

#### Severity / Confidence
**Severity**: CRITICAL — primary trader workflow ("triage alert → read detail → act") is broken
**Confidence**: HIGH
**Flagged by**: User

#### Root Cause Analysis
- **What**: `RecentAlerts.tsx:163-185` wraps the row in `<Link href="/alerts">`. `AlertsList.tsx:289` likewise navigates to `/instruments/${entity_id}` on click.
- **Why**: There is no per-alert detail panel/page route in the frontend. PLAN-0045 wired clickability but did not add a destination.
- **Where**: Frontend route tree at `apps/worldview-web/app/(app)/alerts/`.

#### Solution Options

**Option A: Modal/sheet over /alerts list (RECOMMENDED)**
- Click row → `/alerts?selected={alert_id}`. AlertsList opens a `<Sheet>` (shadcn) that shows full payload, source event link, related entity, ack/snooze controls. Closing returns to `/alerts`.
- Benefits: Lightweight, deep-link friendly, no new route, no new page-level data fetch (alert is already in the list).
- Drawbacks: Mobile experience needs a full-screen variant.
- Effort: Low · Risk: Low

**Option B: Dedicated /alerts/[alertId] route**
- Full page with source article preview, signal extraction, related KG context.
- Benefits: Bookmarkable, shareable
- Drawbacks: Heavier — requires its own data fetch + S9 endpoint; trader rarely needs a full page just to read one alert
- Effort: Medium · Risk: Low

**Option C: Future LLM-generated summary** (user mentioned, deferred)
- A `/alerts/{id}/summary` endpoint calling S8 to summarise the alert + linked article + entity context. Not part of this plan.

#### Recommended Option
**Option A** — modal sheet on `/alerts?selected={id}`. Matches the trader's "scan list → drill in → act" workflow without leaving the alerts hub.

---

### Issue F-003: Morning Brief body still contains redundant "Market Overview" / "Morning Market Briefing" / "Date:" headers (MAJOR)

#### Summary
Despite `stripBriefPreamble()` in `MorningBriefCard.tsx:330-339`, the user reports seeing the date, "Market Overview", "Morning Market Briefing", date again, "Market Overview" again, and "Read more" — wasting 15% of the page on chrome that says nothing.

#### Severity / Confidence
**Severity**: MAJOR — primary intelligence widget visually fails its purpose
**Confidence**: HIGH
**Flagged by**: User

#### Root Cause Analysis
- **What**: The LLM prompt (`libs/prompts/src/prompts/briefing/morning.py:16-21`) explicitly instructs the model: "Organize the briefing with these sections: 1. **Market Overview** — Sector performance... 2. **Portfolio Impact** ... 3. **Key News** ... 4. **Active Alerts & Signals**". The LLM dutifully outputs `## Market Overview` as the first heading. `stripBriefPreamble()` only strips the FIRST matching block, then leaves the second `## Market Overview` (which is actually the section header, not the preamble) in place. The card header itself shows `MORNING BRIEFING` + the timestamp, so the LLM's `Date: ...` line is also redundant.
- **Why**: Prompt template was written assuming the consumer (email) wanted explicit section headers. The dashboard widget's collapsed view doesn't.
- **Where**: `libs/prompts/src/prompts/briefing/morning.py` (prompt template) + `MorningBriefCard.tsx` (collapsed-view layout).

#### Impact
The collapsed (3-line) view wastes its three lines on date + "MARKET OVERVIEW" + opening section text. Three lines of valuable real estate hold zero useful information.

#### Solution Options

**Option A: Two-tier brief output (RECOMMENDED)**
- Description: LLM emits a two-part brief:
  1. A 1-2 sentence `summary:` block (compact paragraph capturing the most important signal of the day) — rendered in collapsed view
  2. A full `details:` markdown block with sections — rendered when expanded
  Both are returned by S8 as a structured response (or split client-side from a sentinel like `---` separator).
- Changes:
  - `libs/prompts/src/prompts/briefing/morning.py` — prompt now asks for `## SUMMARY` (1-2 sentences) + `---` + structured sections
  - `services/rag-chat/src/rag_chat/api/schemas.py` — `BriefingResponse` adds `summary: str` + keeps `narrative: str`
  - `MorningBriefCard.tsx` — collapsed = render `summary`, expanded = render `narrative`
- Benefits: Collapsed view is one tight paragraph (the user's request); expanded view keeps institutional structure; no client-side stripping fragility.
- Drawbacks: Schema change in BriefingResponse (additive; safe); prompt change requires re-eval.
- Effort: Medium · Risk: Low

**Option B: Enhanced client-side stripping**
- Description: Strip ALL `## Market Overview` headers (not just preamble), strip "Date:" anywhere. Inline first paragraph as the headline.
- Drawback: Fragile — every prompt change can break the regex; collapses sections unexpectedly when expanded.
- Effort: Low · Risk: Medium

#### Recommended Option
**Option A** — two-tier output. Cleanly separates "the headline" from "the structured content", makes the dashboard's compact mode genuinely informative.

---

### Issue F-004: Morning Brief lacks news links / citations rendered as clickable items (MAJOR)

#### Summary
User wants to "display the most important news in the briefing with a link to the article". Current brief renders entity mentions as `/instruments/{id}` links but does not render article citations as outbound links.

#### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH

#### Root Cause Analysis
S8 already returns `BriefingResponse.citations: list[Citation]` with `doc_id`, `title`, `url`. The frontend never reads them — the brief is rendered as raw markdown only. The prompt also doesn't ask the LLM to inline links to top articles in the body.

#### Recommended Solution
- Below the summary paragraph (collapsed view) and above the structured sections (expanded view), render a "Top Stories" strip showing the 3 highest-relevance citations as `<Link href={url}>` chips with title + source.
- Wave is part of PLAN-0048 A-2 below.

---

### Issue F-005: TopBar PORT / Daily / Unrlzd values overlap and labels are still cryptic (MAJOR)

#### Summary
User reports portfolio total value visually overlaps the % gain figure on dashboard widgets, and that "D" / "U" — even after the partial PLAN-0047 fix to "Daily" / "Unrlzd" — still aren't fully explicit. User wants the values to occupy more horizontal space and shift the rest of the bar leftward.

#### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH (live UI confirmed)
**Flagged by**: User

#### Root Cause Analysis
- **TopBar overlap**: `TopBar.tsx:114-117` uses `absolute left-1/2 -translate-x-1/2` to center IndexTicker. When PORT + Daily + Unrlzd all populate, the right-side block grows past the centered IndexTicker's right edge → visual collision.
- **PortfolioSummary overlap**: `PortfolioSummary.tsx:278-311` stacks `formatPrice(totalValue)` (text-xl) with the P&L row immediately below — at certain values the percentage `({+12.34%})` wraps and overlaps the value above on narrow viewports.
- **Label clarity**: PLAN-0047 partial fix changed "D" → "Daily" / "U" → "Unrlzd"; user feedback says even "Unrlzd" is jargon-heavy. Suggested: "Day P&L", "Total P&L".

#### Recommended Solution (Option A)
1. Change TopBar IndexTicker center positioning from absolute to flex with constrained width — guarantees no overlap with right block.
2. Allocate explicit min-width slots for each value (`Day P&L`, `Total P&L`) so they never reflow.
3. Rename: `Daily` → `Day P&L`, `Unrlzd` → `Total P&L` (or `Open P&L`). Keep `PORT $X.XM` as is.
4. PortfolioSummary: refactor the value/P&L block to a 2-column flex (value on left, P&L on right) so they cannot overlap regardless of value size.

---

### Issue F-006: PortfolioGainersLosers ("Portfolio Movers") delivers little value — user calls it "totally useless" (MAJOR)

#### Summary
Row 3 col-3 currently renders `PortfolioGainersLosers` which derives from cached holdings + quotes. User feedback: this widget occupies prime real estate (col-span-4, ~400px wide) but its content (3 gainers + 3 losers from already-visible PortfolioSummary) duplicates information.

#### Severity / Confidence
**Severity**: MAJOR — wastes a full quarter of Row 3
**Confidence**: HIGH

#### Root Cause Analysis
The widget was added in C-4 of an earlier plan to replace `AiSignalsWidget`. It does correctly derive top movers from cached data — but the same data is already present (with sparklines and prices) in `PortfolioSummary`'s holdings table 2 cells over. There is no incremental insight.

#### Recommended Solution
Replace `PortfolioGainersLosers` with one of:
- **Option A (RECOMMENDED)**: `WatchlistMoversWidget` from PLAN-0047 Wave A — shows the user's own watchlist, sorted by abs(change_pct). Adds genuine signal (positions they're TRACKING but don't OWN).
- **Option B**: Move `PredictionMarketsWidget` from Row 2 col-5 to Row 3 col-4, and use the freed Row 2 col-5 for an enriched MarketSnapshot (futures + commodities + dollar index).
- **Option C**: A "Today's Top Stories from your Portfolio Holdings" panel — merges news already filtered to held tickers.

User explicitly suggested Option B — moving predictions to where Portfolio Movers currently sits.

---

### Issue F-007: PredictionMarketsWidget content is thin — only Y/N% and volume (MAJOR)

#### Summary
User feedback: "Y 98%, N 2%, $0 volume — investigate what other information we could display". Predictions widget shows odds + volume only.

#### Severity / Confidence
**Severity**: MAJOR — widget occupies col-span-5 (large) but conveys minimal data
**Confidence**: HIGH

#### Root Cause Analysis
The S3 detail endpoint (`/prediction-markets/{id}`) returns `description`, `close_time`, `created_at`, plus history snapshots. The dashboard summary uses only the cheapest fields. Volume is null because of the JOIN omission (covered in PLAN-0047 Wave C).

#### Recommended Additional Fields
1. **Movement vs. yesterday**: Δ in yes-probability over the last 24h (requires latest two snapshots → already available in history endpoint). Render `+5.2pp` next to current odds.
2. **Volume** (PLAN-0047 Wave C JOIN fix unblocks this).
3. **Close countdown**: `closes in 3d` or `closes today` instead of just date.
4. **Mini sparkline**: 7-day yes-probability sparkline using existing snapshots — visual context for trend.
5. **Resolution category badge** (Macro/Politics/Sports) from existing S3 categorisation if available; else from client-side keyword filter.

---

### Issue F-008: SectorHeatmapWidget visual treatment too dense / non-engaging (MAJOR)

#### Summary
User: "the sector heatmap is also not very attractive, we could display it in a more visual way, maybe using a treemap or a sunburst chart". The current 2-column horizontal-bar list (PLAN-0045 D-2) is functional but not glanceable.

#### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: User

#### Root Cause Analysis
2-column bar list works but doesn't convey relative magnitude visually — every bar is normalised to ±3% so a 0.5% move and a 2.5% move look qualitatively similar. A treemap with sector size = market cap weight (or equal-weighted) and fill color = % change communicates "what is moving the market" in a single glance. PLAN-0047 Wave B already drafts this fix.

#### Recommended Solution
Implement PLAN-0047 Wave B: CSS flex treemap (avoids recharts dependency). Add user-requested enhancement: clicking a sector tile expands an inline popover showing top 3 movers IN that sector (the user's exact request: "investigate to display the top movers in each sector"). Top-mover data: filter `getTopMovers()` results client-side by sector — no backend change required because company overview already has `sector` field.

---

### Issue F-009: Top movers widget needs sector dropdown / filter (MAJOR)

Already covered by PLAN-0047 Wave E. No additional investigation; defer to PLAN-0047.

---

### Issue F-010: Portfolio total value ($) overlaps % gain on PortfolioSummary widget (MAJOR)

#### Summary
User: "the portfolio values still overlap (total value of position is over the percentage of gains)". Live inspection of `PortfolioSummary.tsx:274-320` confirms the value (text-xl) and the P&L line (text-sm with absolute + percent) stack vertically — at certain quantity / cost combinations the percentage in parentheses can exceed the cell width and wrap.

#### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH

#### Root Cause Analysis
Block layout with no min/max width constraint on the inner `<span>`. When `formatPercent` produces a long value (e.g., `+1,234.56%`) it line-wraps under the value.

#### Recommended Solution
Refactor block to a flex row: `[value (flex-1, leftmost)] [P&L abs/pct (right-aligned)]`. Both fields wear `whitespace-nowrap` and `tabular-nums` so they cannot collide.

---

### Issue F-011: Prediction widget volume always shows $0 (MAJOR — BP-264 follow-up)

#### Summary
PLAN-0045 follow-up null-guarded the display (`> 0` hides), but the underlying S3 endpoint never returns volume because it's hardcoded to `None`. PLAN-0047 Wave C fixes this. No additional work needed — implement PLAN-0047 Wave C.

---

### Issue F-012: Recent Alert future enhancement — LLM summary (deferred / not scoped now)

User explicitly deferred this: "we might want to investigate to redirect an alert information to a model to generate a summary, this could be in the future, not now". Captured for PRD intake; not part of PLAN-0048.

---

## Recommendations

Implement **PLAN-0048** (created in this session at `docs/plans/0048-dashboard-ux-phase3-plan.md`) which:

1. **Wave A (Brief redesign)** — splits brief output into `summary` + `narrative`; renders compact paragraph in collapsed view + structured sections in expanded; integrates citation links as a "Top Stories" strip.
2. **Wave B (Alert UX)** — backend payload enrichment (entity_name + ticker + signal_label) + frontend deep-link sheet on `/alerts?selected={id}` with full alert detail.
3. **Wave C (TopBar + PortfolioSummary layout)** — flex-based TopBar that cannot overlap, explicit "Day P&L" / "Total P&L" labels, value/P&L flex-row in PortfolioSummary.
4. **Wave D (Prediction enrichment)** — Δ24h move, close countdown, sparkline, resolution category.
5. **Wave E (Row 3 reorganisation)** — drop PortfolioGainersLosers; move PredictionMarkets to Row 3 col-4; place WatchlistMovers (PLAN-0047 A) in the freed Row 2 col-5; restructure freed Row 2 col-3 with enriched MarketSnapshot.
6. **Wave F (Sector heatmap as treemap with click-to-drill)** — implements PLAN-0047 Wave B + adds sector → top-movers popover.

PLAN-0047's Wave A (WatchlistMovers), Wave C (S3 volume JOIN), Wave D (alert enrichment) and Wave E (sector filter) are absorbed into PLAN-0048 to ship as one coordinated change set.

---

## Compounding Updates

- **BP-266** (new bug pattern, will be added to `docs/BUG_PATTERNS.md` during PLAN-0048 implementation): _Alert payload field assumptions_. The frontend must not assume any field exists in `payload` beyond what the source Avro schema guarantees. Always trace fallback chains against the actual source schema.
- **HR-pattern (new heuristic, `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`)**: _LLM prompt-driven section headers in dashboard widgets_. Whenever a prompt instructs the LLM to emit Markdown sections, the widget that consumes it must either (a) accept those sections in expanded view OR (b) request a separate compact form from the LLM. Client-side stripping of LLM section headers is fragile and a smell.
