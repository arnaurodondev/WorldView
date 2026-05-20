# Cluster 4 — Watchlist Endpoint Contract + Sidebar Interaction

> **PRD**: PRD-0089 (Platform Page Redesign)
> **Scope**: Resolve all open questions related to the sidebar `WatchlistPanel` and the underlying S1 watchlist endpoints.
> **Author**: Frontend redesign agent
> **Date**: 2026-05-19
> **Status**: PROPOSED — needs review

---

## 1. Cluster Summary

The sidebar watchlist is the most-glanced surface on the platform (every page, all market hours). The current shape has shipped, but several open questions remain about:

1. What data the sidebar *should* render (the spec asks for a 1D sparkline column that does not yet exist on the wire).
2. Whether sparkline closes come from a per-ticker fetch or a batched one.
3. How "freshness" is rendered, and on what SLA.
4. Whether responsive auto-collapse belongs in v1.
5. Section divider rendering (hairline vs spacing).
6. The UX of the add-flow (modal vs inline) — the master PRD already picked "modal" but the sidebar context requires its own decision.
7. Multi-watchlist switching (already shipped with a dropdown; should we keep / extend / replace?).
8. Future-state sharing (read-only public links).

### What we already have (confirmed by reading the code)

| Capability | Endpoint | Frontend touch-point |
|---|---|---|
| List watchlists | `GET /v1/watchlists` → bare array of `WatchlistResponse` | `gateway.getWatchlists()` → `WatchlistPanel`, `/watchlists` hub |
| Single watchlist | `GET /v1/watchlists/{id}` → `WatchlistResponse` | `gateway.getWatchlist(id)` (also fans out to members) |
| List members | `GET /v1/watchlists/{id}/members?limit&offset` → `{members, total}`, each `{entity_id, entity_type, ticker, name, instrument_id, added_at, resolution}` | `gateway.getWatchlistMembers(id)` |
| Create / rename / delete | `POST` / `PATCH` / `DELETE /v1/watchlists[/{id}]` | `gateway.createWatchlist`, `renameWatchlist`, `deleteWatchlist` |
| Add / remove member | `POST` / `DELETE /v1/watchlists/{id}/members[/{entity_id}]` | `gateway.addWatchlistMember`, `removeWatchlistMember` |
| Composite "insights" | `GET /v1/watchlists/{id}/insights` → `{movers, sectors, news, alerts}` | `gateway.getWatchlistInsights` (dashboard widget) |
| Batch quotes | `POST /v1/quotes/batch` → `{quotes: {[id]: Quote}}` | `gateway.getBatchQuotes(ids)` (Quote shape includes `freshness_status`, `data_as_of`, `stale_reason`) |
| Batch OHLCV | `POST /v1/ohlcv/batch` (max 50 symbols, 5m timeframe supported, 5-min Cache-Control) → `{results: [{instrument_id, bars[]}], fetched_at}` | not yet wired for the sidebar |

### What we don't have

| Gap | Impact |
|---|---|
| The `01-global-shell.md` doc cites `GET /v1/instruments/{id}/intraday?interval=5m&period=1d`. **This route does not exist in S9.** Closest equivalent is `/v1/ohlcv/{id}?timeframe=5m&start=…` (single) and `/v1/ohlcv/batch` (batched). | The sparkline column blocked unless we either (a) use `ohlcv/batch`, or (b) build a new dedicated intraday endpoint. |
| Quote `freshness_status` exists on `/v1/quotes/{id}` but is not documented for the *batch* shape in the inventory. | Need to confirm batch returns the same fields. |
| No `?expand=` parameter on `GET /v1/watchlists` — sidebar must do N+1 (list → first.members → batch quotes → batch sparklines). | 4 RTT on cold path; mitigatable via cache + parallel fetch. |
| No push channel for quote updates (REST only, 30s refetch). | OK for v1 — Bloomberg-grade real-time is out of scope. |

---

## 2. Per-OQ Deep Dive

### 2.1 OQ 1 — IndexStrip ticker set (^TNX vs USO)

