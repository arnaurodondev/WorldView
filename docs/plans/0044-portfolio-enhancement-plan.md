# PLAN-0044 — Portfolio Page Enhancement

**Created**: 2026-04-28
**Status**: draft
**PRD**: Design investigation session 2026-04-28 — portfolio enhancements
**Tracking**: `docs/plans/TRACKING.md`

---

## Problem Statement

The portfolio page has multiple gaps identified through live use:

1. **Sidebar right-edge bug** — drag handle visual line appears 3px inside the boundary, causing visible misalignment between the sidebar and main content
2. **Holdings table lacks day change** — current table shows P&L from avg cost but not today's absolute price change (already in quotes data — not displayed)
3. **Weight column is plain text** — a plain percentage gives no visual weight signal; Bloomberg uses mini bars
4. **No column sort** — holdings can't be sorted by any column
5. **Watchlist missing delete** — members can be added but not removed; no delete/create watchlist capability
6. **Brokerages tab is an island** — brokerage connections are in a separate tab disconnected from transaction history; merging simplifies the mental model

## Non-Goals (deferred)

- Portfolio performance time-series chart — no S9 endpoint exists; requires separate PRD
- Global top bar portfolio widget — Bloomberg convention keeps portfolio data in portfolio views; deferred
- Sparklines per holding — expensive (N concurrent OHLCV queries); deferred to later wave
- Beta/dividend columns — requires fundamentals lazy-load per holding; deferred

## Codebase State (verified against source)

| Component | File | Current State | Delta |
|-----------|------|--------------|-------|
| CollapsibleSidebar drag handle | `components/shell/CollapsibleSidebar.tsx:339` | `div.w-1` hit zone, inner `div.w-px.bg-border` defaults to leftmost pixel | Add `flex justify-end` to outer div → aligns visual line to right edge |
| WatchlistMemberRow | `components/portfolio/WatchlistsTabPanel.tsx` | 5 columns (Ticker, Name, Price, CHG%, CHG$) — no delete button | Add delete `×` button on row right, shown on hover |
| WatchlistsTabPanel | `components/portfolio/WatchlistsTabPanel.tsx` | Tab bar shows watchlist names + member count; no create/delete watchlist | Add `[+ New]` button + delete per watchlist tab |
| SemanticHoldingsTable | `components/portfolio/SemanticHoldingsTable.tsx` | 10 cols; no day change; weight is plain `%` text; no sort | Add DAY$ + DAY% cols; visual weight bar; click-to-sort headers |
| Portfolio page tabs | `app/(app)/portfolio/page.tsx` | 4 tabs: Holdings, Transactions, Watchlist, Brokerages | Merge Brokerages into Transactions tab |

## S9 Endpoint Check

| Feature | Endpoint | Status |
|---------|----------|--------|
| Day change per holding | `POST /v1/quotes/batch` — `change`, `change_pct` already in response | ✅ Ready |
| Delete watchlist member | `DELETE /v1/watchlists/{id}/members/{entity_id}` → `removeWatchlistMember()` | ✅ Ready |
| Create watchlist | `POST /v1/watchlists` → `createWatchlist()` | ✅ Ready |
| Delete watchlist | `DELETE /v1/watchlists/{id}` → `deleteWatchlist()` | ✅ Ready |
| Brokerage connections | `GET /v1/brokerage-connections` already used in Brokerages tab | ✅ Ready |

---

## Wave 1: Bug Fix + Watchlist CRUD

**Goal**: Fix the sidebar edge bug and give watchlists full create/read/update/delete capability.
**Depends on**: none
**Estimated effort**: 45–60 minutes
**Architecture layer**: UI components

### Tasks

