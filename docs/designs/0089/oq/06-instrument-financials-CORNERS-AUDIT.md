# W3 (Instrument Financials) — Corners Audit

**Date**: 2026-05-21
**Auditor**: Claude (revise-prd skill)
**Target design doc**: `docs/designs/0089/06-instrument-financials.md` (506 lines)
**Status of the design doc**: design-proposal iter-2; supersedes PLAN-0090 T-C-01..C-03 (shipped 2026-05-19).
**Overall verdict**: NEEDS REVISION — design has a clear ASCII wireframe at §4 and a detailed numerical visual spec at §6, but **6 corners conflict with already-shipped F1/F2/W1/W2 contracts** and **2 backend/wave-ordering issues are blocking**. None of the 39 corners below are show-stoppers; all are fixable by amending the design doc or splitting one corner into a Wave F dependency.

---

## Design clarity check (the user explicitly asked)

| Item | Status | Notes |
|---|---|---|
| ASCII wireframe at 1440×900 | ✅ PRESENT (§4 lines 137–202) | The full left-column + 240px sidebar wireframe is rendered; placement of FUNDAMENTALS SNAPSHOT → INCOME → EARNINGS → PEER → INSIDER → INSTITUTIONAL is unambiguous. |
| Numerical visual spec | ✅ PRESENT (§6) | Every spacing/typography value pinned (8 rows × 6 cells × 18px). Cell-by-cell color rules in §6.4. |
| Density math (above-fold cell count) | ✅ PRESENT (§4.2) | 172 cells target vs. 80 minimum — math shown. |
| Sidebar composition (240×900) | ✅ PRESENT (§5.2) | 7 panels stacked vertically with px heights summing to 768/840 (70px buffer). |
| Layout grid description | ✅ PRESENT (§4.1) | `grid grid-cols-6 gap-x-3 gap-y-0`; sticky scroll behaviour described. |
| Component inventory + line budgets | ✅ PRESENT (§5.1) | 9 new components with file paths + line budgets + props. |
| Loading / Error / Empty states | ✅ PRESENT (§7.4) | All 3 states defined per block. |
| Hotkey table | ✅ PRESENT (§7.1) — **BUT see C-W1-04 (conflict with InstrumentTabs)** |
| Per-cell color rules for 40 grid cells | ✅ PRESENT (§6.4) | One-row-per-section table with formatter + color class per cell. |

**Bottom line on clarity**: the design is the most concretely visualised of the six wave docs so far. The wireframe survives diff (pure ASCII) and the math is checkable. **No new sketches / diagrams are needed** — the corners below are about consistency with the foundation work, not legibility.

---

## Category A — F1 (design system) conflicts