**Context (from `01-global-shell.md` §10.1)**: The current proposal is a 10-cell index strip: `SPY, QQQ, IWM, DIA, VIX, TLT, DXY, GLD, USO, BTC-USD`. The OQ asks whether USO should be swapped for the 10Y Treasury yield (^TNX).

**Cluster note**: this is NOT strictly a watchlist OQ, but the global shell doc folded it in. Including for completeness because the IndexStrip lives in the same `components/shell/` directory.

**Discussion**:
- A serious institutional shell carries one rates ticker. **Bloomberg's** default has the 2Y/10Y on the top strip; **Koyfin** shows 10Y prominently in its top KPI ribbon. Skipping rates entirely is unusual.
- USO (oil ETF) is *commodity*, but we already have GLD (also commodity). Two commodity tickers without a rates ticker is unbalanced.
- The strip needs to fit on a 1280px viewport at 11px mono font; 10 cells × ~115px = 1150px — already tight. Adding an 11th cell would crowd.
- **Recommended swap**: drop USO, keep GLD as the lone commodity, add ^TNX in the 9th slot. Order: `SPY, QQQ, IWM, DIA, VIX, TLT, DXY, GLD, ^TNX, BTC-USD`.

**Data feasibility**: S9 `/v1/quotes/batch` accepts ticker symbols via `instrument_id`. ^TNX is exposed by EODHD (`TNX.INDX`) — confirmed by `services/api-gateway/src/api_gateway/routes/market.py` which proxies any symbol to S3. No new endpoint needed.

**Risk**: ^TNX is a *yield*, not a price. The IndexStrip cell layout was designed for `price + change_pct`. For ^TNX the "price" is itself a percent (e.g. 4.52). Frontend must NOT render an extra `%` suffix on a yield ticker. Add a tiny helper: `isYieldSymbol(s) => s.startsWith("^") && s.endsWith("TNX")`.

**Decision**: **SWAP USO → ^TNX**. Owner: design. No backend work.

---

### 2.2 OQ 2 — Sparkline data source

**Context**: The 22px row needs a 40×16px sparkline column showing today's trend (~14 closes).

**Reality check on existing endpoints**:

| Option | Endpoint | Bars returned | Notes |
|---|---|---|---|
| A — Single intraday per ticker | `/v1/ohlcv/{id}?timeframe=5m&start=<today>` | up to 78 (full session) | exists, but N+1 — 10 sidebar tickers = 10 round-trips |
| B — **Batch intraday** | `POST /v1/ohlcv/batch` with `[{instrument_id, timeframe: "5m", limit: 78}, …]` | up to 50 instruments × N bars per call | exists today, used by screener (50-cap, 5-min Cache-Control) |
| C — Add a new lean endpoint | `POST /v1/sparklines/batch` returning only `closes[]` | new | smaller payload (~20% of ohlcv batch) but new code + tests |
| D — Composite extension to `/v1/watchlists/{id}` with `?expand=quotes,sparklines` | new query param | one-shot | breaks single-responsibility — S1 would have to call S3 |

**Sizing exercise** for option B with 10 sidebar tickers × 78 bars × 6 fields (open/high/low/close/volume/timestamp):
- raw JSON ≈ 10 × 78 × ~80B per bar = ~62 KB
- gzipped over HTTPS ≈ ~6-8 KB
- Sparkline only needs `close`; we waste ~80% of payload. Acceptable for v1.

**Latency**:
- Option A: 10 × ~150ms = ~1.5s sequential, or ~200ms parallel (browser limits to ~6 in parallel — still 2 round-trip-batches).
- Option B: 1 × ~200ms total (S3 fans out internally via asyncio.gather, BP-026).
- Option C: 1 × ~120ms (smaller payload).

**Cache strategy**:
- Sparkline rarely changes (5-min Cache-Control already on `/ohlcv/batch`).
- TanStack key: `qk.watchlists.sparklines(memberIds, "5m")` with `staleTime: 60_000`, `gcTime: 300_000`.
- DO NOT share key with the chart cache `qk.instruments.ohlcv(id, "1D")` — the chart wants 90 calendar days at `1d` granularity, the sparkline wants ~78 bars at `5m`. Different shape, different TTL.