#### T-44-1-01: Fix Sidebar Drag Handle Alignment

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/shell/CollapsibleSidebar.tsx`

**What to build**:
The drag handle at `line 339` has a 4px hit zone (`w-1`) with a 1px visual indicator line inside it. The inner `div.w-px` defaults to the leftmost pixel of the 4px zone, making the visible separator appear 3px inside from the actual sidebar boundary. Adding `flex justify-end` to the outer div pushes the 1px line to the rightmost pixel, which is flush with the sidebar's actual right edge.

**Logic**:
- Find: `className="absolute right-0 top-0 h-full w-1 cursor-col-resize group z-10"`
- Change to: `className="absolute right-0 top-0 h-full w-1 cursor-col-resize group z-10 flex justify-end"`
- No other changes needed

**Acceptance criteria**:
- [ ] Visual separator line is flush with the sidebar's right edge when expanded
- [ ] Drag resize still works correctly
- [ ] No TypeScript or lint errors

---

#### T-44-1-02: Watchlist — Delete Member Button

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx`

**What to build**:
Add a delete (×) button to each row in `WatchlistMemberRow`. The button is hidden by default and reveals on row hover using `group/row` + `group-hover/row:opacity-100`. On click, it calls `removeWatchlistMember(watchlistId, entityId)` mutation which maps to `DELETE /v1/watchlists/{id}/members/{entity_id}`. On success, invalidate `["watchlists"]` so the table re-renders.

**Components**:
- `WatchlistMemberRow` — add `onDelete: (entityId: string) => void` prop, add delete button cell
- `WatchlistTable` — pass `deleteWatchlistMember` mutation's `mutate` function as `onDelete`
- `WatchlistsTabPanel` — create one `useMutation` for `removeWatchlistMember`, pass as callback

**Logic**:
1. In `WatchlistsTabPanel`, create a `deleteMemberMutation = useMutation({ mutationFn: ({watchlistId, entityId}) => gateway.removeWatchlistMember(watchlistId, entityId), onSuccess: () => queryClient.invalidateQueries(["watchlists"]) })`
2. Pass the mutate function down to `WatchlistTable` → `WatchlistMemberRow`
3. In `WatchlistMemberRow`, add `group/row` to the `<tr>`, add a final `<td>` with a `<button>` containing `X` (3px icon) that calls `onDelete(member.entity_id)`
4. Button classes: `opacity-0 group-hover/row:opacity-100 transition-opacity` — prevents the delete button from cluttering the default view
5. While `isPending`, show a spinner; on error, show a brief error state

**Acceptance criteria**:
- [ ] Delete `×` button appears on row hover (invisible at rest)
- [ ] Clicking delete removes the member and updates the list
- [ ] `["watchlists"]` cache is invalidated on success
- [ ] No TypeScript or lint errors

---

