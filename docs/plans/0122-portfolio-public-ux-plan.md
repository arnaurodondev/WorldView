---
id: PLAN-0122
title: "Portfolio Public-Launch UX — Dual-Mode Page, Trusted Brokerage Connect, and Manual-Position Editing"
prd: PRD-0122
status: done
created: 2026-07-09
updated: 2026-07-09
---

# PLAN-0122 — Portfolio Public-Launch UX — Dual-Mode Page, Trusted Brokerage Connect, and Manual-Position Editing

## Overview

**PRD**: [PRD-0122](../specs/0122-portfolio-public-ux.md)
**Services affected**: `apps/worldview-web` (Next.js 15 frontend) — **frontend-only**. No backend, no S9 gateway, no Alembic, no Kafka, no Avro. PRD §8 proves this exhaustively.
**Total waves**: 6 (W-A … W-F, preserving the PRD §15 wave structure)

### Goal

Take the portfolio product **public** by putting a **Simple mode** in front of today's power-user layout — a *rendering gate, never a fork* — plus three trust/edit upgrades that are pure client-side unlocks of already-existing backend capability:

1. **Dual-mode `/portfolio`** (Simple default, Advanced opt-in) driven by one `mode` value threaded down as a prop; every power-user surface conditionally renders. Advanced === today's output, byte-for-byte (guarded by a snapshot test).
2. **Brokerage connect trust + honest timing copy** (two pure copy blocks).
3. **Add Position trade-date picker + debounced ticker typeahead** over the existing `searchInstruments` endpoint.
4. **Edit Position (honest adjusting BUY/SELL trade), partial close, and a visible row-kebab affordance** — all via the existing `POST /v1/transactions`.
5. **Holdings column-group toggle** (Core / Portfolio / Advanced) layered over the existing AG-Grid state persistence.
6. **A dismissible, non-blocking onboarding tour** after first portfolio creation (custom shadcn `Popover` state machine — **no new dependency**).

### The key enabling fact (drives sequencing)

**The backend is already sufficient — every capability this PRD ships is a frontend unlock** (PRD §1.2, §8):
- `executed_at` is a first-class field on `POST /v1/transactions` today; the "always now" Add-Position behaviour is a frontend omission (`lib/api/portfolios.ts:656` hardcodes `new Date().toISOString()`).
- A partial SELL is already valid — `quantity` is validated only as positive; Close's read-only quantity is a frontend lock.
- Holdings are **derived** from transactions and there is **no** transaction PATCH/DELETE — so Edit Position **must** be an adjusting trade, never an in-place edit (PRD §1.2.4, §6.4).
- The ticker-search endpoints already exist and are public (`searchInstruments` → `GET /v1/search/instruments`); we only add a debounced typeahead in front of them.

So risk concentrates in **W-A/W-B** (the render gate must not become a fork; existing e2e must be forced into Advanced) and **W-D** (the honest adjusting-trade mechanism), not in any new wiring.

### Sub-Plans

This is a single cohesive plan (one sub-plan **A — Portfolio Public-Launch UX**) because every wave threads through the same `mode` value and the same portfolio page tree (`page.tsx` → `HoldingsTab` → `SemanticHoldingsTable`); splitting by "feature" would fragment the mode-gate contract that W-A establishes and W-B/W-E depend on. Task IDs: `T-A-<wave-letter>-<seq>` (e.g. `T-A-A-01`).

### Dependency graph

```
W-A (mode-state hook + PortfolioModeToggle + prop threading, default still Advanced
     behind PORTFOLIO_SIMPLE_DEFAULT=false + Advanced-snapshot parity test)
     │  establishes the single mode value + the regression guard
     ▼
W-B (full Simple render matrix: KPI variant, tab-bar gate, strip gates, 4-tile
     skeleton; flip PORTFOLIO_SIMPLE_DEFAULT=true; force existing e2e to Advanced)
     │  Simple/Core wiring now exists
     ├─────────────────────────────► W-E (column-group toggle — needs Simple/Core wiring)
     ▼
W-C (brokerage trust + timing copy; Add-Position trade-date + typeahead + gateway
     tradeDate param)                    ── INDEPENDENT of W-B (can land before/after)
     ▼
W-D (EditPositionDialog + adjusting-transaction helper; partial-close un-lock;
     pinned-right ACTIONS kebab reusing the floating menu)
     ▼
W-F (onboarding tour + create-dialog trigger; docs; e2e hardening + new specs)
```

- **W-A → W-B is a strict chain** on the mode contract (Simple gating needs the hook + toggle + prop threading).
- **W-C is independent** — brokerage copy + Add-Position typeahead touch disjoint files (PRD §10.3); it MAY be authored in parallel with W-B.
- **W-E depends on W-B** — it reuses the Simple-forces-Core wiring and the `mode` prop on `SemanticHoldingsTable`.
- **W-D depends on W-A** only for the `mode`-aware table entry points (the ACTIONS kebab is a Core-group column); its dialogs are additive and independent of Simple gating.
- **W-F is last** — the tour anchors `data-tour-target` attributes added across W-A (mode toggle), W-C (Add Position button), and W-E (column toggle), and the e2e hardening must run after every surface exists.

### Wave summary

| Wave | Title | Reqs | Size | Depends on |
|------|-------|------|------|-----------|
| W-A | Mode scaffold: `usePortfolioMode` + `PortfolioModeToggle` + prop threading (default Advanced) + Advanced-snapshot parity test | R-1, R-6, R-7 | M | none |
| W-B | Full Simple render matrix (KPI variant, tab-bar gate, strip gates, 4-tile skeleton) + flip default to Simple + force existing e2e to Advanced | R-2, R-3, R-4, R-5 | L | W-A |
| W-C | Brokerage trust block + honest callback copy; Add-Position trade-date + debounced typeahead + gateway `tradeDate` param | R-8, R-9, R-10, R-11, R-12, R-13, R-14 | M | none (soft: W-A for `data-tour-target`) |
| W-D | EditPositionDialog + adjusting-transaction helper; partial-close un-lock; pinned-right ACTIONS kebab reusing the floating menu | R-15, R-16, R-17, R-18, R-19, R-20, R-21, R-22, R-23 | L | W-A |
| W-E | Column-group metadata + `HoldingsColumnGroupToggle` + persistence + Simple/Advanced interaction | R-24, R-25, R-26, R-27 | M | W-B |
| W-F | `PortfolioTour` + create-dialog trigger; docs; e2e hardening (force Advanced + new Simple/typeahead/edit/tour specs) | R-28, R-29, R-30, R-31 | M | W-A…W-E |

---

## Phase 0.5 — PRD Pre-Flight Gate

| Check | Result | Note |
|-------|--------|------|
| No unresolved BLOCKING open questions | **PASS** | §14 has 5 OQs, all DEFERRED with an assumption-to-proceed; none BLOCKING. |
| No unverified external API fields | **PASS** | Zero backend changes; every endpoint used is verified existing (PRD §8 file:line). |
| No active cross-plan conflicts | **PASS (with a declared dependency + soft file overlap)** | The frontend-touching active plans are **PLAN-0114** (the declared `depends-on`; in-progress 4/6 — W1/W2/W5/W6 shipped, **W3–W4 pending**) and **PLAN-0105** (frontend portfolio latency; in-progress). PLAN-0114 already shipped the exact baseline this PRD builds on (`ClosePositionDialog`, `SemanticHoldingsTable` context-menu wiring, `ag-holdings-columns.tsx` `DIV YLD hide:true`, `CreatePortfolioDialog` `CostBasisMethodSelector`, `EditPortfolioDialog`, `patchPortfolio`) — verified present this session. **Soft overlap**: PLAN-0114 **W4 "Holdings tab polish" (pending)** edits the same `features/portfolio/components/HoldingsTab.tsx` that PLAN-0122 W-B gates — sequence 0114 W4 first or rebase W-B onto it. PLAN-0105's shipped `portfolio-overview-*` Playwright specs are in this plan's force-Advanced audit set (T-A-B-05 / W-B guardrail). PLAN-0119/0121 touch S6/S7/libs/k3s — no overlap. **Not blocking** (dependency declared), but the HoldingsTab.tsx W4↔W-B overlap is a sequencing note for the implementer. |
| PRD recency | **PASS** | Created 2026-07-09 (today). |
| Architecture compliance | **PASS** | §7.1 gate: R14 (frontend→S9 only), R15 (docs), R19 (never weaken tests), DS shadcn-only, pnpm/0-CVE all PASS; no FAIL rows. |

Gate clears — decomposition proceeds.

---

## Codebase State Verification (read from code — authoritative)

Paths are relative to `apps/worldview-web/`. Confirmed present this session (frontend has NO `src/` prefix; components split between `components/portfolio/` and `features/portfolio/components/`; tests in `components/portfolio/__tests__/`; e2e in `e2e/`; root-level `hooks/` and `lib/`).

| PRD Reference | Type | Actual Current State (from code / PRD §4) | PRD Expected State | Delta |
|--------------|------|-------------------------------------------|--------------------|-------|
| `app/(app)/portfolio/page.tsx` | page shell | Thin client shell; `usePortfolioData()` owns 8 queries + KPI maths; header → PerformanceStrip → KPI strip (8 tiles) + `SectorAllocationDonut` → 4 `Tabs` (Holdings/Transactions/Analytics/Watchlist); dialogs lazy via `next/dynamic`; `nuqs` URL state for `?tab`/`?period`/`?sector`; loading skeleton assumes 8 tiles + donut (l.283-317). | read `mode`; gate KPI-tile count, tab bar, donut, strips on mode; render mode toggle; mount `PortfolioTour`; skeleton matches active mode. | **W-A** (thread `mode`) + **W-B** (gate) + **W-F** (tour) |
| `features/portfolio/components/PortfolioPageHeader.tsx` | header | Stateless; portfolio selector, count badge, Add Position / New Portfolio / Delete, ROOT hint, scope sub-line. | render `PortfolioModeToggle` in the action row (left of Add Position); `data-tour-target` on the Add Position button. | **W-A** + **W-C** (tour target) |
| `components/portfolio/PortfolioKPIStrip.tsx` | KPI strip | 8 tiles via `divide-x`: Total Value, Day P&L, Unrealised P&L, Realized P&L, Cash, Buying Pwr, Top Gain, Top Lose. `positionCount` deprecated. | gains `variant?: "simple"\|"advanced"` (default `"advanced"`); Simple returns after the 4th tile (Total Value / Day P&L / Unrealised P&L / Cash). | **W-B** |
| `features/portfolio/components/HoldingsTab.tsx` | holdings body | 7-row anchored layout: overview band, concentration strip, perf chart, sector bar, table chrome, `SemanticHoldingsTable`, bottom cluster; brokerage strips; detail-pill row + slide-over; sector-filter chip. | gains `mode?: "simple"\|"advanced"` (default `"advanced"`); Simple wraps each power-strip in `mode==="advanced" && (…)`; passes Simple column-group to the table. | **W-B** |
| `components/portfolio/SemanticHoldingsTable.tsx` | AG-Grid table | TICKER pinned-left; column state persisted to localStorage `worldview-holdings-cols` via `applyColumnState` (l.243-277 `handleGridReady`); URL-backed sort; floating right-click context menu (`useContextMenuActions`) + hand-added "Close Position" group; pinned bottom TOTAL row. | gains `mode`/`columnGroups` prop → apply group visibility via `setColumnsVisible` AFTER `applyColumnState` restore; add pinned-right ACTIONS renderer opening the same floating menu; wire Edit + partial-close entry points. | **W-D** (kebab) + **W-E** (groups) |
| `components/portfolio/ag-holdings-columns.tsx` | column defs | 15 colIds `ticker,name,qty,avg_cost,current,dayChange,dayChangePct,spark,value,pnl,pnlPct,weight,sector,asset,divYld`; `divYld hide:true` default, rest visible. | add `group:"core"\|"portfolio"\|"advanced"` metadata per colId; add `actions` colId (pinned right, `suppressMovable`, `sortable:false`, `lockPinned:"right"`). | **W-D** (actions col) + **W-E** (group metadata) |
| `features/portfolio/components/AddPositionDialog.tsx` | add dialog | RHF + Zod; ticker `<Input>` uppercased; NumberInput qty (>0); optional avg price; on submit `searchInstruments(ticker,1)` → `addPosition()`. **No date, no typeahead.** | add `tradeDate` date picker (default today, `max=today`, Zod refine ≤ today); replace ticker `<Input>` with a `Command` combobox (debounced 250ms `searchInstruments(q,8)`); stash resolved `instrument_id`; keep submit-time fallback. | **W-C** |
| `components/portfolio/ClosePositionDialog.tsx` | close dialog | Ticker + **read-only** quantity (full close only, l.269-275); Sale Price (>0); Trade Date (default today); POST SELL with idempotency key. | un-lock quantity → editable NumberInput, default full; validate `0 < qty ≤ holding.quantity`; Full/Partial affordance + dynamic title. | **W-D** |
| `components/brokerage/ConnectBrokerageModal.tsx` | connect modal | SnapTrade blurb + ToS link + consent checkbox; Connect → `initiate` → redirect. **No credentials-safety reassurance.** | add a bordered `ShieldCheck` trust block above the ToS notice (`data-testid="brokerage-trust-block"`); ToS checkbox unchanged. | **W-C** |
| `app/(app)/portfolio/brokerage/callback/page.tsx` | callback | idle→loading→success→error; success heading *"Brokerage account connected successfully!"* + sub-copy *"will begin syncing shortly."* (misleading). | **keep the heading** (e2e-pinned); replace only the sub-copy with honest "few minutes … up to a few hours … Sync Now" timing. | **W-C** |
| `lib/api/portfolios.ts` | gateway | `addPosition(portfolioId, instrumentId, qty, avgCost)` hardcodes `executed_at: new Date().toISOString()` (l.656); `addTransaction(tx)` honours `tx.executed_at ?? now` (l.721); `deletePortfolio()`. | `addPosition` gains optional `tradeDate?: string` (ISO) → used for `executed_at` when present, else preserves now. | **W-C** |
| `lib/api/search.ts` | search API | `searchInstruments(q,limit)` → `GET /v1/search/instruments` (public, no token); `searchFundamentals`; `resolveTickersBatch`. | reuse `searchInstruments` in the typeahead (TanStack Query key `["instrument-search", query]`). | reuse (no change) |
| `features/portfolio/components/CreatePortfolioDialog.tsx` | create dialog | RHF + Zod create; `onSuccess` invalidates + closes. | `onSuccess` sets `localStorage["worldview:portfolioTourSeen:v1"]="pending"` **only if unset**. | **W-F** (additive, no field change) |
| `hooks/usePortfolioMode.ts` | mode hook | **absent** (root `hooks/` dir exists). | new hook: localStorage `worldview:portfolioMode:v1` + nuqs `?mode=` param; default `simple`; precedence URL→localStorage→default; `{mode,setMode}`. | **W-A** (NEW) |
| `components/portfolio/PortfolioModeToggle.tsx` | toggle | **absent**. | new 2-segment `Simple\|Advanced` control, `role="radiogroup"`, `data-tour-target="mode-toggle"`. | **W-A** (NEW) |
| `components/portfolio/EditPositionDialog.tsx` | edit dialog | **absent**. | new adjusting-trade dialog (§6.4). | **W-D** (NEW) |
| `components/portfolio/HoldingsColumnGroupToggle.tsx` | column toggle | **absent**. | new `Settings2` ⚙ `Popover` with Core(locked)/Portfolio/Advanced checkboxes + Reset, `data-tour-target="column-toggle"`. | **W-E** (NEW) |
| `components/portfolio/PortfolioTour.tsx` | tour | **absent**. | new custom shadcn `Popover` state machine (≤5 steps). | **W-F** (NEW) |
| `lib/portfolio/holdings-column-groups.ts` | group config | **absent** (`lib/portfolio/` dir absent). | new module: Core/Portfolio/Advanced colId membership + Advanced default + localStorage `worldview:holdingsColGroups:v1`. | **W-E** (NEW) |
| `lib/portfolio/adjusting-transaction.ts` | delta helper | **absent**. | new pure `computeAdjustment(currentQty, targetQty) → {side, quantity}`. | **W-D** (NEW) |
| e2e specs | Playwright | `plan0108-portfolio-redesign.spec.ts`, `portfolio-overview-density.spec.ts`, `portfolio-overview-no-tabs.spec.ts`, `qa-exhaustive.spec.ts`, `transactions-filters.spec.ts` all present; they assert **full-layout** structure. | force **Advanced** (seed `localStorage["worldview:portfolioMode:v1"]="advanced"` or nav `?mode=advanced`) so they keep passing (R19); add new Simple/typeahead/edit/tour/copy specs. | **W-B** (force Advanced) + **W-F** (new specs) |