**Decision**: **Option B (use `POST /v1/ohlcv/batch`)** for v1. No backend work. Frontend creates a `WatchlistSparkline` component that consumes the existing batch endpoint. If sparkline traffic ever dominates the OHLCV call site, revisit option C.

**Implementation sketch**:
```ts
// useWatchlistSparklines.ts
const memberIds = members.map(m => m.entity_id);
const today = new Date().toISOString().slice(0, 10);  // YYYY-MM-DD
const { data } = useQuery({
  queryKey: qk.watchlists.sparklines(memberIds, "5m"),
  queryFn: () => gateway.getBatchOHLCV({
    requests: memberIds.map(id => ({
      instrument_id: id, timeframe: "5m", start: today, limit: 78,
    })),
  }),
  enabled: memberIds.length > 0,
  staleTime: 60_000,
});
```

---

### 2.3 OQ 3 — Freshness dot thresholds

**Context**: The StatusBar shows a freshness dot reflecting the age of the most recent quote tick. `01-global-shell.md §6` proposes 5s / 30s thresholds via colors.

**SLA reality**: S9 `/v1/quotes/{id}` returns a `freshness_status` field and a `data_as_of` timestamp (see `00-backend-data-inventory.md` §1.2). The contract documents the following enum (from `services/market-data` `QuoteResponse`):

| `freshness_status` | Server-defined meaning |
|---|---|
| `fresh` | tick received in last ~10s during market hours |
| `delayed` | 10-60s old; partial degradation |
| `stale` | >60s old or after-hours |
| `closed` | market closed; quote is last-print-of-session |

**Proposed dot mapping**:

| State | Dot | Tooltip |
|---|---|---|
| `fresh` (< 5s) | solid green `bg-positive` | "Live · {N}s ago" |
| `fresh` (5-30s) | solid green | "Live · {N}s ago" |
| `delayed` (30-60s) | amber `bg-warning` | "Delayed · {N}s ago" |
| `stale` (>60s, market open) | red `bg-negative` | "Stale · {N}s ago — last tick {timestamp}" |
| `closed` (after-hours) | grey muted | "AH · last tick {timestamp}" |
| weekend / holiday | hidden | replaced by `CLOSED` text badge |

**Rule for the *dot itself*** (1.5×1.5px in §6): drive entirely from the *server-provided* `freshness_status`, not from a frontend timer. Reason: the frontend timer would tick to "red" while the page was idle (e.g. user away from desk), which doesn't reflect actual data quality. The server-side enum already accounts for market hours.

**Drift handling**: if the client sees `data_as_of` > 90s in the past while `freshness_status === "fresh"`, log a warning to Sentry — this indicates a server-clock skew or stuck pipeline (BP candidate).

**Decision**: **Drive freshness dot from `freshness_status` enum** (server-authoritative), not a client-side timer. The "<5s/<30s/<60s" thresholds are a *display* concern only used to compose the tooltip's "N seconds ago" string.

**Backend confirmation needed**: verify that `/v1/quotes/batch` returns `freshness_status` for each quote. The inventory only documents the single-quote shape — batch shape needs explicit verification before this OQ closes. **Follow-up OQ**: see §8.

---

### 2.4 OQ 4 — Sidebar auto-collapse at <1280px

**Context**: PRD-0089 calls v1 desktop-only (≥1280px target). Should the sidebar auto-collapse on smaller viewports (e.g. resize-down to 1024px tablet)?

**Cases**:
- **Bloomberg Terminal**: fixed-width window, no responsive collapse. User explicitly opens/closes via Function key.
- **TradingView / Koyfin**: auto-collapse below `md` (≈768px) into a hamburger overlay.
- **Modern SaaS norm**: auto-collapse below `lg` (1024px).

**Tradeoffs**:
- *For auto-collapse*: prevents the 200px sidebar from squeezing the main content to <800px (which breaks the screener grid and many wide tables).
- *Against auto-collapse*: PRD-0089 explicitly scopes v1 to desktop; the platform is institutional and not optimised for touch. Auto-behaviours steal control from power users. The user can already toggle with `mod+b`.

