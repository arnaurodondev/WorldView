# W5 (Instrument Quote — density) — Corners Audit

**Date**: 2026-05-21
**Auditor**: Claude (revise-prd skill)
**Target design doc**: `docs/designs/0089/05-instrument-quote.md` (562 lines)
**Status of the design doc**: in-discovery iteration on top of PLAN-0090 baseline (shipped 2026-05-20).
**Sibling foundation**: F1 (design system) / F2 (entity ID) / W1 (global shell) / W2 (portfolio) / W3 (Financials sidebar — audit done, not yet shipped).
**Overall verdict**: NEEDS REVISION — wireframe is the clearest and most actionable of the 0089 page docs, but **9 corners are BLOCKING** (foundation conflicts + 4 missing backend endpoints + 2 references to components that don't exist). 19 IMPORTANT corners. 16 NICE.

---

## Design clarity check (the user explicitly asked)

| Item | Status | Notes |
|---|---|---|
| ASCII wireframe at 1440×900 | ✅ PRESENT (§4.1 lines 137–185) | Two-column wireframe with sticky header + brief banner + tab strip + chart/strips left + 8-card right rail. Most legible of the 6 wave docs. |
| Numerical visual spec | ✅ PRESENT (§6) | Every spacing, typography, and row dimension pinned. |
| Grid description | ✅ PRESENT (§4.2) | CSS Grid (not flex), 7-row left × vertical-stack right; per-row track heights enumerated. |
| Density math | ✅ PRESENT (§4.3) | ~113 cells above-fold target (2.2× the 50-cell minimum). |
| Component inventory (modify + new) | ✅ PRESENT (§5.1, §5.2) | 5 modified + 11 new, each with file path + line budget + props. |
| Re-use map | ✅ PRESENT (§5.3) | Which existing primitive each new component leans on. |
| Per-surface loading/error/empty states | ✅ PRESENT (§7.4) | All 10 surfaces have all 3 states defined. |
| Hotkey table | ✅ PRESENT (§7.1) — **see C-W1-04** |
| Open questions enumerated | ✅ PRESENT (§10) | 7 open questions, all flagged. |

**Bottom line on clarity**: this is the strongest design doc in the 0089 corpus. The 9 blocking corners are mechanical fixes (rename, backend endpoint coordination, F1 token alignment). No structural rework needed.

---

## Category A — F1 (design system) conflicts

| # | Corner | Where in design | Where in F1 | Severity | Fix |
|---|--------|----------------|-------------|----------|-----|
| C-F1-01 | Design proposes `MetricGrid4Col` with `90px × 22px` cells (§6.4) and "22px row height" (§4.2) | F1: default `data-table-grid` row = **20px**; hyper-dense = 18px. 22px is legacy. | BLOCKING | Cells should be `90px × var(--row-h)` (default 20px). Parent wears `<div data-table-grid>`. Drop the hardcoded 22 references. |
| C-F1-02 | Design uses `text-[9px]` for MetricGrid labels and insider/news secondary text (§6.2) | F1 typography floor: 10px. 9px reserved for tertiary tags only (per W3 C-F1-07). | IMPORTANT | Keep labels at 10px. 9px only for the section-accent tag column (one micro-pill per group), not body labels. |
| C-F1-03 | Design says "rounded-[2px] max — keep" for panels (§6.5) | F1 lock (DISCUSS-3 + DISCUSS-11): **rounded=0 globally**. No exceptions. Architecture test `no-rounded` will fail any `rounded-*`. | BLOCKING | Drop the 2px allowance. All panel corners hard square. |
| C-F1-04 | Design doesn't declare `data-table-grid` opt-in on the metric grid + strips | F1 §16.3 + arch test: the 7 v1 surfaces wear `data-table-grid`. Financials/Quote/Holdings/Screener/Watchlist/Workspace/PeerComparison — Quote's `MetricGrid4Col` qualifies. | BLOCKING | Add `<div data-table-grid>` on `MetricGrid4Col` root; for the insider/earnings/news 18px lists wear `data-table-grid="dense"`. Drop the explicit `border-r border-border/30` between columns — `data-table-grid` supplies it. |
| C-F1-05 | Design uses `border-border/30` for inner column dividers (§6.1) | F1 token: `--border-subtle` (#1E1E22). The `/30` opacity may not match. | IMPORTANT | Replace with `border-[hsl(var(--border-subtle))]` (or rely on `data-table-grid`'s built-in `border-right` rule for `[role="cell"]`). |
| C-F1-06 | Design proposes `border-b border-border/50` between right-rail cards (§6.1) | F1: section dividers = hairline `border-t border-border-subtle` (FU-5.8 lock). `/50` opacity is one-off. | IMPORTANT | Switch to `border-t border-border-subtle` (matches F1 group divider). |
| C-F1-07 | Design uses `text-foreground/80` and `text-muted-foreground/60` opacity tweaks for narrative body text (§6.2) | F1: opacity tweaks are allowed but only for "absent data" `/50`, `/40`. Body narrative should be `text-foreground` straight. | NICE | Use straight `text-foreground` for the brief preview and about narrative — match Bloomberg DES which uses solid body weight, not 80%. |
| C-F1-08 | Existing `MetricRow.tsx:18-19` still hardcodes `h-[22px]` and that's where the design's "22px row" claim comes from | F1 should have flipped this to 20px in the F1 row-height purge (PR-F). | IMPORTANT | If F1's PR-F hasn't yet flipped MetricRow → `h-[20px]`, do it as part of W5's first commit. Don't bake new 22-row code on top of legacy 22. |
| C-F1-09 | Design mentions "no animation, no `transition`" (§6.5) but the existing `AiBriefBanner.tsx:95` already has `transition-[transform]` on the chevron | F1 ships `animation-policy` arch test banning `animate-*` and most `transition-*`. The chevron is a directional indicator — verify the policy's exact rules. | NICE | Add chevron animation to allowlist OR drop the transition (Bloomberg-grade caret instant flip is fine). |

**Subtotal F1 conflicts**: 9 (3 blocking, 4 important, 2 nice).

---

## Category B — F2 (entity ID unification) conflicts

| # | Corner | Where in design | Where in F2 | Severity | Fix |
|---|--------|----------------|-------------|----------|-----|
| C-F2-01 | Peer row click: `router.push("/instruments/" + peer.entity_id)` (§7.3, §5.2 PeersStrip props) | F2 lock (DISCUSS-2): URLs by **TICKER**, not entity_id. `/instruments/{TICKER}` (e.g. `/instruments/AAPL`), multi-class via dot. | BLOCKING | `router.push("/instruments/" + peer.ticker)`. Use F2 `TickerLink` primitive if it shipped — `git grep TickerLink apps/worldview-web/components/`. |
| C-F2-02 | `AiBriefBanner` props take `entityId` and the design preserves the distinction throughout (§5.1, §5.2 RelatedHeadlinesList) | Post-F2: `instrument_id` = `entity_id` for tradable securities (DISCUSS-2). The distinction is dead. | IMPORTANT | Components can take `instrumentId` everywhere; brief endpoint still uses the same UUID. Update the prop names to `instrumentId` for consistency with sibling waves; document the rename in the W5 plan. |
| C-F2-03 | Design's `getInstrumentBrief(entityId)` cache key has `:user_id` suffix per current code (`AiBriefBanner.tsx:64`) | DISCUSS-7 lock: **drop `:user_id`** from public-instrument cache key. Wave E (Financials) backend dep. | BLOCKING | The W5 backend dep list (B-Q-5) must include the DISCUSS-7 cache-key change AND coordinate with W3 — whichever ships first owns it. |

**Subtotal F2 conflicts**: 3 (2 blocking, 1 important).

---

## Category C — W1 (global shell) conflicts

| # | Corner | Where in design | Where in W1 | Severity | Fix |
|---|--------|----------------|-------------|----------|-----|
| C-W1-01 | Design's "STICKY HEADER 36px (existing InstrumentHeader)" (§4.1 line 139) | W1's global TopBar is 32px (not 36); the instrument page header sits BELOW the W1 TopBar | IMPORTANT | Clarify: row 139 is the **page-local** InstrumentHeader (under the W1 TopBar). Currently `InstrumentHeader.tsx` is 36px-ish — verify it doesn't conflict with W1's contextual slots. Wave 5 may need to shave it to 28px to give the brief banner + tabs room. |
| C-W1-02 | Design hotkey `B` toggles brief expand (§7.1) | W2 plan uses `B` for "Buy" action on portfolio rows (per W2 §5 hotkeys). Scope is page-local in W2, but a quote-tab `B` may conflict if the user lands on /instruments/AAPL via portfolio drill-down (no shared scope guard between pages). | IMPORTANT | Verify: page-scoped hotkeys are reset on route change. If yes, no conflict. If not, switch quote-tab `B` to `Shift+B` or repurpose. Document the scope guard in the plan. |
| C-W1-03 | Design hotkey `P` focuses Peers strip (§7.1) | W3 hotkey `p` toggles Annual/Quarterly on income statement (Δ12) — page-scoped to Financials. No conflict on Quote tab. | NICE | Already isolated by tab scope. Confirm in plan. |
| C-W1-04 | Design hotkey `1`/`5`/`30` → chart timeframe ("already exists") | Code check: `OHLCVChart.tsx:108` only registers `Escape` (fullscreen exit). **Numeric chord is NOT bound today.** | BLOCKING | The "already exists" claim is false. Either (a) ship the numeric chord as part of W5, or (b) drop the claim from the design doc. Recommend (a) — 1D/5D/30D timeframe hotkey is high-utility. |
| C-W1-05 | Design hotkey `Shift+R` refetches Quote tab data (§7.1) | F1 / W1 don't reserve `Shift+R` globally. No conflict. | NICE | Confirm in plan. |
| C-W1-06 | Design's `AiBriefBanner` v2 is rewritten to use lazy generation (§5.1 + §9.3) | W3 (Financials) is doing the same lazy-generate flow (Δ19 in W3 plan §0). Whichever wave ships first owns the `useInstrumentBrief` hook. | BLOCKING | Cross-wave coordination: W3 plan (just written) defines `useInstrumentBrief(id)` at `components/instrument/hooks/useInstrumentBrief.ts`. W5 must reuse this hook, not duplicate it. If W3 ships after W5, the hook moves from W3 plan to W5 plan; pick a winner. Recommend: W5 ships the hook (Quote tab is the primary surface; Financials sidebar reuses it). |

**Subtotal W1 conflicts**: 6 (2 blocking, 2 important, 2 nice).

---

## Category D — W2 / W3 cross-wave conflicts

| # | Corner | Where in design | Where in sibling wave | Severity | Fix |
|---|--------|----------------|----------------------|----------|-----|
| C-CX-01 | Design B-Q-1 ships `/v1/instruments/{id}/peers?limit=5` | W3 audit promoted `/peers` from W5 to W3 (Δ16 in W3 plan). W3 is currently planned to ship the endpoint. | BLOCKING | Pick a wave to own `/peers`: either W3 ships it and W5 consumes, OR W5 ships it and W3 defers PeerComparisonTable. Recommend: **W5 owns it** because design discovery for peers is more developed here (§5.2 PeersStrip + open Q-2 ranking criteria). Update W3 plan to consume, not produce. |
| C-CX-02 | Design's `MetricsTable` refactor splits into `MetricGrid4Col` blocks + mini-cards; W4 (deferred) deletes the legacy `MetricRow` | §5.4 says "deferred to plan W4" but PRD-0089 doesn't have a W4 — the wave list is A/B/C/D/E/F/G/H… | IMPORTANT | Replace "W4" reference with the actual wave name (probably "v1.1" or "Wave G — Intelligence cleanup"). Or just delete the legacy code in this wave to avoid the dangling reference. |
| C-CX-03 | Design's `WhatsMovingStrip` reads `bundle.top_news` (5 articles) for the top 3 | W2 (Portfolio Overview) also reads `bundle.top_news` for the activity strip | NICE | No conflict — same key, different render. Confirm staleTime alignment (5 min in design §8.2). |
| C-CX-04 | Design's "EarningsMiniList" (last 4 quarters, EPS actual/est/surprise) reads `getEarningsHistory` (ANNUAL records per `lib/api/instruments.ts:465`) | W3 plan §0 Δ25 says the EarningsMiniList sparkline (sidebar variant) uses **quarterly** `/earnings-trend`. | IMPORTANT | The W5 design implies quarterly but the existing endpoint returns annual. Decide: (a) use annual (rename to "Recent Annual Earnings") or (b) add quarterly endpoint (which W3 already calls out — B-Q-? in W3 §3?). Recommend (a) for W5 (less backend work; consistent with the existing API), with a v1.1 follow-up to add quarterly. |
| C-CX-05 | Design refers to `ArticleDetailModal` (existing component) for headline click (§7.3) | `find apps/worldview-web -name "ArticleDetailModal*"` → **0 matches**. Component does not exist. | BLOCKING | Either: (a) ship `ArticleDetailModal` as part of W5, or (b) navigate to a dedicated article page route (`/news/{article_id}`). Recommend (b) — modal is a v1.1 enhancement; route works now. |
| C-CX-06 | Design references `<DataFreshnessTooltip>` at `components/instrument/DataFreshnessTooltip.tsx` (§7.2) | `find` returns **0 matches**. Component does not exist. F1 ships `DataFreshnessPill` and `FreshnessDot` primitives. | BLOCKING | Use F1 `DataFreshnessPill` (or a new lightweight `<Tooltip>` wrapper). Drop the DataFreshnessTooltip reference. |
| C-CX-07 | Design's PeersStrip "5 peer instruments × {P/E, mkt cap, 1Y return}" overlaps W3's PeerComparisonTable (5 peers × 9 cols) | W3 PeerComparisonTable is below-fold on Financials tab; W5 PeersStrip is below-fold on Quote tab. Same data, different layouts. | IMPORTANT | Reuse `qk.instruments.peers(id)` across both. Both consume the same query; W5 renders 3 columns of peers, W3 renders 9. No backend duplication. |

**Subtotal cross-wave conflicts**: 7 (3 blocking, 3 important, 1 nice).

---

## Category E — Backend / endpoint reality check

| # | Corner | Where in design | Where in code | Severity | Fix |
|---|--------|----------------|---------------|----------|-----|
| C-BE-01 | **B-Q-1**: `/v1/instruments/{id}/peers?limit=5` | Does NOT exist (`git grep` returns zero on api-gateway and market-data). Already noted in W3 audit. | BLOCKING | Ship in this wave (see C-CX-01). ~30 LOC S9 + ~60 LOC S2/S3. |
| C-BE-02 | **B-Q-2**: `/v1/fundamentals/{id}/intraday-stats` (VWAP/ATR/RSI/GAP/PREM/SI Δ) | Does NOT exist. ATR/RSI are computed client-side today (`FlatMetricsGrid.tsx:269-281`). VWAP / gap / premarket high-low / short-interest delta NOT computed anywhere. | BLOCKING | Ship as S9 wrapper (~80 LOC) that composes OHLCV bars + technicals_snapshot section. Add field-by-field formulas in plan §3. |
| C-BE-03 | **B-Q-3**: `/v1/fundamentals/{id}/multi-period-returns` | Does NOT exist. | BLOCKING | Ship as S9 wrapper (~50 LOC) reading from existing OHLCV bars (close-on-close returns over 7 anchor periods). Add anchor-date math in plan §3. |
| C-BE-04 | **B-Q-4**: `/v1/fundamentals/{id}/price-levels` | Does NOT exist. | BLOCKING | Ship as S9 wrapper (~60 LOC) computing classic floor pivots from prior-day OHLCV. Open Q-3 (Camarilla deferred) handled in plan §12 out-of-scope. |
| C-BE-05 | **B-Q-5**: `/v1/briefings/instrument/{id}?lazy=true` variant | DISCUSS-7 lock locks `POST /v1/briefings/instrument/{id}/generate` (not `?lazy=true` query param). The Wave E (Financials) backend list already includes this. | IMPORTANT | Align with DISCUSS-7: the lazy contract is POST `/generate` + GET poll, NOT `?lazy=true`. Update design wording. |
| C-BE-06 | Design's `intradayStats` staleTime = 60s (§8.2) | If B-Q-2 returns ATR/VWAP from prior-bar OHLCV, the 60s staleTime is mismatched (data only refreshes when a new bar prints, every 1min or 5min). | NICE | Set staleTime to match the underlying bar resolution. For 1D bars: 5min staleTime; for live mid-day, ~60s OK. |
| C-BE-07 | Design's "open Q-1: sentiment_score on RankedArticle" | Code: `RankedArticle.sentiment: "positive" \| "negative" \| "neutral" \| "mixed" \| null` (categorical). No score. | IMPORTANT | Resolve open Q-1: use the categorical `sentiment` directly (5 colour buckets). Drop expectation of a numeric score. |

**Subtotal backend issues**: 7 (4 blocking, 2 important, 1 nice).

---

## Category F — Genuinely new edges

| # | Corner | Severity | Fix |
|---|--------|----------|-----|
| C-NEW-01 | Design's "fixed 380px right rail with 1280px breakpoint → 320px" needs a media query | IMPORTANT | Plan must specify the Tailwind breakpoint: `lg:w-[320px] xl:w-[380px]`. |
| C-NEW-02 | Design's CSS Grid (not flex) is a structural rewrite of `QuoteTab.tsx` (188 lines today) | IMPORTANT | Plan must include a single commit that flips flex → grid before any new components land — avoids cascading layout bugs. |
| C-NEW-03 | Design's L6 (CompanyAboutCard, 110px) sits between the strips and the bottom triple — currently the chart fills that space | IMPORTANT | Plan: explicitly shrink chart min-height from 440px (current) to 320px in T-XX BEFORE adding the about card; document the rationale. |
| C-NEW-04 | Design's `WhatsMovingStrip` uses `entityId` prop (§5.2) — but post-F2 it's `instrumentId` | IMPORTANT | Rename to `instrumentId` per C-F2-02. |
| C-NEW-05 | Design's `RelatedHeadlinesList` re-uses `getEntityNews(entity_id)` — that endpoint is `/v1/news/entity/{entity_id}` and post-F2 still uses entity_id internally | NICE | Keep the prop name as it is — F2 renames at the URL layer, not the internal KG layer. Document in plan §4. |
| C-NEW-06 | Design's `PeersStrip` truncates tickers at 5 chars; some tickers (BRK.B, BF.B) are 5+ chars with dot | IMPORTANT | Set `min-w-[60px]` (W2 already allowed 5–6 char tickers). |
| C-NEW-07 | Design's "MetricGrid4Col cell 90px × 22px" math: 4 × 90 = 360, + 20px padding = 380px rail — but if rail is 380, the inner padding eats the cell width | IMPORTANT | Either rail = 400px (4×90 + 8px×2 borders + 24px padding) or cells = 84px each (4×84 + 8 + 24 = 368). Lock the math. |
| C-NEW-08 | Design's BottomTripleStrip (132px tall, 3 columns × 132px) — the wireframe shows 5 peers + 7 levels + 3 news, but 132px ÷ 18px = 7 rows max | NICE | Wireframe checked: peers 5 rows, levels 7 rows, news 3 rows. All fit within 132 / 18 = 7. Confirmed. |
| C-NEW-09 | Design's "ABOUT" card (§4.1 line 167) shows `Apple designs, manufactures, and markets…` — but `Instrument.description` may be null for ETFs and indices | IMPORTANT | Empty state per §7.4: render only name + exchange + "Description not available" muted. Plan must test against an ETF (SPY) AND a single-stock (AAPL). |
| C-NEW-10 | Design's "Founded: 1976" — verify `General.Founded` exists in EODHD response and S9 surfaces it | NICE | `git grep -i "founded"` against EODHD fundamentals client; if missing, drop the founded line. |
| C-NEW-11 | Design's `MetricGrid4Col.cells: Array<{label, value, color}>` (§5.2) — 8 cells per block × 3 blocks = 24 cells; but the design wireframe only shows 12 cells (4×3 in valuation block + 4×1 in margins) | IMPORTANT | Reconcile: §4.3 claims 12 cells visible in the Statistics grid. §5.2 props say 8 cells × 3 blocks = 24. Pick one: 4-col × 6-row × 24 cells, OR 4-col × 3-row × 12 cells. Recommend the former — matches Finviz density. |
| C-NEW-12 | Design hotkey `Shift+R` invalidates `qk.instruments.detail(id)` — but the cache hierarchy `qk.instruments.detail.id.<sub>` requires the cascade to be set up correctly | IMPORTANT | Verify `qk.instruments.detail(id)` matches all sub-keys (peers/intradayStats/multiPeriodReturns/priceLevels). If not, the cascade fails silently. Test in U-XX. |
| C-NEW-13 | Design proposes `pre-fetch peer's page-bundle on hover` (§7.2) — N=5 peers × ~50KB = 250KB just on hover-intent | NICE | Throttle: only prefetch on `pointerenter` with a 200ms delay (i.e. only if the user actually hovers, not for grazing). |
| C-NEW-14 | Design says `MetricsTable` is "refactored, not removed — preserving the 198-line component" + "Once the grid version is verified, the single-column row variant is deleted (deferred to plan W4)" | IMPORTANT | This is a feature-flag pattern with no flag defined. Either ship the grid + delete legacy in one wave (recommended — no flag), or define the env flag in plan §3. |
| C-NEW-15 | Design's "tab content edge inset: 0" (§6.1) is currently `p-3` on QuoteTab root | IMPORTANT | Document the strip in plan: this is the visible "no-gaps" win the user asked for. |
| C-NEW-16 | Design Vitest density gate: "≥ 52 cells above-fold" — but the design target is 113 | NICE | Lock the test threshold at 80 (matches W3 acceptance). 52 is the minimum; 80 is the target floor for "Bloomberg-grade". |
| C-NEW-17 | Design Playwright e2e: not enumerated in §11 | IMPORTANT | Add 4 e2e tests in plan §6.2: (a) AAPL 52+ cells, (b) peer row click → /instruments/MSFT, (c) `Shift+R` refetches, (d) brief banner lazy-generate flow. |
| C-NEW-18 | Design's Brief banner timeline "5 min poll then collapse to BRIEF unavailable" — but the lazy-generate flow is also rate-limited per open Q-5 | NICE | Plan §4: document the rate-limit fallback. If 429 hit, render "BRIEF quota exceeded — retry in N min" muted. |
| C-NEW-19 | Design's "tab strip 28px (existing InstrumentTabs)" — current InstrumentTabs.tsx height not verified | NICE | `grep h- apps/worldview-web/components/instrument/tabs/InstrumentTabs.tsx`. If not 28, add one-line fix. |

**Subtotal genuinely new edges**: 19 (0 blocking, 11 important, 8 nice).

---

## Summary tallies

| Severity | Count |
|----------|------:|
| BLOCKING | **9** |
| IMPORTANT | **20** |
| NICE | **15** |
| **Total** | **44** |

| Source of conflict | Count |
|--------------------|------:|
| F1 (design system) | 9 |
| F2 (entity ID) | 3 |
| W1 (global shell) | 6 |
| W2 / W3 cross-wave | 7 |
| Backend / endpoint reality | 7 |
| Genuinely new edges | 19 (8 indirectly flow from foundations) |

---

## Recommendation

Same pattern as W3 — **Option B**: write `docs/plans/0089-pages/W5-instrument-quote-plan.md` with the 9 blocking + 20 important corners baked into a §0 deltas table, plus the file-by-file change set. Don't patch the design doc twice.

**Cross-wave coordination required before either wave starts**:

1. Pick an owner for `/peers` endpoint (C-CX-01). Recommend W5 owns; W3 consumes.
2. Pick an owner for `useInstrumentBrief(id)` hook + lazy-generate flow (C-W1-06). Recommend W5 owns; W3 consumes.
3. Confirm DISCUSS-7 lazy contract is `POST /generate` + GET poll, NOT `?lazy=true` (C-BE-05). Update design doc B-Q-5 wording in passing.

After those 3 coordination points, W5 can plan and ship in parallel with W3.

---

## What's clear, what's not (final design clarity verdict)

**Clear**:
- ASCII wireframe with row/column tracks and 7-row left grid + 13-row right rail.
- Per-surface loading/error/empty states (most rigorous in the corpus).
- Open questions explicitly listed — the design author was thoughtful.
- Competitor research with citations (Bloomberg DES, TradingView, Finviz, Stockanalysis, Koyfin, Yahoo Pro).

**Not yet clear (covered by corners above)**:
- Whether `MetricGrid4Col` has 8 or 12 cells per block (C-NEW-11).
- Cell width math vs rail width (C-NEW-07).
- Lazy brief endpoint contract (C-BE-05 — DISCUSS-7 lock vs design wording).
- Which wave owns `/peers` (C-CX-01).
- ArticleDetailModal + DataFreshnessTooltip don't exist (C-CX-05, C-CX-06).
- 1/5/30 chart hotkey claim is false (C-W1-04).

After resolving the 9 blocking corners, the design will be implementation-ready.