**Every Delta row maps to a task below.** No row requires a backend change (PRD §8 confirmed).

### Name verification (BP-405 pass)

- **Existing** (verified this session): `app/(app)/portfolio/page.tsx`, `PortfolioPageHeader.tsx`, `PortfolioKPIStrip.tsx`, `HoldingsTab.tsx`, `SemanticHoldingsTable.tsx`, `ag-holdings-columns.tsx`, `AddPositionDialog.tsx`, `ClosePositionDialog.tsx`, `ConnectBrokerageModal.tsx`, `brokerage/callback/page.tsx`, `CreatePortfolioDialog.tsx`, `lib/api/portfolios.ts` (`addPosition`, `addTransaction`, `deletePortfolio`), `lib/api/search.ts` (`searchInstruments`, `resolveTickersBatch`), `hooks/` dir, `e2e/` specs listed above, `components/portfolio/__tests__/`.
- **NEW — created in this plan**: `hooks/usePortfolioMode.ts`; `components/portfolio/PortfolioModeToggle.tsx`; `components/portfolio/EditPositionDialog.tsx`; `components/portfolio/HoldingsColumnGroupToggle.tsx`; `components/portfolio/PortfolioTour.tsx`; `lib/portfolio/holdings-column-groups.ts`; `lib/portfolio/adjusting-transaction.ts`; the `PORTFOLIO_SIMPLE_DEFAULT` build-time constant (`lib/portfolio/mode-flag.ts`, NEW); localStorage keys `worldview:portfolioMode:v1`, `worldview:holdingsColGroups:v1`, `worldview:portfolioTourSeen:v1`; the `actions` AG-Grid colId; the `variant` prop on `PortfolioKPIStrip`; the `mode` prop on `HoldingsTab`/`SemanticHoldingsTable`; new e2e specs `portfolio-simple-mode.spec.ts`, `portfolio-add-position-typeahead.spec.ts`, `portfolio-edit-partial-close.spec.ts`, `portfolio-onboarding-tour.spec.ts`, `brokerage-connect-copy.spec.ts`; new unit tests enumerated per wave.

---

## Wave A: Mode scaffold — state hook + toggle + prop threading (default Advanced) + Advanced-snapshot parity

**Goal**: Land the single `mode` value (localStorage + URL, default *would be* Simple but the build-time flag `PORTFOLIO_SIMPLE_DEFAULT=false` keeps production on Advanced), the header toggle, and the prop plumbing into `page.tsx`/`HoldingsTab`/`SemanticHoldingsTable` — with an **Advanced-mode snapshot test** proving the rendered tree is byte-identical to today. **No power-user surface is hidden yet** (that is W-B); this wave is pure scaffolding + the regression guard.
**Depends on**: none
**Estimated effort**: 60–90 min
**Architecture layer**: shared hook + page shell + prop threading (no gating logic yet)
**Satisfies**: R-1, R-6, R-7

#### Tasks

#### T-A-A-01: `PORTFOLIO_SIMPLE_DEFAULT` flag + `usePortfolioMode` hook
**Type**: impl
**depends_on**: none
**blocks**: [T-A-A-02, T-A-A-03]
**Target files**: `apps/worldview-web/lib/portfolio/mode-flag.ts` (NEW), `apps/worldview-web/hooks/usePortfolioMode.ts` (NEW), `apps/worldview-web/hooks/__tests__/usePortfolioMode.test.tsx` (NEW)
**PRD reference**: §6.1 "State source (R-1)", §10.1

**What to build**: The single source of the mode value + the rollout flag. The hook resolves precedence URL → localStorage → default, writes BOTH sinks on change (sticky + shareable), and is the ONLY place any component reads/writes the mode.

**Entities / Components**:
- `PORTFOLIO_SIMPLE_DEFAULT` const in `lib/portfolio/mode-flag.ts`: `export const PORTFOLIO_SIMPLE_DEFAULT = false;` — a build-time constant (NOT env-driven; a literal edit in W-B flips it) with a heavy WHY-comment: "rollout gate — while `false`, an unset user still lands on Advanced (today's behaviour) so production is unchanged until W-B proves parity; flipping to `true` makes Simple the public default (§10.2). Rollback = set back to `false`."
- `usePortfolioMode()` hook returns `{ mode: "simple" | "advanced", setMode: (m) => void }`:
  - **localStorage key**: `worldview:portfolioMode:v1`.
  - **URL param**: `?mode` via `nuqs` `useQueryState("mode", parseAsStringLiteral(["simple","advanced"]).withOptions({ clearOnDefault: true }))`.
  - **Default**: `PORTFOLIO_SIMPLE_DEFAULT ? "simple" : "advanced"` when neither URL nor localStorage is set.
  - **Precedence**: URL param (if present) wins for this render; else localStorage; else default.
  - `setMode(m)` writes the nuqs param AND `localStorage.setItem("worldview:portfolioMode:v1", m)`.
  - SSR-safe: read localStorage inside `useEffect` (never during render); hydrate to default first, reconcile in effect to avoid a hydration mismatch.

**Logic & Behavior**: pure client state. No API. When `PORTFOLIO_SIMPLE_DEFAULT` is `false` (this wave) an unset user resolves to `"advanced"` — production is unchanged; the flag flips in T-A-B-05.

**Tests to write** (inline, Vitest + Testing Library):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_mode_default_follows_flag | flag `false` + no URL/localStorage → `mode==="advanced"`; (parametrised) flag `true` → `"simple"` | unit |
| test_mode_url_param_wins | `?mode=advanced` overrides a localStorage `simple` for this render | unit |
| test_setmode_writes_both_sinks | `setMode("advanced")` sets localStorage key AND the nuqs param | unit |
| test_mode_localstorage_when_no_url | no URL param + localStorage `advanced` → `"advanced"` | unit |
- Minimum test count: 4
- Edge cases: corrupted localStorage value (not in the literal set) → falls back to default; SSR first render uses default (no `window`).

**Acceptance criteria**:
- [ ] Hook returns `{mode,setMode}`; precedence URL→localStorage→default honoured; both sinks written on change.
- [ ] `PORTFOLIO_SIMPLE_DEFAULT=false` this wave (production unchanged); heavy WHY-comment present.
- [ ] No hydration warning (localStorage read only in effect); typecheck + lint clean.

#### T-A-A-02: `PortfolioModeToggle` component + header mount
**Type**: impl
**depends_on**: [T-A-A-01]
**blocks**: [T-A-A-04]
**Target files**: `apps/worldview-web/components/portfolio/PortfolioModeToggle.tsx` (NEW), `apps/worldview-web/features/portfolio/components/PortfolioPageHeader.tsx` (MODIFY — action row), `apps/worldview-web/components/portfolio/__tests__/PortfolioModeToggle.test.tsx` (NEW)
**PRD reference**: §6.1 "Mode toggle control (R-6)"

**What to build**: A 2-segment `Simple | Advanced` control mounted in the header action row (left of "Add Position"), wired to `usePortfolioMode`.

**Entities / Components**:
- `PortfolioModeToggle` props: `{ mode: "simple"|"advanced"; onModeChange: (m) => void }` (presentational; the header owns the hook so the toggle stays testable in isolation).
- Styling (DS terminal density): shadcn segmented/`Tabs`-style buttons, `h-6`, `text-[10px] uppercase`, active segment `bg-primary/10 text-primary`, container `role="radiogroup"`, `aria-label="Portfolio detail level"`, `title="Switch between a simple overview and the full analytics layout"`, `data-tour-target="mode-toggle"` (consumed by the W-F tour).
- Copy: labels exactly `"Simple"` and `"Advanced"`.
- **Header change**: call `usePortfolioMode()` in `PortfolioPageHeader`, render `<PortfolioModeToggle mode={mode} onModeChange={setMode} />` at the left of the existing action button row. Do NOT mount it in the empty-portfolio early-return branch (PRD §6.1: no data to show there).

**Logic & Behavior**: clicking a segment calls `onModeChange`; keyboard `role="radiogroup"` semantics (arrow keys optional, click/Enter required). Heavy inline comments (user new to Next.js) on the radiogroup a11y and the tour-target attribute.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_toggle_renders_two_segments | renders Simple + Advanced; active reflects `mode` prop | unit |
| test_toggle_calls_onchange | clicking Advanced fires `onModeChange("advanced")` | unit |
| test_toggle_has_tour_target_and_role | `data-tour-target="mode-toggle"` + `role="radiogroup"` present | unit |
- Minimum test count: 3

**Acceptance criteria**:
- [ ] Toggle renders in the header action row (not in the empty early-return); active segment matches `mode`.
- [ ] `role="radiogroup"`, `aria-label`, `title`, `data-tour-target` all present; DS density classes applied.

#### T-A-A-03: Thread `mode` through `page.tsx` → `HoldingsTab` → `SemanticHoldingsTable` (no gating yet)
**Type**: impl
**depends_on**: [T-A-A-01]
**blocks**: [T-A-A-04]
**Target files**: `apps/worldview-web/app/(app)/portfolio/page.tsx` (MODIFY), `apps/worldview-web/features/portfolio/components/HoldingsTab.tsx` (MODIFY — add `mode?` prop, default `"advanced"`), `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx` (MODIFY — accept optional `mode?` prop, unused this wave)
**PRD reference**: §6.1 "Rendering-gate implementation (R-7)"

**What to build**: Plumb the `mode` value from `page.tsx` (via `usePortfolioMode`) down as a prop. **Add the prop with default `"advanced"` everywhere** so every existing caller/test is unchanged and this wave produces identical output. NO conditional rendering is added yet — that is W-B.

**Entities / Components**:
- `page.tsx`: call `usePortfolioMode()`; pass `mode` to `PortfolioKPIStrip` (as a future `variant`, but this wave leave the strip untouched — pass nothing until W-B) and to `HoldingsTab` (`mode={mode}`). Keep the `<Tabs>` wrapper and all surfaces exactly as today.
- `HoldingsTab`: add `mode?: "simple" | "advanced"` to its props, default `"advanced"`; do not branch on it yet (thread-only).
- `SemanticHoldingsTable`: add `mode?: "simple" | "advanced"` prop (default `"advanced"`), unused this wave — reserved for W-D/W-E.

**Logic & Behavior**: prop-threading only. The defaults guarantee byte-identical output; the snapshot test (T-A-A-04) proves it.

**Tests to write** (inline): covered by T-A-A-04's snapshot + a shape assertion:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_holdingstab_defaults_mode_advanced | `HoldingsTab` without a `mode` prop behaves as `"advanced"` (renders all strips) | unit |
- Minimum test count: 1

**Acceptance criteria**:
- [ ] `mode` threaded `page → HoldingsTab → SemanticHoldingsTable`; all defaults `"advanced"`; no branch added.
- [ ] Every existing `HoldingsTab`/`SemanticHoldingsTable` test passes unchanged.