**Recommendation**: **No auto-collapse in v1.** Below 1280px we show a small banner in the StatusBar: `Display optimised for ≥1280px — press ⌘B to collapse`. The breakpoint logic is one line: a `useMediaQuery("(min-width: 1280px)")` hook → boolean → conditional banner. Out of scope: any tablet/mobile shell rework (deferred to v2 entirely).

**Decision**: **Manual-only collapse via `mod+b`**. No viewport-driven auto-collapse in v1. Add a non-blocking banner at <1280px.

---

### 2.5 OQ 5 — Section-divider rendering (hairline vs spacing)

**Context**: `01-global-shell.md §10.5` notes the brief asks for "1px hairlines, NOT spacing" between sidebar sections (nav cluster ↔ watchlist ↔ alarms ↔ bottom chrome).

**Today**: the sidebar uses `gap-2` / `space-y-*` between sections (visual breathing room).

**Proposed**: replace gaps with `border-t border-border` divider lines, exactly like Bloomberg's mono-typographic panels.

**Tradeoffs**:
| Approach | Density gain | Visual feel |
|---|---|---|
| `gap-2` (today) | 0 | airy, modern SaaS |
| `border-t border-border` | +8px (gap removed) | tight, terminal-grade |
| `border-t border-border` + 4px padding | +4px | tight but breathable |

**Recommendation**: hairline `border-t border-border` between sections WITH a 4px (`py-1`) interior padding on each section header. Reason: Bloomberg's bars are *truly* flush (0 padding) and feel cramped at modern resolutions. 4px gives us the divider but keeps the section label readable.

**Decision**: **hairline dividers with 4px interior padding**. Update `CollapsibleSidebar.tsx` to remove `gap-2` and add `border-t border-border py-1` on each subsection.

---

### 2.6 OQ-D7 (master PRD) — Watchlist add-flow UX

**Context**: PRD-0089 §OQ-D7 already proposes "Modal". This cluster confirms.

**Patterns**:
- **Bloomberg `WMON`**: a *focused modal* (you press F2 → type symbol → enter). Closeable with Esc. Modal carries autocomplete from the symbol universe.
- **TradingView**: inline `+` chip at the bottom of the symbol list with autocomplete dropdown.
- **Robinhood / Koyfin**: inline `+` chip.

**Tradeoffs**:
| Pattern | Pros | Cons |
|---|---|---|
| Modal (Bloomberg) | Focused, keyboard-driven, scales to "advanced add" (paste 10 tickers at once) | Steals page focus; an extra step for casual users |
| Inline `+` chip | Lightning-fast, low-friction, matches retail apps | Crowded sidebar (already shows nav + watchlist + alarms + bottom chrome); harder to discover |
| **Hybrid — inline `+` chip with mini-autocomplete that escalates to modal for "Advanced"** | Best of both | More code; two implementations to maintain |

**Sidebar-specific constraint**: the panel is 196px wide (interior). An inline autocomplete dropdown at 196px is too narrow to render `ticker + name + exchange` per row legibly. A modal *opens to 480px* and fits everything.

**Recommendation**: **Modal**. Triggered by:
1. `+` button in the WatchlistPanel header (next to the dropdown switcher).
2. Global hotkey `Cmd+Shift+A` ("Add to watchlist").
3. Right-click context menu on any instrument row.

Modal contents:
- Search input with autocomplete against `/v1/screener/search?q=…`
- Active watchlist preselected; switcher inside the modal
- Esc closes; Enter adds + closes; Shift+Enter adds + keeps open (power-user mode)
- Bulk paste: comma-separated tickers ⇒ multi-add

**Drag-and-drop ticker from instrument page → sidebar watchlist** — **deferred to v2**. Implementing HTML5 drag-and-drop with a moving "ghost" preview is ~200 LoC and brittle across browsers. The modal + global hotkey already covers 95% of the use case.

**Decision**: **Modal**, with header `+` button, global hotkey, and right-click integration. Drag-and-drop deferred.

---

