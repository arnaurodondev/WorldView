# W3 — Instrument Financials Sidebar Restoration — Plan

**PRD**: 0089 platform page redesign
**Design**: `docs/designs/0089/06-instrument-financials.md` (iter-2, 506 lines)
**Audit**: `docs/designs/0089/oq/06-instrument-financials-CORNERS-AUDIT.md` (39 corners)
**Sibling foundation**: F1 (design system, shipped) / F2 (entity ID, shipped) / W1 (global shell, shipped) / W2 (portfolio overview, shipped) / W5 (Quote tab, shipped 2026-05-21)
**Status**: ready-to-execute (W5 amendment applied — see §3 note below)
**Estimated**: 6–7 engineer-days
**Branch**: `feat/plan-0089-w3` (off the W2/W5 integration head)

---

## §0. Design deltas from `06-instrument-financials.md` (post-audit)

The design doc remains the source of truth for the **what** (layout, density, fields, panels). The 8 BLOCKING + 19 IMPORTANT corners from the audit are resolved in-plan below. Nice-to-have corners (14) are deferred to v1.1 or absorbed into individual step descriptions.

| # | Corner | Design says | Plan locks |
|---|--------|-------------|------------|
| Δ1 | C-F1-01 | "6-col grid" wording | Snapshot grid root wears `<div data-table-grid="dense">` → 18px rows + 6px cell padding from CSS tokens. Peer / Insider / Institutional tables wear plain `data-table-grid` (20px). Income table stays 20px. |
| Δ2 | C-F1-02 | New `DenseMetricCell` | **Reuse F1 `components/primitives/MetricCell.tsx`**. Row height comes from parent `data-table-grid` variant via `--row-h`. **Delete** legacy `components/instrument/financials/MetricCell.tsx` after migration (T-09 sub-step). |
| Δ3 | C-F1-03 | New `components/instrument/shared/Sparkline.tsx` | **Reuse F1 `components/primitives/Sparkline.tsx`**. Pass `width={40} height={12} trend="auto"` for income-table column; `width={120} height={20}` for sidebar beat/miss panel. |
| Δ4 | C-F1-04 | `px-2` (8px) on table cells | Drop `px-2`; `data-table-grid` parent supplies 6px via `--cell-px`. |
| Δ5 | C-F1-06 | `h-[18px]` everywhere | 18px ONLY on snapshot grid (dense variant). Income/Peer/Insider/Institutional tables = 20px (default). Sidebar panels = no fixed row height (free flow). |
| Δ6 | C-F1-07 | `text-[9px]` labels | Keep F1 default `text-[10px]` for metric cell labels. 9px reserved for tertiary tags only. |
| Δ7 | C-F1-08 | `text-[18px]` 12-MO TARGET hero | Drop to `text-[14px]` (DISCUSS-3 hero scale lock). Mono tabular-nums. |
| Δ8 | C-F2-01 | "entity_id vs instrument_id" warning comment in FinancialsTab | Remove the comment block at FinancialsTab.tsx lines 53–57. Post-F2 they are the same UUID. AI brief panel receives the same `instrumentId` prop. |
| Δ9 | C-F2-02 | "navigate to that ticker's Financials tab" | Peer row click → `router.push('/instruments/' + peer.ticker)` (Quote tab, default). User chord `f` to switch tabs after landing. Use F2 TickerLink primitive (already shipped at `components/instruments/TickerLink.tsx` per F2 plan). |
| Δ10 | C-F2-03 | `/v1/briefings/instrument/{entity_id}` cache key `:user_id` suffix | DISCUSS-7 ships `POST /v1/briefings/instrument/{id}/generate` lazy pair + drops `:user_id` from key. AIBriefPanel uses GET→404→POST→poll sequence (see §0 Δ16). Backend dep included in §3. |
| Δ11 | C-W1-01 | "TopBar (32px) — ticker • price • change • freshness" | The 32px row IS the W1 global TopBar (already contextually populated). Wave 3 does not re-implement a TopBar. Wireframe annotation updated in §0 only. |
| Δ12 | C-W1-04 | `q` hotkey toggles Annual/Quarterly | **Collision with `InstrumentTabs.tsx:31` `q`→Quote tab.** Re-map: `p`/`P` toggles period (Annual ⇄ Quarterly). Add to InstrumentTabs hotkey scope guard. |
| Δ13 | C-W1-05 | `1`–`5` jump to section | `1`/`2`/`3` may already be tab-index chords on InstrumentTabs. Use `Alt+1..5` for section jump (verify against InstrumentTabs.tsx; if `1-3` are unused as numeric tab chords, downgrade to bare `1`–`5`). |
| Δ14 | C-W1-06 | Freshness pill not placed | Freshness pill (F1 `DataFreshnessPill`) sits next to the 12-MO TARGET value (caller's freshness, `updated_at` from fundamentals). Not global. |
| Δ15 | C-BE-01 | `/institutional-holders` and `/fund-holders` "exposed by S9" | **FALSE** — S3 has them, S9 does NOT proxy. Add 2 S9 routes in this wave (T-S9). |
| Δ16 | C-BE-02 | `/v1/instruments/{id}/peers` (open Q-1) "in Wave F" | **Promote to Wave 3**. PeerComparisonTable is a §1 user-intent surface; cannot defer. Add S2/S3 route + S9 passthrough (T-S2-peers + T-S9). |
| Δ17 | C-BE-03 | `/analyst-targets-by-firm` (open Q-2) | **Defer panel content to v1.1**. v1 sidebar renders `TargetsByAnalystPanel` with single consensus row + "Per-firm targets pending data source" placeholder. Panel shell still ships. |
| Δ18 | C-BE-04 | RevisionsPanel 30-day delta (open Q-3) | **Defer content to v1.1**. v1 panel renders `—` placeholders + "Revisions history pending" footnote. Panel shell still ships. |
| Δ19 | C-BE-05 | "Brief generating… check back in 30s" | Specify GET→404→POST `/generate`→poll GET every 30s up to 5 attempts→fallback empty state. Encapsulate in `useInstrumentBrief(id)` hook. |
| Δ20 | C-NEW-01 | `useFinancialsTabData` extended with 4 more fetches | Split: keep `useFinancialsTabData` (6 fetches); add `useFinancialsSidebarData` (4 fetches: insider/institutional/fundHolders/peers) + `useInstrumentBrief` (1 fetch + lazy POST). |
| Δ21 | C-NEW-02 | New `qk.instruments.insiderTxns(id)` | **Use existing** `qk.instruments.ownership(id)` (page-bundle seeds it at `InstrumentPageClient.tsx:139`). Insider table reads from this key. |
| Δ22 | C-NEW-04 | Hide INT COVERAGE / CREDIT RATING | New `DenseMetricsGrid` does NOT pass these fields. Snapshot type retained on backend — workers may backfill. |
| Δ23 | C-NEW-05 | `percent_insiders` / `percent_institutions` snake_case | Use PascalCase `PercentInsiders` / `PercentInstitutions` paths (S9 returns EODHD-verbatim per prior chart-fix session). |
| Δ24 | C-NEW-06 | Quarterly toggle on Income statement | v1 ships Annual + Quarterly. Refactor `IncomeStatementTable` to support both periodTypes (column count goes 5→8). |
| Δ25 | C-NEW-07 | BeatMissHistoryPanel 8-quarter sparkline | Uses `/v1/fundamentals/{id}/earnings-trend` (quarterly), NOT `earnings-annual-trend` (annual). Confirmed proxy at `market.py:297`. |
| Δ26 | C-NEW-09/10 | `c` / `e` hotkeys (expand company snapshot / AI brief) | Verify against W1 hotkey registry before final landing. If conflict, switch to `d` (description) / `b` (brief). |
| Δ27 | C-NEW-13 | 1Y return for peer table | `(close[last] / close[first]) - 1`. Gate on `bars.length >= 252`. Use `POST /v1/ohlcv/batch` with the 5 peer instrument_ids (single round-trip). |
| Δ28 | C-NEW-15 | AI brief bullet rendering contract | Render `bullets[0..2]` as `{bullet.kind?.toUpperCase()}: {bullet.text}` if `kind ∈ {bull, bear, risk}`; else `{bullet.text}` unprefixed. Defer prompt rewrite (open Q-5) to v1.1. |
| Δ29 | C-NEW-18 | Playwright e2e plan | 4 e2e tests added — see §6.2. |
| Δ30 | C-NEW-21 | Self-fetch via `enabled: false` for new tables | New tables use `enabled: !!instrumentId` (own fetch trigger). No parent coordination required. |

**Deferred to v1.1** (NICE corners not absorbed): C-NEW-08 (full-history modal → use stub page route), C-NEW-12 (peer self-row highlight detail), C-NEW-19 (formatVolume vs formatMarketCap audit), C-NEW-22 (n/a vs — discriminator), C-W2-01/02 (peer click target tab), C-BE-06 (surprise_percent runtime guard — non-blocking).

---

## §1. Bloomberg-grade resemblance checks (acceptance gate)

After this wave lands, the page MUST:

1. Above-fold cell count ≥ 80 on 1440×900 (target: 172).
2. Sidebar empty space ≤ 100px (target: ~70px buffer only).
3. Snapshot grid renders 40 cells (6 cols × 8 rows minus 8 empty placeholder slots).
4. No cell renders `—` for INT COVERAGE / CREDIT RATING / DAY RETURN / RSI(14) / ATR(14) (those are gone from the grid; RSI/ATR moved to Quote tab).
5. AI brief panel renders ≥ 3 bullets (or graceful empty state).
6. Company snapshot panel renders SECTOR + INDUSTRY + EMPLOYEES + HQ + 4-line DESCRIPTION.
7. Insider transactions table renders ≥ 8 rows or empty state.
8. Institutional holders table renders ≥ 10 rows or empty state.
9. Fund holders table renders ≥ 10 rows or empty state.
10. Peer comparison renders self + 5 peers × 9 columns.
11. Income statement supports Annual + Quarterly toggle via `p` chord.
12. EarningsBarChart shows EPS surprise % chip per bar.
13. Snapshot grid wears `data-table-grid="dense"`; tables wear `data-table-grid` (default).
14. All metric cell labels at `text-[10px]` (F1 default).
15. 12-MO TARGET hero at `text-[14px]` (DISCUSS-3 lock).
16. Sparkline column on income table = F1 primitive (no fork).
17. MetricCell = F1 primitive (no fork; legacy financials/MetricCell.tsx deleted).
18. Peer row click → `/instruments/{TICKER}` (F2 ticker URLs).
19. AI brief uses lazy-generate flow (GET→POST `/generate`→poll).
20. Arch tests pass: `no-off-palette-colors`, `data-table-grid-scope`, `animation-policy`, `empty-copy-dictionary`.
21. Vitest density test: `expect(visibleCells).toBeGreaterThanOrEqual(80)`.
22. 4 Playwright e2e tests pass.
23. No new query keys duplicate existing ones (`qk.instruments.ownership` reused, not forked).
24. No legacy `MetricCell` import path remains in `components/instrument/financials/`.
25. Sidebar timestamp / freshness uses `DataFreshnessPill` (F1 primitive), not a one-off `<span>`.

---

## §2. Pre-flight (verify before writing any code)

1. `git log --oneline -25` — confirm F1, F2 commits present. Look for `plan-0089-f1`, `plan-0089-f2`. W1/W2 should be present too if their branches merged.
2. `rg "MetricCell" apps/worldview-web/components/primitives/` — confirm F1 MetricCell exists with NO hardcoded height.
3. `rg "Sparkline" apps/worldview-web/components/primitives/Sparkline.tsx` — confirm `width`/`height`/`trend` props.
4. `rg "TickerLink" apps/worldview-web/components/instruments/` — confirm F2 TickerLink exists. If not, the peer-click navigation falls back to `<Link href={...}>`.
5. `rg "qk.instruments.ownership" apps/worldview-web/lib/query/keys.ts` — confirm key exists.
6. `rg "data-table-grid" apps/worldview-web/app/globals.css` — confirm F1 CSS rules + `data-table-grid="dense"` variant.
7. `rg "InstrumentTabs" apps/worldview-web/components/instrument/tabs/InstrumentTabs.tsx` — read the file; confirm `q`/`f`/`i` chord registration and whether `1-3` are bound.
8. Confirm S9 routes exist for: `/fundamentals/{id}/insider-transactions`, `/briefings/instrument/{entity_id}`, `/briefings/instrument/{entity_id}/generate`. The last two: `git grep "briefings/instrument" services/api-gateway/`.
9. Confirm `/v1/ohlcv/batch` accepts multi-instrument: `grep -n "ohlcv/batch" services/api-gateway/src/api_gateway/routes/market.py`.
10. Confirm S3 endpoints exist for institutional-holders + fund-holders: `grep -n "institutional-holders\|fund-holders" services/market-data/src/market_data/api/routers/fundamentals.py`.

If any check fails, stop and report — don't improvise.

---

## §3. Backend dependencies (Wave 3 ships these)

> **W5 amendment (2026-05-21)**: T-S9-03, T-S2-04, T-S8-05, T-S8-06, T-S9-07 (peers tests), T-S2-08 (peers tests) and the `useInstrumentBrief` hook (T-05) were **all shipped in W5** on commit range `ce5a7b43`..`ce3de480` on `feat/plan-0089-w2`. Do NOT re-implement them. W3 only needs T-S9-01/02 (institutional/fund-holder proxies) from the original backend table.

| ID | Service | Change | LOC est. | Status |
|----|---------|--------|----------|--------|
| T-S9-01 | api-gateway | Add `GET /v1/fundamentals/{id}/institutional-holders` proxy → S3 `/institutional-holders` | ~15 | **pending** |
| T-S9-02 | api-gateway | Add `GET /v1/fundamentals/{id}/fund-holders` proxy → S3 `/fund-holders` | ~15 | **pending** |
| ~~T-S9-03~~ | ~~api-gateway~~ | ~~`GET /v1/instruments/{id}/peers?n=5` proxy → S2~~ | — | **DONE in W5** (feat(w5): T-S9-01) |
| ~~T-S2-04~~ | ~~market-data~~ | ~~`GET /v1/instruments/{id}/peers?n=5` SQL~~ | — | **DONE in W5** (feat(w5): T-S2-01) |
| ~~T-S8-05~~ | ~~rag-chat~~ | ~~`POST /v1/briefings/instrument/{id}/generate`~~ | — | **DONE in W5** (feat(w5): T-S8-05/06) |
| ~~T-S8-06~~ | ~~rag-chat~~ | ~~Drop `:user_id` from cache key~~ | — | **DONE in W5** (feat(w5): T-S8-05/06) |
| T-S9-07 (partial) | api-gateway | Add tests for T-S9-01/02 (2 tests in `tests/test_routes.py`) | ~30 | **pending** (peers test already done in W5) |
| ~~T-S2-08~~ | ~~market-data~~ | ~~peer endpoint tests~~ | — | **DONE in W5** (feat(w5): T-S2-08) |

**Total remaining backend LOC**: ~60 (T-S9-01/02 routes + 2 tests). **Estimated**: 5.5–6 days total (reduced by W5 backend pre-work).

---

## §4. File-by-file frontend change set (each sub-step = one commit)

### Block A — Foundation (primitives + hook split)

**T-01 (NEW)** `components/instrument/financials/sidebar/` — create directory.

**T-02 (NEW)** `apps/worldview-web/lib/gateway.ts` — add 4 client methods: `getInsiderTransactions(id)`, `getInstitutionalHolders(id)`, `getFundHolders(id)`, `getPeers(id, n=5)`. (Brief methods already exist — reuse `getInstrumentBriefing(entityId)`; add `triggerInstrumentBriefingGeneration(entityId)` for the lazy POST.)

**T-03 (EDIT)** `apps/worldview-web/lib/query/keys.ts` — add new keys: `qk.instruments.institutionalHolders(id)`, `qk.instruments.fundHolders(id)`, `qk.instruments.peers(id)`. Do **NOT** add `insiderTxns` — reuse `qk.instruments.ownership(id)` per Δ21.

**T-04 (NEW)** `apps/worldview-web/components/instrument/hooks/useFinancialsSidebarData.ts` — 4 queries (insider via `qk.instruments.ownership`, institutional, fundHolders, peers), all staleTime 24h, `enabled: !!instrumentId`.

**T-05 (NEW)** `apps/worldview-web/components/instrument/hooks/useInstrumentBrief.ts` — GET→404→POST `/generate`→poll GET every 30s up to 5 attempts→error fallback. Encapsulates lazy-generate flow.

### Block B — Snapshot grid (replaces FlatMetricsGrid for the dense surface)

**T-06 (NEW)** `apps/worldview-web/components/instrument/financials/DenseMetricsGrid.tsx` (≤260 LOC) — 6-col CSS grid (`grid grid-cols-6 gap-x-3 gap-y-0`), 8 logical rows, parent wears `<div data-table-grid="dense">`, uses **F1 `MetricCell` primitive** (no fork). Fields per audit (40 cells: VALUATION 6 / PROFITABILITY 6 / GROWTH 3 / BALANCE 4 / CASH FLOW 3 / DIVIDENDS 4 / OWNERSHIP 4+3 SHORTS / TECHNICALS-LITE 6). Empty cells render `<div className="h-[var(--row-h)]"/>`. PascalCase paths for PercentInsiders / PercentInstitutions (Δ23).

**T-07 (EDIT)** `apps/worldview-web/components/instrument/financials/FlatMetricsGrid.tsx` — **delete** or downgrade to a thin re-export of `DenseMetricsGrid`. Reading consumers: only `FinancialsTab.tsx`. Easiest: delete file, switch import in FinancialsTab.

**T-08 (DELETE)** `apps/worldview-web/components/instrument/financials/MetricCell.tsx` — legacy, h-[22px] hardcoded. Wave 3 obsoletes it. Replaced by `@/components/primitives/MetricCell` everywhere.

**T-09 (EDIT)** `apps/worldview-web/components/instrument/financials/__tests__/MetricCell.test.tsx` — port any unique assertions onto `__tests__/primitives/MetricCell.test.tsx` if not already covered, then delete the legacy test file.

### Block C — Tables (income / peer / insider / institutional / fund holders)

**T-10 (EDIT)** `apps/worldview-web/components/instrument/financials/IncomeStatementTable.tsx` — add `periodType: "ANNUAL" | "QUARTERLY"` state (controlled by `p` chord at parent), add Sparkline trend column at right edge (F1 primitive, `width={40} height={12} trend="auto"`), wear `<div data-table-grid>` (default 20px rows), handle 5-col annual / 8-col quarterly. Read `/v1/fundamentals/{id}/income-statement` (already wired) for annual; add `/v1/fundamentals/{id}/income-statement?period=quarterly` call for quarterly mode (verify endpoint accepts the param; if not, separate endpoint `/income-statement-quarterly` — flag and add S9 work to §3).

**T-11 (EDIT)** `apps/worldview-web/components/instrument/financials/EarningsBarChart.tsx` — drop from 80px to 64px, add EPS surprise % chip per bar (read `surprise_percent` from records; null-safe — hide chip if all 5 null).

**T-12 (NEW)** `apps/worldview-web/components/instrument/financials/PeerComparisonTable.tsx` (≤180 LOC) — 5 peers + self × 9 cols, wears `<div data-table-grid>` (default 20px), self-row `bg-muted/30`, peer row click → `router.push('/instruments/' + peer.ticker)` (F2 ticker URLs). Fetches peers via `qk.instruments.peers(id)`; fetches 1Y returns via `POST /v1/ohlcv/batch` with peer instrument_ids (Δ27 calculation).

**T-13 (NEW)** `apps/worldview-web/components/instrument/financials/InsiderTransactionsTable.tsx` (≤150 LOC) — 8 rows × 7 cols, wears `<div data-table-grid>` (default 20px), reads from `qk.instruments.ownership(id)` (Δ21 — already seeded by page-bundle). "View all" → `/instruments/{TICKER}/insiders` stub route.

**T-14 (NEW)** `apps/worldview-web/components/instrument/financials/InstitutionalHoldersTable.tsx` (≤150 LOC) — 10 rows × 5 cols, wears `<div data-table-grid>`, reads `qk.instruments.institutionalHolders(id)`.

**T-15 (NEW)** `apps/worldview-web/components/instrument/financials/FundHoldersTable.tsx` (≤150 LOC) — 10 rows × 5 cols, wears `<div data-table-grid>`, reads `qk.instruments.fundHolders(id)`.

**T-16 (NEW)** `apps/worldview-web/app/(app)/instruments/[id]/insiders/page.tsx` — stub route for "View all" insider transactions (Δ deferred — for v1.1 a full modal lands; for v1 just a page placeholder listing last 100 from same endpoint).

### Block D — Sidebar (7 panels)

**T-17 (NEW)** `components/instrument/financials/sidebar/AnalystConsensusPanel.tsx` — header + AnalystMiniBar (reuse from quote/metrics) + "N analysts" subline.

**T-18 (NEW)** `components/instrument/financials/sidebar/TargetPricePanel.tsx` — "12-MO TARGET" header + `text-[14px]` mono price (Δ7) + ▲/▼ delta vs current quote + F1 `DataFreshnessPill` (Δ14).

**T-19 (NEW)** `components/instrument/financials/sidebar/RevisionsPanel.tsx` — panel shell only (Δ18 defers content to v1.1). Renders 3 placeholder rows with `—` and footnote "Revisions history pending."

**T-20 (NEW)** `components/instrument/financials/sidebar/TargetsByAnalystPanel.tsx` — panel shell only (Δ17 defers content). Renders consensus row + "Per-firm targets pending data source" footnote.

**T-21 (NEW)** `components/instrument/financials/sidebar/BeatMissHistoryPanel.tsx` — fetches `/v1/fundamentals/{id}/earnings-trend` (Δ25 — quarterly, NOT annual), renders F1 Sparkline (`width={120} height={20}`) + "N beats / M misses" caption.

**T-22 (NEW)** `components/instrument/financials/sidebar/AIBriefPanel.tsx` — uses `useInstrumentBrief(id)` hook (T-05). Renders `bullets[0..2]` with Δ28 contract. Risk chip from `risk_summary.level` if present. "Expand →" cta opens overlay (Esc closes — shadcn Dialog).

**T-23 (NEW)** `components/instrument/financials/sidebar/CompanySnapshotPanel.tsx` — SECTOR / INDUSTRY / EMPLOYEES / HQ (City + Country) / DESCRIPTION (4-line clamp + "more"). Reads `fundamentals.General` (verify field paths — `git grep AddressData` and `FullTimeEmployees` on the response shape).

**T-24 (EDIT)** `apps/worldview-web/components/instrument/financials/AnalystSidebar.tsx` — rewrite into thin shell that composes the 7 panels in order. Vertical stack with `border-b border-border` between panels, `w-full` (parent gives `w-[240px]`).

### Block E — Orchestrator + hotkeys + route stub

**T-25 (EDIT)** `apps/worldview-web/components/instrument/financials/FinancialsTab.tsx` — rewrite:
- 240px sidebar width (was 280px — Δ from §9.3 of design).
- Left column order: DenseMetricsGrid → IncomeStatementTable → EarningsBarChart → PeerComparisonTable → InsiderTransactionsTable → InstitutionalHoldersTable → FundHoldersTable.
- Strip the entity_id vs instrument_id comment (Δ8).
- Wire `p`/`P` chord for income period toggle (Δ12).
- Wire `Alt+1..5` (or `1-5` if non-conflicting per Δ13) section scroll.

**T-26 (EDIT)** `apps/worldview-web/components/instrument/tabs/InstrumentTabs.tsx` — register `p` chord as Financials-scoped (does not switch tabs). Verify `1-3` chord behaviour; if numeric tab-switch, document and use `Alt+1..5` in T-25.

**T-27 (EDIT)** `apps/worldview-web/components/instrument/hooks/useFinancialsTabData.ts` — leave as-is (already correct per Δ20 split; sidebar hooks are separate).

### Block F — Arch tests + Vitest density gates

**T-28 (EDIT)** `apps/worldview-web/__tests__/architecture/data-table-grid-scope.test.ts` — comment update on entry 7 ("Peer Comparison" — clarify now lives under `components/instrument/financials/` not `intelligence/`).

**T-29 (NEW)** `apps/worldview-web/__tests__/instrument/financials-density.test.ts` — Vitest test: render DenseMetricsGrid with mock data → assert ≥ 40 visible MetricCell nodes; render full FinancialsTab → assert ≥ 80 visible data cells (snapshot + sidebar combined).

**T-30 (NEW)** unit tests for each new component (T-12/13/14/15/17/18/19/20/21/22/23) — minimum 1 test per component covering: empty state, populated state, hover/click handler.

### Block G — Playwright e2e

**T-31 (NEW)** `apps/worldview-web/e2e/instrument-financials.spec.ts` — 4 tests:
1. AAPL snapshot grid renders ≥ 40 cells.
2. Sidebar renders 7 panels with non-empty content (or graceful placeholders).
3. Peer table renders 5 + self = 6 rows.
4. `p` chord toggles Annual ⇄ Quarterly on income table.

---

## §5. Hotkeys (Financials-tab scope only)

| Chord | Action | Scope |
|-------|--------|-------|
| `p` / `P` | Toggle Annual ⇄ Quarterly income statement | Financials tab |
| `Alt+1`..`Alt+5` | Jump scroll to section (snapshot / income / earnings / peers / insider) | Financials tab |
| `b` (verify) | Expand AI brief panel to overlay | Financials tab |
| `d` (verify) | Expand company snapshot description | Financials tab |
| `Esc` | Close any overlay | All tabs (shadcn Dialog default) |

Tab-switch chords `q` / `f` / `i` remain owned by `InstrumentTabs`.

---

## §6. Tests

### 6.1 Unit (Vitest)

| # | File | Asserts |
|---|------|---------|
| U-1 | `__tests__/instrument/financials-density.test.ts` (T-29) | ≥ 40 cells in snapshot, ≥ 80 in full tab |
| U-2 | `components/instrument/financials/__tests__/DenseMetricsGrid.test.tsx` | renders 8 sections, handles null fundamentals |
| U-3 | `components/instrument/financials/__tests__/PeerComparisonTable.test.tsx` | renders 5 peers + self, sorts by market cap, click handler |
| U-4 | `components/instrument/financials/__tests__/InsiderTransactionsTable.test.tsx` | renders 8 rows, empty state |
| U-5 | `components/instrument/financials/__tests__/InstitutionalHoldersTable.test.tsx` | renders 10 rows, empty state |
| U-6 | `components/instrument/financials/__tests__/FundHoldersTable.test.tsx` | renders 10 rows, empty state |
| U-7 | `components/instrument/financials/sidebar/__tests__/AnalystConsensusPanel.test.tsx` | null counts → empty state, populated → mini-bar |
| U-8 | `components/instrument/financials/sidebar/__tests__/TargetPricePanel.test.tsx` | renders price + delta + freshness pill |
| U-9 | `components/instrument/financials/sidebar/__tests__/AIBriefPanel.test.tsx` | renders bullets per Δ28 contract, lazy-generate flow on 404 |
| U-10 | `components/instrument/financials/sidebar/__tests__/CompanySnapshotPanel.test.tsx` | renders 5 fields + 4-line description |
| U-11 | `components/instrument/hooks/__tests__/useInstrumentBrief.test.ts` | GET→404→POST→poll sequence, 5-attempt cap |
| U-12 | `components/instrument/hooks/__tests__/useFinancialsSidebarData.test.ts` | 4 queries fire, shared cache dedup |

### 6.2 Playwright e2e

T-31 above (4 tests).

### 6.3 Backend tests

| # | File | Asserts |
|---|------|---------|
| B-1 | `services/api-gateway/tests/test_routes.py` | `/institutional-holders` proxies to S3 |
| B-2 | `services/api-gateway/tests/test_routes.py` | `/fund-holders` proxies to S3 |
| B-3 | `services/api-gateway/tests/test_routes.py` | `/instruments/{id}/peers` proxies to S2 |
| B-4 | `services/market-data/tests/test_peers.py` | top-5 market-cap peers in same industry, excludes self, respects `n` param |

---

## §7. Acceptance criteria

The 25 checks in §1 are the acceptance gates. All must pass before merging.

---

## §8. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R-1 | S9 `/institutional-holders` proxy returns 500 because S3 endpoint is stubbed-but-broken | LOW | HIGH | Pre-flight check 10 confirms the S3 route exists; verify it returns 200 against AAPL live before shipping the S9 proxy |
| R-2 | `/income-statement?period=quarterly` doesn't accept the param — separate endpoint needed | MEDIUM | MEDIUM | Pre-flight verification step; if separate endpoint required, add 1 S9 route (+30 LOC) |
| R-3 | F2 TickerLink primitive doesn't exist yet (Wave F2 may not have shipped it) | MEDIUM | LOW | Fallback: peer rows use plain `<Link href={'/instruments/' + ticker}>`. Add TickerLink later. |
| R-4 | Hotkey `p` collides with something else not in InstrumentTabs | LOW | LOW | Pre-flight verifies; fallback chord `Shift+P`. |
| R-5 | 5 peers' 1Y returns require 5 OHLCV fetches → batch endpoint stalls on slow S3 | LOW | MEDIUM | `POST /v1/ohlcv/batch` is one round-trip; add 5s timeout client-side; render `—` on timeout. |
| R-6 | DenseMetricsGrid PascalCase paths drift again (PercentInsiders etc.) | MEDIUM | HIGH | Snapshot test U-2 includes a fixture with PascalCase keys; CI catches regressions. |
| R-7 | Lazy-generate brief endpoint not yet shipped | MEDIUM | HIGH | T-S8-05 is part of Wave 3 backend deps; cannot ship UI without it. Order backend before frontend. |

---

## §9. Files touched (forecast)

**New** (24):
- 1 directory + 3 hook files + 1 grid + 1 peer + 1 insider + 1 institutional + 1 fund holders + 7 sidebar panels + 1 stub route page + 1 density test + 1 e2e spec + 4 backend test files + 1 W3 plan doc (this file)

**Modified** (~8):
- `FinancialsTab.tsx` (orchestrator rewrite, ~150 LOC)
- `IncomeStatementTable.tsx` (+ quarterly + sparkline col, ~80 LOC)
- `EarningsBarChart.tsx` (height + surprise chip, ~25 LOC)
- `AnalystSidebar.tsx` (rewrite into shell, ~50 LOC)
- `InstrumentTabs.tsx` (chord scope, ~20 LOC)
- `lib/gateway.ts` (+4 methods, ~50 LOC)
- `lib/query/keys.ts` (+3 keys, ~10 LOC)
- `__tests__/architecture/data-table-grid-scope.test.ts` (comment update, ~5 LOC)
- 3 backend route files (api-gateway routes + market-data routes + market-data peer query)

**Deleted** (2):
- `apps/worldview-web/components/instrument/financials/MetricCell.tsx` (legacy)
- `apps/worldview-web/components/instrument/financials/__tests__/MetricCell.test.tsx` (legacy)

**Net LOC**: ~+1800 / -350. Two thirds in new sidebar panels (7 × ~80 = 560 LOC) and tables (4 × ~150 = 600 LOC).

---

## §10. Estimation

| Block | Days |
|-------|------|
| Backend (T-S9-01/02/03, T-S2-04, T-S8-05/06, tests B-1..4) | 1.5 |
| Block A — Foundation (T-01..05) | 0.5 |
| Block B — Snapshot grid (T-06..09) | 1.0 |
| Block C — Tables (T-10..16) | 1.5 |
| Block D — Sidebar (T-17..24) | 1.5 |
| Block E — Orchestrator + hotkeys (T-25..27) | 0.25 |
| Block F — Arch tests + density gates (T-28..30) | 0.25 |
| Block G — Playwright e2e (T-31) | 0.25 |
| Validation gate + QA + deploy | 0.25 |
| **Total serial** | **7.0** |
| Parallelizable wall-clock (1 backend + 1 frontend agent) | **4.5** |

---

## §11. Rollback plan

Per-commit revert. The 31 commits are independent enough that any single one can be backed out without breaking the rest. The riskiest:

- **T-25 (FinancialsTab rewrite)**: if the orchestrator breaks, revert this commit alone; sub-components stay shipped (no consumers in the immediate state) and the legacy FlatMetricsGrid path is gone after T-07. Mitigation: keep T-07 (FlatMetricsGrid delete) as the LAST commit in the Block B block so a Block E revert doesn't strand the old grid.

If the entire wave needs to roll back, `git revert <first-commit>..<last-commit> --no-commit` and commit a single revert PR.

---

## §12. Out of scope (deferred to v1.1+)

- Per-firm analyst targets endpoint (Δ17 — content deferred, shell ships).
- Analyst-revisions 30-day history (Δ18 — content deferred, shell ships).
- Full-history modal for insider/institutional rows (Δ stub-route ships; modal is v1.1).
- AI brief prompt rewrite for "fundamentals-emphasised" variant (open Q-5).
- Interest coverage / credit rating fields (always-null on current data; backend backfill is its own initiative).
- Day return / RSI / ATR fields on Financials grid (these belong on Quote tab per Wave F).
- i18n on company description (open Q-4).
- Drag-to-add insider/institutional row to watchlist (cross-cutting watchlist UX, deferred).

---

## §13. Definition of Done

1. All 25 acceptance checks in §1 pass.
2. All 12 unit tests + 4 e2e tests + 4 backend tests pass.
3. All 4 arch tests pass (`no-off-palette-colors`, `data-table-grid-scope`, `animation-policy`, `empty-copy-dictionary`).
4. `pnpm --filter worldview-web typecheck` + `lint` pass with zero errors.
5. Container `worldview-web` + `api-gateway` + `market-data` + `rag-chat` rebuilt and healthy in local compose.
6. Live walk-through against `/instruments/AAPL` confirms: 7 sidebar panels visible, snapshot grid 40 cells, peer table 6 rows, income table toggles Annual/Quarterly via `p`, AI brief renders or shows graceful empty state.
7. Memory updated with W3 state (Wave 3 complete, plan-0089-w3 branch shipped).
8. Commit log clean (one commit per T-NN sub-step, ~31 commits).