#### T-A-A-04: Advanced-mode snapshot parity test (the anti-fork guard)
**Type**: test
**depends_on**: [T-A-A-02, T-A-A-03]
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/__tests__/portfolio-advanced-snapshot.test.tsx` (NEW)
**PRD reference**: §6.1 "Invariant test", §9 `test_advanced_mode_is_todays_layout`, §11 (fork risk)

**What to build**: A component test that renders the portfolio Holdings surface in **Advanced** mode with a fixed fixture and asserts the rendered tree matches a committed snapshot (8 KPI tiles, tabs present, all strips present). This is the **merge gate** against a Simple/Advanced fork across W-B and every later wave — any accidental change to Advanced output fails here.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_advanced_mode_is_todays_layout | Advanced render (fixed fixture) === committed snapshot: 8 KPI tiles, `TabsList` with 4 triggers, overview band + concentration strip + perf chart + sector bar + bottom cluster all present | unit (snapshot) |
| test_advanced_mode_kpi_tile_count_is_eight | Advanced KPI strip renders exactly 8 tiles | unit |
- Minimum test count: 2
- The snapshot is captured from the current (pre-W-B) render so it encodes "today's layout"; it MUST NOT be regenerated to accommodate a Simple-mode regression — a diff here is a real fork bug.

**Acceptance criteria**:
- [ ] Snapshot captured from today's Advanced render and committed; test green.
- [ ] Documented in-file: "regeneration of this snapshot requires an explicit Advanced-layout change, never a Simple-mode side effect."

#### Pre-read (agent must read before starting)
- `apps/worldview-web/app/(app)/portfolio/page.tsx` (full — the `usePortfolioData` shell, the `<Tabs>` block, the loading skeleton l.283-317)
- `apps/worldview-web/features/portfolio/components/PortfolioPageHeader.tsx` (the action button row)
- `apps/worldview-web/features/portfolio/components/HoldingsTab.tsx` (props + the strip layout)
- an existing hook that uses `nuqs` (`git grep -l "useQueryState" apps/worldview-web/hooks apps/worldview-web/features/portfolio`) for the URL-state convention
- `apps/worldview-web/components/portfolio/__tests__/` (existing test setup / render helpers)
- `docs/ui/DESIGN_SYSTEM.md` §5.1 (shadcn primitives) + §6 density conventions

#### Validation Gate
- [ ] `pnpm lint` passes on changed files
- [ ] `pnpm typecheck` passes (`tsc --noEmit`)
- [ ] `pnpm vitest run components/portfolio hooks` — minimum **10** new tests green
- [ ] `test_advanced_mode_is_todays_layout` snapshot committed + green
- [ ] `PORTFOLIO_SIMPLE_DEFAULT === false` (production still Advanced this wave)
- [ ] No e2e change required this wave (default is still Advanced) — existing specs stay green

#### Architecture Compliance
- [ ] **R14 — Frontend → S9 only**: no new network calls; mode state is client-only (localStorage + URL).
- [ ] **R19 — Never weaken tests**: no existing test deleted; the Advanced-snapshot is additive.
- [ ] **DS — shadcn/ui only**: toggle uses shadcn `Tabs`/`Button` primitives, semantic tokens, `rounded-[2px]`, no new lib.
- [ ] **Heavy inline comments**: hook + toggle + flag carry WHY-comments (user new to Next.js).
- [ ] **pnpm / 0 CVE / exact versions**: no dependency added.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `features/portfolio/components/PortfolioPageHeader.tsx` tests (if any assert the exact action-row children) | a new toggle child is added to the action row | update the expected children / add an assertion for the toggle; do not remove existing assertions (R19) |
| `HoldingsTab` / `SemanticHoldingsTable` callers | new optional `mode?` prop | none — prop is optional with default `"advanced"`; no caller change needed |
| `app/(app)/portfolio/page.tsx` render tests | `usePortfolioMode` now called in the tree | ensure the test wraps in the nuqs/`NuqsAdapter` + a router mock the same way other URL-state portfolio tests do |

#### Regression Guardrails
- **CSS `hsl(var())` no-paint bug class** (memory `feedback` / frontend sprint): the toggle uses semantic tokens (`bg-primary/10`) — verify the active segment actually paints in the dark theme, not a transparent no-op.
- **Hydration mismatch**: localStorage MUST be read in `useEffect`, never during render, or SSR/CSR diverge — the default-first-then-reconcile pattern is mandatory.
- **Anti-fork invariant**: `test_advanced_mode_is_todays_layout` is the permanent tripwire for the PRD's #1 risk (Simple/Advanced drift) — it must exist and stay green through W-F.
- **Frontend comment density** (feedback): the mode precedence logic is subtle — comment WHY URL wins over localStorage (shareable links).

---

## Wave B: Full Simple render matrix + flip default to Simple + force existing e2e to Advanced

**Goal**: Implement every §6.1 per-mode gate — 4-tile KPI variant, tab-bar hidden in Simple, all power-strips gated, 4-tile loading skeleton — so Simple shows exactly {4 KPI tiles, PerformanceStrip, brokerage strips, Core-column Holdings list} and Advanced is unchanged. Then flip `PORTFOLIO_SIMPLE_DEFAULT=true` and **force the 5 existing e2e specs into Advanced** so they keep passing (R19). This is the largest wave; the Advanced-snapshot from W-A is the merge gate.
**Depends on**: W-A
**Estimated effort**: 120–150 min
**Architecture layer**: page shell + KPI strip + holdings body gating + e2e hardening
**Satisfies**: R-2, R-3, R-4, R-5

#### Tasks

#### T-A-B-01: `PortfolioKPIStrip` gains `variant` (Simple = 4 tiles)
**Type**: impl
**depends_on**: none (within-wave; uses W-A prop plumbing)
**blocks**: [T-A-B-04]
**Target files**: `apps/worldview-web/components/portfolio/PortfolioKPIStrip.tsx` (MODIFY), `apps/worldview-web/components/portfolio/__tests__/PortfolioKPIStrip.test.tsx` (MODIFY — add cases, keep 8-tile)
**PRD reference**: §6.1 render matrix "KPI tiles" row, §5 (KPI break surface), §9 `test_kpi_strip_variant_simple_renders_four_tiles`

**What to build**: Add `variant?: "simple" | "advanced"` (default `"advanced"`). Simple renders exactly the first 4 tiles — **Total Value, Day P&L, Unrealised P&L (with %), Cash** — and returns before the Realized P&L / Buying Pwr / Top Gain / Top Lose tiles. The `divide-x` equal-width invariant holds within each set.

**Entities / Components**:
- `PortfolioKPIStrip` prop `variant`; when `"simple"`, render only the 4-tile subset (in the order above) and stop; when `"advanced"` (default), render all 8 exactly as today (no output change).
- Heavy comment: WHY the Simple set answers the casual "what's it worth / today / total gain / free cash" question (PRD §6.1 note; OQ-3 assumption).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_kpi_strip_variant_simple_renders_four_tiles | `variant="simple"` → exactly Total Value / Day P&L / Unrealised P&L / Cash | unit |
| test_kpi_strip_default_variant_renders_eight | no `variant` → 8 tiles (backward compat) | unit |
| test_kpi_strip_simple_unrealised_shows_pct | Simple Unrealised tile still shows the % sub-value | unit |
- Minimum test count: 3 (existing 8-tile assertions PRESERVED — R19)

**Acceptance criteria**:
- [ ] `variant="simple"` → 4 tiles; default → 8 tiles unchanged; `divide-x` widths equal within each set.
- [ ] All prior `PortfolioKPIStrip.test.tsx` assertions kept; new Simple cases added.

#### T-A-B-02: Gate tab bar + donut + strips in `page.tsx`; 4-tile skeleton
**Type**: impl
**depends_on**: none (uses W-A `mode`)
**blocks**: [T-A-B-04, T-A-B-05]
**Target files**: `apps/worldview-web/app/(app)/portfolio/page.tsx` (MODIFY — `<Tabs>` block, donut render, skeleton l.283-317)
**PRD reference**: §6.1 render matrix rows: Allocation donut, Tabs, Loading skeleton; "Rendering-gate implementation (R-7)"

**What to build**: In `page.tsx`, gate on `mode`:
- Pass `variant={mode}` to `PortfolioKPIStrip`.
- `SectorAllocationDonut`: render only when `mode === "advanced"` (keep its existing `xl:flex` responsive behaviour inside that branch).
- **Tabs**: when `mode === "advanced"`, render the full `<Tabs>` with the 4-trigger `TabsList` exactly as today. When `mode === "simple"`, do NOT render `TabsList`; render `<HoldingsTab mode="simple" …/>` **directly** (PRD §6.1: prefer direct render over a 1-tab bar). The `?tab` nuqs param stays in the URL harmlessly and is ignored while Simple.
- **Loading skeleton** (l.283-317): when Simple, render a 4-tile skeleton with NO donut placeholder and table rows only; when Advanced, keep today's 8-tile + donut placeholder. Extract a small `mode`-aware skeleton helper so the two shapes are explicit.

**Logic & Behavior**: pure render gate; each branch's Advanced arm is byte-identical to today (verified by the W-A snapshot). Heavy comments explaining WHY Simple renders `HoldingsTab` directly (avoid a lone tab).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_page_simple_hides_tablist_and_donut | Simple render → no `TabsList`, no `SectorAllocationDonut`; Holdings body present | unit |
| test_page_advanced_shows_tablist_and_donut | Advanced render → `TabsList` (4 triggers) + donut present | unit |
| test_skeleton_simple_four_tiles_no_donut | loading + Simple → 4 skeleton tiles, no donut placeholder | unit |
| test_skeleton_advanced_eight_tiles_donut | loading + Advanced → 8 skeleton tiles + donut placeholder | unit |
- Minimum test count: 4

**Acceptance criteria**:
- [ ] Simple: no tab bar, no donut, `HoldingsTab` rendered directly with `mode="simple"`.
- [ ] Advanced: full tabs + donut unchanged (W-A snapshot still green).
- [ ] Skeleton matches active mode.

#### T-A-B-03: Gate power-strips inside `HoldingsTab` on `mode`
**Type**: impl
**depends_on**: none (uses W-A `mode` prop)
**blocks**: [T-A-B-04]
**Target files**: `apps/worldview-web/features/portfolio/components/HoldingsTab.tsx` (MODIFY — l.396-743 region)
**PRD reference**: §6.1 render matrix rows: Overview band, Concentration strip, Perf chart, Sector bar, Bottom cluster, Detail-pill row, Sector-filter chip, Brokerage strips

**What to build**: Wrap each power-user block in `mode === "advanced" && (…)` so Simple hides: the overview panel band (Market/Sector/Perf-periods, l.421-437), `ConcentrationSectorTeaseStrip`, `PerformanceChartPanel`, `SectorAllocationBar`, `BottomStripCluster`, the detail-pill row + `HoldingDetailSlideOver`, and the sector-filter chip row. **Keep shown in both modes**: `PerformanceStrip` (compact, casual-friendly) and the **brokerage sync strips / status banner** (still useful to casual brokerage users — PRD §6.1). Pass the Simple column-group to the table (Core-only) — the actual column-group mechanism lands in W-E; this wave passes `mode` to `SemanticHoldingsTable` and, until W-E, Simple relies on the table's `mode` to show a Core subset via a minimal inline guard (documented TODO pointing at W-E for the full toggle).

**Logic & Behavior**: many conditional guards; **Advanced output must be unchanged** (snapshot gate). Heavy comments on each gated block naming the PRD matrix row it implements.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_holdingstab_simple_hides_power_strips | Simple → no overview band, concentration, perf chart, sector bar, bottom cluster, detail-pill row, sector-filter chip | unit |
| test_holdingstab_simple_keeps_perf_and_brokerage | Simple → PerformanceStrip + brokerage status strip still rendered | unit |
| test_holdingstab_advanced_unchanged | Advanced → all strips present (matches W-A snapshot expectations) | unit |
- Minimum test count: 3

**Acceptance criteria**:
- [ ] Simple hides exactly the matrix-listed strips; keeps PerformanceStrip + brokerage strips.
- [ ] Advanced render unchanged; W-A snapshot green.

#### T-A-B-04: Flip `PORTFOLIO_SIMPLE_DEFAULT` to `true`
**Type**: config
**depends_on**: [T-A-B-01, T-A-B-02, T-A-B-03]
**blocks**: [T-A-B-05]
**Target files**: `apps/worldview-web/lib/portfolio/mode-flag.ts` (MODIFY — `false` → `true`)
**PRD reference**: §10.2 "flip `PORTFOLIO_SIMPLE_DEFAULT=true` only after the snapshot + Simple specs pass"

**What to build**: One-line flip: `export const PORTFOLIO_SIMPLE_DEFAULT = true;`. An unset user now lands on Simple (the public default). Update the WHY-comment to note the flip happened in W-B and rollback is setting it back to `false`.

**Logic & Behavior**: only do this AFTER T-A-B-01..03 and the T-A-A-04 snapshot are green — otherwise existing e2e (which don't yet force Advanced) break. Sequencing within the wave: T-A-B-05 (force e2e Advanced) MUST land in the same commit/wave so no spec observes Simple-by-default unexpectedly.

**Tests to write** (inline): the parametrised `test_mode_default_follows_flag` (T-A-A-01) now exercises the `true` branch as the live value.

**Acceptance criteria**:
- [ ] Flag is `true`; unset user resolves to Simple.
- [ ] Landed in the same wave as T-A-B-05 (e2e forced Advanced) so no spec regresses.

#### T-A-B-05: Force the 5 existing e2e specs into Advanced (R19-safe)
**Type**: test
**depends_on**: [T-A-B-04]
**blocks**: none
**Target files**: `apps/worldview-web/e2e/plan0108-portfolio-redesign.spec.ts`, `apps/worldview-web/e2e/portfolio-overview-density.spec.ts`, `apps/worldview-web/e2e/portfolio-overview-no-tabs.spec.ts`, `apps/worldview-web/e2e/qa-exhaustive.spec.ts`, `apps/worldview-web/e2e/transactions-filters.spec.ts`, **`apps/worldview-web/e2e/portfolio-overview-perf.spec.ts`** (the 6th — audited this session: it mocks + scrolls the full power-user layout, so it needs Advanced) (all MODIFY)
**PRD reference**: §5 Break Surface (E2E row, HIGH risk), §9 E2E "Update existing", R19

**What to build**: Every spec that asserts full-layout structure must load `/portfolio` in **Advanced** mode. **Verified-Simple-safe (leave unchanged, no `forceAdvancedMode`)**: `portfolio-overview-root-aware.spec.ts`, `portfolio-overview-ticker-click.spec.ts`, `portfolio-stub-routes.spec.ts`, `shell-portfolio-switcher.spec.ts` — they assert only header/shell/sub-route/Core-column surfaces present in both modes (audit conclusion recorded in the Break Impact table). Add a shared helper (e.g. `e2e/utils/forceAdvancedMode.ts`, NEW) that seeds `localStorage["worldview:portfolioMode:v1"]="advanced"` before navigation (via `page.addInitScript`) AND/OR navigates with `?mode=advanced`. Apply it in each spec's `beforeEach`/setup. **Do not weaken or delete any assertion** — the specs keep asserting the full layout; they just force the mode that shows it.

**Logic & Behavior**: `addInitScript` runs before app JS so the hook reads Advanced from localStorage on first paint (avoids a Simple flash then re-render). `?mode=advanced` is the belt-and-suspenders fallback for specs that hard-navigate.

**Tests to write**: no new assertions — this is a targeted fix to keep existing coverage green under the new default (R19). Optionally add one guard assertion per spec that the tab bar IS present (proves Advanced took effect).

**Acceptance criteria**:
- [ ] All 6 full-layout specs (the 5 named + `portfolio-overview-perf`) seed/navigate Advanced before asserting; all assertions preserved (R19). The 4 Simple-safe specs are left unchanged.
- [ ] `pnpm playwright test <each spec>` green under `PORTFOLIO_SIMPLE_DEFAULT=true`.
- [ ] The shared `forceAdvancedMode` helper is reused (no copy-paste drift).

#### Pre-read
- `apps/worldview-web/app/(app)/portfolio/page.tsx` (the `<Tabs>` block + skeleton l.283-317)
- `apps/worldview-web/features/portfolio/components/HoldingsTab.tsx:396-743` (the strip layout + which components are named)
- `apps/worldview-web/components/portfolio/PortfolioKPIStrip.tsx` (the 8-tile `divide-x` structure)
- the 5 e2e specs above (their `beforeEach` + the assertions that need Advanced)
- an existing e2e that uses `page.addInitScript` (`git grep -l "addInitScript" apps/worldview-web/e2e`) for the localStorage-seed pattern

#### Validation Gate
- [ ] `pnpm lint` + `pnpm typecheck` clean
- [ ] `pnpm vitest run components/portfolio features/portfolio` — minimum **13** new tests green
- [ ] `test_advanced_mode_is_todays_layout` (W-A snapshot) STILL green — the anti-fork gate
- [ ] `pnpm playwright test e2e/plan0108-portfolio-redesign.spec.ts e2e/portfolio-overview-density.spec.ts e2e/portfolio-overview-no-tabs.spec.ts e2e/qa-exhaustive.spec.ts e2e/transactions-filters.spec.ts e2e/portfolio-overview-perf.spec.ts` all green (forced Advanced)
- [ ] Documentation touch: none mandatory this wave (full docs in W-F), but note the mode gate in the PR description

#### Architecture Compliance
- [ ] **R14 — Frontend → S9 only**: no new network calls.
- [ ] **R19 — Never weaken tests**: existing e2e forced to Advanced, not deleted/weakened; existing KPI 8-tile assertions preserved.
- [ ] **DS — shadcn/ui only**: no new primitives; only conditional rendering of existing ones.
- [ ] **Heavy inline comments**: each gated block names its PRD matrix row.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `e2e/plan0108-portfolio-redesign.spec.ts`, `portfolio-overview-density.spec.ts`, `portfolio-overview-no-tabs.spec.ts`, `qa-exhaustive.spec.ts`, `transactions-filters.spec.ts` | default flips to Simple → full-layout assertions fail | T-A-B-05: seed Advanced via `forceAdvancedMode` helper (R19 — no assertion removed) |
| `components/portfolio/__tests__/PortfolioKPIStrip.test.tsx` | Simple variant added; skeleton assumes 8 | add Simple cases; keep 8-tile cases; page skeleton test updated in T-A-B-02 |
| any `page.tsx` render test asserting the tab bar unconditionally | Simple hides `TabsList` | scope the assertion to Advanced mode (seed `mode="advanced"` in the test render) |
| `portfolio-overview-perf.spec.ts` (NOT in the PRD's 5 but asserts full layout) | mocks + scrolls the full power-user layout (`ConcentrationSectorTeaseStrip`, `ExposureCurrencyStrip`, FPS≥60 over the whole page) → hidden in Simple | **audit conclusion (verified this session): FORCE ADVANCED.** Add `forceAdvancedMode` to its setup (R19 — no assertion removed). |
| `portfolio-overview-root-aware.spec.ts`, `portfolio-overview-ticker-click.spec.ts`, `portfolio-stub-routes.spec.ts`, `shell-portfolio-switcher.spec.ts` | default to Simple | **audit conclusion (verified this session): SIMPLE-SAFE — no change needed.** They assert only header/shell/sub-route surfaces present in both modes (ROOT hint + `+ ADD POSITION`, the Core `ticker` link → `/instruments/AAPL`, sub-route back-links, the `portfolio-switcher-chip` popover) — no tab bar, no power-strip. Re-confirm with the W-F full-suite grep. |

#### Regression Guardrails
- **Anti-fork (PRD §11 top risk)**: Advanced output must not change — run the W-A snapshot after every gate edit.
- **Silent e2e breakage (PRD §5 HIGH)**: audit ALL portfolio e2e specs, not only the 5 named — the extra `portfolio-overview-*` specs may also assert full layout and default to Simple. Grep `e2e/` for `TabsList`/`Analytics`/power-strip selectors before declaring green.
- **CSS `hsl(var())` no-paint bug class**: the 4-tile Simple skeleton must actually paint the tile placeholders in dark theme.
- **Frontend comment density**: comment WHY brokerage strips stay in Simple but analytics strips don't (casual brokerage user still needs sync status).

---

## Wave C: Brokerage trust + timing copy; Add-Position trade-date + debounced typeahead + gateway `tradeDate`

**Goal**: Two pure copy changes (trust block + honest sync timing) and the Add-Position upgrade (trade-date picker + debounced ticker typeahead over the existing `searchInstruments`, plus the additive gateway `tradeDate` param). Fully independent of the mode gate (disjoint files) — MAY land before or after W-B.
**Depends on**: none (soft: W-A only if adding the Add-Position `data-tour-target` this wave; otherwise W-F adds it)
**Estimated effort**: 90–120 min
**Architecture layer**: brokerage components + add-position dialog + gateway client
**Satisfies**: R-8, R-9, R-10, R-11, R-12, R-13, R-14

#### Tasks

#### T-A-C-01: Brokerage trust block in `ConnectBrokerageModal`
**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/brokerage/ConnectBrokerageModal.tsx` (MODIFY — above the ToS notice, ~l.144), `apps/worldview-web/components/brokerage/__tests__/ConnectBrokerageModal.test.tsx` (MODIFY or NEW)
**PRD reference**: §6.2 "Reassurance block (R-8)", §9 `test_brokerage_trust_block_present`