### 2.7 Multi-watchlist switching pattern

**Context**: today's `WatchlistPanel.tsx` uses a dropdown switcher in the header (lines 137-191). A user with N watchlists picks one to "pin" to the sidebar.

**Alternative patterns**:
| Pattern | Example | Pro | Con |
|---|---|---|---|
| Dropdown switcher (today) | TradingView | Compact | One-list-at-a-time; can't compare |
| Tab strip across the top of the panel | Bloomberg WTC | Quick switch, see all names | Costs 22px vertical and crowds with >4 names |
| Stacked: all watchlists visible, each collapsible | Robinhood | No switch needed | Vertical-scroll heavy with many lists |

**User research signal (from MEMORY.md)**: "Power users (Bloomberg PMs, quant analysts) arrange their workspace to their screen size." They want one list visible *per surface*, with the rest one click away — exactly the current pattern.

**Tweaks proposed**:
1. **Persist the selected watchlist** to localStorage (key `sidebar.activeWatchlistId`) so a refresh keeps the user's choice. Today it defaults to `[0]` on every mount.
2. **Show a tiny badge** next to the dropdown if any *other* watchlist has a fresh alert (`alerts.lastTriggeredAt < 5 min`). Subtle visual hint that another list deserves attention.
3. **Keyboard cycle**: `Alt+[` / `Alt+]` cycles to previous/next watchlist. Power-user nicety.

**Decision**: **Keep the dropdown switcher**. Add localStorage persistence, cross-list alert badge, and keyboard cycle hotkeys.

---

### 2.8 Watchlist sharing / collaboration (future)

**Out of scope for v1**. Recorded here so we don't lose the thought.

**The feature**: a user generates a read-only URL of a watchlist (`/share/w/<token>`) that anyone can view without auth. Useful for blog posts, Twitter threads, internal slack.

**Cost**:
- New `watchlist_shares` table (`token, watchlist_id, created_at, expires_at, view_count`) — ~1 migration.
- S9 anonymous endpoint `GET /public/watchlists/{token}` — ~50 LoC.
- Frontend `/share/w/[token]` public page — ~120 LoC.
- ACL caveat: the shared watchlist must NOT leak the owner's email, alert prefs, or membership in other watchlists. Strict response shape: `{name, members: [{ticker, name}], created_at, expires_at}` only.
- Rate-limit by IP (avoid scraping).

