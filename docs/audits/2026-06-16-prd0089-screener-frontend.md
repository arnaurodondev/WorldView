# PRD-0089 Screener Frontend — IB-L3 / IB-L4 / IB-L5 Audit

> **Date**: 2026-06-16
> **Scope**: §2 of `docs/plans/0089-pages/DEFERRED-WORK-PLAN.md` — the IB-L3 / IB-L4 / IB-L5
> screener frontend waves.
> **Worktree**: `worldview-wt-md-reliability` @ HEAD `2e447e8be`
> **Mode**: READ-ONLY investigation. No code changed.

---

## TL;DR

All three "deferred" frontend waves are, in fact, **largely already implemented** in the
working tree — the plan §2 is stale relative to the code. IB-L3 and IB-L4 are functionally
**DONE** (columns + filters + state + request mapping + sorting all wired). IB-L5 is
**DONE on the frontend** (the 5 rollup filter rows are live, NEWS 7D / BRIEF SCORE columns
exist) but remains **gated on the L-5b backend** for real data — flipping it on today shows
empty/null values universe-wide (the silent-failure pattern the plan warns about).

**The single most important finding is a wiring bug, not a missing wave:** the IB-L3 / IB-L4 /
IB-L5 columns exist as AG-Grid `ColDef`s but are **absent from the `DEFAULT_COLUMNS`
catalogue** in `lib/screener-columns.ts` that `ColumnSettingsPopover` reads from. So the
8 IB-L3 + 6 IB-L4 + 2 IB-L5 columns can **never be revealed by the user** — the gear popover
doesn't list them, and the page's `applyColumnState` only toggles colIds that exist as prefs.
They are dead, permanently-hidden columns. Conversely, 8 columns in the popover catalogue
(`avgVol`, `epsTtm`, `fcf`, `fcfMargin`, `interestCoverage`, `netDebtToEbitda`, `creditRating`,
`evEbitda`) have **no matching ColDef**, so toggling them is a no-op.

---

## LENS 1 — Per-wave existence verdict (file:line evidence)

### IB-L3 — 8 returns + 52W distance → **DONE** (with the catalogue caveat below)

| Surface | Field | Evidence |
|---|---|---|
| Columns | all 8 | `components/screener/ag-screener-columns.tsx:1066-1158` — PERFORMANCE col group, `dist52wHigh/dist52wLow/return1m/3m/6m/Ytd/1y/3y`, each `hide:true`, dedicated renderers `Dist52wHighCellRenderer…Return3yCellRenderer` (lines 551-574). |
| Renderers | signed-pct + bull/bear | `ReturnPctCellRenderer` `ag-screener-columns.tsx:524-547`; `formatReturnPct` `:48-53`. |
| Filters | 8 range rows | `components/screener/ScreenerFilterBar.tsx:657-746` — "Performance" `<Section>`, 8 `RangeInput`s. |
| State | 16 fields | `features/screener/lib/filter-state.ts:141-156` (`dist52wHighPctMin…return3yMax`). |
| Request map | byte-exact metric names | `features/screener/lib/build-filters.ts:79-86` (`dist_from_52w_high_pct`, `return_1m`, …). |
| Active counts | performance group | `features/screener/lib/active-counts.ts:103-111`. |

**Verdict: DONE.** Filters fully functional (server-side). Columns defined but unreachable
via the popover (see Lens 1 caveat / the catalogue mismatch in the TL;DR and Root Cause §2.5).

### IB-L4 — analyst / insider / ownership → **DONE** (with caveats)