**What to build**: A bordered info block above the existing ToS notice, styled like the ToS box (`rounded-[2px] border border-border/50 bg-muted/30 px-3 py-2.5 text-xs`) with a `ShieldCheck` lucide icon (`aria-hidden`). Copy exactly (PRD §6.2):
> **Your credentials stay with SnapTrade — never Worldview.** We use SnapTrade's secure, read-only connection. Worldview never sees or stores your brokerage username or password, and can only *read* your holdings and transactions — it can never place trades or move money.

`data-testid="brokerage-trust-block"`. Does NOT replace the ToS consent checkbox (still required to enable Connect).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_brokerage_trust_block_present | modal shows the credentials-stay-with-SnapTrade / read-only block (`data-testid`) | unit |
| test_connect_still_requires_consent | Connect stays disabled until the ToS checkbox is checked (unchanged behaviour) | unit |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] Trust block renders above the ToS notice with the exact copy + `ShieldCheck`; `data-testid` present.
- [ ] ToS consent gating unchanged (Connect still gated on the checkbox).

#### T-A-C-02: Honest timing copy on the brokerage callback
**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/app/(app)/portfolio/brokerage/callback/page.tsx` (MODIFY — success sub-copy l.193-197), `apps/worldview-web/app/(app)/portfolio/brokerage/callback/__tests__/*` or the nearest callback test (MODIFY/NEW)
**PRD reference**: §6.2 "Honest timing copy (R-9, R-10)", §9 `test_callback_timing_copy`

**What to build**: Replace ONLY the success sub-copy; **keep the pinned heading** *"Brokerage account connected successfully!"* (e2e/qa asserts it). New sub-copy (PRD §6.2):
> Your first sync has started. Holdings usually appear within a few minutes, but a full import can take up to a few hours. If you don't see them yet, open the connected brokerage and press **Sync Now** to pull the latest data.

The "Go to Portfolio" button is unchanged. Timing is qualitative ("up to a few hours") so a future cycle change doesn't falsify the string.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_callback_timing_copy | success sub-copy mentions "few minutes" / "few hours" / "Sync Now" | unit |
| test_callback_heading_unchanged | heading string "Brokerage account connected successfully!" preserved | unit |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] Sub-copy replaced with the honest timing string; heading + "Go to Portfolio" button unchanged.

#### T-A-C-03: Gateway `addPosition` gains optional `tradeDate`
**Type**: impl
**depends_on**: none
**blocks**: [T-A-C-04]
**Target files**: `apps/worldview-web/lib/api/portfolios.ts` (MODIFY — `addPosition` l.636-696), `apps/worldview-web/lib/api/__tests__/portfolios.test.ts` (MODIFY/NEW)
**PRD reference**: §6.3 "Gateway change (R-13)", §8 (no backend change)

**What to build**: `addPosition(portfolioId, instrumentId, quantity, averageCost, tradeDate?: string)` — when `tradeDate` (ISO string) is provided, use it for `executed_at`; else keep `new Date().toISOString()` (backward compatible; the hardcode at l.656). **No backend change** — `executed_at` is already accepted (PRD §8). Additive trailing optional param → no existing caller breaks.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_addposition_uses_tradedate_when_given | passing `tradeDate` → request `executed_at` === that value | unit |
| test_addposition_defaults_now_when_absent | no `tradeDate` → `executed_at` defaults to now (unchanged) | unit |
- Minimum test count: 2

**Acceptance criteria**:
- [ ] `tradeDate` optional trailing param; used for `executed_at` when present, else now; existing callers unaffected.

#### T-A-C-04: Add-Position trade-date picker + debounced typeahead combobox
**Type**: impl
**depends_on**: [T-A-C-03]
**blocks**: none
**Target files**: `apps/worldview-web/features/portfolio/components/AddPositionDialog.tsx` (MODIFY — l.108-347), `apps/worldview-web/features/portfolio/components/__tests__/AddPositionDialog.test.tsx` (MODIFY/NEW)
**PRD reference**: §6.3 "Trade-date picker (R-11, R-13)" + "Inline debounced ticker typeahead (R-12, R-14)", §9 three add-position tests

**What to build**:
1. **Trade-date field** (R-11): native `<input type="date">`, chrome `h-7 font-mono text-[12px]`, label `"Trade Date"`, default = today (local `YYYY-MM-DD` via the same local-date builder as `ClosePositionDialog.tsx:92-98`), `max={today}`; Zod refine `tradeDate <= today` → `"Trade date can't be in the future."`. On submit pass `${tradeDate}T00:00:00Z` to `addPosition(..., tradeDate)`.
2. **Ticker typeahead** (R-12): replace the bare `<Input>` with a shadcn `Command`/`CommandList` combobox (`shouldFilter={false}` — server-side filtering, DS §6.15). On type (≥1 char) debounce **250 ms** (CommandPalette convention) and `searchInstruments(query, 8)` via TanStack Query key `["instrument-search", query]` (shared cache). Dropdown rows: `TICKER` (`font-mono text-primary`) + `SearchResult.name`; keyboard-navigable (↑/↓/Enter) + mouse-selectable — wire **both** `onSelect` AND `onClick` (SEARCH-001 dual-handler rule, DS §6.15). Selecting a row sets the ticker field to `result.ticker` and stashes the resolved `instrument_id` in form state so submit **skips** the redundant search. Editing the ticker string by hand clears the stashed `instrument_id` (re-resolve on submit).
3. **Fallback** (R-14): if the user submits a typed-but-unpicked ticker, keep today's submit-time `searchInstruments(ticker, 1)` resolution (`AddPositionDialog.tsx:146`) — behaviour never regresses.
4. **States**: `Skeleton` row while fetching; muted `"No instruments match \"{q}\"."` when empty. Placeholder `"Search ticker or company… e.g. AAPL"`.

**Logic & Behavior**: RHF integration for the async combobox; debounce cancels in-flight on unmount (TanStack handles). Typeahead is public (no token) — works pre-auth-refresh like today's search. Heavy comments on the dual-handler rule + the stash/clear `instrument_id` logic.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_add_position_trade_date_defaults_today_and_blocks_future | date defaults today; future date → validation error; submit sends `executed_at` from picked date | unit |
| test_add_position_typeahead_debounces_and_selects | typing debounces 250 ms, shows results, selecting a row stashes `instrument_id` + skips submit-time search | unit |
| test_add_position_typeahead_empty_and_fallback | empty results → muted message; typed-but-unpicked ticker still resolves via `searchInstruments(…,1)` | unit |
| test_add_position_manual_edit_clears_instrument_id | picking then hand-editing the ticker clears the stashed id (re-resolve) | unit |
- Minimum test count: 4
- Edge cases: unmount mid-fetch (no state-update warning); 0-char query (no fetch); server error (no crash — mirror `search.ts` guards).

**Acceptance criteria**:
- [ ] Trade-date defaults today, blocks future, flows to `executed_at`.
- [ ] Typeahead debounces 250 ms, dual-handler select, stashes `instrument_id`, submit-time fallback intact.
- [ ] Empty/loading states render; no crash on error; public search works pre-auth.

#### Pre-read
- `apps/worldview-web/components/brokerage/ConnectBrokerageModal.tsx:133-199` (ToS box styling to mirror)
- `apps/worldview-web/app/(app)/portfolio/brokerage/callback/page.tsx:183-210` (state machine + success block)
- `apps/worldview-web/features/portfolio/components/AddPositionDialog.tsx:1-347` (RHF + Zod + submit-time resolve at l.146)
- `apps/worldview-web/components/portfolio/ClosePositionDialog.tsx:92-98,164` (local-date builder + `executed_at` send pattern to reuse)
- `apps/worldview-web/lib/api/search.ts:26-216` (`searchInstruments` signature + `SearchResult` shape)
- `apps/worldview-web/lib/api/portfolios.ts:636-760` (`addPosition` + `addTransaction`)
- the CommandPalette / GlobalSearch component (`git grep -l "instrument-search\|shouldFilter" apps/worldview-web`) for the debounced-combobox + dual-handler convention (DS §6.15)

#### Validation Gate
- [ ] `pnpm lint` + `pnpm typecheck` clean
- [ ] `pnpm vitest run components/brokerage features/portfolio lib/api` — minimum **10** new tests green
- [ ] No backend/gateway URL added (R14); `addPosition` param is additive
- [ ] `pnpm playwright test e2e/brokerage-connect-copy.spec.ts e2e/portfolio-add-position-typeahead.spec.ts` (added in W-F, or stub here) — deferred to W-F if specs not yet written

#### Architecture Compliance
- [ ] **R14 — Frontend → S9 only**: `searchInstruments` + `addPosition` both go through the existing gateway; no new endpoint.
- [ ] **DS — shadcn/ui only**: typeahead reuses `Command`/`CommandList`; date field native input styled per DS; `rounded-[2px]`, `font-mono tabular-nums`.
- [ ] **SEARCH-001 dual-handler (DS §6.15)**: both `onSelect` + `onClick` wired on dropdown rows.
- [ ] **pnpm / 0 CVE**: no new dependency.
- [ ] **Heavy inline comments**: debounce, stash/clear id, dual-handler, fallback all commented.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `AddPositionDialog.test.tsx` (existing) | ticker `<Input>` replaced by a combobox; new date field | update selectors to the combobox input; add date-field cases; keep the submit-time-resolve fallback assertion |
| `lib/api/__tests__/portfolios.test.ts` | `addPosition` signature gains a param | add `tradeDate` cases; existing 4-arg calls still valid (optional) |
| `ConnectBrokerageModal.test.tsx` | new trust block child | add `data-testid` assertion; keep ToS-gating assertion |
| any e2e asserting the callback success body text | sub-copy changed | update to the new timing string; keep the heading assertion (still pinned) |

#### Regression Guardrails
- **SEARCH-001 dual-handler (DS §6.15)**: mouse-only selection silently no-ops if only `onSelect` is wired — the tripwire is `test_add_position_typeahead_debounces_and_selects` clicking (not keyboard) a row.
- **Prompt/label vs lookup mismatch (feedback, generalised)**: the stashed `instrument_id` MUST be cleared when the ticker text is hand-edited, or submit posts a stale instrument — `test_add_position_manual_edit_clears_instrument_id` guards it.
- **Callback heading is e2e-pinned (PRD §5)**: change ONLY the sub-copy; a heading edit breaks qa-exhaustive.
- **Frontend comment density**: comment the 250 ms debounce rationale (cold ILIKE 2–4 s → shared cache) and why the fallback resolve stays.

---

## Wave D: Edit Position (adjusting trade) + partial close + pinned-right ACTIONS kebab

**Goal**: The three manual-edit unlocks — an honest **Edit Position** adjusting-trade dialog, **partial close** (un-lock the Close quantity), and a **visible row-kebab** affordance reusing the existing floating menu — all via the existing `POST /v1/transactions`. Holdings are derived and never mutated in place (PRD §1.2.4); Edit records a NEW BUY/SELL of the delta.
**Depends on**: W-A (the `mode` prop + Core-group ACTIONS column anchor)
**Estimated effort**: 120–150 min
**Architecture layer**: pure helper + two dialogs + AG-Grid column + menu wiring
**Satisfies**: R-15, R-16, R-17, R-18, R-19, R-20, R-21, R-22, R-23

#### Tasks

#### T-A-D-01: `computeAdjustment` pure helper
**Type**: impl
**depends_on**: none
**blocks**: [T-A-D-02]
**Target files**: `apps/worldview-web/lib/portfolio/adjusting-transaction.ts` (NEW), `apps/worldview-web/lib/portfolio/__tests__/adjusting-transaction.test.ts` (NEW)
**PRD reference**: §6.4 "What edit means" + request shape; §9 `test_adjusting_transaction_delta`

**What to build**: A pure, unit-tested function computing the adjusting trade from current/target quantity (R-16 mechanism).

**Entities / Components**:
- `computeAdjustment(currentQty: number, targetQty: number): { side: "BUY" | "SELL"; quantity: number } | null`:
  - `delta = targetQty − currentQty`; `delta > 0` → `{side:"BUY", quantity: delta}`; `delta < 0` → `{side:"SELL", quantity: Math.abs(delta)}`; `delta === 0` → `null` (nothing to record → Submit disabled).
  - Guards: `targetQty < 0` or `NaN` → throw/`null` (caller shows inline error).
  - Pure — no I/O; heavy comment on the honest-ledger rationale (holdings are derived, PRD §6.4).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_adjusting_transaction_delta_buy | target > current → BUY of delta | unit |
| test_adjusting_transaction_delta_sell | target < current → SELL of `abs(delta)` | unit |
| test_adjusting_transaction_delta_zero_null | target === current → `null` | unit |
| test_adjusting_transaction_target_zero_full_sell | target 0 with current N → SELL of N | unit |
- Minimum test count: 4

**Acceptance criteria**:
- [ ] Correct `{side, quantity}` for +/−; `null` on 0; full-sell on target 0; invalid → handled.

#### T-A-D-02: `EditPositionDialog` (honest adjusting trade)
**Type**: impl
**depends_on**: [T-A-D-01]
**blocks**: [T-A-D-04]
**Target files**: `apps/worldview-web/components/portfolio/EditPositionDialog.tsx` (NEW), `apps/worldview-web/components/portfolio/__tests__/EditPositionDialog.test.tsx` (NEW)
**PRD reference**: §6.4 (full), §9 `test_edit_position_posts_delta_trade` + `test_edit_position_ledger_note_present`

**What to build**: A dialog showing the current derived position **read-only** (Ticker, current Qty, current Avg Cost, current Mkt Value) and collecting a **target quantity** + **adjustment price** + **trade date**; on submit it POSTs the adjusting BUY/SELL via `addTransaction` (existing gateway), never mutating a holding.

> **NAMING GUARD (verified this session)**: this NEW file is `EditPosition**Dialog**.tsx` (edits a *holding* via an adjusting trade). Do **not** confuse it with the already-shipped `EditPortfolio**Dialog**.tsx` from PLAN-0114 W6 (edits a *portfolio's* `cost_basis_method` via `PATCH /portfolios/{id}`). Different file, different purpose — both coexist.

**Entities / Components** (fields/validation/copy from §6.4):
- Target Quantity: NumberInput, `≥ 0`, `≤ 1,000,000`; `0` = close entirely (full SELL, allowed).
- Adjustment Price: `> 0`; default = current live price (from the row's `livePrice`) if available, else avg cost.
- Trade Date: date picker, default today, not future (same rule + local-date builder as §6.3).
- **Ledger note (R-17), unmissable**: "This records an **adjusting trade** in your history (a BUY or SELL for the difference) — it does not rewrite past transactions. Your average cost is recalculated from your full trade history."
- Submit label reflects action via `computeAdjustment`: `"Record BUY of {n}"` / `"Record SELL of {n}"`; disabled when `delta === 0` or price invalid.
- Request (identical to Close/Add — no new endpoint): `transaction_type:"TRADE"`, `trade_side` from `sign(delta)`, `quantity: abs(delta)`, `price`, `fees:0`, `currency:"USD"`, `executed_at:"${tradeDate}T00:00:00Z"`, `external_ref:null`; idempotency key via `useRef(crypto.randomUUID())` (mirrors `ClosePositionDialog`).
- Success: `toast.success("Adjustment recorded", { description: "Holdings update within seconds." })` then `onHoldingsRefetch()` (same invalidation path as Add/Close). Error → `toast.error` + keep dialog open.
- Root portfolio → the dialog is never opened (entry point hidden in T-A-D-04; S1 rejects root trades).

**Logic & Behavior**: read-only current position + delta preview so the effect (BUY/SELL of N @ price) is transparent before submit (R-17: no silent avg-cost overwrite). Heavy comments on WHY this is an adjusting trade (derived holdings, no PATCH).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_edit_position_posts_delta_trade_buy | target > current → posts BUY of delta with correct body | unit |
| test_edit_position_posts_delta_trade_sell | target < current → posts SELL of delta | unit |
| test_edit_position_submit_disabled_on_zero_delta | target === current → Submit disabled | unit |
| test_edit_position_ledger_note_present | the adjusting-trade note renders | unit |
| test_edit_position_error_keeps_dialog_open | POST failure → toast.error + dialog stays open | unit |
- Minimum test count: 5
- Edge cases: negative/NaN target → inline error; target 0 → full SELL; price default from `livePrice` then avg cost.

**Acceptance criteria**:
- [ ] Posts the correct adjusting BUY/SELL via the existing endpoint; disabled on 0 delta; ledger note present.
- [ ] Idempotency key + toast + refetch match Close/Add; error keeps dialog open; no holding mutated.

#### T-A-D-03: Partial close — un-lock the Close quantity
**Type**: impl
**depends_on**: none
**blocks**: [T-A-D-04]
**Target files**: `apps/worldview-web/components/portfolio/ClosePositionDialog.tsx` (MODIFY — l.269-275 read-only quantity), `apps/worldview-web/components/portfolio/__tests__/ClosePositionDialog.test.tsx` (MODIFY)
**PRD reference**: §6.5 (R-19, R-20, R-21), §9 `test_partial_close_quantity_editable_and_validated`

**What to build**: Make the quantity editable (R-19): NumberInput, **default = full holding quantity** (full close stays one click). Validate `0 < quantity ≤ holding.quantity` (R-20): `"Quantity must be greater than 0."` / `"You only hold {n} shares."`. Add a Full/Partial affordance (R-21): a "Sell all" link resetting quantity to full; title updates — `"Close Position"` (full) vs `"Sell {n} of {total}"` (partial); dialog header stays `Close Position — {ticker}`. Submit posts the same SELL body with the entered quantity; idempotency key + trade date behaviour unchanged.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_partial_close_quantity_editable_default_full | quantity editable, defaults to full holding | unit |
| test_partial_close_blocks_over_and_zero | `> holding` blocked; `0` blocked with the right messages | unit |
| test_partial_close_full_still_one_click | leaving default (full) posts the full SELL exactly as today | unit |
| test_partial_close_title_reflects_partial | entering a partial qty → title "Sell {n} of {total}"; "Sell all" resets to full | unit |
- Minimum test count: 4

**Acceptance criteria**:
- [ ] Quantity editable, default full, validated `0 < q ≤ holding`; full close unchanged; partial title + "Sell all" reset work; idempotency preserved.

#### T-A-D-04: Pinned-right ACTIONS kebab column reusing the floating menu
**Type**: impl
**depends_on**: [T-A-D-02, T-A-D-03]
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/ag-holdings-columns.tsx` (MODIFY — add `actions` colId), `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx` (MODIFY — cell renderer + menu wiring + Edit/partial-close entry points), `apps/worldview-web/components/portfolio/__tests__/SemanticHoldingsTable.test.tsx` (MODIFY), `apps/worldview-web/components/portfolio/__tests__/ag-holdings-columns-pinned.test.tsx` (MODIFY)
**PRD reference**: §6.6 (R-22, R-23), §9 `test_row_action_kebab_opens_menu`

**What to build**:
- **ACTIONS column (R-22)**: add `colId:"actions"` to `ag-holdings-columns.tsx` — pinned right (`lockPinned:"right"`), `suppressMovable:true`, `sortable:false`, width 40 px, `group:"core"` (always present, never hideable — see W-E). Cell renders a `MoreVertical` (kebab) icon button, `aria-label="Actions for {ticker}"`, visible on row hover and always visible on touch (`@media (hover: none)`). Pinned bottom TOTAL row → ACTIONS cell empty.
- **Menu wiring (R-23)**: clicking/tapping the kebab opens the **same floating menu** as the right-click path (`useContextMenuActions`), positioned at the button's bounding rect, offering **Edit Position** (opens `EditPositionDialog`) · **Partial Close / Close Position** (opens `ClosePositionDialog`) · plus the existing `ctxGroups` actions (view instrument, add to watchlist). The right-click context menu is preserved unchanged (purely additive).
- Root portfolio: Edit/Close items hidden (today's close gating); the kebab still offers read-only actions (view instrument).

**Logic & Behavior**: the pinned-right column is appended to `holdingsAgColumns` so saved `worldview-holdings-cols` state that predates it keeps it at its defined position (AG Grid keeps unknown-to-saved columns). Heavy comments on the reuse of the floating menu (no new menu system).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_row_action_kebab_opens_menu | kebab renders per row; click opens the menu with Edit + Close; right-click still works | unit |
| test_actions_column_pinned_right_locked | `actions` colId is `lockPinned:"right"`, `suppressMovable`, `sortable:false`, `group:"core"` | unit |
| test_actions_empty_on_total_row | pinned bottom TOTAL row renders an empty ACTIONS cell | unit |
| test_root_portfolio_hides_edit_close | root portfolio → kebab hides Edit/Close, keeps view-instrument | unit |
- Minimum test count: 4

**Acceptance criteria**:
- [ ] Pinned-right ACTIONS kebab per row (hover + touch), opens the same floating menu with Edit/Close + existing actions; right-click preserved.
- [ ] Survives `applyColumnState` restore; TOTAL row empty; root gating honoured.

#### Pre-read
- `apps/worldview-web/components/portfolio/ClosePositionDialog.tsx:72-352` (idempotency key, date field, SELL body, read-only quantity l.269-275)
- `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx:243-321,569-704` (`handleGridReady`/`applyColumnState`, `useContextMenuActions`, the hand-added "Close Position" group, floating-menu positioning)
- `apps/worldview-web/components/portfolio/ag-holdings-columns.tsx:344-585` (colDef structure, pinned-left `ticker`, the TOTAL pinned row)
- `apps/worldview-web/lib/api/portfolios.ts:696-760` (`addTransaction` body + `executed_at`)
- `apps/worldview-web/components/portfolio/__tests__/ag-holdings-columns-pinned.test.tsx` (existing pinned-column assertions)

#### Validation Gate
- [ ] `pnpm lint` + `pnpm typecheck` clean
- [ ] `pnpm vitest run components/portfolio lib/portfolio` — minimum **17** new tests green
- [ ] `test_advanced_mode_is_todays_layout` (W-A snapshot) still green (ACTIONS column is additive; update the snapshot ONLY for the intentional new pinned-right column, documented)
- [ ] `pnpm playwright test e2e/portfolio-edit-partial-close.spec.ts` (added in W-F)

#### Architecture Compliance
- [ ] **R14 — Frontend → S9 only**: Edit/partial-close use the existing `POST /v1/transactions` via the gateway; no new endpoint.
- [ ] **Honest ledger (PRD §6.4/R-17)**: Edit never mutates a holding; records a visible adjusting trade; ledger note present.
- [ ] **DS — shadcn/ui only**: dialogs use shadcn `Dialog`; kebab reuses the existing floating menu; `MoreVertical` lucide icon; `rounded-[2px]`.
- [ ] **Heavy inline comments**: WHY adjusting-trade (derived holdings, no PATCH), WHY menu reuse.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `components/portfolio/__tests__/ag-holdings-columns-pinned.test.tsx` | new pinned-right `actions` column | add a case for the right pin; keep the pinned-left `ticker` assertions (R19) |
| `components/portfolio/__tests__/SemanticHoldingsTable.test.tsx` | new column + kebab + menu entries | add kebab/menu cases; keep right-click assertions |
| `components/portfolio/__tests__/ClosePositionDialog.test.tsx` | quantity now editable | add partial-quantity cases; keep full-close default assertion |
| `portfolio-advanced-snapshot.test.tsx` (W-A) | ACTIONS column adds a pinned-right cell to the Advanced table | intentional layout change → regenerate the snapshot WITH the ACTIONS column and document it in-file (this is a real, approved Advanced change, not a Simple side effect) |
| saved `worldview-holdings-cols` localStorage (runtime, not a test) | predates `actions` colId | AG Grid appends the unknown column at its defined position — verify manually; no migration needed |

#### Regression Guardrails
- **New pinned-right column breaks pinned test (PRD §11)**: `ag-holdings-columns-pinned.test.tsx` MUST get the right-pin case; column is `lockPinned:"right"` + `suppressMovable`.
- **Edit perceived as history rewrite (PRD §11, high impact)**: the adjusting-trade note (R-17) + the visible Transactions-tab BUY/SELL are the mitigation; `test_edit_position_ledger_note_present` is the tripwire.
- **Partial over-sell (PRD §11)**: client-side `≤ holding.quantity` guard; `test_partial_close_blocks_over_and_zero`.
- **Idempotency (BP)**: reuse the `useRef(crypto.randomUUID())` key pattern from `ClosePositionDialog` so a double-submit is de-duped — do not mint a fresh key per render.
- **Column-state restore (PRD §6.6)**: the `actions` column must survive `applyColumnState`; verify saved state that predates it doesn't drop it.

---

## Wave E: Holdings column-group toggle (Core / Portfolio / Advanced) + persistence + mode interaction

**Goal**: Add `group` metadata to each colId, a persisted three-group visibility layer applied AFTER the AG-Grid state restore, the ⚙ `HoldingsColumnGroupToggle` popover, and the Simple-forces-Core / Advanced-uses-saved-state interaction — preserving today's Advanced layout (all columns except `divYld`).
**Depends on**: W-B (Simple/Core wiring + the `mode` prop on `SemanticHoldingsTable`); reuses the `actions` colId + `group` field from W-D
**Estimated effort**: 90–120 min
**Architecture layer**: column-group config + table visibility layer + toggle UI
**Satisfies**: R-24, R-25, R-26, R-27

#### Tasks

#### T-A-E-01: Column-group metadata + config module
**Type**: impl
**depends_on**: none (uses W-D's `group` field on `actions`)
**blocks**: [T-A-E-02]
**Target files**: `apps/worldview-web/lib/portfolio/holdings-column-groups.ts` (NEW), `apps/worldview-web/components/portfolio/ag-holdings-columns.tsx` (MODIFY — add `group` to each colId), `apps/worldview-web/lib/portfolio/__tests__/holdings-column-groups.test.ts` (NEW)
**PRD reference**: §6.7 "Column groups (R-24)" + "Persistence (R-25)"

**What to build**: Assign each colId to a group (R-24) and centralise membership + persistence config.

**Entities / Components** (groups per PRD §6.7):
- **Core** (always on; Simple set): `ticker` (pinned-left, locked), `qty`, `avg_cost`, `current`, `value`, `pnl`, `actions` (pinned-right, locked).
- **Portfolio**: `name`, `dayChange`, `dayChangePct`, `pnlPct`, `weight`.
- **Advanced**: `spark`, `sector`, `asset`, `divYld`.
- `ticker` + `actions` are locked-visible (never hideable — they anchor the row).
- `holdings-column-groups.ts` exports: `COLUMN_GROUPS` (colId → group map), `colIdsForGroups(groups)`, `HOLDINGS_COL_GROUPS_KEY = "worldview:holdingsColGroups:v1"`, `ADVANCED_GROUP_DEFAULT = { core: true, portfolio: true, advanced: true }` (shows every column except `divYld`, which keeps its own `hide:true` — today's layout preserved), `SIMPLE_GROUPS = { core: true, portfolio: false, advanced: false }`, plus `loadGroupState()` / `saveGroupState()` with corrupt/absent → Advanced default.
- Add `group: "core"|"portfolio"|"advanced"` metadata to each colId in `ag-holdings-columns.tsx` (the `actions` colId already `group:"core"` from W-D).
- **DUPLICATE-FILE GUARD (verified this session)**: edit **`ag-holdings-columns.tsx`** (`holdingsAgColumns`, the AG-Grid defs that `SemanticHoldingsTable` actually imports). Do NOT edit the sibling **`components/portfolio/holdings-columns.tsx`** (`holdingsColumns`, an older TanStack-`ColumnDef` array that is dead for the grid — only its `EnrichedHoldingRow` type + `fmtPnl`/`formatStalenessAwarePrice` helpers are still imported). PLAN-0114 W6 added `DIV YLD` to BOTH files; the group work belongs only in the AG-Grid one. Adding `group` metadata to `holdings-columns.tsx` would be a silent no-op.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_column_groups_membership_and_lock | Core/Portfolio/Advanced membership matches §6.7; `ticker`+`actions` locked-visible | unit |
| test_colids_for_groups | `colIdsForGroups({core,portfolio})` → the right colId union | unit |
| test_load_group_state_corrupt_falls_back | absent/corrupt localStorage → Advanced default | unit |
- Minimum test count: 3

**Acceptance criteria**:
- [ ] Every colId has a group; `ticker`+`actions` locked; Advanced default = all except `divYld`; corrupt state → default.

#### T-A-E-02: Apply group visibility in `SemanticHoldingsTable` (after state restore) + Simple/Advanced gate
**Type**: impl
**depends_on**: [T-A-E-01]
**blocks**: [T-A-E-03]
**Target files**: `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx` (MODIFY — `handleGridReady` l.243-277), `apps/worldview-web/components/portfolio/__tests__/SemanticHoldingsTable.test.tsx` (MODIFY)
**PRD reference**: §6.7 "Persistence (R-25)" + "Interaction with Simple/Advanced (R-26)"

**What to build**: After the existing `applyColumnState` restore in `handleGridReady`, apply the group-visibility layer via `api.setColumnsVisible(colIds, visible)` so it sits ON TOP of the AG-Grid width/order persistence (`worldview-holdings-cols` stays untouched — the two localStorage keys are orthogonal, R-25). Mode interaction (R-26): **Simple** → force Core-only regardless of saved group state (leaving Simple restores the user's Advanced choice); **Advanced** → the saved group state governs. `divYld` remains individually toggleable via AG-Grid's own column menu without affecting the group flags.

**Logic & Behavior**: read `mode` (prop) + `loadGroupState()`; compute visible colIds = Simple ? Core : `colIdsForGroups(saved)`; call `setColumnsVisible` after restore. Heavy comment: WHY two orthogonal keys (visibility groups vs widths/order) and WHY apply after restore (so the group layer wins).

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_group_visibility_applied_after_restore | `setColumnsVisible` called after `applyColumnState` with the group colIds | unit |
| test_simple_forces_core_only | `mode="simple"` → only Core columns visible regardless of saved state | unit |
| test_advanced_uses_saved_group_state | `mode="advanced"` + saved `{portfolio:false}` → Portfolio columns hidden | unit |
- Minimum test count: 3

**Acceptance criteria**:
- [ ] Group visibility applied after restore via `setColumnsVisible`; orthogonal to `worldview-holdings-cols`.
- [ ] Simple forces Core-only; Advanced honours saved state; `divYld` still individually toggleable.

#### T-A-E-03: `HoldingsColumnGroupToggle` ⚙ popover + persistence wiring
**Type**: impl
**depends_on**: [T-A-E-02]
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/HoldingsColumnGroupToggle.tsx` (NEW), `apps/worldview-web/features/portfolio/components/HoldingsTab.tsx` (MODIFY — mount in `HoldingsTableChrome`, Advanced only), `apps/worldview-web/components/portfolio/__tests__/HoldingsColumnGroupToggle.test.tsx` (NEW)
**PRD reference**: §6.7 "Toggle UI (R-27)" + "Interaction (R-26)"

**What to build**: A `Settings2` (⚙) icon button (`h-7 w-7`) in `HoldingsTableChrome`, opening a shadcn `Popover` with three checkboxes — **Core** (checked, disabled), **Portfolio**, **Advanced** — plus a "Reset" restoring the Advanced default. Follows the existing Column-Settings pattern (DS §6.5d). `data-tour-target="column-toggle"` (consumed by W-F). Toggling a group calls `saveGroupState()` + re-applies visibility (via a callback into the table / shared state). **Shown only in Advanced** (hidden in Simple — the group toggle UI is gated on `mode === "advanced"`, matching R-26).

**Copy** (§6.7): popover heading `"Columns"`; rows `"Core (always shown)"`, `"Portfolio detail"`, `"Advanced metrics"`; reset `"Reset to default"`.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_column_group_toggle_persists_and_gates | toggling Portfolio off hides its columns + persists to `worldview:holdingsColGroups:v1`; Core checkbox disabled | unit |
| test_column_toggle_hidden_in_simple | `mode="simple"` → the ⚙ toggle is not rendered | unit |
| test_column_toggle_reset_restores_default | Reset → Advanced default `{portfolio:true,advanced:true}` | unit |
| test_column_toggle_has_tour_target | `data-tour-target="column-toggle"` present | unit |
- Minimum test count: 4

**Acceptance criteria**:
- [ ] ⚙ popover with Core(locked)/Portfolio/Advanced + Reset; persists + re-applies; hidden in Simple; tour target present.

#### Pre-read
- `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx:243-321` (`handleGridReady`, `applyColumnState`, `HOLDINGS_COLS_KEY`)
- `apps/worldview-web/components/portfolio/ag-holdings-columns.tsx:95-585` (all 15 colIds + the W-D `actions` colId)
- `apps/worldview-web/features/portfolio/components/HoldingsTab.tsx` (`HoldingsTableChrome` — where the ⚙ mounts)
- an existing Column-Settings popover (`git grep -l "Settings2\|Column" apps/worldview-web/components` per DS §6.5d)
- `docs/ui/DESIGN_SYSTEM.md` §6.5d (Column-Settings pattern)

#### Validation Gate
- [ ] `pnpm lint` + `pnpm typecheck` clean
- [ ] `pnpm vitest run components/portfolio lib/portfolio features/portfolio` — minimum **10** new tests green
- [ ] `test_advanced_mode_is_todays_layout` still green (Advanced default = all-except-`divYld`, i.e. today's layout)
- [ ] Two localStorage keys proven orthogonal (`worldview-holdings-cols` widths/order untouched by group toggling)

#### Architecture Compliance
- [ ] **R14 — Frontend → S9 only**: no network calls; pure client visibility + localStorage.
- [ ] **DS — shadcn/ui only**: `Popover` + `Checkbox` + `Button`; `Settings2` lucide; `rounded-[2px]`; follows §6.5d.
- [ ] **R19 — Never weaken tests**: table tests extended, not weakened.
- [ ] **Heavy inline comments**: orthogonal-keys + apply-after-restore + Simple-forces-Core all commented.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `components/portfolio/__tests__/SemanticHoldingsTable.test.tsx` | `setColumnsVisible` now called after restore; new `mode`-driven visibility | add the group-visibility cases; keep the `applyColumnState` restore assertion |
| `components/portfolio/__tests__/ag-holdings-columns*.test.tsx` | every colId gains a `group` field | assert the group membership; keep existing colId assertions |
| `HoldingsTab` chrome test (if any) | new ⚙ toggle child in Advanced | add an assertion for the toggle in Advanced; assert absent in Simple |

#### Regression Guardrails
- **Group layer fights `applyColumnState` (PRD §11)**: visibility MUST be applied AFTER the restore via `setColumnsVisible`, and the two keys kept orthogonal — `test_group_visibility_applied_after_restore` is the tripwire.
- **Advanced default preserves today (PRD §6.7 / US-B1)**: default `{portfolio:true,advanced:true}` shows all-except-`divYld` — the W-A snapshot proves no regression.
- **Corrupt localStorage**: `loadGroupState()` must fall back to Advanced default (never crash) — `test_load_group_state_corrupt_falls_back`.
- **Frontend comment density**: comment WHY `divYld` stays individually hideable independent of the group flags.

---

## Wave F: Onboarding tour + create-dialog trigger + docs + e2e hardening

**Goal**: A dismissible, non-blocking guided tour (custom shadcn `Popover` state machine, no new dependency) triggered once after first portfolio creation; wire the create-dialog trigger; write all §12 docs; add the new Simple/typeahead/edit/tour/copy e2e specs and finish the existing-spec Advanced hardening.
**Depends on**: W-A…W-E (the tour anchors `data-tour-target` on the mode toggle [W-A], Add Position button [W-C], column toggle [W-E]; e2e hardening needs every surface to exist)
**Estimated effort**: 90–120 min
**Architecture layer**: tour component + create-dialog trigger + docs + e2e
**Satisfies**: R-28, R-29, R-30, R-31

#### Tasks

#### T-A-F-01: `PortfolioTour` custom popover state machine
**Type**: impl
**depends_on**: none (consumes `data-tour-target` attrs from prior waves)
**blocks**: [T-A-F-02]
**Target files**: `apps/worldview-web/components/portfolio/PortfolioTour.tsx` (NEW), `apps/worldview-web/app/(app)/portfolio/page.tsx` (MODIFY — mount `<PortfolioTour/>`), `apps/worldview-web/components/portfolio/__tests__/PortfolioTour.test.tsx` (NEW)
**PRD reference**: §6.8 "Steps (R-29)" + "Non-blocking/dismissible (R-30, R-31)"

**What to build**: A lightweight, client-only (`"use client"`) tour built on shadcn `Popover` (Radix) anchored to `data-tour-target` attributes via `document.querySelector("[data-tour-target='…']")`. **No new dependency** (react-joyride/shepherd forbidden — DS shadcn-only + pnpm 0-CVE, PRD §7).

**Entities / Components**:
- State machine: `step` index (0..N); Radix `Popover open` controlled per step.
- Steps (≤5, each ≤2 sentences, PRD §6.8): (1) Welcome — page header; (2) Detail level — `data-tour-target="mode-toggle"`; (3) Add a position — Add Position button (`data-tour-target` added in W-C, else the header CTA); (4) Connect a brokerage — Transactions/Connect (in Simple, anchor header + mention switching to Advanced); (5) Advanced columns — `data-tour-target="column-toggle"`, **shown only in Advanced, skipped in Simple**.
- Each popover: "Back"/"Next" (or "Done" on last) + persistent "Skip tour" + "×". Missing anchor → step skipped. Non-blocking: subtle backdrop dims but does not trap focus / swallow primary actions (R-30, R-31).
- Reduced-motion: no animated spotlight. SSR: reads localStorage only in effect.

**Logic & Behavior**: on ×/Skip/Escape/route-change → end tour + set the flag to "done" (R-30/R-31). Heavy comments on WHY custom (no dependency) + the querySelector anchor resolution + step-skip when target missing.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_tour_steps_advance_and_skip_missing | Next advances; a step whose `data-tour-target` is absent (e.g. column-toggle in Simple) is skipped | unit |
| test_tour_dismiss_paths_end_and_flag | ×, Skip, Escape each end the tour and set the flag "done" | unit |
| test_tour_non_blocking | page primary actions remain clickable while the tour is open | unit |
- Minimum test count: 3

**Acceptance criteria**:
- [ ] ≤5 anchored steps; missing anchor skipped; Skip/×/Esc/route-change end + flag "done"; non-blocking; no new dependency.

#### T-A-F-02: Create-dialog trigger + first-visit flag backfill
**Type**: impl
**depends_on**: [T-A-F-01]
**blocks**: none
**Target files**: `apps/worldview-web/features/portfolio/components/CreatePortfolioDialog.tsx` (MODIFY — `onSuccess`), `apps/worldview-web/app/(app)/portfolio/page.tsx` (MODIFY — auto-start + backfill logic), `apps/worldview-web/features/portfolio/components/__tests__/CreatePortfolioDialog.test.tsx` (MODIFY/NEW)
**PRD reference**: §6.8 "Trigger (R-28)"

**What to build**: `CreatePortfolioDialog.onSuccess` sets `localStorage["worldview:portfolioTourSeen:v1"]="pending"` **only if unset** (first-ever create). On the next `/portfolio` render with holdings/empty state visible and flag === "pending", `PortfolioTour` auto-starts (step 0), then the flag is set to "done" the moment the tour starts (never re-triggers even if abandoned). Backfill: users who already have ≥1 portfolio get the flag set to "done" on first mount (never surprised) — R-28 + OQ-4 assumption.

**Tests to write** (inline):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| test_tour_triggers_once_after_first_create | flag "pending" → tour starts → flag "done"; reload → does not re-trigger | unit |
| test_create_sets_pending_only_if_unset | `onSuccess` sets "pending" only when the key is unset | unit |
| test_existing_users_backfilled_done | first mount with ≥1 existing portfolio → flag "done", tour never shows | unit |
- Minimum test count: 3

**Acceptance criteria**:
- [ ] First create → "pending" (only if unset); auto-start once → "done"; existing users backfilled "done"; never re-triggers.

#### T-A-F-03: New + hardened e2e specs
**Type**: test
**depends_on**: [T-A-F-01, T-A-F-02]
**blocks**: none
**Target files** (NEW): `apps/worldview-web/e2e/portfolio-simple-mode.spec.ts`, `apps/worldview-web/e2e/portfolio-add-position-typeahead.spec.ts`, `apps/worldview-web/e2e/portfolio-edit-partial-close.spec.ts`, `apps/worldview-web/e2e/portfolio-onboarding-tour.spec.ts`, `apps/worldview-web/e2e/brokerage-connect-copy.spec.ts`; also verify the W-B `forceAdvancedMode` hardening across ALL portfolio e2e
**PRD reference**: §9 E2E table

**What to build** (scenarios per §9):
- `portfolio-simple-mode.spec.ts`: default load → Simple (4 tiles, no tabs, 6-col table); toggle → Advanced full layout; reload persists.
- `portfolio-add-position-typeahead.spec.ts`: type "AAPL" → dropdown → select → set a past date → submit → toast; verify request `executed_at` reflects the picked date.
- `portfolio-edit-partial-close.spec.ts`: kebab → Edit → change target qty → adjusting trade appears in Transactions; Partial Close sells part; full close still works.
- `portfolio-onboarding-tour.spec.ts`: first portfolio create → tour appears → Skip dismisses → does not reappear on reload.
- `brokerage-connect-copy.spec.ts`: modal shows the trust block; callback stub shows the honest timing copy (heading unchanged).
- **Re-verify** every portfolio e2e is forced Advanced where it asserts full layout (finish the W-B §5 audit).

**Acceptance criteria**:
- [ ] All 5 new specs green; all existing portfolio specs green under `PORTFOLIO_SIMPLE_DEFAULT=true`.
- [ ] The Advanced-snapshot component test remains the merge gate (documented in the PR).

#### T-A-F-04: Documentation updates (mandatory, §12)
**Type**: docs
**depends_on**: [T-A-F-01, T-A-F-02]
**blocks**: none
**Target files**: `docs/apps/worldview-web.md`, `docs/ui/DESIGN_SYSTEM.md`, `apps/worldview-web/.claude-context.md` (or the app context note), `docs/audits/2026-07-08-portfolio-public-launch-ux-investigation.md`, `docs/plans/TRACKING.md`, `.claude/review/checklists/REVIEW_CHECKLIST.md`
**PRD reference**: §12

**What to build**:
- `docs/apps/worldview-web.md`: dual-mode portfolio page, `usePortfolioMode`, the mode URL param + localStorage keys, column-group toggle, onboarding tour, Edit/Partial-close dialogs.
- `docs/ui/DESIGN_SYSTEM.md`: add the "Progressive-disclosure / dual-mode pattern" (casual default + advanced opt-in as a render gate), the onboarding-tour popover pattern, and the holdings column-group toggle (cross-ref §6.5d).
- app context note: record the localStorage keys `worldview:portfolioMode:v1`, `worldview:holdingsColGroups:v1`, `worldview:portfolioTourSeen:v1` alongside the existing `worldview-holdings-cols`.
- audit doc: mark Tier 0 + Tier 1 as "scoped by PRD-0122".
- TRACKING.md: update PLAN-0122 waves to `6/6` on completion.
- REVIEW_CHECKLIST.md: add "new UI surfaces must define a casual-user default + progressive disclosure before public exposure" (report §7).

**Acceptance criteria**:
- [ ] All §12 docs updated; the three localStorage keys recorded; the review-checklist item added.

#### Pre-read
- `apps/worldview-web/features/portfolio/components/CreatePortfolioDialog.tsx` (`onSuccess`)
- `apps/worldview-web/app/(app)/portfolio/page.tsx` (mount point + first-mount effect for the flag backfill)
- an existing e2e that seeds localStorage + stubs a redirect (`git grep -l "addInitScript\|route(" apps/worldview-web/e2e`)
- `docs/apps/worldview-web.md`, `docs/ui/DESIGN_SYSTEM.md` §6.5d, `docs/audits/2026-07-08-portfolio-public-launch-ux-investigation.md`
- a shadcn `Popover`-based component for the controlled-open pattern

#### Validation Gate
- [ ] `pnpm lint` + `pnpm typecheck` clean
- [ ] `pnpm vitest run components/portfolio features/portfolio` — minimum **9** new tests green
- [ ] `pnpm playwright test e2e/portfolio-simple-mode.spec.ts e2e/portfolio-add-position-typeahead.spec.ts e2e/portfolio-edit-partial-close.spec.ts e2e/portfolio-onboarding-tour.spec.ts e2e/brokerage-connect-copy.spec.ts` all green
- [ ] `pnpm playwright test e2e/` — the FULL portfolio e2e suite green under Simple default (existing specs forced Advanced)
- [ ] `test_advanced_mode_is_todays_layout` green
- [ ] All §12 docs updated; TRACKING.md → `6/6`

#### Architecture Compliance
- [ ] **R14 — Frontend → S9 only**: tour + flag are client-only; no network.
- [ ] **R15 — Update docs**: §12 targets all updated this wave.
- [ ] **DS — shadcn/ui only + no new dependency**: tour is a custom `Popover` state machine (react-joyride/shepherd rejected — PRD §7).
- [ ] **R19 — Never weaken tests**: existing e2e forced Advanced; new specs additive.
- [ ] **Heavy inline comments**: tour anchor resolution + flag lifecycle commented.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `CreatePortfolioDialog.test.tsx` | `onSuccess` now sets a localStorage flag | add the flag-set assertion; keep existing create-flow assertions |
| any remaining portfolio e2e not yet forced Advanced | Simple default | apply `forceAdvancedMode` (finish the W-B audit); R19 — no assertion removed |
| `docs/apps/worldview-web.md` / `DESIGN_SYSTEM.md` staleness checks (docs-audit) | new capabilities documented | add the dual-mode / tour / column-group sections |
| `docs/plans/TRACKING.md` | plan completes | update waves to `6/6`, status → the appropriate state |

#### Regression Guardrails
- **Tour anchors missing (PRD §11)**: a missing `data-tour-target` (e.g. column-toggle in Simple) MUST skip the step, never crash — `test_tour_steps_advance_and_skip_missing`.
- **Tour re-trigger surprise (PRD §11 / OQ-4)**: flag set to "done" the moment the tour STARTS (not on complete) so an abandoned tour never re-shows; existing users backfilled "done".
- **No new dependency (PRD §7 / DS)**: `pnpm audit` 0 CVEs, exact versions — the tour must not add react-joyride/shepherd; verify `package.json` unchanged.
- **Focus trap / SSR**: tour is client-only, reads localStorage in effect, does not destructively trap focus (R-31).
- **Docs-and-tracking mandatory (feedback)**: update the plan file + TRACKING.md + docs in the wave commit, not as a follow-up.

---

## Cross-Cutting Concerns

- **Contract changes**: **NONE** on the wire. No Avro, no API contract, no S9 route change. The only "contract" edit is client-side and additive: `gateway.addPosition()` gains a trailing optional `tradeDate?: string` (PRD §8; existing 4-arg callers unaffected). Edit/partial-close reuse the existing `POST /v1/transactions` body verbatim.
- **Migration needs**: **NONE** (frontend-only; PRD §8). No Alembic, no intelligence_db, no R24/R32 concerns.
- **Event-flow changes**: **NONE**. No Kafka topics, no consumers.
- **Configuration changes**: one **build-time constant** `PORTFOLIO_SIMPLE_DEFAULT` (`lib/portfolio/mode-flag.ts`, NEW) — NOT an env var; `false` in W-A → `true` in W-B; rollback is a one-line flip (PRD §10). Three new client localStorage keys (`worldview:portfolioMode:v1`, `worldview:holdingsColGroups:v1`, `worldview:portfolioTourSeen:v1`) + the reused `?mode=` nuqs URL param. No new dependency (`pnpm audit` 0 CVEs preserved).
- **Documentation updates**: §12 targets (T-A-F-04) — `docs/apps/worldview-web.md`, `docs/ui/DESIGN_SYSTEM.md`, the app `.claude-context` note, the investigation audit doc, TRACKING.md, and the review-checklist item. Per feedback_tracking_and_docs_mandatory: update the plan file + TRACKING.md + docs in every wave commit.
- **Optional analytics** (PRD §13, best-effort, non-blocking, no PII): `portfolio_mode_changed`, `add_position_typeahead_selected`, `edit_position_recorded`/`partial_close_recorded`, `onboarding_tour`, `column_group_toggled` — wire only if the app's analytics shim exists; not a gating requirement.

## Risk Assessment

- **Critical path**: `W-A → W-B → W-E`, then `W-F` last. W-A establishes the mode contract + the anti-fork snapshot; W-B gates every surface + flips the default (the highest-blast-radius edit); W-E layers columns on the Simple/Core wiring; W-F hardens e2e once every surface exists. **W-C and W-D have real parallel slack** — W-C (brokerage + typeahead) touches disjoint files and can land any time; W-D (edit/partial/kebab) depends only on W-A.
- **Highest-risk wave: W-B** — it flips the public default AND must keep 5+ existing e2e green. The dual mitigation is (1) the W-A Advanced-snapshot as a component-level merge gate and (2) forcing every full-layout e2e into Advanced (R19, §5). The subtle failure is an *unlisted* portfolio e2e (`portfolio-overview-perf/root-aware/ticker-click`) that also defaults to Simple — the guardrail is a full `e2e/` grep for tab/power-strip selectors, not just the 5 named specs.
- **Second-highest risk: W-D honesty mechanism** — Edit Position must be perceived as (and actually be) an adjusting trade, never a history rewrite. Mitigation: the pure `computeAdjustment` helper + the unmissable ledger note (R-17) + the trade appearing in Transactions; `test_edit_position_ledger_note_present` is the tripwire. The pinned-right ACTIONS column is the one *intentional* Advanced-snapshot change in the plan (documented in W-D break-impact).
- **Rollback**: `PORTFOLIO_SIMPLE_DEFAULT=false` (or a user's localStorage/URL override) returns every user to today's Advanced layout instantly — a pure render switch, no data migration, no destructive change (PRD §10). The copy changes (W-C) and the additive dialogs (W-D) are inert unless invoked.
- **Testing gaps**: the tour's real UX (spotlight, focus behaviour) is hard to fully unit-test — the e2e `portfolio-onboarding-tour.spec.ts` covers the trigger-once + dismiss paths; live QA on touch (kebab visibility via `@media (hover:none)`) is a manual check.

## TRACKING.md entry (append to Active Plans — DONE this session)

```markdown
| PLAN-0122 | **Portfolio Public-Launch UX** — PRD-0122. Frontend-only (`apps/worldview-web`), zero backend. 6 waves: W-A mode scaffold (`usePortfolioMode` + `PortfolioModeToggle` + prop threading + Advanced-snapshot parity, default Advanced behind `PORTFOLIO_SIMPLE_DEFAULT`); W-B Simple render matrix (4-tile KPI variant, tab-bar/strip gates, flip default to Simple, force existing e2e to Advanced R19); W-C brokerage trust+timing copy + Add-Position trade-date + debounced typeahead + gateway `tradeDate`; W-D EditPositionDialog (adjusting trade) + partial-close un-lock + pinned-right ACTIONS kebab; W-E Core/Portfolio/Advanced column-group toggle; W-F onboarding tour + docs + e2e hardening. **Next: W-A**. | draft | 0/6 | none | 2026-07-09 |
```
(Already inserted at the top of the Active Plans table this session.)

## Definition of Done — Requirement → Wave → Task coverage matrix

All **31 requirements (R-1 … R-31)** are mapped to at least one task. No gaps.

| Req | Summary (PRD) | Wave | Task(s) |
|-----|---------------|------|---------|
| R-1 | Mode state source (`usePortfolioMode`, localStorage + URL, default Simple) | W-A | T-A-A-01 |
| R-2 | Simple KPI = 4 tiles; Advanced = 8 | W-B | T-A-B-01 |
| R-3 | Simple hides donut/overview band/concentration/perf chart/sector bar/bottom cluster/detail-pill/sector-chip | W-B | T-A-B-02, T-A-B-03 |
| R-4 | Simple = Holdings only (tab bar hidden; render HoldingsTab directly) | W-B | T-A-B-02 |
| R-5 | Mode-aware loading skeleton (4-tile Simple / 8-tile+donut Advanced) | W-B | T-A-B-02 |
| R-6 | `PortfolioModeToggle` control in the header | W-A | T-A-A-02 |
| R-7 | Rendering-gate implementation (prop threading, no fork) + Advanced-parity invariant | W-A | T-A-A-03, T-A-A-04 |
| R-8 | Brokerage trust/reassurance block | W-C | T-A-C-01 |
| R-9 | Honest callback timing sub-copy | W-C | T-A-C-02 |
| R-10 | Keep the pinned success heading; qualitative timing | W-C | T-A-C-02 |
| R-11 | Add-Position trade-date picker (default today, block future) | W-C | T-A-C-04 |
| R-12 | Inline debounced ticker typeahead (250 ms, dual-handler) | W-C | T-A-C-04 |
| R-13 | Gateway `addPosition` optional `tradeDate` → `executed_at` | W-C | T-A-C-03, T-A-C-04 |
| R-14 | Submit-time `searchInstruments(…,1)` fallback preserved | W-C | T-A-C-04 |
| R-15 | Edit Position = adjusting trade via existing `POST /transactions` (mechanism) | W-D | T-A-D-01, T-A-D-02 |
| R-16 | Delta → BUY/SELL derivation (`computeAdjustment`) | W-D | T-A-D-01 |
| R-17 | Honest-ledger note; no silent avg-cost overwrite | W-D | T-A-D-02 |
| R-18 | Edit fields/validation/copy + idempotency + toast/refetch | W-D | T-A-D-02 |
| R-19 | Partial close: editable quantity, default full | W-D | T-A-D-03 |
| R-20 | Partial-close validation `0 < q ≤ holding` | W-D | T-A-D-03 |
| R-21 | Full/Partial affordance + dynamic title | W-D | T-A-D-03 |
| R-22 | Pinned-right ACTIONS kebab column | W-D | T-A-D-04 |
| R-23 | Kebab opens the same floating menu (Edit/Close + existing actions); right-click preserved | W-D | T-A-D-04 |
| R-24 | Column-group metadata (Core/Portfolio/Advanced) | W-E | T-A-E-01 |
| R-25 | Group-visibility persistence (`worldview:holdingsColGroups:v1`) applied after restore | W-E | T-A-E-01, T-A-E-02 |
| R-26 | Simple forces Core-only; Advanced uses saved state | W-E | T-A-E-02, T-A-E-03 |
| R-27 | `HoldingsColumnGroupToggle` ⚙ popover UI | W-E | T-A-E-03 |
| R-28 | Tour trigger once after first portfolio create (+ backfill existing) | W-F | T-A-F-02 |
| R-29 | Tour steps (≤5 anchored popovers) | W-F | T-A-F-01 |
| R-30 | Tour non-blocking | W-F | T-A-F-01 |
| R-31 | Tour dismissible (×/Skip/Esc/route-change → flag done) | W-F | T-A-F-01 |

**Coverage: 31/31 requirements mapped. Zero gaps.** Supporting cross-cutting requirements (PRD §12 docs, §9 e2e, R14/R15/R19/DS compliance) are covered by T-A-F-03 (e2e), T-A-F-04 (docs), and the per-wave Architecture Compliance + Validation Gates.

## Task-status tables (pending / in-progress / done)

### Wave A
| Task | Title | Status |
|------|-------|--------|
| T-A-A-01 | `PORTFOLIO_SIMPLE_DEFAULT` flag + `usePortfolioMode` hook | done |
| T-A-A-02 | `PortfolioModeToggle` + header mount | done |
| T-A-A-03 | Thread `mode` through page → HoldingsTab → table | done |
| T-A-A-04 | Advanced-mode snapshot parity test | done |

### Wave B
| Task | Title | Status |
|------|-------|--------|
| T-A-B-01 | `PortfolioKPIStrip` `variant` (Simple = 4 tiles) | done |
| T-A-B-02 | Gate tab bar + donut + strips in page.tsx; 4-tile skeleton | done |
| T-A-B-03 | Gate power-strips inside HoldingsTab | done |
| T-A-B-04 | Flip `PORTFOLIO_SIMPLE_DEFAULT` to `true` | done |
| T-A-B-05 | Force the 5 existing e2e specs into Advanced (R19) | done |

### Wave C
| Task | Title | Status |
|------|-------|--------|
| T-A-C-01 | Brokerage trust block | done |
| T-A-C-02 | Honest callback timing copy | done |
| T-A-C-03 | Gateway `addPosition` optional `tradeDate` | done |
| T-A-C-04 | Add-Position trade-date + debounced typeahead | done |

### Wave D
| Task | Title | Status |
|------|-------|--------|
| T-A-D-01 | `computeAdjustment` pure helper | done |
| T-A-D-02 | `EditPositionDialog` (adjusting trade) | done |
| T-A-D-03 | Partial close — un-lock the Close quantity | done |
| T-A-D-04 | Pinned-right ACTIONS kebab column | done |

### Wave E
| Task | Title | Status |
|------|-------|--------|
| T-A-E-01 | Column-group metadata + config module | done |
| T-A-E-02 | Apply group visibility after restore + Simple/Advanced gate | done |
| T-A-E-03 | `HoldingsColumnGroupToggle` ⚙ popover + wiring | done |

### Wave F
| Task | Title | Status |
|------|-------|--------|
| T-A-F-01 | `PortfolioTour` custom popover state machine | done |
| T-A-F-02 | Create-dialog trigger + first-visit flag backfill | done |
| T-A-F-03 | New + hardened e2e specs | done |
| T-A-F-04 | Documentation updates (§12) | done |

**Total: 24 tasks across 6 waves.**

## Final QA Gate (before marking PLAN-0122 complete)

- [x] All 6 waves' validation gates green (`pnpm lint` + `pnpm typecheck` + `pnpm vitest run` + `pnpm playwright test` per wave).
- [x] `test_advanced_mode_is_todays_layout` green — Advanced === today's layout (the one intentional change: the W-D pinned-right ACTIONS column, documented).
- [x] Default flips to Simple only with the e2e Advanced-hardening landed in the same wave (W-B); no portfolio e2e observes Simple unexpectedly.
- [x] Edit Position records a visible adjusting BUY/SELL (never mutates a holding); ledger note present (R-17).
- [x] Partial close validated `0 < q ≤ holding`; full close still one click.
- [x] Add-Position typeahead debounced 250 ms, dual-handler, `instrument_id` stash/clear, submit-time fallback intact; trade-date → `executed_at`.
- [x] Column groups: Advanced default = all-except-`divYld`; Simple forces Core-only; two localStorage keys orthogonal.
- [x] Tour triggers once after first create, non-blocking, dismissible, backfilled for existing users; no new dependency (`pnpm audit` 0 CVEs).
- [x] Zero backend/S9/migration/Kafka change (R14; PRD §8) — confirmed by diff scope = `apps/worldview-web` only.
- [x] All §12 docs + TRACKING.md updated; consider a `/qa` frontend pass given the page-shell blast radius.

## Compounding check

Candidate additions (apply during T-A-F-04 as warranted):
- **BUG_PATTERNS.md** — "Dual-mode render gate silently forks" — a Simple/Advanced (or any progressive-disclosure) gate must be a prop-driven render gate guarded by an Advanced-parity snapshot test, never a duplicated component tree; prevention = `test_advanced_mode_is_todays_layout` as a merge gate.
- **BUG_PATTERNS.md** — "Default-mode flip silently breaks e2e" — flipping a page's default view (Advanced→Simple) breaks every e2e asserting the old layout unless they force the old mode; prevention = seed the mode in `addInitScript` for ALL affected specs (grep the suite, don't trust the named list).
- **REVIEW_CHECKLIST.md** — "new UI surfaces must define a casual-user default + progressive disclosure before public exposure" (PRD §12 / report §7).
- **DESIGN_SYSTEM.md** — the progressive-disclosure/dual-mode pattern, the onboarding-tour popover pattern, the column-group toggle (T-A-F-04).
- No RULES.md change needed — R14/R15/R19 + DS cover the design. No new rule.
