---
id: PRD-0122
title: "Portfolio Public-Launch UX — Dual-Mode Page, Trusted Brokerage Connect, and Manual-Position Editing"
status: draft
created: 2026-07-09
updated: 2026-07-09
author: "human + claude"
services: [apps/worldview-web]
priority: P0
estimated-waves: 6
depends-on: ["PRD-0114 — Portfolio Positions Enhancement (Close Position, kind-aware empty states, transaction filters)"]
enables: []
---

# PRD-0122: Portfolio Public-Launch UX — Dual-Mode Page, Trusted Brokerage Connect, and Manual-Position Editing

## 1. Overview & Goals

### 1.1 Background

The owner is taking the portfolio product **public**. The investigation report
`docs/audits/2026-07-08-portfolio-public-launch-ux-investigation.md` (4 parallel
subagents, verified against live code) found that the **plumbing is sound and
secure** — backend CRUD, SnapTrade OAuth (read-only, credentials never touch
Worldview), tenant isolation, and empty states are all correct. The gap is
**UX surface**:

- The `/portfolio` page defaults to a **6-layer, 40+ component power-user wall**:
  an 8-tile KPI strip, a 3-panel β-adjusted-exposure / leverage / HHI overview
  band, an equity curve with SPY overlay, a 14-column holdings table, a 3-panel
  bottom cluster, and 4 tabs whose Analytics tab is expert-only. A brand-new user
  with holdings lands straight into this — cognitive-load rating **7.5/10
  overwhelming** (`page.tsx:441-580`, `HoldingsTab.tsx`, `PortfolioKPIStrip.tsx`).
- A few high-value manual actions are **missing or hidden**: no Edit Position, no
  partial close, delete/close only via right-click (undiscoverable on
  touch/trackpad), and Add Position has no trade-date field and resolves tickers
  only at submit time (2–4 s cold, no typeahead).
- The brokerage flow **under-sells its own safety** ("no password reassurance")
  and **mis-sets timing expectations** ("syncing shortly" despite a real 4-hour
  cycle).

This PRD covers **Tier 0 + Tier 1** of the report's action plan. It is a
**frontend-only** effort in `apps/worldview-web`; the backend and S9 gateway are
unchanged (§8 proves this line by line).

### 1.2 The Key Enabling Facts (verified live this session)

The cost of this PRD is small precisely because the primitives already exist:

1. **Ticker→instrument search endpoints already exist and are correct.** The
   backend agent's claim that "users must paste UUIDs" is **FALSE** (report §2).
   `searchInstruments()` → `GET /v1/search/instruments` (S3 ILIKE),
   `resolveTickersBatch()` → `POST /v1/instruments/resolve-tickers` (exact,
   ~200 ms), and `GET /v1/instruments/lookup?symbol=X` all exist
   (`lib/api/search.ts:43,203-214`). AddPositionDialog already resolves a ticker
   at submit time (`AddPositionDialog.tsx:146`). We only need a **debounced
   typeahead dropdown** in front of the existing search.

2. **`executed_at` is already a first-class field on the transaction API.**
   `RecordTransactionRequest.executed_at: datetime` (`api/schemas.py:121`) is
   accepted today; `ClosePositionDialog` already sends a user-picked date
   (`ClosePositionDialog.tsx:164`). The Add-Position "always now" limitation is a
   **frontend omission** (`lib/api/portfolios.ts:656` hardcodes
   `new Date().toISOString()`), not a backend gap.

3. **A partial-quantity SELL is already valid.** `quantity: Decimal` is validated
   only as **positive** (`api/schemas.py:138-142`); S1 records a SELL of any
   quantity and the derived-holdings recompute reduces the position. Partial close
   is a **frontend un-locking** of the read-only quantity field
   (`ClosePositionDialog.tsx:269-275`).