| Surface | Field | Evidence |
|---|---|---|
| Columns | 5 backend + 1 derived | `ag-screener-columns.tsx:1160-1243` — OWNERSHIP group: `analystTarget`, `analystUpside` (derived `valueGetter` `:1189-1196`), `analystConsensus`, `insiderNet90d`, `instOwn`, `shortPct`, all `hide:true`. |
| ANALYST UPSIDE | client-side derived | `AnalystUpsideCellRenderer` `:597-617` = `(target/price)-1`; sortable via `valueGetter` returning `null` when underivable. |
| Consensus tone | ≥4 bull / ≤2 bear | `AnalystConsensusCellRenderer` `:627-644`. |
| Insider null≠0 | `—` not `$0` | `formatInsiderCompact` `:65-72`; `InsiderNet90dCellRenderer` `:646-663`. |
| Filters | 5 range rows | `ScreenerFilterBar.tsx:748-808` — "Ownership" `<Section>` (no ANALYST UPSIDE filter, by spec). |
| State | 10 fields | `filter-state.ts:158-171`. |
| Request map | **named snapshot fields** (not metric rows) | `build-filters.ts:88-152` — the 2026-06-15 bugfix block: sends `analyst_target_price_min` etc. merged onto `filters[0]`, NOT `{metric:"short_percent"}`. |
| Active counts | ownership group | `active-counts.ts:116-121`. |

**Verdict: DONE.** Two live caveats baked into the code (not bugs, but data-quality
limits): insider data is non-null for only ~3 tickers until §3 universe activation; ANALYST
UPSIDE is sort-only (no server filter).

### IB-L5 — 7 intelligence filters + NEWS 7D / BRIEF SCORE columns → **PARTIAL (frontend DONE, backend-gated)**

| Surface | Field | Evidence |
|---|---|---|
| Columns | NEWS 7D, BRIEF SCORE | `ag-screener-columns.tsx:1245-1279` — INTELLIGENCE group, both **default-visible** (no `hide`). Renderers `News7dCellRenderer` `:714-732`, `BriefScoreCellRenderer` `:744-761`. |
| Filter rows | 5 live + 2 future | `components/screener/IntelligenceFilterGroup.tsx:149-320`. |
| backendReady defaults | 5 true / 2 false | `IB_L5_DEFAULTS` `IntelligenceFilterGroup.tsx:70-78` (newsCount7d/aiBrief/activeAlert/contradictions/llmRelevance = `true`; upcomingEarnings/upcomingDividend = `false`). |
| State | 6 numeric + 2 bool | `filter-state.ts:180-193`. |
| Request map | named intel fields | `build-filters.ts:154-183` (`news_count_7d_min`, `has_ai_brief`, …). |
| Mounted | in the bar | `ScreenerFilterBar.tsx:941-942` `<IntelligenceFilterGroup value={form} onChange={setForm} />`. |

**BackendPendingBadge count:** **exactly 2 render at default** — `upcomingEarnings` +
`upcomingDividend` (`IntelligenceFilterGroup.tsx:301,315`). The other 3 `BackendPendingBadge`
JSX sites (`:176,205,235,261,286`) are dead branches guarded by `!ready.*` which is `false`
under `IB_L5_DEFAULTS`. Confirmed by the test
`components/screener/__tests__/IntelligenceFilterGroup.test.tsx:28` ("shows exactly 2…").

**`backendReady` / `BACKEND_PENDING_KEYS`:** `backendReady` is a per-row override prop, never
passed from `ScreenerFilterBar` (so defaults apply). **`BACKEND_PENDING_KEYS` does not exist
anywhere** in the codebase (grep returns nothing) — the plan §2.7 assumption that it lives in
`ColumnSettingsPopover.tsx` and "is currently empty" is stale; the symbol was never created.

**Verdict: PARTIAL.** The frontend is shipped. What is NOT done: the L-5b backend worker
(plan §1) that materialises `news_count_7d` etc. into the snapshot. Until that runs, the live
filters and the two default-visible columns return null/empty for the whole universe — exactly
the "silent failure" the plan §1.2 flags. The stale-rollup UX (T-IB5-04: read
`intelligence_rollup_synced_at`, show "data N hours stale") is **not implemented** — no
reference to `intelligence_rollup_synced_at` exists on the frontend.

### Summary table

| Wave | Columns | Filters | State | build-filters | Verdict |
|---|---|---|---|---|---|
| IB-L3 | ✅ (8, `hide:true`) | ✅ (8 range) | ✅ | ✅ | **DONE** (columns unreachable via popover) |
| IB-L4 | ✅ (5+1 derived) | ✅ (5 range) | ✅ | ✅ (named-field fix) | **DONE** (insider/upside data caveats) |
| IB-L5 | ✅ (2 default-visible) | ✅ (5 live + 2 pending) | ✅ | ✅ | **PARTIAL** — backend L-5b gates real data; stale-UX missing |