| # | Corner | Where in design | Where in F1 | Severity | Fix |
|---|--------|----------------|-------------|----------|-----|
| C-F1-01 | Design proposes `<div data-table-grid>` only implicitly via "6-col grid" wording, not as an opt-in attribute | §4.1 | F1 §16.3 + arch test `data-table-grid-scope.test.ts`: Financials FlatMetricsGrid + Peer Comparison are 2 of the 7 v1 surfaces that MUST wear the wrapper | BLOCKING | Add explicit `<div data-table-grid="dense">` on `DenseMetricsGrid` root (drives `--row-h: 18px` + `--cell-px: 6px`); set `data-table-grid` (default 20px) on Peer / Insider / Institutional tables. |
| C-F1-02 | Design introduces a **new** `DenseMetricCell` component because "existing MetricCell has h-[22px] hardcoded" | §5.1 + §10 Q-6 | F1 already ships `components/primitives/MetricCell.tsx` (10px label / 11px value / **no hardcoded height**). The h-[22px] is in the **legacy duplicate** at `components/instrument/financials/MetricCell.tsx` which Wave 3 is about to obsolete | BLOCKING | Don't create a third MetricCell. Reuse F1 primitive; row height comes from `data-table-grid="dense"` parent (sets `--row-h: 18px`). Delete legacy `components/instrument/financials/MetricCell.tsx` (after Wave 3 migration). |
| C-F1-03 | Design introduces a **new** `Sparkline` at `components/instrument/shared/Sparkline.tsx` for IncomeStatementTable trend column | §5.1 row 4 + §10 Q-6 | F1 already shipped `components/primitives/Sparkline.tsx` (40×16, trend="auto"/"positive"/"negative"/"flat", aria-label, 3-state tinted per FU-5.6) | BLOCKING | Reuse F1 Sparkline. Income table trend column passes `data={values}` `width={40}` `height={12}` (height override supported, default 16). Beat/miss sparkline in sidebar reuses the same primitive. |
| C-F1-04 | Design hardcodes `gap-x-3` (12px) between metric cells, `py-0 px-2` (8px) on table cells | §6.2 | F1 token: `--cell-px: 6px` (auto-applied by `data-table-grid` to `[role="cell"]`) | IMPORTANT | Drop explicit `px-2` on table cells — once the parent wears `data-table-grid`, the rule fires automatically. Snapshot grid is NOT a role-based table (it's CSS grid), so `gap-x-3` on the grid is fine; only the per-cell padding is owned by F1. |
| C-F1-05 | Design proposes section accent colors `border-l-2 border-{section}` with conceptual hues (blue-900, emerald-900, etc.) | §6.4 footnote | F1 bans new palette colors (off-palette arch test) | RESOLVED IN-DOC | Design's own footnote (§6.4 last paragraph) already says implementation MUST use `border-l-2 border-border` for all sections. Promote the footnote to a §6.4 lead line so the implementor reads it before the conceptual table. |
| C-F1-06 | Design uses `h-[18px]` on **every** financials surface (snapshot grid, income table, peer table, insider table, institutional table) | §6.2 | F1: 18px is "hyper-dense" (Screener / Tx ledger). Default `data-table-grid` row = **20px**. Income statement, peer table, holders tables are not hyper-dense. | IMPORTANT | Use `data-table-grid="dense"` (18px) on the Snapshot grid only. Income / Peer / Insider / Institutional get the default `data-table-grid` (20px). Preserves above-fold count (snapshot is the largest block) while keeping the F1 contract honest. |
| C-F1-07 | Design proposes `text-[9px]` for metric cell labels (down 1px from MetricCell's 10px) | §6.1 | F1 typography scale: labels = 10px. 9px is below the floor. | IMPORTANT | Keep labels at 10px (F1 default). The space savings claimed (1px × 8 rows = 8px) is dwarfed by the dense grid's 18px row gain. |
| C-F1-08 | Design wants a `font-mono text-[18px]` hero on the 12-MO TARGET sidebar value | §6.1 row "Sidebar target price value" | DISCUSS-3 lock: **14px hero for page-primary values**. The 12-MO TARGET is a sidebar value, not page-primary, but 18px is louder than the portfolio total (14px) | IMPORTANT | Drop to 14px to honor the locked hero scale. The W2 hero is 14px for the portfolio total — Financials sidebar shouldn't out-shout it. |

**Subtotal F1 conflicts**: 8 (2 blocking, 5 important, 1 self-resolved).

---

## Category B — F2 (entity ID unification) conflicts

| # | Corner | Where in design | Where in F2 | Severity | Fix |
|---|--------|----------------|-------------|----------|-----|
| C-F2-01 | Design separates `instrument_id` (FinancialsTab prop) and `entity_id` (briefings) and warns about the distinction in FinancialsTab.tsx comment | §5.3 ("WHY instrument_id not entity_id") | F2 lock: KG `canonical_entities.entity_id` for tradable securities EQUALS `instruments.id` (DISCUSS-2). One UUID. Comment is now stale. | IMPORTANT | Remove the entity_id/instrument_id distinction note from `FinancialsTab.tsx` comment block during Wave 3. The AI brief panel can be called with the same UUID it received as `instrumentId`. |
| C-F2-02 | Design's peer-table row click: "navigate to that ticker's Financials tab" (§7.3) — no URL shape locked | §7.3 | F2 lock: URLs by ticker `/instruments/{TICKER}`. Multi-class via dot (e.g. `/instruments/BRK.B`). | IMPORTANT | Specify the navigation contract: peer row click → `router.push('/instruments/' + peer.ticker)`. Use the F2 TickerLink primitive if it survived Wave 2 (it should — W2 §4.10). |
| C-F2-03 | Design `/v1/briefings/instrument/{entity_id}` cache key uses `:user_id` suffix per current code | §8 | DISCUSS-7 lock: **drop `:{user_id}`** from public-instrument cache key (Wave E ships this). The brief is per-instrument, not per-user. | BLOCKING | The S8 cache-key change is part of this wave's backend dependencies. Add to §3.5 backend deps. AIBriefPanel staleTime (30s) needs to account for the new cache invalidation behaviour. |

**Subtotal F2 conflicts**: 3 (1 blocking, 2 important).

---

## Category C — W1 (global shell) conflicts

| # | Corner | Where in design | Where in W1 | Severity | Fix |
|---|--------|----------------|-------------|----------|-----|
| C-W1-01 | Design's TopBar is annotated "32px — ticker • price • change • freshness" — sounds like a page-local mini-bar, not the W1 global TopBar | §4 line 142 | W1 TopBar (17 slots, 32px) is global — owns ticker/price/change as part of the instrument-page contextual slot | IMPORTANT | Clarify in §4 that the 32px row is the **W1 global TopBar in its instrument context** (slots already populated by W1). Wave 3 does NOT re-implement a TopBar. |
| C-W1-02 | Design adds a separate "Tab strip (28px) [Quote] [Financials*] [Intelligence]" row directly below TopBar | §4 line 143 | This tab strip is **page-scoped** (`InstrumentTabs.tsx` already shipped at PLAN-0090 T-A-04) — not a W1 surface. No conflict with W1 itself. | NICE | Confirm in design that the InstrumentTabs strip stays — Wave 3 only swaps tab contents. |
| C-W1-03 | Design wants the AI brief panel always visible on the Financials tab + on the Intelligence tab (dedup) | §7.3 + §8.1 dedup note | W1 ships a global brief surface; per-tab brief on Financials sidebar = duplicate render of the same cache | NICE | Acceptable — both consume the same TanStack key (`qk.briefings.instrument(id)`), so it's free. Mention dedup explicitly in §8.1 (already mentioned at line 386). |
| C-W1-04 | **HOTKEY CONFLICT**: design hotkey `q` (§7.1) = toggle Annual/Quarterly on income statement | `InstrumentTabs.tsx:31` ships `q`/`f`/`i` as the tab-switch chord (quote/financials/intelligence). `q` already takes the user away from Financials. | BLOCKING | Re-map the toggle to a non-conflicting chord. Suggest `Shift+Q` (annual) / `Shift+P` (quarterly) or single-letter `p` (period). Per F1 hotkey discipline, single-letter alphas are reserved for global navigation; modifiers for in-tab actions. |
| C-W1-05 | Design hotkey `1`–`5`: jump to section | `InstrumentTabs.tsx` may already register `1`/`2`/`3` for tab-by-index (verify) | IMPORTANT | If `1`–`3` are tab chords, scope the section-jump to `Alt+1..5` or use anchor links. Verify InstrumentTabs implementation before locking. |
| C-W1-06 | Design's "freshness" annotation on the TopBar is implied but no DataFreshnessPill placement specified | §4 line 142 | F1 ships `DataFreshnessPill` primitive | NICE | Specify in §4.1 whether the freshness pill is in the TopBar (W1) or page-local (next to the 12-MO TARGET sidebar value, for the target's `updated_at`). Recommend latter — caller's freshness, not global. |

**Subtotal W1 conflicts**: 6 (1 blocking, 2 important, 3 nice).

---

## Category D — W2 (portfolio overview) conflicts

| # | Corner | Where in design | Where in W2 | Severity | Fix |
|---|--------|----------------|-------------|----------|-----|
| C-W2-01 | Design peer row click → "navigate to that ticker's Financials tab" — collides with W2's TickerLink that navigates to `/instruments/{TICKER}` (Quote tab default) | §7.3 | W2 §4.10: TickerLink renders `<Link href={'/instruments/' + ticker}>` (no `?tab=financials`) | NICE | Pick a side: (a) peer click goes to default tab (Quote — consistent with everywhere else), or (b) peer click goes to `/instruments/{TICKER}?tab=financials` (analyst flow). Recommend (a) — user can chord `f` to switch tabs after landing. |
| C-W2-02 | Design's AnalystSidebar panel ordering vs W2's BrokerageStatusBanner placement — not in conflict but worth noting both panels touch the right rail | n/a | n/a | NICE | Confirm Financials sidebar is page-scoped (right rail of Financials tab only) — does NOT bleed into Portfolio Overview right rail. |

**Subtotal W2 conflicts**: 2 (0 blocking, 0 important, 2 nice).

---

## Category E — Backend / wave ordering issues

| # | Corner | Where in design | Where in code/decisions | Severity | Fix |
|---|--------|----------------|------------------------|----------|-----|
| C-BE-01 | Design assumes `/v1/fundamentals/{id}/institutional-holders` and `/v1/fundamentals/{id}/fund-holders` are exposed by S9 | §3.2 + §8 | **S9 does NOT expose either endpoint today.** S3 (market-data) has them at `services/market-data/src/market_data/api/routers/fundamentals.py`, but no S9 proxy passthrough exists. `git grep` for `/institutional-holders` in `services/api-gateway` returns zero matches. | BLOCKING | Add S9 proxy work to this wave: 2 new routes in `services/api-gateway/src/api_gateway/routes/market.py` (`/institutional-holders`, `/fund-holders`). Inventory line 608 explicitly calls this out as a follow-up. ~30 LOC + 2 tests. Add to §3.5 backend deps. |
| C-BE-02 | Design assumes peer endpoint `/v1/instruments/{id}/peers?n=5` (open Q-1) is a Wave 3 dep | §3.5, §10 Q-1 | Decisions §G assigns `/instruments/{id}/peers` (part of B-Q-1..4) to **Wave F** (Instrument Quote). Wave 3 = Wave E (Financials) currently runs before Wave F. | BLOCKING | Either: (a) **promote `/peers` from Wave F to Wave E** (this wave) — it's needed here more than on Quote, ~30 LOC S9 + S3; or (b) defer PeerComparisonTable to Wave F. Recommend (a) — peer comparison is a §1 user-intent task ("Compare to 5 peers"), not a nice-to-have. |
| C-BE-03 | Design assumes `/v1/fundamentals/{id}/analyst-targets-by-firm` exists (open Q-2) | §5.2 row TargetsByAnalystPanel | No such endpoint in S3 or S9. EODHD exposes individual firm targets in `AnalystRatings.*` but they're not extracted today. | IMPORTANT | Either: (a) defer the TargetsByAnalystPanel to v1.1 + replace with "10 firms — pending data source" placeholder, or (b) add a single S3 worker pass to write `analyst_targets_by_firm` as part of the fundamentals fetch (~80 LOC). Recommend (a) — backend churn is steep for one sidebar panel. |
| C-BE-04 | Design's RevisionsPanel needs 30-day history of `analyst_consensus` snapshots (open Q-3) | §5.2 row RevisionsPanel | S3 keeps only the latest analyst-consensus record. No historical retention. | IMPORTANT | Defer RevisionsPanel content to v1.1. v1 Sidebar shows "↑ 12 upgrades / ↓ 3 downgrades / ↑ 8 target raises" with `—` placeholders until S3 ships history retention (parallel to `earnings_trend`). Mark panel with `(coming soon)` badge or replace with a sparkline of consensus_avg over time. |
| C-BE-05 | Design's "Sidebar AI brief: 'Brief generating… check back in 30s' + auto-refetch on 30s interval" — implies lazy-generate flow | §7.4 | DISCUSS-7 ships `POST /v1/briefings/instrument/{id}/generate` lazy pair (Wave E). The `GET` returns cached; the `POST /generate` triggers. The 30s auto-refetch flow needs to call `POST /generate` once on 404, then poll `GET`. | BLOCKING | Add the explicit call sequence to §7.4: (1) `GET /briefings/instrument/{id}` → if 404, (2) `POST /briefings/instrument/{id}/generate`, (3) poll `GET` every 30s up to 5 attempts, (4) abandon to "Brief unavailable" empty state. |
| C-BE-06 | Design's `EarningsBarChart` "add EPS surprise % chip per bar" reads from `earnings-annual-trend.surprise_percent` | §3.2 last row + §8.2 | The current `earnings_annual` records expose `surprise_percent` only if S3 backfilled it. Verify presence in the live API response before assuming. | NICE | Add a runtime guard: if `surprise_percent` is null on all 5 bars, hide the chip column rather than render 5× "—". |

**Subtotal backend issues**: 6 (3 blocking, 2 important, 1 nice).

---

## Category F — Genuinely new edges (not foundation conflicts)

| # | Corner | Severity | Fix |
|---|--------|----------|-----|
| C-NEW-01 | Design proposes a **new** `useFinancialsTabData` hook extension to fetch insider/institutional/peers/brief. Current hook fetches 6 sub-resources; adding 4 more puts it past comfortable limits. | IMPORTANT | Split into 2 hooks: keep `useFinancialsTabData` for the 6 main fetches; add `useFinancialsSidebarData` for the 4 sidebar fetches. Both share TanStack cache. |
| C-NEW-02 | Design's `qk.instruments.insiderTxns(id)` is a **new** query key — but `qk.instruments.ownership(id)` already exists and is used by `InstrumentPageClient.tsx:139` to seed page-bundle insider data | BLOCKING | Use the existing `qk.instruments.ownership(id)` key (reuses page-bundle seed). Do NOT add `insiderTxns`. |
| C-NEW-03 | Design row "SHRT SHRS / SHRT RATIO / SHRT %" is rendered as a 9th sub-row but the snapshot is described as 8 rows × 6 cells | §6.4 row 9 has note "sub-row of 8" | NICE | Clarify §6.4: either combine SHRT fields into row 7 (OWNERSHIP) as additional cells, or accept 9 rows (162px instead of 144px). Recommend combine — row 7 currently uses 4 of 6 cells; add SHRT SHRS / SHRT R / SHRT % as cells 5/6/7 (overflow to row 9 only if needed). |
| C-NEW-04 | Design proposes hiding INT COVERAGE / CREDIT RATING — but the current code at `FlatMetricsGrid.tsx:454,485` reads `snapshot?.interest_coverage` and `snapshot?.credit_rating` as actual fields | IMPORTANT | Migration: delete those two cells in the new `DenseMetricsGrid` component (don't pass them through). Keep `interest_coverage` and `credit_rating` on the `FundamentalsSnapshot` type — backfill workers may light them up later. |
| C-NEW-05 | Design has `SHARES OUT / FLOAT / %INSID / %INST` in row 7 — `percent_insiders` and `percent_institutions` fields are PascalCase in the actual S9 response (`PercentInsiders`, `PercentInstitutions`) per the prior chart-fix session (memory entry "PascalCase field paths") | BLOCKING | Use the PascalCase paths. `shareStats.percent_insiders` (snake_case in TS types) was wrong before and got fixed; ensure new DenseMetricsGrid uses the right shape (check current FlatMetricsGrid path — it already uses `shareStats?.PercentInsiders` likely). |
| C-NEW-06 | Design's 4-FY income statement table — current `IncomeStatementTable.tsx:103` comment says "ANNUAL only: quarterly columns (12+ narrow cells) would overflow 1fr." | §5.1 row IncomeStatementTable: "+ periodType: ANNUAL | QUARTERLY" | IMPORTANT | The quarterly toggle is non-trivial (column count goes 5→8, layout reflow). Either commit to refactoring the grid to handle both, or defer to v1.1 ("Annual only in v1, Quarterly button visible but disabled with tooltip"). |
| C-NEW-07 | Design's BeatMissHistoryPanel sparkline of 8 quarters — but `earnings-annual-trend` is annual, not quarterly. The 8-bar quarterly history would need `/v1/fundamentals/{id}/earnings-trend` (quarterly endpoint) | §5.2 row BeatMissHistoryPanel | IMPORTANT | Use `earnings-trend` (quarterly, last 8q) not `earnings-annual-trend`. Confirm S9 proxy exists (`market.py:297`). |
| C-NEW-08 | Design's "click → modal with full history of that holder/insider" (§7.2) — no modal component currently exists for that purpose | §7.2 | NICE | Defer modal to v1.1; for v1, "View all" link navigates to a dedicated page `/instruments/{TICKER}/insiders` (stub route). |
| C-NEW-09 | Design's `c` hotkey expands Company snapshot description; `c` is currently unbound on the Financials tab but it MIGHT be in use globally (W1 search etc.) | §7.1 | IMPORTANT | Verify against W1 global hotkey table; if `c` conflicts, switch to `d` (description) or `Shift+C`. |
| C-NEW-10 | Design's `e` hotkey expands AI brief — same potential conflict with global "expand chat" or similar | §7.1 | IMPORTANT | Same as C-NEW-09. Verify against W1 hotkey registry. |
| C-NEW-11 | Design proposes **Esc** to close any overlay — needs a stack-aware overlay manager that doesn't exist yet | §7.1 | NICE | Use shadcn Dialog's built-in Esc behaviour (already wired). Add a sentence to §7.1: "Esc behaviour delegated to shadcn Dialog component." |
| C-NEW-12 | Design's "self-row in peer table: bg-muted/30" (§6.3) — needs to identify which row is "self" | §6.3 | NICE | Trivial: row.instrumentId === currentInstrumentId → apply class. Mention in §5.1 PeerComparisonTable props. |
| C-NEW-13 | Design tells implementor to "compute 1Y return client-side from `/v1/ohlcv/batch`" for peer comparison (open Q-7) | §10 Q-7 | IMPORTANT | Specify the calculation: `(close[last] / close[first]) - 1`; gate on `bars.length >= 252` (1 trading year) else render `—`. Confirm `/v1/ohlcv/batch` supports multi-instrument fetch (`market.py:586` — yes, POST endpoint exists). |
| C-NEW-14 | Design `IncomeStatementTable` adds sparkline trend column — but each row needs 4-FY+TTM values to compute trend, which is the same data already in the table cells | §4 line 167 | NICE | Confirm sparkline data source: `values = [FY22, FY23, FY24, FY25, TTM]` per row → F1 Sparkline `trend="auto"`. No extra fetch. |
| C-NEW-15 | Design proposes "Bull/Bear/Risk" formatted bullets in AIBriefPanel — but `BriefingResponse.sections[0].bullets` is a list of dicts whose shape varies by prompt | §5.2 + §3.2 + §6.1 row AI brief bullet | IMPORTANT | Pin the AIBriefPanel render contract: render `bullets[0..2]` as `{bullet.text}` with `{bullet.kind || ''}` prefix (kind ∈ {bull, bear, risk}). If kind missing, render unprefixed. Defer the proposed prompt rewrite (open Q-5) — out of scope for Wave 3. |
| C-NEW-16 | Design "FullTimeEmployees" — EODHD field; verify it's surfaced in the S9 fundamentals response | §3.2 row | NICE | `git grep FullTimeEmployees` — confirm present on the fundamentals JSON path. |
| C-NEW-17 | Design "AddressData.City/Country" — nested EODHD shape | §3.2 row | NICE | Confirm S9 `getFundamentals(id)` response carries `General.AddressData` nested object; if S9 flattens it, adjust the CompanySnapshotPanel field path. |
| C-NEW-18 | Design has no Playwright e2e plan — only §11 acceptance checklist mentions "Playwright above-the-fold screenshot diff (manual review)" | §11 | IMPORTANT | Add 4 Playwright e2e tests: (1) snapshot grid renders 40+ cells; (2) sidebar renders 7 panels with non-empty content for AAPL; (3) peer table renders 5+1 rows; (4) `q`/`p` hotkey toggles annual/quarterly. |
| C-NEW-19 | Design's `formatVolume` for SHRT SHRS row — `lib/utils.ts` already has formatVolume for OHLCV daily volume; check it handles share-count units (raw shares, not bar volume) | §6.4 row 9 | NICE | Reuse `formatMarketCap` for share counts (it handles M/B units cleanly); reserve `formatVolume` for traded-volume contexts. |
| C-NEW-20 | Design 64px earnings chart height (was 80px) | §5.1 EarningsBarChart row | NICE | Trivial change — verify the chart's internal SVG viewBox scales (it currently uses `h-[80px]` Skeleton at FlatMetricsGrid line 100). |
| C-NEW-21 | Design "self-fetch" pattern for IncomeStatementTable + EarningsBarChart (no props) — but Wave 3 also adds peer / insider / institutional tables that the design says should self-fetch via `enabled: false` cache lookup pattern | §5.3 | IMPORTANT | The `enabled: false` pattern only works if the parent fired the fetch first. PeerComparisonTable etc. are NEW components — the parent (`FinancialsTab`) must fire those queries OR the child must use `enabled: !!instrumentId`. Pick the latter — simpler, no parent coordination. |
| C-NEW-22 | Design "n/a not —" for non-applicable metrics (ETF with no dividend) | §6.5 | NICE | Pin which metrics auto-render `n/a` for ETF/index instruments — add a check on `instrument.kind` field (post-F2 unified discriminator). |

**Subtotal genuinely new edges**: 22 (2 blocking, 8 important, 12 nice).

---

## Summary tallies

| Severity | Count |
|----------|------:|
| BLOCKING | **8** |
| IMPORTANT | **17** |
| NICE | **14** |
| **Total** | **39** |

| Source of conflict | Count |
|--------------------|------:|
| F1 (design system) | 8 |
| F2 (entity ID) | 3 |
| W1 (global shell) | 6 |
| W2 (portfolio) | 2 |
| Backend / wave ordering | 6 |
| Genuinely new edges | 22 (but 8 of those flow from foundation context) |

---

## Recommendation

Two options:

**Option A — patch the design doc first** (1–2 hours): apply the 8 blocking corners as in-place edits to `docs/designs/0089/06-instrument-financials.md`. Then write the Wave 3 plan with the (now-clean) design as the source of truth.

**Option B — bake corners directly into the Wave 3 plan** (~1 hour, no design edit): write `docs/plans/0089-pages/W3-instrument-financials-plan.md` with the 8 blocking corners pre-resolved in the file-by-file change set, plus a §0 "Design deltas from `06-instrument-financials.md`" section that lists the 8 corners and how they were resolved. This mirrors how W1 and W2 were handled (the design docs were not patched; the plans absorbed the corners).

**Recommend Option B** — design doc is iter-2 already, and patching it twice creates drift. The plan absorbs design + audit + locked decisions in one file the executor reads.

---

## What's clear, what's not (final design clarity verdict)

**Clear**:
- Layout, density, sidebar composition, per-cell formatting, hotkey list, file inventory.
- The ASCII wireframe is the most useful artefact in the whole 0089 design corpus.

**Not yet clear (covered by corners above)**:
- Which row height applies where (C-F1-01, C-F1-06).
- Whether to reuse F1 MetricCell + Sparkline or fork (C-F1-02, C-F1-03).
- The full backend dependency list — design names 7 endpoints, code has 5 (C-BE-01, C-BE-02, C-BE-03, C-BE-04).
- Hotkey scoping (C-W1-04, C-NEW-09, C-NEW-10).
- Quarterly toggle scope (C-NEW-06).

After resolving the 8 blocking corners, the design will be implementation-ready.