4. **Holdings are DERIVED from transactions, never mutated directly**
   (`services/portfolio/.claude-context.md` pitfall: *"Holdings are NOT updated by
   `RecordTransactionUseCase` … only the recompute consumer writes holdings"*).
   There is **no transaction PATCH/DELETE endpoint** (verified: S1 exposes only
   `POST /transactions` + read GETs). Therefore **Edit Position MUST be an
   adjusting transaction**, never an in-place edit (§6.4 specifies the exact
   honest mechanism).

### 1.3 Business Value

- **A casual investor can use the portfolio product on day one.** The Simple
  default answers "what do I own, what's it worth, am I up or down?" without a
  finance-jargon wall — an estimated 60–70% cognitive-load reduction.
- **Zero feature loss for power users.** Advanced mode preserves today's full
  layout byte-for-byte; it is a rendering gate, not a fork.
- **The #1 brokerage-linking trust barrier is removed.** Explicit "your
  credentials stay with SnapTrade, never Worldview; read-only" copy and honest
  sync timing reduce connect-flow churn.
- **Manual portfolios become editable without ledger pollution.** Edit, partial
  close, and a discoverable row action replace the close-and-re-add workaround —
  and every edit is an honest, visible adjusting trade.

---

## 2. Non-Goals

- **Tier 2 / Tier 3 items** from the report (§5): default-portfolio auto-create on
  provision, jargon tooltips, sync-progress indicator, concrete brokerage error
  messages, mutation-endpoint rate limiting. These are separate follow-ups.
- **Any backend or S9 change.** No new endpoints, schemas, migrations, or events.
  If any wave discovers a backend gap, it is escalated — not silently added.
- **A transaction-level edit/delete capability.** Correcting an *original*
  transaction (true history rewrite) is explicitly out of scope; Edit Position
  records a *new adjusting* transaction instead (§6.4). A future
  `PATCH/DELETE /transactions` is noted as a genuine backend follow-up (§14 OQ-2)
  but is NOT built here.
- **Removing or redesigning any existing power-user surface.** Every strip, panel,
  tab, and column that exists today remains reachable in Advanced mode.
- **Cost-basis-method simplification** (FIFO/AVCO dropdown on Create — report §4b).
  It is a Tier-2 concern; CreatePortfolioDialog is untouched by this PRD except
  for firing the onboarding-tour trigger (§6.8).
- **Mobile-specific redesign.** Existing responsive breakpoints are preserved;
  the dual-mode gate improves small screens as a side effect but no new mobile
  layout is authored.

---

## 3. Target Users & Journeys

### Persona A — Casual investor (Maya), the new public audience
| ID | Story | Priority |
|----|-------|----------|
| US-A1 | As a first-time user, when I open my portfolio I see a clean view (a few headline numbers + a simple holdings list), not a trading terminal, so I'm not overwhelmed. | must-have |
| US-A2 | As a casual user, a short guided tour after I create my first portfolio shows me how to add a position and switch to the advanced view, and I can dismiss it any time. | must-have |
| US-A3 | As someone linking a real brokerage, I'm told up front that Worldview never sees my password and access is read-only, so I trust the connect button. | must-have |
| US-A4 | After connecting, I'm told holdings can take minutes to a few hours and that I can press "Sync Now", so I don't think it's broken when nothing appears immediately. | must-have |
| US-A5 | When I add a position I get a ticker dropdown as I type and can set the date I actually bought it. | must-have |
| US-A6 | I can fix a position I entered wrong (quantity/cost) and I can sell part of a position — without deleting and re-adding. | should-have |

### Persona B — Power user / thesis-demo trader (Arnau)
| ID | Story | Priority |
|----|-------|----------|
| US-B1 | As a power user, I flip one toggle to Advanced and get today's full layout — every KPI tile, exposure/HHI strip, analytics tab, and all 14 columns — with nothing removed. | must-have |
| US-B2 | My mode choice persists across reloads and is shareable via a URL param, and my column-visibility choices persist. | must-have |
| US-B3 | I can show/hide holdings columns in Core / Portfolio / Advanced groups so I tune the table to my workflow. | should-have |
| US-B4 | Right-click context actions still work exactly as before; the new visible row affordance is additive. | must-have |

### Journey contrast (the core design)
```
NEW USER (Simple, default)                    POWER USER (Advanced, opt-in)
─────────────────────────────                 ─────────────────────────────
Header (portfolio name + actions)             Header (unchanged)
[ Mode: Simple | Advanced ]  ← toggle         [ Mode: Simple | Advanced ]
4 KPI tiles:                                   8 KPI tiles + allocation donut
  Total Value | Day P&L |                      Overview band (β-adj/leverage/HHI)
  Unrealised P&L | Cash                         Concentration strip
Holdings list (6 columns)                      Performance chart + SPY overlay
  Ticker Qty AvgCost Last MktVal Unrl$          Sector allocation bar
(no tabs, no strips, no donut,                  14-column table + column toggle
 no analytics, no bottom cluster)               Bottom cluster + detail pills
                                                Tabs: Holdings|Transactions|
                                                      Analytics|Watchlist
```

---

## 4. Currently-Implemented Map

Grounded in the source read this session (file:line authoritative).

| Area | Today | Key files |
|------|-------|-----------|
| **Page shell** | Thin client shell; `usePortfolioData()` owns 8 queries + KPI maths; renders header → PerformanceStrip → KPI strip + donut → 4 Tabs (Holdings/Transactions/Analytics/Watchlist). Dialogs (Create/AddPosition/Delete) lazy-loaded via `next/dynamic`. `nuqs` URL state for `?tab=`, `?period=`, `?sector=`. | `app/(app)/portfolio/page.tsx:143-773` |
| **Header** | Stateless; portfolio selector (multi only), position-count badge, Add Position / New Portfolio / Delete buttons, ROOT read-only hint, scope-hint sub-line. | `features/portfolio/components/PortfolioPageHeader.tsx:62-281` |
| **KPI strip** | **8 tiles** via `divide-x`: Total Value, Day P&L, Unrealised P&L, Realized P&L, Cash, Buying Pwr, Top Gain, Top Lose. `positionCount` prop deprecated. | `components/portfolio/PortfolioKPIStrip.tsx:246-461` |
| **Holdings tab body** | 7-row anchored layout: overview panel band (Market/Sector/Performance-periods), concentration strip, performance chart, sector-allocation bar, table chrome, `SemanticHoldingsTable`, bottom cluster; plus brokerage sync strips, detail-pill row + slide-over, sector-filter chip. | `features/portfolio/components/HoldingsTab.tsx:183-743` |
| **Holdings table** | AG Grid; TICKER pinned-left. Column state (width/order/visibility) persisted to localStorage `worldview-holdings-cols` via `applyColumnState`. URL-backed sort. Cell flash on quote change. Floating right-click context menu (`useContextMenuActions`) + a hand-added "Close Position" group. Pinned bottom TOTAL row. | `components/portfolio/SemanticHoldingsTable.tsx:162-704` |
| **Columns** | 15 colIds: `ticker,name,qty,avg_cost,current,dayChange,dayChangePct,spark,value,pnl,pnlPct,weight,sector,asset,divYld`. `divYld` `hide:true` by default; all others visible. | `components/portfolio/ag-holdings-columns.tsx:95-585` |
| **Add Position** | RHF + Zod dialog. Ticker `<Input>` (uppercased on change), NumberInput qty (>0), optional avg price. On submit: `searchInstruments(ticker,1)` → `addPosition()`. **No date field; no typeahead.** | `features/portfolio/components/AddPositionDialog.tsx:1-347` |
| **Close Position** | Lazy dialog opened from context menu. Ticker + **read-only quantity** (full close only), Sale Price (>0), Trade Date picker (defaults today). POSTs `/api/v1/transactions` with `trade_side:"SELL"`, `executed_at`, idempotency key. | `components/portfolio/ClosePositionDialog.tsx:72-352` |
| **Brokerage connect** | Modal: SnapTrade blurb, ToS link + consent checkbox ("read-only access"), Connect → `initiate` → `window.location.href = redirect_uri`. **No "credentials stay with SnapTrade / never Worldview" reassurance.** | `components/brokerage/ConnectBrokerageModal.tsx:62-239` |
| **Brokerage callback** | State machine idle→loading→success→error; on success activates connection + invalidates. Success copy: *"will begin syncing shortly."* **Misleading** (real cycle 4h). | `app/(app)/portfolio/brokerage/callback/page.tsx:183-210` |
| **Gateway** | `addPosition(portfolioId, instrumentId, qty, avgCost)` hardcodes `executed_at: new Date().toISOString()`. `addTransaction(tx)` already honours `tx.executed_at ?? now`. `deletePortfolio()`. | `lib/api/portfolios.ts:636-760` |
| **Search API** | `searchInstruments(q,limit)`, `searchFundamentals`, `resolveTickersBatch`. Public instrument search (no token). | `lib/api/search.ts:26-216` |
| **Manual empty state** | Rendered correctly at `HoldingsTab.tsx:622`, gated manual + 0 holdings. Report §2 confirms it is NOT a bug. | `components/portfolio/ManualPortfolioEmptyState.tsx:55-114` |

---

## 5. Break Surface

Components/tests/clients this PRD touches, with the risk each carries. Cite these
when planning waves; every listed test must be updated (not deleted — R19) if its
assertions change.

| Surface | Change | Risk | Refs |
|---------|--------|------|------|
| `page.tsx` | Add `mode` URL/localStorage state; gate KPI-tile count, tab bar, strips, donut, bottom cluster on mode; render mode toggle in header; mount `PortfolioTour`. | HIGH — this is the largest edit; must remain a **render gate**, not a fork. | `page.tsx:143-773` |
| `PortfolioKPIStrip.tsx` | Accept a `variant: "simple" \| "advanced"` (or `visibleTiles`) prop; Simple renders 4 tiles. Preserve 8-tile default. | MED — tile-count skeleton in `page.tsx:297` also assumes 8; update the loading skeleton to match active mode. | `PortfolioKPIStrip.tsx`, `page.tsx:283-317` |
| `PortfolioKPIStrip.test.tsx` | New assertions for 4-tile Simple render; keep 8-tile Advanced assertions. | MED | `components/portfolio/__tests__/PortfolioKPIStrip.test.tsx` |
| `HoldingsTab.tsx` | Accept `mode`; in Simple hide overview band, concentration strip, perf chart, sector bar, bottom cluster, detail-pill row, brokerage strips-optional; pass Simple column-group to the table. | HIGH — many conditional guards; must not change Advanced output. | `HoldingsTab.tsx:396-743` |
| `SemanticHoldingsTable.tsx` | Add `columnGroups`/`mode` prop → apply group visibility after restoring saved state; add pinned-right ACTIONS column renderer that opens the menu; wire Edit + Partial-close entry points. | HIGH — interacts with `applyColumnState` restore + `HOLDINGS_COLS_KEY`. | `SemanticHoldingsTable.tsx:243-321,569-704` |
| `SemanticHoldingsTable.test.tsx`, `ag-holdings-columns-pinned.test.tsx` | New actions column + group-visibility; pinned-column test may need the extra pinned-right col. | MED | `components/portfolio/__tests__/` |
| `ag-holdings-columns.tsx` | Add `group: "core"\|"portfolio"\|"advanced"` metadata per colId; add ACTIONS colId (pinned right, not movable, not sortable). | MED | `ag-holdings-columns.tsx:344-585` |
| `AddPositionDialog.tsx` | Add trade-date picker + debounced typeahead dropdown; call `addPosition(..., tradeDate)`. | MED — RHF integration + async dropdown a11y. | `AddPositionDialog.tsx:108-347` |
| `ClosePositionDialog.tsx` | Un-lock quantity (editable, validated ≤ holding.quantity); Full/Partial affordance; relabel. | MED — must keep idempotency key + default-full behaviour. | `ClosePositionDialog.tsx:72-352` |
| `ClosePositionDialog.test.tsx` | New partial-quantity validation cases; keep full-close default. | MED | `components/portfolio/__tests__/ClosePositionDialog.test.tsx` |
| `ConnectBrokerageModal.tsx` | Add reassurance copy block. | LOW | `ConnectBrokerageModal.tsx:133-199` |
| `brokerage/callback/page.tsx` | Replace success timing copy. | LOW — string change; keep the e2e-pinned success heading. | `callback/page.tsx:191-197` |
| `lib/api/portfolios.ts` | `addPosition` gains optional `tradeDate?: string` (ISO); default preserves "now". | LOW — additive param. | `portfolios.ts:636-696` |
| `CreatePortfolioDialog.tsx` | On success, set the tour-trigger localStorage flag (only if unset). | LOW — additive; no field changes. | `features/portfolio/components/CreatePortfolioDialog.tsx` |
| **New files** | `PortfolioModeToggle.tsx`, `PortfolioTour.tsx`, `EditPositionDialog.tsx`, `HoldingsColumnGroupToggle.tsx`, `lib/portfolio/holdings-column-groups.ts`, `hooks/usePortfolioMode.ts`, `lib/portfolio/adjusting-transaction.ts`. | — | — |
| **E2E** | `plan0108-portfolio-redesign.spec.ts`, `portfolio-overview-density.spec.ts`, `portfolio-overview-no-tabs.spec.ts`, `qa-exhaustive.spec.ts`, `transactions-filters.spec.ts` assert full-layout structure — they must run in **Advanced** mode (set `?mode=advanced` or seed localStorage) so they keep passing, and new specs cover Simple. | HIGH — silent breakage if these default to Simple. | `apps/worldview-web/e2e/` |

---

## 6. Detailed Design

> **Ordering: Tier 0 first (§6.1–6.3), then Tier 1 (§6.4–6.8).**
> Every feature is frontend-only unless a "Backend touchpoint" row says otherwise
> (none do — §8 confirms).

### 6.1 [Tier 0] Dual-mode portfolio page (Simple default / Advanced opt-in)

**Design principle (LOCKED): a rendering gate, never a fork.** There is exactly
one `page.tsx`, one `HoldingsTab`, one `SemanticHoldingsTable`. Mode is a single
value threaded down as a prop; each surface *conditionally renders* its
power-user chrome. No component is duplicated, and **no feature is removed** —
Advanced === today's output.

#### State source (R-1)
A new hook `hooks/usePortfolioMode.ts`:
- **localStorage key**: `worldview:portfolioMode:v1`, value `"simple" | "advanced"`.
- **URL param**: `?mode=simple|advanced` via `nuqs` `parseAsStringLiteral(["simple","advanced"])`
  with `.withOptions({ clearOnDefault: true })` (Simple is default → no `?mode=` noise).
- **Default**: **`simple`** when neither URL nor localStorage is set (the public
  default). An existing user who never chose still gets Simple — acceptable, and
  the tour + toggle make Advanced one click away.
- **Precedence**: URL param (if present) wins for *this render* (shareable links);
  otherwise localStorage; otherwise default. Selecting a mode writes **both** the
  URL param and localStorage so the choice is sticky and shareable.
- Hook returns `{ mode, setMode }`. `setMode` updates the nuqs param and
  `localStorage.setItem`.

#### Mode toggle control (R-6)
New `components/portfolio/PortfolioModeToggle.tsx` — a 2-segment control
(`Simple | Advanced`) rendered in `PortfolioPageHeader` action row (left of "Add
Position"). shadcn `Tabs`-style segmented button, terminal density (`h-6`,
`text-[10px] uppercase`, active = `bg-primary/10 text-primary`), `role="radiogroup"`,
`aria-label="Portfolio detail level"`. `data-tour-target="mode-toggle"` for the
tour. Also mount an identical toggle in the empty-portfolio early-return branch is
NOT needed (no data to show there).

#### Precise per-mode render matrix (R-2, R-3, R-4, R-5)

| Surface | Simple | Advanced (= today) |
|---|---|---|
| **KPI tiles** | **4**: Total Value, Day P&L, Unrealised P&L (with %), Cash | **8**: + Realized P&L, Buying Pwr, Top Gain, Top Lose |
| **Allocation donut** (`SectorAllocationDonut`) | hidden | shown (`xl:flex`) |
| **PerformanceStrip** | shown (compact 1-line perf is casual-friendly) | shown |
| **Overview panel band** (Market/Sector/Perf-periods, `HoldingsTab:421-437`) | hidden | shown |
| **ConcentrationSectorTeaseStrip** | hidden | shown |
| **PerformanceChartPanel** (equity curve + SPY) | hidden | shown |
| **SectorAllocationBar** | hidden | shown |
| **BottomStripCluster** (contributors/detractors/activity) | hidden | shown |
| **Detail-pill row + HoldingDetailSlideOver** | hidden | shown |
| **Brokerage sync strips / status banner** | shown (still useful to casual brokerage users) | shown |
| **Sector-filter chip row** | hidden (donut that sets it is hidden) | shown |
| **Tabs** | **Holdings only** — the `TabsList` is not rendered; the Holdings body renders directly | Holdings \| Transactions \| Analytics \| Watchlist |
| **Holdings table columns** | **Core group (6)** — see §6.7 | column-group toggle state (default: all except `divYld`) |
| **Column-group toggle** (⚙) | hidden | shown |
| **Loading skeleton** | 4-tile skeleton, no donut placeholder, table rows only | 8-tile + donut placeholder (today's `page.tsx:283-317`) |

Notes:
- Simple hiding the tab bar means Transactions/Analytics/Watchlist are reachable
  only in Advanced. This is the report's explicit "Holdings tab only" decision
  (§5 Tier 0.1). The toggle makes the switch a single click; the tour points at it.
- KPI Simple set is chosen for the casual "what's it worth / today / total gain /
  free cash" question. Implementation: `PortfolioKPIStrip` gains
  `variant?: "simple" | "advanced"` (default `"advanced"`); Simple returns after
  the 4th tile. The `divide-x` invariant (equal tile widths) holds within each set.

#### Rendering-gate implementation (R-7)
- `page.tsx`: read `mode`; pass to `PortfolioKPIStrip` (variant), to `HoldingsTab`
  (`mode` prop), and gate `SectorAllocationDonut` + `TabsList` on
  `mode === "advanced"`. In Simple, render `<HoldingsTab …>` directly instead of
  the `<Tabs>` wrapper (or render `<Tabs>` with a single trigger hidden — prefer
  direct render to avoid a 1-tab bar).
- `HoldingsTab.tsx`: add `mode?: "simple" | "advanced"` (default `"advanced"` so
  existing callers/tests are unchanged). Wrap each power-strip block in
  `mode === "advanced" && (...)`.
- **Invariant test**: an Advanced-mode snapshot must equal the pre-change snapshot
  (see §9 `test_advanced_mode_is_todays_layout`). This is the guard against a
  fork/regression.

**Copy strings** (mode toggle): labels `"Simple"`, `"Advanced"`; toggle
`title="Switch between a simple overview and the full analytics layout"`.

**Edge cases**:
- Root (aggregate) portfolio: mode still applies; Simple shows the 4 tiles + Core
  table; the ROOT read-only hint remains.
- Empty portfolio / 0-portfolio early returns are unaffected (they short-circuit
  before the mode-gated render).
- Deep link `?tab=analytics&mode=simple`: Simple has no tabs → `?tab` is ignored
  while Simple; switching to Advanced restores the tab. (nuqs keeps `?tab` in the
  URL harmlessly.)

### 6.2 [Tier 0] Brokerage connect: trust + timing copy

Two pure copy changes; no logic, no new state.

#### Reassurance block in the modal (R-8)
In `ConnectBrokerageModal.tsx`, add a bordered info block above the ToS notice
(`ConnectBrokerageModal.tsx:144`), styled like the existing ToS box
(`rounded-[2px] border border-border/50 bg-muted/30 px-3 py-2.5 text-xs`), with a
`ShieldCheck` lucide icon:

> **Your credentials stay with SnapTrade — never Worldview.**
> We use SnapTrade's secure, read-only connection. Worldview never sees or stores
> your brokerage username or password, and can only *read* your holdings and
> transactions — it can never place trades or move money.

`data-testid="brokerage-trust-block"`. Icon `aria-hidden`. This does not replace
the existing ToS consent checkbox (still required to enable Connect).

#### Honest timing copy on the callback (R-9, R-10)
In `brokerage/callback/page.tsx`, replace the success body
(`callback/page.tsx:193-197`) — **keep the pinned success heading** *"Brokerage
account connected successfully!"* (e2e/qa asserts it) and change only the sub-copy:

> Your first sync has started. Holdings usually appear within a few minutes, but
> a full import can take up to a few hours. If you don't see them yet, open the
> connected brokerage and press **Sync Now** to pull the latest data.

The "Go to Portfolio" button is unchanged. (Sync Now already exists on the
connected-brokerages list — `qk.brokerage.connections()` surface; this copy just
points users to it.)

**Edge cases**: copy is static; no i18n in scope. The 4-hour figure
(`config.py:114`) is described qualitatively ("up to a few hours") so a future
cycle-time change doesn't falsify the string.

### 6.3 [Tier 0] Add Position: trade-date picker + inline debounced typeahead

#### Trade-date picker (R-11, R-13)
- Add a `tradeDate` field to `AddPositionDialog` (native `<input type="date">`,
  same chrome as ClosePositionDialog's date field: `h-7 font-mono text-[12px]`).
  Default = today (local `YYYY-MM-DD`, using the same local-date builder as
  `ClosePositionDialog.tsx:92-98`). Label `"Trade Date"`.
- Validation: not in the future (`max={today}`); Zod refine
  `tradeDate <= today` → message `"Trade date can't be in the future."`.
- On submit, pass `${tradeDate}T00:00:00Z` to the gateway.
- **Gateway change (R-13)**: `addPosition(portfolioId, instrumentId, quantity,
  averageCost, tradeDate?: string)` — when `tradeDate` is provided use it for
  `executed_at`; else keep `new Date().toISOString()` (backward compatible;
  `lib/api/portfolios.ts:656`). No backend change — `executed_at` already accepted.

#### Inline debounced ticker typeahead (R-12, R-14)
- Replace the bare `<Input>` for ticker with a combobox: the input plus an
  absolutely-positioned results dropdown. As the user types (≥1 char), debounce
  **250 ms** (matching the CommandPalette convention, DS §6.15) and call
  `searchInstruments(query, 8)` via TanStack Query keyed
  `["instrument-search", query]` (shared cache with GlobalSearch/CommandPalette).
- Dropdown rows: `TICKER (font-mono, text-primary)` + synthesised name/exchange
  (`SearchResult.name`), keyboard-navigable (↑/↓/Enter), mouse-selectable
  (wire BOTH `onSelect` + `onClick` — the SEARCH-001 dual-handler rule, DS §6.15).
  Selecting a row sets the ticker field to `result.ticker` and stashes the
  resolved `instrument_id` in form state so submit **skips the redundant search**.
- If the user types a ticker and submits without picking a row, keep today's
  submit-time `searchInstruments(ticker,1)` fallback (`AddPositionDialog.tsx:146`)
  so behaviour never regresses.
- Loading/empty states: a `Skeleton` row while fetching; a muted
  *"No instruments match \"XYZ\""* when empty (no crash — mirrors search.ts guards).
- Reuse shadcn `Command`/`CommandList` primitives (DS §5.1) inside the dialog with
  `shouldFilter={false}` (we filter server-side) — the DS §6.15 reuse rule.

**Copy strings**: input placeholder `"Search ticker or company… e.g. AAPL"`;
empty `"No instruments match \"{q}\"."`; date label `"Trade Date"`.

**Edge cases**:
- Typeahead is public (no token) — works pre-auth-refresh like today's search.
- Debounce cancels in-flight queries on unmount (TanStack handles).
- A picked instrument then hand-edited ticker string invalidates the stashed
  `instrument_id` (clear it on manual edit) so submit re-resolves.

### 6.4 [Tier 1] Edit Position (adjusting transaction — honest ledger)

**Locked mechanism (R-15) (from §1.2.4): holdings are DERIVED; there is no transaction
PATCH/DELETE. Edit Position therefore records a NEW adjusting transaction via the
existing `POST /v1/transactions`. It NEVER mutates a holding in place and NEVER
rewrites history.**

New `components/portfolio/EditPositionDialog.tsx`, opened from the row action
menu (§6.6) and the right-click context menu.

#### What "edit" means, precisely (R-16)
The dialog shows the current derived position **read-only** (Ticker, current Qty,
current Avg Cost, current Mkt Value) and asks the user for a **target quantity**
and an **adjustment price**:

- `delta = targetQty − currentQty`
- `delta > 0` → record a **BUY** of `delta` shares at the adjustment price.
- `delta < 0` → record a **SELL** of `|delta|` shares at the adjustment price.
- `delta == 0` → Submit disabled (nothing to record).

Request shape (identical to Close/Add — no new endpoint):
```jsonc
POST /api/v1/transactions
Headers: { "Idempotency-Key": <stable per dialog instance>, Authorization: Bearer … }
{
  "portfolio_id": "<uuid>",
  "instrument_id": "<uuid>",
  "transaction_type": "TRADE",
  "trade_side": "BUY" | "SELL",     // derived from sign(delta)
  "quantity": <abs(delta)>,          // > 0 (schema-validated)
  "price": <adjustmentPrice>,        // > 0
  "fees": 0,
  "currency": "USD",
  "executed_at": "<tradeDate>T00:00:00Z",
  "external_ref": null
}
```
Helper `lib/portfolio/adjusting-transaction.ts` computes `{ side, quantity }` from
`(currentQty, targetQty)` — pure + unit-tested.

#### Honest-ledger requirements (R-17)
- The dialog carries an explicit, unmissable note:
  > This records an **adjusting trade** in your history (a BUY or SELL for the
  > difference) — it does not rewrite past transactions. Your average cost is
  > recalculated from your full trade history.
- The Transactions tab therefore shows a real adjusting BUY/SELL — the ledger is
  truthful. There is **no silent avg-cost overwrite**.
- Because avg cost is a *derived* figure (AVCO blend or FIFO lots, per
  `portfolios.cost_basis_method`), the user changes it only through the
  adjustment price on the delta trade. The dialog surfaces the *resulting*
  direction (BUY/SELL of N @ price) so the effect is transparent before submit.
- **Correcting an original typo** (e.g. bought 100 not 10) is done by an adjusting
  SELL/BUY of the difference — visible and honest. True original-record editing is
  OQ-2 (§14), a backend follow-up, explicitly out of scope.

#### Fields, validation, copy (R-18)
- Target Quantity: NumberInput, `≥ 0`, `≤ 1,000,000`. `0` means "close entirely"
  (records a full SELL) — allowed.
- Adjustment Price: `> 0`; default = current live price if available (from the
  row's `livePrice`), else avg cost.
- Trade Date: date picker, default today, not future (same rule as §6.3).
- Submit label reflects the action: `"Record BUY of {n}"` / `"Record SELL of {n}"`;
  disabled when `delta === 0` or price invalid.
- Success: `toast.success("Adjustment recorded", { description: "Holdings update within seconds." })`,
  then `onHoldingsRefetch()` (same invalidation path as Add/Close).
- Idempotency key via `useRef(crypto.randomUUID())` (mirrors ClosePositionDialog).

**Edge cases**: root portfolio → entry point hidden (S1 rejects root trades);
`targetQty === currentQty` → disabled; negative/NaN → inline error; network error →
`toast.error` + keep dialog open (mirrors ClosePositionDialog).

**Backend touchpoint: NONE** (uses existing `POST /transactions`).

### 6.5 [Tier 1] Partial close

Un-lock the quantity in `ClosePositionDialog.tsx` (today it is read-only and full
only — `ClosePositionDialog.tsx:269-275`).

- **R-19**: quantity becomes an editable NumberInput, **default = full holding
  quantity** (unchanged default behaviour → full close is still one click).
- **R-20**: validation `0 < quantity ≤ holding.quantity`; messages
  *"Quantity must be greater than 0."* / *"You only hold {n} shares."*
- **R-21**: a Full/Partial affordance — a small "Sell all" link/button that
  resets quantity to the full holding; the title updates to
  *"Close Position"* (full) vs *"Sell {n} of {total}"* (partial) so intent is
  explicit. Dialog header stays `Close Position — {ticker}`.
- Submit posts the same SELL body with the entered `quantity` (already valid per
  §1.2.3 — S1 accepts any positive quantity). Idempotency key + trade date
  behaviour unchanged.

**Edge cases**: entering the full quantity behaves exactly like today; a partial
SELL leaves a reduced derived holding after recompute; quantity > holding is
blocked client-side (and S1 would still record it, but we prevent an
over-sell UX). No backend change.

### 6.6 [Tier 1] Visible row-level action affordance (in addition to right-click)

Delete/close is only reachable via right-click today (report §4d) — invisible on
touch/trackpad.

- **R-22**: add a pinned-right, non-movable, non-sortable **ACTIONS** column
  (`colId:"actions"`, width 40 px, `group:"core"` so it's always present) to
  `ag-holdings-columns.tsx`. Its cell renders a `MoreVertical` (kebab) icon button
  — visible on row hover (and always visible on touch via
  `@media (hover: none)`), `aria-label="Actions for {ticker}"`.
- **R-23**: clicking/tapping the kebab opens the **same floating menu** used by
  the right-click path, positioned at the button's bounding rect, offering:
  **Edit Position** (§6.4) · **Partial Close / Close Position** (§6.5) · plus the
  existing `ctxGroups` actions (view instrument, add to watchlist, etc.). The
  right-click context menu is preserved unchanged (additive requirement).
- Root portfolio: the Edit/Close items are hidden (as today's close gating);
  the kebab still offers the read-only actions (view instrument).
- Pinned bottom TOTAL row: ACTIONS cell renders empty.

**Edge cases**: the pinned-right column must survive `applyColumnState` restore —
it is added to `holdingsAgColumns` so saved state that predates it simply appends
it (AG Grid keeps unknown-to-saved columns at their defined position). The
existing `ag-holdings-columns-pinned.test.tsx` gets a case for the new right pin.

### 6.7 [Tier 1] Holdings-table column-visibility toggle (Core / Portfolio / Advanced)

#### Column groups (R-24)
Add `group` metadata to each colId in `ag-holdings-columns.tsx`:

| Group | colIds | Count |
|-------|--------|-------|
| **Core** (always on; Simple-mode set) | `ticker` (pinned, locked), `qty`, `avg_cost`, `current`, `value`, `pnl`, `actions` (pinned right) | 6 data + actions |
| **Portfolio** | `name`, `dayChange`, `dayChangePct`, `pnlPct`, `weight` | 5 |
| **Advanced** | `spark`, `sector`, `asset`, `divYld` | 4 |

`ticker` and `actions` are locked-visible (never hideable — they anchor the row).
Simple mode (§6.1) renders **exactly the Core group**.

#### Persistence (R-25)
- New key `worldview:holdingsColGroups:v1` storing
  `{ core: true (locked), portfolio: boolean, advanced: boolean }`.
- **Advanced-mode default** = `{ portfolio: true, advanced: true }` → shows every
  column except `divYld` (which keeps its own `hide:true` today) — i.e. **today's
  layout is preserved** (US-B1). `divYld` remains an individually toggleable
  Advanced column.
- Group visibility is applied via `api.setColumnsVisible(colIds, visible)` **after**
  the existing `applyColumnState` restore in `handleGridReady`
  (`SemanticHoldingsTable.tsx:243-277`), so the group layer sits on top of the
  AG-Grid width/order persistence (which stays in `worldview-holdings-cols`). The
  two keys are orthogonal (one = visibility groups, one = widths/order).

#### Interaction with Simple/Advanced (R-26)
- **Simple mode**: force Core-only regardless of the saved group state (the group
  toggle UI is hidden). Leaving Simple restores the user's Advanced group choice.
- **Advanced mode**: the saved group state governs; the ⚙ toggle is shown.

#### Toggle UI (R-27)
New `components/portfolio/HoldingsColumnGroupToggle.tsx` — a `Settings2` (⚙) icon
button (`h-7 w-7`) in `HoldingsTableChrome`, opening a shadcn `Popover` with three
checkboxes: **Core** (checked, disabled), **Portfolio**, **Advanced**, plus a
"Reset" that restores the Advanced default. Follows the existing Column-Settings
pattern (DS §6.5d). `data-tour-target="column-toggle"`.

**Copy**: popover heading `"Columns"`; rows `"Core (always shown)"`,
`"Portfolio detail"`, `"Advanced metrics"`; reset `"Reset to default"`.

**Edge cases**: corrupted/absent localStorage → Advanced default; a saved state
that hides a now-removed colId is ignored; `divYld` can be individually shown via
AG Grid's own column menu without affecting the group flags.

### 6.8 [Tier 1] Guided onboarding tour (after first portfolio creation)

New `components/portfolio/PortfolioTour.tsx` — a lightweight, **custom** tour
built on shadcn `Popover` (Radix) anchored to `data-tour-target` attributes. **No
new dependency** (react-joyride/shepherd would require a pnpm add + CVE audit —
DS forbids non-shadcn libs; §7 rationale).

#### Trigger (R-28)
- `CreatePortfolioDialog.onSuccess` sets `localStorage["worldview:portfolioTourSeen:v1"]`
  **to a "pending" sentinel only if unset** (first-ever portfolio create).
- On the next `/portfolio` render with holdings/empty state visible and the flag
  === "pending", `PortfolioTour` auto-starts (step 0), then the flag is set to
  "done" the moment the tour starts (so it never re-triggers even if abandoned).
- Never triggers for users who already have portfolios (flag already set by their
  first create, or backfilled to "done" on first mount if they have ≥1 portfolio).

#### Steps (R-29)
Anchored popovers, ≤ 5 steps, each ≤ 2 sentences:
1. **Welcome** (anchor: page header) — "This is your portfolio. Here's a 20-second tour."
2. **Detail level** (anchor `data-tour-target="mode-toggle"`) — "Start in **Simple**
   for a clean overview; switch to **Advanced** any time for full analytics."
3. **Add a position** (anchor: Add Position button) — "Add holdings manually here —
   search a ticker and set the date you bought."
4. **Connect a brokerage** (anchor: Transactions tab / Connect button; in Simple,
   anchor the header and mention switching to Advanced) — "Or connect a brokerage
   to import automatically — read-only, credentials stay with SnapTrade."
5. **Advanced columns** (anchor `data-tour-target="column-toggle"`, shown only in
   Advanced; skipped in Simple) — "Show or hide table columns to match how you work."

Each popover: "Back" / "Next" (or "Done" on last) + a persistent **"Skip tour"**
and an **×**. A subtle backdrop dims the page but **does not block** clicks outside
targets is acceptable; the tour must never trap focus destructively.

#### Non-blocking / dismissible (R-30, R-31)
- Any of ×, Skip, Escape, or route-change ends the tour and sets the flag "done".
- The tour never prevents interacting with the page (no modal overlay that
  swallows the primary actions); it is a guide layer, not a gate.
- Implementation is a small state machine (`step` index) + Radix `Popover`
  `open` controlled per step; targets resolved by `document.querySelector([data-tour-target])`.
  If a target is missing (e.g. step 5 in Simple), the step is skipped.

**Edge cases**: SSR — tour is client-only (`"use client"`, reads localStorage in
effect); reduced-motion — no animated spotlight; missing anchor — skip step;
empty-portfolio state — steps 3/4 still anchor to the header CTAs.

---

## 7. Architecture Decisions & Trade-offs

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| Simple vs Advanced | **One codebase, prop-driven render gate** | Separate `/portfolio/simple` route or duplicated components | A fork doubles maintenance and guarantees drift/feature-loss; the gate makes Advanced provably === today (§9 snapshot test) and keeps one source of truth. |
| Mode default | **Simple** | Advanced (status quo) | The public audience is casual; Advanced-by-default is the exact wall the report flags. Power users opt in once (sticky). |
| Mode persistence | **localStorage + URL param** | Cookie / server-side pref | Matches existing portfolio URL-state convention (`?tab`, `?period`, `?sector` via nuqs); URL param makes a view shareable; localStorage makes it sticky. No backend pref store needed. |
| Edit Position | **Adjusting BUY/SELL via existing `POST /transactions`** | (a) in-place holding mutation; (b) new `PATCH /transactions` | (a) is impossible/dishonest — holdings are derived and never written by the API; (b) is a backend project out of scope. The adjusting trade is honest, visible, and zero-backend. |
| Partial close | **Un-lock quantity on the existing SELL dialog** | New partial-close endpoint | S1 already accepts any positive SELL quantity; it's a pure client un-lock. |
| Row action affordance | **Pinned-right kebab column reusing the existing floating menu** | Separate delete button / new menu system | Reuses `useContextMenuActions` + the existing floating menu; additive to right-click; discoverable on touch. |
| Column groups | **Group metadata + `setColumnsVisible` over the existing state restore** | Rebuild column persistence | Preserves the AG-Grid width/order persistence already in place; groups are an orthogonal visibility layer. |
| Onboarding tour | **Custom shadcn `Popover` state machine** | react-joyride / shepherd.js | DS mandates shadcn/ui-only + `pnpm audit` 0 CVEs; a 5-step popover tour doesn't justify a new dependency. |
| Typeahead | **Debounced `searchInstruments` in a `Command` combobox** | New search endpoint / paste-UUID | Endpoints already exist (report §2 correction); reuse the CommandPalette cache key + dual-handler rule. |

### 7.1 Architecture Compliance Gate

| Rule | Applies? | Design decision | Compliant? |
|------|----------|-----------------|-----------|
| **R14 — Frontend → S9 only** | yes | All calls go through the existing gateway (`/api/v1/*`); no direct backend URLs; no new endpoints. | PASS |
| **R15 — Update docs** | yes | §12 lists `docs/apps/worldview-web.md`, DS, `.claude-context` updates. | PASS |
| **R19 — Never delete/weaken tests** | yes | Existing e2e run in Advanced mode; unit tests are updated with new cases, not removed. | PASS |
| **DS — shadcn/ui only, Terminal Dark, mono numbers, 2px radius** | yes | New components use shadcn `Popover`/`Command`/`Dialog`/`Tabs`, semantic tokens, `font-mono tabular-nums`, `rounded-[2px]`. | PASS |
| **Frontend pnpm / 0 CVEs / exact versions** | yes | **No new dependency added** (custom tour, existing search). | PASS |
| **Heavy inline comments (user new to Next.js)** | yes | All new components carry WHY-comments per the frontend-comments feedback. | PASS |
| **No backend / no migration** | yes | §8 confirms every touchpoint is client-side. | PASS |

No FAIL rows.

---

## 8. Data / API Changes

**None.** Enumerated exhaustively so `/plan` can assert "no backend wave":

| Capability | Endpoint used | Already exists? | Evidence |
|---|---|---|---|
| Add position with a chosen date | `POST /v1/transactions` (`executed_at`) | **Yes** | `api/schemas.py:121` (`executed_at: datetime`); gateway already sends it in `addTransaction` (`portfolios.ts:721`). |
| Partial close | `POST /v1/transactions` (SELL, any positive qty) | **Yes** | `api/schemas.py:138-142` validates qty **positive** only. |
| Edit position (adjusting trade) | `POST /v1/transactions` (BUY or SELL of delta) | **Yes** | same route; no PATCH/DELETE needed. |
| Ticker typeahead | `GET /v1/search/instruments` | **Yes** | `lib/api/search.ts:43-84`; public. |
| Column toggle / mode / tour | localStorage + `nuqs` URL param | client-only | no API. |

**Explicitly NOT built (would be backend, out of scope):**
`PATCH /v1/transactions/{id}` and `DELETE /v1/transactions/{id}` (true original-record
edit) — see §14 OQ-2. Nothing in this PRD depends on them.

Client-side additive change only: `gateway.addPosition()` gains an optional
`tradeDate?: string` parameter (`lib/api/portfolios.ts`).

---

## 9. Testing Strategy

### Unit / component (Vitest + Testing Library)
| Test | Verifies | Feature |
|------|----------|---------|
| `test_mode_default_is_simple` | No URL/localStorage → Simple; 4 KPI tiles; no tab bar; no overview band. | 6.1 |
| `test_advanced_mode_is_todays_layout` | With `mode=advanced`, the rendered tree matches the pre-change snapshot (8 tiles, tabs, all strips). **Regression guard against a fork.** | 6.1 |
| `test_mode_toggle_persists` | Clicking Advanced writes `worldview:portfolioMode:v1` + `?mode=advanced`; reload restores it. | 6.1 |
| `test_kpi_strip_variant_simple_renders_four_tiles` | `PortfolioKPIStrip variant="simple"` renders exactly Total Value / Day P&L / Unrealised / Cash. | 6.1 |
| `test_brokerage_trust_block_present` | Modal shows the "credentials stay with SnapTrade, never Worldview / read-only" block. | 6.2 |
| `test_callback_timing_copy` | Success sub-copy mentions "few minutes"/"few hours"/"Sync Now"; heading string unchanged. | 6.2 |
| `test_add_position_trade_date_defaults_today_and_blocks_future` | Date defaults today; future date → validation error; submit sends `executed_at` from the picked date. | 6.3 |
| `test_add_position_typeahead_debounces_and_selects` | Typing debounces 250 ms, shows results, selecting a row stashes `instrument_id` and skips submit-time search. | 6.3 |
| `test_add_position_typeahead_empty_and_fallback` | Empty results render the muted message; submitting a typed-but-unpicked ticker still resolves via `searchInstruments(…,1)`. | 6.3 |
| `test_adjusting_transaction_delta` | `computeAdjustment(current, target)` → correct `{side, quantity}` for +, −, 0. | 6.4 |
| `test_edit_position_posts_delta_trade` | Target > current → BUY of delta; target < current → SELL of delta; delta 0 → submit disabled. | 6.4 |
| `test_edit_position_ledger_note_present` | The "adjusting trade, not a rewrite" note renders. | 6.4 |
| `test_partial_close_quantity_editable_and_validated` | Quantity editable, default full; `> holding` blocked; `0` blocked; full still one click. | 6.5 |
| `test_row_action_kebab_opens_menu` | Kebab renders per row, opens the same menu with Edit / Close; right-click still works. | 6.6 |
| `test_column_groups_membership_and_lock` | Core/Portfolio/Advanced colId membership; `ticker`+`actions` locked-visible. | 6.7 |
| `test_column_group_toggle_persists_and_gates` | Toggling Portfolio off hides its columns + persists; Simple forces Core-only regardless. | 6.7 |
| `test_tour_triggers_once_after_first_create` | Flag "pending" → tour starts, flag → "done"; never re-triggers; Skip/Esc/× end it. | 6.8 |

### E2E (Playwright)
| Spec | Scenario |
|------|----------|
| **Update existing** `plan0108-portfolio-redesign.spec.ts`, `portfolio-overview-density.spec.ts`, `portfolio-overview-no-tabs.spec.ts`, `qa-exhaustive.spec.ts`, `transactions-filters.spec.ts` | Force **Advanced** (seed `localStorage["worldview:portfolioMode:v1"]="advanced"` or nav `?mode=advanced`) so full-layout assertions keep passing (R19). |
| `portfolio-simple-mode.spec.ts` (new) | Default load shows Simple (4 tiles, no tabs, 6-col table); toggle → Advanced shows full layout; reload persists. |
| `portfolio-add-position-typeahead.spec.ts` (new) | Type "AAPL" → dropdown → select → set past date → submit → toast; verify request `executed_at`. |
| `portfolio-edit-partial-close.spec.ts` (new) | Kebab → Edit → target qty change records adjusting trade (visible in Transactions); Partial Close sells part; full close still works. |
| `portfolio-onboarding-tour.spec.ts` (new) | First portfolio create → tour appears → Skip dismisses → does not reappear on reload. |
| `brokerage-connect-copy.spec.ts` (new or extend) | Modal shows trust block; callback stub shows honest timing copy. |

Coverage bar: all new components ≥ the repo's existing portfolio-component
coverage; the Advanced-snapshot test is a required gate before merge.

---

## 10. Rollout / Flagging

Phased, each wave independently shippable and reversible:

1. **W-A — Mode scaffold (dark-safe).** `usePortfolioMode` + toggle, but default
   left at **Advanced** behind a build-time constant `PORTFOLIO_SIMPLE_DEFAULT=false`
   so production is unchanged while the gate is wired and the Advanced-snapshot
   test proves parity.
2. **W-B — Simple render matrix.** Implement all §6.1 gating; flip
   `PORTFOLIO_SIMPLE_DEFAULT=true` only after the snapshot + Simple specs pass.
3. **W-C — Brokerage copy + Add-Position date/typeahead** (independent; can ship
   before or after W-B).
4. **W-D — Edit Position + partial close + row kebab.**
5. **W-E — Column-group toggle** (depends on W-B's Simple/Core wiring).
6. **W-F — Onboarding tour + docs + e2e hardening.**

**Rollback**: setting `PORTFOLIO_SIMPLE_DEFAULT=false` (or the localStorage/URL
override) returns every user to today's Advanced layout instantly — the gate is a
pure render switch, no data migration, no destructive change. Copy changes and the
additive dialogs are inert unless invoked.

---

## 11. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Simple/Advanced diverges into a fork (feature loss for power users) | med | high | Single prop-gated codebase; **`test_advanced_mode_is_todays_layout` snapshot** is a merge gate; §6.1 forbids duplication. |
| Existing e2e break because they now load Simple by default | high | med | Break-surface §5 lists them; W-A/W-B update them to force Advanced (R19, not deletion). |
| Column group layer fights the AG-Grid `applyColumnState` restore | med | med | Group visibility applied *after* restore via `setColumnsVisible`; two orthogonal localStorage keys; unit test `test_column_group_toggle_persists_and_gates`. |
| Edit Position perceived as "editing history" (dishonest) | med | high | Explicit adjusting-trade note (R-17); the trade appears in Transactions; never mutates a holding; §6.4 copy. |
| Partial over-sell (qty > holding) confuses derived recompute | low | med | Client-side `≤ holding.quantity` guard (R-20); S1 still safe. |
| Typeahead latency / cold ILIKE (2–4 s) feels slow | med | low | 250 ms debounce + shared cache with CommandPalette; `resolveTickersBatch`/exact-lookup path already fast; skeleton row communicates loading. |
| Tour anchors missing (Simple hides step 5 target) | med | low | Missing `data-tour-target` → step skipped; tour is non-blocking and dismissible. |
| New pinned-right ACTIONS column breaks pinned-column test | med | low | Update `ag-holdings-columns-pinned.test.tsx`; column is `lockPinned:"right"`, `suppressMovable`. |
| Mode default flip surprises returning users | med | med | Sticky localStorage from any prior explicit choice; tour explains the toggle; one click to Advanced. |

---

## 12. Documentation Updates (mandatory)

- `docs/apps/worldview-web.md` — dual-mode portfolio page, `usePortfolioMode`,
  the mode URL param + localStorage keys, column-group toggle, onboarding tour,
  Edit/Partial-close dialogs.
- `docs/ui/DESIGN_SYSTEM.md` — add: "Progressive-disclosure / dual-mode pattern"
  (casual default + advanced opt-in as a render gate), the onboarding-tour popover
  pattern, and the holdings column-group toggle (cross-ref DS §6.5d).
- `apps/worldview-web` context note — record the localStorage keys
  (`worldview:portfolioMode:v1`, `worldview:holdingsColGroups:v1`,
  `worldview:portfolioTourSeen:v1`) alongside the existing `worldview-holdings-cols`.
- `docs/audits/2026-07-08-portfolio-public-launch-ux-investigation.md` — mark
  Tier 0 + Tier 1 as "scoped by PRD-0122".
- `docs/plans/TRACKING.md` — register PRD-0122.
- Add the review-checklist item from the report §7: *"new UI surfaces must define a
  casual-user default + progressive disclosure before public exposure."*

---

## 13. Observability

Frontend-only; no server metrics. Optional client analytics events (if the app's
analytics shim is wired) — non-blocking, best-effort:
- `portfolio_mode_changed` `{ to: "simple"|"advanced" }`
- `add_position_typeahead_selected` `{ resolved: bool }`
- `edit_position_recorded` `{ side, qty }` / `partial_close_recorded` `{ pct }`
- `onboarding_tour` `{ action: "start"|"skip"|"complete", step }`
- `column_group_toggled` `{ group, visible }`

No PII, no evidence text; tickers/qty only.

---

## 14. Open Questions

All core decisions are LOCKED. Remaining items have an assumption to proceed — none
block implementation.

| # | Question | Class | Assumption to proceed |
|---|----------|-------|-----------------------|
| OQ-1 | Should Simple mode expose a lightweight Transactions view (e.g. a "recent activity" strip) instead of hiding transactions entirely? | DEFERRED | Follow the report literally: **Holdings-only** in Simple; Transactions live in Advanced. Revisit if casual users report "where's my history?". |
| OQ-2 | Do we eventually need `PATCH/DELETE /v1/transactions` for true original-record correction (vs adjusting trades)? | DEFERRED (backend) | **Out of scope.** Edit Position uses adjusting trades. If original-record editing is demanded, it's a separate backend PRD (S1 + FIFO recompute implications). |
| OQ-3 | Exact 4-tile Simple KPI set — is "Cash" more valuable than "Realized P&L" for casual users? | DEFERRED | Ship Total Value / Day P&L / Unrealised P&L / Cash; the tile set is a one-line change if user testing prefers Realized P&L. |
| OQ-4 | Should the onboarding tour also run for existing users on their next visit (not just brand-new)? | DEFERRED | No — trigger only on **first portfolio create**; backfill the flag to "done" for users who already have portfolios so it never surprises them. |
| OQ-5 | Should Advanced's default column set include `divYld` (dividend investors) rather than keeping it `hide:true`? | DEFERRED | Keep `divYld` hidden by default (today's behaviour); it's individually toggleable. Revisit per user segment. |

---

## 15. Estimation

| Wave | Scope (requirements) | Size |
|------|----------------------|------|
| **W-A** | `usePortfolioMode` + `PortfolioModeToggle` + Advanced-snapshot parity test; wire prop threading with default still Advanced (R-1, R-6, R-7). | M |
| **W-B** | Full Simple render matrix — KPI variant, tab-bar gate, strip gates, 4-tile skeleton; flip default to Simple (R-2, R-3, R-4, R-5). | L |
| **W-C** | Brokerage trust block + honest callback copy; Add-Position trade-date + debounced typeahead + gateway `tradeDate` param (R-8..R-14). | M |
| **W-D** | EditPositionDialog + adjusting-transaction helper; partial-close un-lock; pinned-right ACTIONS kebab reusing the floating menu (R-15..R-23). | L |
| **W-E** | Column-group metadata + `HoldingsColumnGroupToggle` + persistence + Simple/Advanced interaction (R-24..R-27). | M |
| **W-F** | `PortfolioTour` + create-dialog trigger; docs; e2e hardening (force Advanced on existing specs, add new specs) (R-28..R-31). | M |

**Requirement count: 31 (R-1 … R-31).**