---

## LENS 2 — Root causes of the gaps

### 2.1 IB-L5 gated on L-5b backend
The 5 live intel filters and the NEWS 7D / BRIEF SCORE columns read snapshot columns
(`news_count_7d`, `display_relevance_7d_weighted`, …) that **no worker populates yet**. Plan §1
(L-5b sync worker, ~3 d) owns materialising 6 of the 8 fields by pulling the 4 internal L-5a
endpoints nightly. Frontend is ready; data is not. Flipping it "on" without L-5b → every row
shows `—` / 0, which erodes trust (memory: "audit return values must be persisted").

### 2.2 IB-L4 insider universe gap
`insider_net_buy_90d` is non-null only for AAPL/TSLA/AMZN because `sched_policies` only
seeds those 3 tickers for EODHD insider polling (plan §3). The `InsiderUniverseLoader` exists
but is **unscheduled** and gated on a ~13k-credit/month EODHD budget decision. The frontend
correctly renders `—` (not `$0`) for null insider data (`InsiderNet90dCellRenderer` +
`formatInsiderCompact`), so the UI degrades gracefully — but a `INSIDER 90D ≥ $1M` filter
returns ~3 names instead of a universe hit-list.

### 2.3 ANALYST UPSIDE client-side derivation
Backend exposes no `analyst_upside` column. The frontend derives `(target/price)-1` per row
via an AG-Grid `valueGetter` (`ag-screener-columns.tsx:1189-1196`), which makes it
**sortable** but **not server-filterable** (you can't push a derived predicate to the DB). The
upside also silently disappears (`—`) whenever `current_price` is null — and live price
coverage is sparse (~7% of instruments per the 52W-range comment at `:302`), so ANALYST UPSIDE
will read `—` for most rows even when a target exists. This is the real practical limiter, more
than the sort-vs-filter distinction.

### 2.4 The 14-column default cap (`fh-column-count-cap`)
`DEFAULT_COLUMNS.filter(visible).length === 14` is an asserted invariant
(`lib/screener-columns.ts:163-165`, regression test in `lib/__tests__/screener-columns.test.ts`),
tied to a density gate (≥240 body cells above the fold at 1440×900, 20 rows × ~14 cols,
`app/(app)/screener/page.tsx:611-628` density comment). This is why all IB-L3/L4 columns are
`hide:true` and only NEWS 7D + BRIEF SCORE are default-visible. The cap is healthy; the problem
is the catalogue mismatch (below) means the user can't trade a visible column for a hidden one.

### 2.5 ⚠️ ROOT-CAUSE BUG — column catalogue desync (the headline finding)
There are **two independent column lists** that must agree but don't:

- **AG-Grid ColDefs** (`ag-screener-columns.tsx`) — defines render + `hide` default.
- **`DEFAULT_COLUMNS`** (`lib/screener-columns.ts`) — the catalogue `ColumnSettingsPopover`
  lists, and the **only** set of colIds `page.tsx` feeds to `gridApi.applyColumnState`
  (`page.tsx:303-318`).

Diff of the two (colId vs key):

- **In ColDefs but NOT in popover catalogue** (defined, rendered, but the user can never
  unhide them): `dist52wHigh, dist52wLow, return1m, return3m, return6m, returnYtd, return1y,
  return3y` (all 8 IB-L3), `analystTarget, analystUpside, analystConsensus, insiderNet90d,
  instOwn, shortPct` (all 6 IB-L4), `news7d, briefScore` (IB-L5), plus `volume, revenue`.
- **In popover catalogue but NO ColDef** (toggling them is a silent no-op): `avgVol, epsTtm,
  fcf, fcfMargin, interestCoverage, netDebtToEbitda, creditRating, evEbitda` (the entire IB-L2
  opt-in block + `evEbitda`).

Consequence: IB-L3/L4 are filterable but their columns are **invisible and unrevealable**.
The IB-L2 opt-ins appear in the popover but never draw. This is the same class of bug the
file headers explicitly warn about ("a column must be declared in BOTH places",
`screener-columns.ts:190-196`) — and it regressed. **This is the highest-leverage fix in the
whole §2 scope** and is not even mentioned in the plan.

---

## LENS 3 — Concrete UI enhancements (prioritised)

Current state is genuinely strong: 20px rows, `tabular-nums font-mono` everywhere, semantic
bull/bear tints (`text-positive`/`text-negative`/`text-warning`), `—` null sentinels
(consistent), right-aligned numerics via a single `NUMERIC_COL_IDS` pass, column groups,
dual-thumb log/linear range sliders, presets (7), saved screens (localStorage CRUD + dialog),
filter chip strip, row-hover toolbar (watch/alert/compare), sort-aware export, sparklines with
>200-row suppression, distinct cold-start vs filtered-to-zero empty states, error+retry. That
is already past most retail screeners. The gaps to "finance-grade":

**P0 — correctness/wiring (ship before any new feature):**
1. **Fix the column-catalogue desync (§2.5).** Add the 16 IB-L3/L4/L5 colIds to
   `DEFAULT_COLUMNS` (visible:false, grouped), and remove or back the 8 orphan popover keys
   with real ColDefs. Without this, IB-L3/L4 columns are dead. Add an architecture test that
   asserts `set(DEFAULT_COLUMNS keys) === set(ColDef colIds)` so it can't regress again.
2. **Group the popover by column group** (Performance / Ownership / Intelligence / Ratios) with
   a "show/hide group" toggle — with 30+ columns a flat checkbox list is unusable. Mirrors the
   AG-Grid group structure already in the ColDefs.

**P1 — finance-grade ergonomics:**
3. **Conditional/heat formatting on numeric columns** beyond the current 2-3 threshold tints.
   Bloomberg-style column heatmaps (e.g. color-scale the whole RTN column by percentile within
   the loaded set). The `HeatCell` palette + `heatCellColor()` already exist; generalise them
   to any numeric column via a per-column `heatmap?: boolean` flag.
4. **Sticky compare tray.** `compareSet` already tracks ≤3 tickers (`page.tsx:212-216`) but the
   `/compare` page is a stub and the set isn't persisted. Persist to sessionStorage and add a
   pinned compare strip.
5. **Keyboard navigation / command palette.** No `j/k` row nav, no `/` to focus search, no
   chord to open the filter panel. Terminal users live on the keyboard. AG-Grid supports cell
   nav; wire row-level + a `Cmd-K` jump-to-ticker.
6. **Stale-data indicator for IB-L5** (plan T-IB5-04, currently missing): surface
   `intelligence_rollup_synced_at` age as a "data N h stale" pill on the Intelligence section
   header once L-5b ships.
7. **Density toggle** (compact 20px ↔ comfortable 28px). The 20px lock is great for power users
   but a per-user toggle (persisted) widens the audience without losing the default.

**P2 — polish:**
8. **Saved-screen sharing** — saved screens are localStorage-only; add URL-encode/share (the
   page already URL-backs sector/capTier via nuqs, extend to the full FilterState).
9. **Add MiniChart in-cell for the RTN columns** (tiny bar instead of just a signed %), and a
   52W-range mini-bar variant already exists — reuse the idiom.
10. **Inline filter editing from the chip strip** (click a chip → popover to edit that range)
    instead of opening the whole panel.
11. **Replace native HTML5 drag/drop** in `ColumnSettingsPopover` (no touch support, awkward
    ghost) with a keyboard-accessible reorder (↑/↓ buttons or `@dnd-kit`) — current impl is
    desktop-mouse-only.

---

## LENS 4 — Bloomberg EQS comparison ("excel against Bloomberg")

### Where we already match or exceed EQS
- **Visual density + sparklines + heat cells in-grid.** EQS is famously text-heavy; our 20px
  rows with inline 30-day sparklines, 52W position bars, and heat-tinted cells are arguably a
  cleaner scan than EQS's raw grid.
- **Intelligence-layer filters (IB-L5).** News-velocity-7d, KG contradiction count, has-AI-brief,
  has-active-alert — **EQS has nothing equivalent.** This is our genuine differentiator: screen
  by narrative/intelligence signals, not just fundamentals. (Pending L-5b data.)
- **Presets + saved screens + one-click reset + URL-backed dimensions.** On par with EQS
  templates; our preset chips are faster to reach than EQS's template menu.
- **Modern affordances:** sort-aware CSV/PDF export, row-hover watch/alert/compare, distinct
  empty/error states with retry. EQS's export is clunky; its error states are cryptic.

### EQS affordances we are missing
1. **Formula / custom-computed columns.** EQS lets users define arbitrary expressions
   (`P/E < sector median`, `(target/price)-1`). We hard-code one derived column (ANALYST
   UPSIDE) client-side. A general client-side formula column engine would leapfrog this.
2. **Relative-to-index / relative-to-sector screening.** EQS's killer feature: "P/E vs SPX",
   "RTN vs sector". We have only absolute values. No `*_vs_index` or `*_percentile` fields.
3. **Peer-relative percentiles.** EQS ranks each metric within a peer group. We show raw values;
   no within-universe percentile column or coloring. (P1 enhancement #3 is the building block.)
4. **Save AND share screens across users + scheduled re-run / alerts-on-screen.** EQS can email
   you when a name enters/exits a screen. Ours are localStorage-only, single-user, no scheduled
   eval, no "alert when a new ticker matches this screen."
5. **Cross-asset + global universe.** EQS spans global equities/credit/funds. We're US-equity-
   centric (the `us-equities-only` preset is the default analyst path).
6. **Backtesting / point-in-time screening.** EQS can screen "as of" a past date. We only screen
   live snapshots.

### Recommendations to "excel against Bloomberg" on the UI
- **Lean into the intelligence moat** (P1 #6 + ship L-5b): make narrative-driven screening the
  headline feature EQS can't copy. "Show names with ≥5 articles/7d AND a KG contradiction AND
  within 5% of 52W high" is a query no Bloomberg user can run.
- **Ship peer-relative coloring** (P1 #3) — cheapest way to feel EQS-grade; the heat
  infrastructure already exists.
- **Add a client-side formula column** (Lens 4 #1) — directly matches EQS's most-loved power-user
  feature and is feasible entirely on the frontend over the loaded result set.
- **Alerts-on-screen** (Lens 4 #4): the alert service (S10) already exists; wiring "notify when
  a ticker enters this saved screen" turns a static screener into a monitoring tool — a concrete
  EQS-parity win.
- **First, fix the catalogue desync (P0 #1).** Right now half the columns the data supports are
  literally unreachable — no amount of EQS-parity features matters if IB-L3/L4 columns can't be
  turned on.

---

## Evidence index (absolute paths)

- `apps/worldview-web/components/screener/ag-screener-columns.tsx` — all IB-L3/L4/L5 ColDefs + renderers
- `apps/worldview-web/components/screener/ScreenerFilterBar.tsx` — Performance/Ownership/News sections, mounts IntelligenceFilterGroup
- `apps/worldview-web/components/screener/IntelligenceFilterGroup.tsx` — 7 rows, IB_L5_DEFAULTS, 2 live BackendPendingBadge
- `apps/worldview-web/components/screener/ColumnSettingsPopover.tsx` — reads DEFAULT_COLUMNS catalogue
- `apps/worldview-web/features/screener/lib/filter-state.ts` — FilterState (all IB-L3/L4/L5 fields)
- `apps/worldview-web/features/screener/lib/build-filters.ts` — FilterState → ScreenFilterRequest (named-field mapping)
- `apps/worldview-web/features/screener/lib/active-counts.ts` — section badge counts
- `apps/worldview-web/lib/screener-columns.ts` — DEFAULT_COLUMNS (catalogue) + 14-col cap invariant
- `apps/worldview-web/lib/screener/presets.ts` — 7 system presets
- `apps/worldview-web/lib/saved-screens.ts` — localStorage saved-screen CRUD
- `apps/worldview-web/app/(app)/screener/page.tsx` — orchestration, applyColumnState, compare set, empty/error states
- `apps/worldview-web/components/screener/HeatCell.tsx` / `MiniChart.tsx` — heat cell + sparkline primitives
- `docs/plans/0089-pages/DEFERRED-WORK-PLAN.md` §2 — the (now stale) deferred-work plan
- `docs/plans/0089-pages/I-screener-plan.md` — Block IB-L3/L4/L5 source spec