**Multi-tenant concern**: shared watchlists *cross tenant boundaries* (a viewer from tenant A sees tenant B's data via the token). This is *allowed by design* (the token is the auth) but must be explicit in the table schema (no `tenant_id` filter on the public read path).

**Decision**: **Defer to v2** (PRD-0089-v2 follow-up). Document the schema sketch in the appendix; do not implement.

---

## 3. Endpoint Shape Recommendation (full schema)

Three layers, all using endpoints that *already exist* in S9 today (no new routes needed for the sidebar).

### 3.1 List shape (unchanged)

```http
GET /v1/watchlists
→ 200 OK
[
  {
    "id": "0193abcd-…",          // UUID
    "tenant_id": "…",
    "user_id": "…",
    "name": "Tech",
    "status": "active",
    "created_at": "2026-05-01T12:34:56Z"
  },
  …
]
```

Frontend mapper (`mapRawWatchlist`) reshapes to `{watchlist_id, name, owner_id, created_at, updated_at, members: [], member_count: 0}`. Member arrays and counts are *not* populated from this call.

### 3.2 Member shape (unchanged)

```http
GET /v1/watchlists/{id}/members?limit=100&offset=0
→ 200 OK
{
  "members": [
    {
      "entity_id": "…",
      "entity_type": "company",
      "ticker": "AAPL",
      "name": "Apple Inc.",
      "instrument_id": "…" | null,
      "added_at": "2026-05-01T12:34:56Z",
      "resolution": "resolved" | "pending"
    }
  ],
  "total": 12
}
```

### 3.3 Live + sparkline composite (NEW — sidebar consumes 2 existing endpoints in parallel)

```ts
// Pseudocode — runs after we know memberIds
const [quotesResp, ohlcvResp] = await Promise.all([
  gateway.getBatchQuotes(memberIds),
  gateway.getBatchOHLCV({
    requests: memberIds.map(id => ({
      instrument_id: id,
      timeframe: "5m",
      start: todayISODate(),
      limit: 78,
    })),
  }),
]);
```

Combined frontend type:

```ts
type SidebarRow = {
  entity_id: string;
  ticker: string;
  name: string;
  quote: {
    price: number;
    change_pct: number;
    freshness_status: "fresh" | "delayed" | "stale" | "closed";
    data_as_of: string;  // ISO timestamp
  } | null;
  sparkline: {
    closes: number[];    // 5m closes for today, length ≤ 78
    first: number | null;  // opening close (for green/red sign)
    last: number | null;
  } | null;
};
```

### 3.4 Why NOT extend the list endpoint with `?expand=members,quotes,sparklines`

| Reason | Detail |
|---|---|
| Service boundary | `/v1/watchlists` lives in S1 (Portfolio). Quotes and OHLCV live in S3 (Market Data). Expanding `/v1/watchlists` forces S1 → S9 → S3 fan-out inside one request, putting cross-service composition into the *list* path (cold and frequent). |
| Cache pressure | A combined response invalidates whenever *any* of its parts changes. Quotes refetch every 30s; that would force the whole composite to refetch even when membership is static. |
| Already a composite endpoint | S9 already has `/v1/watchlists/{id}/insights` (the existing "composite" route). The sidebar's needs are a different shape and a different cache profile — we'd want a *second* composite, which is then 3 ways to fetch the same data. Worse than the N+1. |

**Verdict**: keep the list shallow. Compose on the frontend with parallel queries and a shared cache.

---

## 4. Sparkline Batch Strategy

### 4.1 Endpoint reuse

**Endpoint**: `POST /v1/ohlcv/batch` (exists today, screener uses it for 30-day sparklines).

| Limit | Today's value | Sidebar usage |
|---|---|---|
| Max symbols per call | 50 (`_BATCH_OHLCV_MAX_SYMBOLS`) | 10-30 typical; well under cap |
| Timeframes accepted | `1m / 5m / 15m / 30m / 1h / 4h / 1d / 1w / 1M` | use `5m` |
| Bars per symbol | up to 2000 per `limit` field | use `limit: 78` (one full session of 5m bars) |
| Cache-Control | 5 min on response | preserves; TanStack `staleTime: 60_000` |

### 4.2 Cache key

```ts
qk.watchlists.sparklines(memberIds, "5m")
// hashed key: stable across reorders if we sort memberIds first
```

**Important**: sort `memberIds` before hashing into the key so a member reorder doesn't bust the cache.

### 4.3 Refetch policy

- `staleTime: 60_000` — intraday bars change every 5 min, no need to hammer.
- `refetchInterval: 60_000` — silent background refresh once a minute.
- `refetchOnWindowFocus: true` — user returns to tab → pull fresh bars.
- Pause refetch when `document.hidden === true` (tab in background).

### 4.4 Empty / partial / pre-market handling

| Case | Backend response | Sidebar rendering |
|---|---|---|
| Pre-market (no 5m bars today yet) | `results: [{instrument_id, bars: []}]` | flat 1px horizontal rule in 40×16 box |
| Symbol not in market data | `results: [{instrument_id, bars: [], error: "not_found"}]` | flat rule + tiny `?` icon on hover |
| Partial set (some symbols 404) | other symbols still return | per-row independent rendering |

### 4.5 Sparkline rendering

Inline SVG path, computed from the `closes` array:

```
- viewBox: 0 0 40 16
- xMin = 0, xMax = 40, scaled linearly across closes.length
- yMin = min(closes), yMax = max(closes), scaled to [14, 2] (2px top/bottom margin)
- stroke: closes[last] >= closes[0] ? "stroke-positive" : "stroke-negative"
- stroke-width: 1
- fill: none
```

No tooltip on hover (40×16 too small; user can click row → instrument detail for full chart).

---

## 5. Add-Flow UX Recommendation

### 5.1 Trigger surfaces

1. **`+` icon in WatchlistPanel header** (currently absent — add it next to the dropdown).
2. **Right-click on any instrument row** anywhere in the platform → context menu item "Add to watchlist".
3. **Global hotkey `Cmd+Shift+A`** — opens modal with current page's instrument preselected if any.
4. **`Cmd+K` palette** → action "Add to watchlist" → opens modal.

### 5.2 Modal layout (480px × 360px)

```
┌─ Add to watchlist ─────────────────────────────────────────[Esc]┐
│                                                                  │
│  Watchlist: [ Tech  ▾ ]   (current active list preselected)      │
│                                                                  │
│  Search symbols:                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ AAPL                                                  🔍 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Suggestions:                                                    │
│   AAPL   Apple Inc.            NASDAQ    [+ Add]                 │
│   AAP    Advance Auto Parts    NYSE      [+ Add]                 │
│   AAPLW  Apple warrant         …                                 │
│                                                                  │
│  Tip: Shift+Enter to add and keep open for bulk entry            │
│                                                                  │
│              [ Cancel ]    [ Add and close ]                     │
└──────────────────────────────────────────────────────────────────┘
```

### 5.3 Behaviours

- Esc closes (focus returns to the trigger element).
- Enter adds the highlighted suggestion + closes.
- Shift+Enter adds + clears input + keeps focus in the input (bulk mode).
- Adding triggers an optimistic update to TanStack — the panel row appears with `resolution: "pending"` (badge: "resolving…") until the backend confirms.
- On failure (duplicate, watchlist deleted concurrently), show inline error inside the modal; do NOT close.

### 5.4 What we explicitly do NOT build in v1

| Feature | Reason |
|---|---|
| Drag-and-drop ticker from page → sidebar | ~200 LoC, browser quirks, modal covers 95% case |
| Inline `+` chip inside the sidebar | sidebar is 196px wide — autocomplete dropdown won't fit comfortably |
| "Smart add" (e.g. "all S&P 500 IT stocks") | screener already covers this; saved-screen → watchlist conversion is a separate feature |

---

## 6. Recommended Decisions Table

| # | OQ | Decision | Backend work | Frontend work |
|---|---|---|---|---|
| 1 | IndexStrip 10Y vs USO | Swap USO → ^TNX (`TNX.INDX`) | none | update IndexStrip ticker list; add `isYieldSymbol()` formatter |
| 2 | Sparkline data source | Reuse `POST /v1/ohlcv/batch` with `timeframe=5m, limit=78` | none | new `WatchlistSparkline` component + `useWatchlistSparklines` hook |
| 3 | Freshness dot thresholds | Drive from server `freshness_status` enum; client-side timer for *display* only | confirm `freshness_status` in `/v1/quotes/batch` response | StatusBar dot logic + tooltip "N seconds ago" string |
| 4 | Sidebar auto-collapse <1280px | NO auto-collapse; show banner | none | one `useMediaQuery` + banner in StatusBar |
| 5 | Section dividers | Hairline `border-t border-border` + 4px interior padding | none | remove `gap-2` in `CollapsibleSidebar.tsx` |
| 6 | Add-flow UX | Modal (480×360) via `+` button, hotkey, right-click | none (uses `/v1/watchlists/{id}/members POST` + `/v1/screener/search`) | new `AddToWatchlistModal` component |
| 7 | Multi-watchlist switching | Keep dropdown + persist localStorage + Alt+[/] cycle + alert badge | none | update `WatchlistPanel.tsx` |
| 8 | Sharing / collaboration | DEFER to v2 | n/a | n/a |

---

## 7. Backend Additions Required

**Net new backend work for this cluster: 0 endpoints.**

What we *do* need from the backend team:

| # | Item | Service | Effort |
|---|---|---|---|
| B1 | **Confirm `/v1/quotes/batch` returns `freshness_status` and `data_as_of` per quote** | S9 | 15 min audit + update inventory doc if missing |
| B2 | **Verify `^TNX` / `TNX.INDX` symbol resolves via S3 + EODHD** | S3 | smoke test |
| B3 | **Ensure `/v1/ohlcv/batch` Cache-Control headers reach the browser** through S9 → frontend (no header strip in middleware) | S9 | curl check |
| B4 | **Document the `freshness_status` enum values** in `docs/services/api-gateway.md` | docs | 10 min |

If B1 reveals that `/v1/quotes/batch` does NOT include `freshness_status`, that becomes the only real backend change (one field added to a batch response — forward-compatible).

---

## 8. Follow-up OQs

Surfaced during this investigation, NOT yet decided:

1. **F-OQ-04.1**: Does `/v1/quotes/batch` include `freshness_status` and `data_as_of`? (B1 above) — blocks OQ 3 implementation.
2. **F-OQ-04.2**: When a member's `resolution: "pending"` (ticker not yet resolved server-side), should the sparkline column show "—" or simply skip the row from the quote/sparkline fetch? Recommended: skip (use `members.filter(m => m.resolution === "resolved")` as the ids).
3. **F-OQ-04.3**: After-hours behaviour for the sparkline — should we extend the 5m bars to include the post-market session (4-8pm ET), or cap at the regular session close? Bloomberg shows both; TradingView caps. Recommended: cap at regular session for v1 (less data, cleaner curve).
4. **F-OQ-04.4**: How many sidebar rows max (`MAX_ROWS=10` today)? If a watchlist has 50+ members, the "+N more →" link sends them to `/portfolio?tab=watchlists`. PRD-0089 has separated watchlists from portfolio — link target should change to `/watchlists/{id}`. Recommended: change link, raise `MAX_ROWS` to 12 (matches Bloomberg WTC default).
5. **F-OQ-04.5**: Localised number formatting in the sparkline tooltip / row — should `change_pct` use the user's locale (e.g. `0,42 %` in `fr-FR`) or always `en-US`? Recommended: always `en-US` (institutional convention; matches existing `formatPercentDirect`).
6. **F-OQ-04.6**: When a user adds a ticker that's *already in* the active watchlist, should the modal reject silently (no-op) or show an error? Recommended: friendly toast "AAPL is already in Tech" — no error state.
7. **F-OQ-04.7**: Should `Alt+[` / `Alt+]` cycle wrap around (last → first → last)? Recommended: yes, wrap.

---

## 9. Cross-references

- **`01-global-shell.md`** §6 (visual spec), §10 (open questions 1-5)
- **`00-backend-data-inventory.md`** §1.2 (quotes, ohlcv), §1.7 (watchlists)
- **`apps/worldview-web/components/shell/WatchlistPanel.tsx`** — current implementation; needs sparkline column + `+` button + localStorage
- **`apps/worldview-web/components/shell/CollapsibleSidebar.tsx`** — remove `gap-2`, add `border-t` dividers
- **`services/portfolio/src/portfolio/api/routes/watchlist.py`** — unchanged
- **`services/api-gateway/src/api_gateway/routes/market.py`** — confirm `freshness_status` on batch
- **PRD-0089 §OQ-D7** — master PRD already states "Modal" for add-flow; this doc confirms

---

## 10. Estimated implementation effort (frontend only)

| Component | LoC | Tests |
|---|---|---|
| `WatchlistSparkline.tsx` (new, ~80 lines) | 80 | 6 unit |
| `useWatchlistSparklines.ts` hook (new) | 60 | 4 unit + 1 MSW integration |
| `AddToWatchlistModal.tsx` (new) | 250 | 12 unit + 1 Playwright |
| `WatchlistPanel.tsx` modifications (+button, localStorage, hotkeys, sparkline column) | +120 | +8 unit |
| `CollapsibleSidebar.tsx` divider refactor | +20 / -10 | +2 unit |
| `StatusBar.tsx` freshness dot logic + <1280px banner | +60 | +5 unit |
| `IndexStrip.tsx` ticker swap + yield formatter | +15 | +2 unit |
| **Total** | **~595 net LoC** | **~40 tests** |

Backend changes are zero (modulo the confirmation items in §7).

---

**End of Cluster 4 design doc.**