#### T-44-1-03: Watchlist — Create and Delete Watchlist

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx`

**What to build**:
Add two affordances: (A) a `[+ New]` button in the watchlist tab bar that opens an inline create form; (B) a `···` menu per watchlist tab with a "Delete" option.

**Logic**:
- Create `createMutation = useMutation({ mutationFn: (name: string) => gateway.createWatchlist(name), onSuccess: () => { queryClient.invalidateQueries(["watchlists"]); setCreating(false); })`
- Create `deleteMutation = useMutation({ mutationFn: (watchlistId: string) => gateway.deleteWatchlist(watchlistId), onSuccess: () => queryClient.invalidateQueries(["watchlists"]) })`
- Add `useState<boolean>` for `creating` mode — when true, show an inline `<input>` + submit in the tab bar instead of the `[+ New]` button
- For delete: add a `···` `<button>` next to each watchlist tab name (visible on tab hover), opening a small `DropdownMenu` with a "Delete watchlist" item in `text-negative`; require confirmation via `window.confirm` before calling the mutation (cheap guard to avoid accidental deletion)
- After deleting the active watchlist, switch to `watchlists[0]?.watchlist_id ?? null`

**Acceptance criteria**:
- [ ] `[+ New]` button creates a watchlist with a user-typed name
- [ ] New watchlist appears in the tab bar immediately after creation
- [ ] Delete removes the watchlist and switches to the next available one
- [ ] Empty state shown when all watchlists are deleted

---

### Validation Gate

- [ ] `pnpm run lint` passes
- [ ] `pnpm run typecheck` passes
- [ ] `pnpm run test` — all existing Vitest tests pass
- [ ] Manual smoke: create watchlist, add member, delete member, delete watchlist
- [ ] Sidebar expanded state shows correct right-edge border alignment

---

## Wave 2: Holdings Table Enhancements

**Goal**: Add day change columns, visual weight bars, and click-to-sort to the holdings table.
**Depends on**: Wave 1 (can run independently — no code dependency, just sequencing)
**Estimated effort**: 60–75 minutes
**Architecture layer**: UI components

### Tasks

#### T-44-2-01: Holdings Table — Add Day Change Columns

**Type**: impl
**depends_on**: none
**blocks**: T-44-2-02
**Target files**: `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx`

**What to build**:
Add two columns: `DAY $` (absolute day change × quantity) and `DAY %` (today's price change percentage). Data already exists in the `quotes` prop (`q.change` and `q.change_pct`). Display "—" when no live quote is available.

**Column positions**: Insert `DAY $` and `DAY %` after `CURRENT` and before `P&L $`.

**Logic**:
- In the row computation: `dayChange = (q?.change ?? null)`, `dayChangePct = (q?.change_pct ?? null)`, `dayChangeValue = (dayChange != null) ? dayChange * h.quantity : null`
- In the `<thead>`: add two `<th>` cells for `DAY $` and `DAY %` with standard `text-right` alignment
- In `<tbody>` rows: add corresponding `<td>` cells using `text-positive`/`text-negative` based on sign
- In `<tfoot>` total row: no aggregate (day change totals are misleading — leave empty)
- Note: table goes from 10 to 12 columns; update `colSpan={5}` in tfoot to `colSpan={7}`

**Acceptance criteria**:
- [ ] Two new columns visible: `DAY $` and `DAY %`
- [ ] Values colored green/red by sign
- [ ] "—" shown when no live quote
- [ ] tfoot TOTAL row still aligns correctly
- [ ] No TypeScript errors on `q.change`/`q.change_pct` (already typed in the `quotes` prop interface)

---

#### T-44-2-02: Holdings Table — Visual Weight Bars + Column Sort

**Type**: impl
**depends_on**: T-44-2-01
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx`

**What to build**:
(A) **Visual weight bars**: Replace the plain `+33.27%` text in the WEIGHT column with a mini inline bar + percentage. The bar is a `div.h-1.rounded-[1px].bg-primary/40` with `width: weight%` inside a `div.w-[60px].bg-muted/30` container, followed by the percentage text. This is the Bloomberg portfolio weight column pattern.

(B) **Click-to-sort**: Add `useState<{col: SortCol; dir: 'asc' | 'desc'}>` where `SortCol = 'ticker' | 'pnl' | 'pnlPct' | 'value' | 'weight' | 'dayChangePct'`. Clicking a sortable column header toggles sort direction; clicking a different column resets to ascending on the new column. Apply the sort to the `rows` array before mapping to `<tr>`. Show a sort indicator (▲/▼, 9px) on the active column header.

**Unsortable columns**: TICKER (always first), NAME, AVG COST, CURRENT, SECTOR — these show no sort affordance.

**Sortable columns**: QTY, DAY $, DAY %, P&L $, P&L %, VALUE, WEIGHT — these show a sort indicator on hover + when active.

**Acceptance criteria**:
- [ ] Weight column shows a visual bar proportional to weight + text percentage
- [ ] Clicking VALUE header sorts by descending value; clicking again reverses
- [ ] Active sort column shows ▲ or ▼ indicator
- [ ] Sort is stable (rows with equal values keep original order)

---

### Validation Gate

- [ ] `pnpm run lint` passes
- [ ] `pnpm run typecheck` passes
- [ ] `pnpm run test` — all existing Vitest tests pass
- [ ] Manual: holdings table shows 12 columns with correct day change data
- [ ] Manual: click column header to sort, click again to reverse

---

## Wave 3: Transactions + Brokerage Merge

**Goal**: Merge the Brokerages tab into the Transactions tab as a collapsible section, reducing tab count from 4 to 3.
**Depends on**: Wave 2
**Estimated effort**: 45–60 minutes
**Architecture layer**: UI components

### Tasks

#### T-44-3-01: Merge Brokerages into Transactions Tab

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/app/(app)/portfolio/page.tsx`
- `apps/worldview-web/components/portfolio/TransactionsTable.tsx`

**What to build**:
Move the brokerage connections UI (currently in the `brokerages` `TabsContent`) to the top of the `transactions` `TabsContent` as a collapsible section. Remove the `Brokerages` tab trigger and content entirely.

**Structure of new Transactions tab**:
```
[ CONNECTED BROKERAGES ▼ ]  [+ Connect]     ← collapsible header row (h-9, always visible)
  ● Interactive Brokers  Last synced: 2m ago     ← expanded section (ConnectedBrokeragesList)
  + Connect a brokerage                           ← shown only when no connections
────────────────────────────────────────────────
[All] [BUY] [SELL] [DIV]            3 / 12   ← existing filter bar
  Transactions table...
```

**Logic**:
1. Add `useState<boolean>` for `brokeragesSectionExpanded` (default: `false` to keep collapsed by default so transactions are immediately visible)
2. In `transactions` `TabsContent`, prepend a `div.border-b.border-border` section:
   - Header row: `CONNECTED BROKERAGES` label (muted, 10px ALL CAPS) + chevron icon + `[+ Connect]` button on the right
   - When expanded: render `<ConnectedBrokeragesList portfolioId={...} />`
3. Remove the `brokerages` `TabsTrigger` and `TabsContent` from the tab bar
4. Move `connectModalOpen` state + `ConnectBrokerageModal` to page level (already at page level — no change needed)
5. Remove the `brokerages` tab trigger from `TabsList`

**Acceptance criteria**:
- [ ] Tab bar shows only 3 tabs: Holdings, Transactions, Watchlist
- [ ] Transactions tab has a collapsible "Connected Brokerages" section at the top
- [ ] Expanding the section shows the brokerage connection list
- [ ] `[+ Connect]` button opens the existing `ConnectBrokerageModal`
- [ ] No regression in brokerage connection/disconnect flow
- [ ] No TypeScript errors

---

### Validation Gate

- [ ] `pnpm run lint` passes
- [ ] `pnpm run typecheck` passes
- [ ] `pnpm run test` — all existing Vitest tests pass
- [ ] Manual: Brokerages tab is gone; brokerage section visible in Transactions tab
- [ ] Manual: collapse/expand brokerage section works correctly

---

## Cross-Cutting Concerns

- No API changes required (all data already available)
- No new S9 routes needed
- No backend changes required
- No Avro schema changes
- No Alembic migrations

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Watchlist tab keyboard navigation conflict (nested tab within tab) | Low | Medium | Already solved — WatchlistsTabPanel uses a custom button bar, not shadcn Tabs |
| Holdings table column count expansion breaks existing tests | Medium | Low | Update `colSpan` in tfoot; check Vitest test assertions for column count |
| Brokerage modal state lifted to wrong level | Low | Low | `connectModalOpen` already at page level — just move trigger button |

## Regression Guardrails

- **BP-023** (ruff format): Use pinned ruff via `~/.cache/pre-commit/`; sync staged + working files before commit
- **BP-065** (pre-commit stash): Fix lint issues before `git add`; never commit with divergent staged/working-tree copies
- **R19** (never delete tests): Update tests to match 12-column table; do not delete or skip any existing test
