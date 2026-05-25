# QA Report: PRD-0089 W1 visual regressions

**Date**: 2026-05-21 05:30 UTC
**Skill**: qa
**Scope**: post-W1 visual review — 3 user-reported regressions + 2 surfaced during investigation
**Branch**: `feat/plan-0089-w1`
**Verdict**: PASS_WITH_WARNINGS (no test/build failures; UX regressions need user direction)
**Report file**: `docs/audits/2026-05-21-qa-w1-visual-regressions-report.md`

---

## Executive Summary

User flagged 3 issues after exercising the live W1 build at `http://localhost:3001`:

1. **TopBar lost portfolio info.** The PortfolioRail box (PORT / Day P&L / Total P&L) is no longer visible. The user prefers either the old animated marquee back, or — more importantly — more portfolio information surfaced where it used to live.
2. **PortfolioSwitcher does nothing observable.** Changing the active portfolio in the new chip dropdown does not change Dashboard or TopBar values, leaving the user asking "what exactly does this control?".
3. **Sidebar watchlist renders empty even when stocks exist.** "Add symbols in Watchlists" is shown despite the Tech watchlist being non-empty (visible in /portfolio → Watchlist tab).

Investigation confirms all three. Two are introduced by the W1 visual contract (the missing PortfolioRail is hidden by a null-guard that pre-dates W1 but is now glaring; the PortfolioSwitcher was explicitly scoped self-contained for W1 with downstream wiring deferred per plan §4.2). The third is a pre-existing data-fetch bug surfaced because the W1 sparkline column finally makes the panel's empty state painful.

Also flagged during investigation: **^TNX cell shows `TNX — —`** because the caret-prefixed ticker doesn't resolve via the search-instruments path, and **IWM / VIX / DIA cells show `0.00 / +0.00%`** because the demo data backend doesn't have recent quotes for those tickers.

No test or build failures. Suite is 1882 passing, typecheck + lint + build all green. Verdict gated on user decisions for the 5 findings below.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| Focused investigation (single reviewer) | 7 | 5 | 0 | 2 | 2 | 1 | 0 |

(5-agent parallel dispatch skipped — scope is 3 specific user-reported visual regressions, not a broad-spectrum audit. Direct investigation produces a sharper answer.)

### Cross-Agent Signals
n/a — single-reviewer scope.

### Fixes Applied
None yet. Awaiting user direction (see "Decisions Needed" below).

### Decisions Needed
| Finding | Question | Recommended option |
|---------|----------|--------------------|
| F-001 | PortfolioRail: render unconditionally with `—` placeholders, or pack denser with more fields (cash, positions count)? | **Option A** — render unconditionally with placeholders; ship denser version with F-002 |
| F-002 | Wire PortfolioSwitcher selection into usePortfolioMetrics now (W1 scope-creep), or defer to W4 as planned? | **Option B** — minimal wiring now (~25 LOC) since F-001 + F-002 together unlock the user's stated need |
| F-003 | Fix sidebar watchlist to fetch members for the active watchlist? | **Option A** — yes, add a per-watchlist members fetch |
| F-004 | ^TNX: hard-map the instrument id, skip caret, or replace with a different rates ticker? | **Option B** — drop the caret in the search query (try `TNX` first, fall back to caret form) |
| F-005 | IWM / VIX / DIA showing $0 — data backend issue, not W1 — open as platform bug? | **YES** — open separately; not in W1 scope |

---

## Test Execution Results

Full validation gate already ran during the W1 final-gate phase (see W1 final report).
Re-running the gates relevant to the 4 source-files that would be touched by the proposed fixes:

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Frontend Unit | `__tests__/` (all) | 1898 | 1882 | 0 | 16 | PASS |
| Frontend Type | `pnpm typecheck` | — | — | 0 | — | PASS |
| Frontend Lint | `pnpm lint` | — | — | 0 errors (3 pre-existing warnings) | — | PASS |
| Frontend Build | `pnpm build` | — | — | 0 | — | PASS |
| Architecture | 4 arch tests | 8 | 8 | 0 | 0 | PASS |
| Backend layers | not in scope (UI-only) | — | — | — | — | n/a |

### Per-Service Breakdown
Not re-run — backend services are unchanged by W1.

---

## Supplementary Checks
| Check | Status | Notes |
|-------|--------|-------|
| Import Guards | PASS | — |
| Documentation Freshness | PASS | W1 PRD frontmatter + TRACKING + DESIGN_SYSTEM updated in commit `430bf882` |
| Container Build | PASS | BUILD_ID `4Hjqm_McQ1MxNKAzXe9V0` running healthy |

---

## Issues — Full Investigation

## Issue F-001: PortfolioRail invisible in TopBar (Image #2)

### Summary
The PORT / Day P&L / Total P&L box that previously surfaced live portfolio NAV in the right cluster of the TopBar no longer renders for the user. The component is intact in `TopBar.tsx`, but its outer wrapper is render-gated on at least one value being non-null. `usePortfolioMetrics` returns null for every field when the active portfolio has no holdings — so the wrapper short-circuits and the whole rail vanishes.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: user (Image #2) + code inspection

### Root Cause Analysis
- **What**: `apps/worldview-web/components/shell/TopBar.tsx:242-307` wraps the three-slot PortfolioRail in a conditional `{(portfolioValue != null || dailyPnl != null || unrealisedPnl != null) && (<div ...>)}`. When all three values are null, the entire box (border, background, labels, dividers) collapses to nothing in the DOM.
- **Why**: `apps/worldview-web/hooks/usePortfolioMetrics.ts:104-130` returns `null` for `portfolioValue` whenever `holdingsResp.holdings.length === 0`. The demo session has no positions → all three values are null → rail hidden.
- **When**: Always, for any user whose currently-selected portfolio has zero holdings (new users, demo sessions, ROOT-aggregated views where every child is empty).
- **Where**: Layer is the TopBar (chrome). The decision lives in two coupled files: usePortfolioMetrics (data) + TopBar (render gate). Plan §4.3 lists the rail as slot 8 of 17 but never specified whether it should render with placeholder dashes when empty.
- **History**: The conditional render predates W1 (the original logic ships with the F-122 commit). W1 just removed `rounded-[2px]` from the box. The reason the user notices it now: with the animated marquee gone, the TopBar's right cluster has noticeably less "alive" content, so the absence of the rail is more conspicuous.

### Evidence
```tsx
// apps/worldview-web/components/shell/TopBar.tsx:242
{(portfolioValue != null || dailyPnl != null || unrealisedPnl != null) && (
  <div
    className="flex items-center gap-2 border border-border/30 bg-muted/20 px-2 py-0.5"
    aria-label="Portfolio header metrics"
  >
    {/* ...PORT / Day P&L / Total P&L slots... */}
  </div>
)}
```
```ts
// apps/worldview-web/hooks/usePortfolioMetrics.ts:104
const portfolioValue: number | null = holdingsResp?.holdings.length
  ? holdingsResp.holdings.reduce(...)
  : null;  // ← null when no holdings → rail collapses
```

### Impact
- **Immediate**: New users / demo sessions see no portfolio info on the TopBar — primary "is my book up or down today?" surface missing.
- **Blast radius**: TopBar only; no downstream code reads these props.
- **Data risk**: None — purely a render decision.
- **User impact**: Visible regression vs the previous design's intent. Verbatim feedback: "the previous moving approach we had and the information about portfolio was better (more information)".

### Solution Options

#### Option A: Render PortfolioRail unconditionally with `—` placeholders
**Description**: Drop the outer conditional. Each of the three value slots already handles null individually — we replace `null` with an em-dash in the render path. The box reserves its width and labels stay visible even on a fresh account.
**Changes required**:
- [ ] `components/shell/TopBar.tsx` — drop the `{(... != null ...) && (...)}` wrapper; render the box unconditionally; per-slot `value != null ? formatted : "—"`
- [ ] `__tests__/shell/TopBar.test.tsx` — add an assertion that the rail is always visible even with all three props undefined
**Benefits**:
- Zero layout shift when prices arrive
- TopBar always communicates "you have a book here" even before data resolves
- Matches IndexStrip's "never collapse to zero width" treatment in the same row
**Drawbacks**:
- A long em-dash row could look "loading" forever for users who genuinely have no portfolio at all (which is the demo case here — but they should fix that by connecting a brokerage)
**Effort**: Low (~15 LOC)
**Risk**: Low

#### Option B: Render denser with more fields (cash, # positions, beta-adj)
**Description**: Same as A, but also surface CASH / # POSITIONS / BETA-ADJ inline in the rail — bringing more density to the TopBar as the user explicitly asked.
**Changes required**:
- [ ] `usePortfolioMetrics.ts` — extend the returned shape with `cash`, `positionsCount`, `betaAdj`
- [ ] `TopBar.tsx` — extend the rail to render the new slots
- [ ] tests + docs
**Benefits**:
- Directly answers the user's "more information about portfolio was better"
- Bloomberg-style density on the rail
**Drawbacks**:
- More LOC; more horizontal space contention with the IndexStrip
- Cash / beta-adj may need new S9 endpoint work (usePortfolioMetrics today computes from holdings)
**Effort**: Medium (~80 LOC + possibly backend)
**Risk**: Medium

#### Option C: Restore an animated marquee element
**Description**: Bring back the animated horizontal scroll for the IndexStrip cells.
**Drawbacks**: Reverses DISCUSS-1 / W1 plan §9.1; violates `prefers-reduced-motion`; loses scanability the static strip gained. Not recommended.

### Recommended Option
**Option A** as a 15-LOC immediate fix today, then ship **Option B** alongside F-002 once the switcher actually selects an active portfolio — the two together give the user the density they want.

### Verification Steps
- [ ] Visit `/dashboard` with no holdings — confirm PORT / Day P&L / Total P&L box is visible with `—` placeholders
- [ ] Add a position — confirm the placeholders flip to live numbers in ≤15 s without layout shift
- [ ] `pnpm vitest run __tests__/shell/TopBar.test.tsx` — passes the new always-visible assertion

---

## Issue F-002: PortfolioSwitcher selection has no downstream effect (Image #2 + #3)

### Summary
The new PortfolioSwitcher chip lets the user pick a portfolio and persists the selection to `localStorage.shell.activePortfolioId`, but nothing reads that selection. `usePortfolioMetrics`, the only thing the TopBar's PortfolioRail consumes, still picks `portfoliosData[0]`. The user asks "what exactly does the tab of portfolio do, what changes does it apply to the dashboard? What side panel should I see in portfolio?". Answer today: nothing — the chip is decorative.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: user (Image #3) + code inspection

### Root Cause Analysis
- **What**: `apps/worldview-web/components/shell/PortfolioSwitcher.tsx:128-141` exposes an `onActivePortfolioChange` callback prop and writes to localStorage; `app/(app)/layout.tsx:300` instantiates `<PortfolioSwitcher />` with NO callback wired (via TopBar default props); `apps/worldview-web/hooks/usePortfolioMetrics.ts:81` ignores localStorage entirely and uses `portfoliosData?.[0]?.portfolio_id`.
- **Why**: The W1 plan §4.2 explicitly scoped the chip as self-contained: *"W1 ships the chip self-contained; W4 integration will plumb the selection."* The author shipped the deferral as documented, but the user (correctly) cannot tell that the chip is non-functional without reading the plan.
- **When**: Always — every user clicking the chip sees the dropdown update its checkmark but no other surface changes.
- **Where**: Spans 3 files — switcher (writes the state), layout (would own the lift), usePortfolioMetrics (would consume the state).
- **History**: Documented W1 deferral. Not a bug per the plan, but a UX gap the user has now flagged.

### Evidence
```tsx
// apps/worldview-web/components/shell/PortfolioSwitcher.tsx:50
const ROOT_SENTINEL = "__root__";
// :128
writePersistedActiveId(portfolioId);
onActivePortfolioChange?.(portfolioId);  // ← no caller passes this prop
```
```tsx
// apps/worldview-web/app/(app)/layout.tsx (rendered via TopBar)
<PortfolioSwitcher />  // ← no onActivePortfolioChange wired
```
```ts
// apps/worldview-web/hooks/usePortfolioMetrics.ts:81
const firstPortfolioId = portfoliosData?.[0]?.portfolio_id;  // ← ignores localStorage
```

### Impact
- **Immediate**: User cannot actually switch what the PortfolioRail / Dashboard / Portfolio page tracks.
- **Blast radius**: Any consumer that should respect the active portfolio (Dashboard widgets, Portfolio detail page, future Wave 4+ pages).
- **Data risk**: None.
- **User impact**: Confusing — verbatim "what exactly does the tab of portfolio do, what changes does it apply to the dashboard?".

### Solution Options

#### Option A: Defer to W4 (as planned)
**Description**: Leave as-is. Document the deferral inline on the chip via a small "(W4)" tooltip so the user knows the wiring is intentional.
**Drawbacks**: User has already noticed and asked. A non-functional chip on the most-visible TopBar element will keep generating the same question.
**Effort**: Trivial
**Risk**: Low — explicit but unsatisfying

#### Option B: Minimal wiring now — usePortfolioMetrics reads localStorage
**Description**: Move the active-portfolio selection into a small React context (or simply read `localStorage.shell.activePortfolioId` inside `usePortfolioMetrics`). The PortfolioSwitcher already writes; we just need the read side. When the sentinel `__root__` is selected, the hook keeps its current "aggregate all portfolios" behaviour (which today equals `portfolios[0]` — see follow-up below for true ROOT semantics).
**Changes required**:
- [ ] `apps/worldview-web/contexts/ActivePortfolioContext.tsx` — new tiny context owning `activePortfolioId: string | null` + `setActivePortfolio`
- [ ] `app/(app)/layout.tsx` — wrap shell with `<ActivePortfolioProvider>`; mount inside `<HotkeyProvider>` so the switcher chord stays scope-aware
- [ ] `components/shell/PortfolioSwitcher.tsx` — consume the context for source of truth instead of (or in addition to) local state; remove the now-redundant `onActivePortfolioChange` prop
- [ ] `hooks/usePortfolioMetrics.ts` — read `useActivePortfolio().portfolioId` first; fall back to `portfoliosData[0]` only when null
- [ ] tests for context + updated PortfolioSwitcher + usePortfolioMetrics
**Benefits**:
- Switcher becomes functional in one ~80-LOC commit
- Sets up the consumer pattern Wave 4 will scale across the rest of the app
- Pairs with F-001 Option B (the denser rail) for a coherent "TopBar communicates your book" answer
**Drawbacks**:
- Scope creep on W1 (already shipped); cleaner as a W2/W3 commit on a new branch
- True ROOT-aggregation semantics ("show NAV summed across all portfolios") is not wired here — selecting ROOT today falls back to `portfolios[0]`, which is the same behaviour as before
**Effort**: Medium (~80–120 LOC)
**Risk**: Medium

#### Option C: Wire selection + true ROOT aggregation
**Description**: Option B plus implement the ROOT-aggregation semantics inside `usePortfolioMetrics` — when the active id is `null`/`__root__`, sum holdings across every portfolio in the response.
**Drawbacks**: Touches more code, needs careful FX handling for multi-currency books (deferred per FU-1.4)
**Effort**: Medium-High (~150 LOC)
**Risk**: Medium

### Recommended Option
**Option B** — ship the minimal wiring on a small `feat/plan-0089-w1.1` follow-up branch so the chip becomes functional immediately. Defer true ROOT aggregation (Option C) to the dedicated Portfolio Overview wave.

### Verification Steps
- [ ] Switch from "All Portfolios" → "Tastytrade Main" in the chip — PortfolioRail PORT/Day/Tot values update within 15 s
- [ ] Reload the page — selection persists (localStorage reads correctly)
- [ ] `pnpm vitest run __tests__/shell/PortfolioSwitcher.test.tsx __tests__/usePortfolioMetrics.test.tsx`

---

## Issue F-003: Sidebar watchlist shows empty state even when stocks exist (Image #3 left, Image #4)

### Summary
The sidebar `<WatchlistPanel>` queries `getWatchlists()` and reads `activeWatchlist.members` to drive the row list. But `getWatchlists()` is documented to return watchlists *without* member arrays for performance — the S1 list endpoint omits members and expects callers to do a second `getWatchlist(id)` round trip when they need them. The panel never makes that second call, so `members` is always `[]` → the empty-state copy "Add symbols in Watchlists" is shown unconditionally even when the watchlist has actual members (visible in `/watchlists/[id]`).

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: user (Image #4) + code inspection + the watchlists.ts file-level doc itself

### Root Cause Analysis
- **What**: `apps/worldview-web/components/shell/WatchlistPanel.tsx:124-141` calls `getWatchlists()` and reads `activeWatchlist?.members ?? []`; `apps/worldview-web/lib/api/watchlists.ts:76-95` returns `Watchlist[]` where `members` is always an empty array (per the gateway's own JSDoc).
- **Why**: The gateway's `mapRawWatchlist` accepts an optional `members` argument; in `getWatchlists()` (plural) it's not passed → defaults to `[]`. The S1 `/v1/watchlists` list endpoint intentionally omits members for performance; the `/v1/watchlists/{id}/members` endpoint is the real source.
- **When**: Always, for every user with at least one watchlist that has members. The empty state only happens to be "correct" when the watchlist genuinely has zero members.
- **Where**: Boundary issue — the WatchlistPanel consumes the wrong gateway method for its use case.
- **History**: **Pre-existing bug, not a W1 regression.** The pre-W1 WatchlistPanel had the exact same logic (`createGateway(accessToken).getWatchlists()`). The user only just noticed because the W1 sparkline column promised meaningful data per row — making the persistent empty state painful.

### Evidence
```ts
// apps/worldview-web/lib/api/watchlists.ts:35-39 (file-level doc)
//   list/watchlists endpoint returns shallow rows (no members array). To populate
//   the members the consumer must call getWatchlist(id) or getWatchlistMembers(id)
//   as a second round trip.
```
```ts
// apps/worldview-web/lib/api/watchlists.ts:84
async getWatchlists(): Promise<Watchlist[]> {
  /* maps each raw row via mapRawWatchlist(raw)  ←  members defaults to [] */
}
```
```tsx
// apps/worldview-web/components/shell/WatchlistPanel.tsx:124
queryFn: () => createGateway(accessToken).getWatchlists(),
// ... members: WatchlistMember[] = activeWatchlist?.members ?? [];  ← always []
```

### Impact
- **Immediate**: Sidebar watchlist is decorative — never shows actual symbols.
- **Blast radius**: Sidebar only. The /watchlists page uses `getWatchlist(id)` and works correctly.
- **Data risk**: None.
- **User impact**: High — sidebar watchlist is the primary "always-visible quotes" surface of the entire shell. Verbatim: "Watchlists rendering in the left side bar seems to be broken, and it does not display any stock even if there exists stock".

### Solution Options

#### Option A: Add a second TanStack query for the active watchlist's members
**Description**: After the list fetch resolves and we know `activeWatchlist.watchlist_id`, fire a dependent `useQuery({ queryKey: qk.watchlists.members(id), queryFn: () => createGateway(...).getWatchlistMembers(id) })`. Use its result for `members` instead of `activeWatchlist.members`.
**Changes required**:
- [ ] `components/shell/WatchlistPanel.tsx` — add the dependent query; consume its `data` array for `displayMembers`
- [ ] `__tests__/shell/WatchlistPanel.test.tsx` — add `getWatchlistMembers` to the mock surface; assert rows render once both queries resolve
**Benefits**:
- Minimal change (~15 LOC)
- Uses the existing `qk.watchlists.members(id)` query key (already defined in lib/query/keys.ts)
- Reuses TanStack cache so /watchlists hub doesn't re-fetch the same members
**Drawbacks**:
- Adds one extra round trip per watchlist switch (60 s staleTime mitigates)
**Effort**: Low (~15 LOC)
**Risk**: Low

#### Option B: Promote `getWatchlists()` to fetch members in parallel via `Promise.all`
**Description**: Extend the gateway method to optionally hydrate members for every watchlist in one go.
**Drawbacks**: N+1 round trips on every list fetch (1 + N); cost grows linearly with how many watchlists the user has. The /watchlists hub doesn't need members. Better-targeted fix is to scope the hydration to the active id only.
**Effort**: Low-Medium
**Risk**: Medium (perf)

#### Option C: Add S1 `?expand=members` query param to the list endpoint
**Description**: Backend change — extend `/v1/watchlists` to accept `?expand=members` and return the union shape. PRD-0089 §D-DISCUSS-9 actually called for exactly this (`?expand=quotes,sparklines`).
**Drawbacks**: Needs backend work; longer turnaround
**Effort**: Medium-High
**Risk**: Medium

### Recommended Option
**Option A** — fastest path to a working sidebar; matches the existing `qk.watchlists.members(id)` key the codebase already defined. Option C is the long-term answer (DISCUSS-9) but does not block this fix.

### Verification Steps
- [ ] Open `/dashboard` with a watchlist that has members — sidebar shows real ticker rows with prices + sparklines + FreshnessDot
- [ ] Switch watchlists via the header dropdown — rows update within 1 s
- [ ] `pnpm vitest run __tests__/shell/WatchlistPanel.test.tsx`

---

## Issue F-004: IndexStrip `^TNX` cell shows `TNX — —` (MAJOR)

**Severity**: MAJOR
**Confidence**: HIGH
**File**: `apps/worldview-web/components/shell/IndexStrip.tsx` (manifest line 60–68)

### Issue
The W1 manifest swapped USO out for `^TNX` (10-Year Treasury yield) per FU-4.3. The chart shows `TNX` label correctly but the price and chg% slots are both `—` because `searchInstruments("^TNX", 1)` does not return an `instrument_id` from the S1 search index — the caret prefix is not a normal lookup term. Other cells (SPY, QQQ, IWM, DIA, TLT) resolve fine because their tickers are unambiguous symbols.

### Solution Options

#### Option A: Hard-map the ^TNX instrument_id in the manifest
**Description**: Pre-resolve treasury yield IDs at design time (or via a small dev script) and skip the search step for those cells.
**Drawbacks**: Hard-coded UUIDs drift if the seed/migration changes them; ugly.

#### Option B: Drop the caret in the search query
**Description**: When resolving, try `cell.ticker.replace(/^\^/, "")` first; if no results, fall back to the literal caret form. Same display label, same URL form, just a more lenient resolver.
**Effort**: Low (~5 LOC)
**Risk**: Low

#### Option C: Replace `^TNX` with a different rates ticker that does index
**Description**: e.g. swap to TLT-tracked yield ETF or to the `US10Y` mnemonic the API may already accept.
**Drawbacks**: Loses the "yield" signal the FU-4.3 swap intended.

### Recommended Option
**Option B** — most resilient; matches the lenient-resolver pattern in lib/api/search.ts.

### Verification Steps
- [ ] Reload `/dashboard` — TNX cell shows a real yield value + change (the demo data should include `TNX` quote)
- [ ] Add a TopBar test that mocks searchInstruments returning `{results: [{instrument_id: "id-TNX"}]}` for the `TNX` query

---

## Issue F-005: IWM / VIX / DIA cells show `0.00 / +0.00%` (MINOR — data, not W1)

**Severity**: MINOR
**Confidence**: MEDIUM
**File**: backend / demo seed — not W1 code

### Issue
The IndexStrip resolves IWM / VIX / DIA to instrument IDs successfully (their cells render), but the `POST /v1/quotes/batch` response returns `price: 0` and `change_pct: 0` for those tickers. The demo data backend doesn't have recent quotes seeded for these. Not a W1 bug — pre-existing seed gap.

**Fix**: Open a separate ticket against the demo seed pipeline (`make seed` should populate ETF quotes for the IndexStrip manifest).

**Auto-fixable**: NO — backend data work.

---

## Recommendations

Priority-ordered, actionable:

1. **F-003 (sidebar watchlist members)** — apply Option A immediately. 15 LOC, instant value, low risk. The most user-visible of the three.
2. **F-001 (PortfolioRail always visible)** — apply Option A immediately as part of the same small follow-up branch. 15 LOC.
3. **F-002 (PortfolioSwitcher wiring)** — apply Option B on the same follow-up. ~80 LOC. Without this, the user keeps asking "what does this control?".
4. **F-004 (^TNX cell)** — apply Option B; trivial.
5. **F-005 (IWM/VIX/DIA zero quotes)** — open separately as a demo-seed bug; not blocking.

Suggested branch + commit cadence for items 1–4:
- Branch `feat/plan-0089-w1.1-followup`
- Commit 1: `fix(plan-0089-w1.1/watchlist-members): hydrate active watchlist members`
- Commit 2: `fix(plan-0089-w1.1/portfolio-rail): always render rail with em-dash placeholders`
- Commit 3: `feat(plan-0089-w1.1/portfolio-selection): wire PortfolioSwitcher → usePortfolioMetrics via ActivePortfolioContext`
- Commit 4: `fix(plan-0089-w1.1/index-strip-tnx): resolve ^TNX without the caret prefix`

Total expected diff: ~130 LOC + tests. Single container rebuild covers the four.

---

## Compounding Check

- **BUG_PATTERNS.md**: F-003 is a clear new pattern — "consumer of `getWatchlists()` assumes members are populated; that endpoint deliberately omits them". Adding to BP-XXX would prevent recurrence. **Recommend adding.**
- **REVIEW_CHECKLIST.md**: Add "when a component calls `getWatchlists()`, does it also fetch members via `getWatchlistMembers()`?" to the data-platform checklist.
- **HIGH_RISK_PATTERNS.md**: F-001's render-gate pattern (`{value != null && box}`) is a recurring anti-pattern — surfaces collapse and create layout shift. Add a rule: "Chrome elements (TopBar, sidebar, status bar) must reserve their slot via skeleton/placeholder rather than collapse."
- **DESIGN_SYSTEM.md**: §4.1 Global Shell entry should add an explicit "TopBar slots are always rendered — even when their data is null they reserve width via em-dash placeholders."
- **Skill definitions**: no updates needed.

I will add the three additions above only after the user confirms the fix plan, so we capture the exact resolved behaviour rather than a hypothetical one.
