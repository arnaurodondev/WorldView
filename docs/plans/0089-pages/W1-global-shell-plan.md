---
id: PRD-0089-W1
title: Wave 1 — Global Shell (TopBar / Sidebar / Watchlist / StatusBar)
prd: PRD-0089
order: W1 (first page wave — runs after F1 + F2 land)
status: ready-to-execute
created: 2026-05-20
platform_state: pre-production (no_backfill: true)
parent_design: docs/designs/0089/01-global-shell.md
corners_audit: docs/designs/0089/oq/01-global-shell-CORNERS-AUDIT.md
depends_on:
  - F1 (design system foundation) — primitives + tokens
  - F2 (entity ID unification) — /instruments/{ticker} routing
unblocks:
  - Pages 2..N (every page consumes the new shell)
---

# Wave 1 — Global Shell (PRD-0089)

> **One sentence.** Replace the TopBar's animated marquee + the loose
> sidebar + the placeholder StatusBar with a Bloomberg-grade fixed
> 32px TopBar (17 information slots), a 200px sidebar with
> sparkline-enriched watchlist + alarm cluster, a 22px registry-driven
> StatusBar, and a portfolio switcher that surfaces the F2-locked ROOT
> default — all while honouring every F1 token (radius 0, 20px rows,
> 4-tier animation policy) and F2 routing (`/instruments/{TICKER}`,
> `/indices/{ticker}`).

## 1. Bloomberg-grade resemblance checklist (acceptance signals)

Every behaviour Wave 1 ships must satisfy:

| # | Test | Verify |
|---|------|--------|
| V1 | TopBar 32px sticky-top with 17 information slots | Inspect, count, screenshot |
| V2 | 10-ticker IndexStrip replaces the animated marquee (USO swapped for ^TNX per FU-4.3) | `grep -L TopBarMarquee components/shell/`; visual smoke confirms static row |
| V3 | PortfolioSwitcher chip ("All Portfolios ▾") between search and IndexStrip; always visible even when user has 1 portfolio | Click opens 240px dropdown listing all portfolios + ROOT |
| V4 | DemoBadge renders adjacent to switcher when active portfolio has `kind="demo"` | Toggle a demo portfolio in dev, confirm chip appears |
| V5 | Sidebar 200px wide; nav rows 28px; watchlist + alarm rows **20px** (F1 lock) | Computed style check |
| V6 | Watchlist row shows Ticker / Price / Chg% / 40×16 trend-tinted Sparkline (3-state positive/negative/flat per FU-5.6) | Visual + DOM check |
| V7 | Watchlist click → `/instruments/{TICKER}` (NOT entity_id) — F2 lock | Inspect href; Playwright spec |
| V8 | IndexStrip cell click → `/indices/{TICKER}` (NOT `/instruments/^TNX`) | Inspect href; Playwright spec |
| V9 | "+N more →" sidebar link → `/watchlists` (NEW route, replaces `/portfolio?tab=watchlists`) — FU-4.2 | Inspect href |
| V10 | StatusBar 22px (was 24px); border-top uses `border-border-subtle` (F1 token) not `border-white/[0.06]` | Computed style |
| V11 | StatusBar WS dot reads from `useAlertStream().connected`; freshness dot reads `freshness_status` from `/v1/quotes/batch` (server-driven per FU-4.1) | Source-grep + runtime check |
| V12 | AskAiPanel wrapped in `<AiContentRail>` (left-2px AI rail per DISCUSS-12) and consumes `<InlineCitationAnchor>` (single primitive per DISCUSS-6) | Source-grep + render check |
| V13 | Deprecated components deleted: `TopBarMarquee.tsx`, `MarqueeTickerChip.tsx`, `IndexTicker.tsx` | `ls` returns nothing |
| V14 | Zero `rounded-*` (except `rounded-full` for dots/avatars) anywhere in `components/shell/` | grep |
| V15 | Zero `text-sm` / `text-base` / `text-lg` in `components/shell/` | grep |
| V16 | Hotkey cheat-sheet (`?`) lists every registered chord; pathname matcher works on the new ticker URLs | Open `?`, navigate, verify |
| V17 | ForceUpdateBanner renders ABOVE TopBar as a 24px notice when active (pushes content down 24px) | Toggle the flag, verify layout |
| V18 | Sonner Toaster mounts at `z-60` top-right (FU-10.3) | Inspect z-index |
| V19 | Skip-to-content link is the first focusable element on the page | Tab from address bar → first focus lands on the skip link |
| V20 | At 1280px viewport, IndexStrip drops tickers in priority order until row fits; hides entirely below 1024px | Resize browser; inspect rendered tickers |
| V21 | When market is closed (weekends), freshness dot shows muted-foreground "MARKET CLOSED" label (no false "stale 42h") | Force `useMarketStatus().status = "closed"`, verify |
| V22 | When logged out, `queryClient.clear()` fires AND HotkeyContext scope stack resets to global | Source-grep + Playwright spec |
| V23 | Multi-tab localStorage sync: opening two tabs, toggling sidebar in one syncs the other within 100ms | Manual test or Playwright with two contexts |
| V24 | All F1 architecture tests still green; new tests for shell primitives added | `pnpm test --run` |

## 2. Pre-flight checks (block dispatch if any fail)

1. **F1 landed** — `git log --oneline | grep "feat(plan-0089-f1"` returns
   the 7 expected commits + F1.1 close-out. `_DECISIONS.md §A DISCUSS-3`
   marked locked. F1 primitive catalogue exists at
   `apps/worldview-web/components/primitives/`.
2. **F2 landed** — `git log --oneline | grep "feat(plan-0089-f2"` returns
   the 14 expected step commits. `/instruments/{ticker}` route resolves.
   ADR-F-XX file exists.
3. **F1 primitives present** — verify each of the 14 + 4 moved primitives
   in `components/primitives/`:
   ```
   ls components/primitives/{TableRow,MetricCell,Sparkline,SeverityCharBadge,
      BulkActionToolbar,DenseArticleRow,InlineCitationAnchor,FreshnessDot,
      DataFreshnessPill,EmptyState,LoadingSkeleton,DemoBadge,AiContentRail,
      FocusRing,MetricLabel,MetricValue,SectionDivider,DataTimestamp,
      InstrumentNotFound}.tsx
   ```
   Missing primitive → escalate to F1.1 amendment before continuing.
4. **TanStack `qk.shell.*` namespace** — currently nonexistent. Wave 1
   adds it. No conflict expected.

## 3. Visual contract (reference, don't duplicate)

See `docs/designs/0089/01-global-shell.md`:
- §4.1 — ASCII wireframe at 1440×900
- §4.2 — grid description (region table)
- §4.3 — density target (17 TopBar + 24 sidebar rows)
- §6 — visual spec per region (px, fonts, colors)

**Deltas from the design doc** (corners audit closes these):

| Design doc says | W1 ships | Reason |
|-----------------|----------|--------|
| Watchlist row `h-[22px]` | `h-[20px]` via `data-table-grid` | F1 lock (C-01) |
| PortfolioRail `rounded-[2px]` | `rounded-none` (i.e. no class) | F1 radius=0 (C-04) |
| StatusBar `border-t border-white/[0.06]` | `border-t border-border-subtle` | F1 token (C-02) |
| Watchlist click → `/instruments/{entity_id}` | `/instruments/{ticker}` | F2 lock (C-08) |
| IndexStrip click → unspecified | `/indices/{ticker}` | C-10 lock |
| `+N more →` link → `/portfolio?tab=watchlists` | `/watchlists` | FU-4.2 (C-09) |
| Sparkline endpoint `intraday` | `POST /v1/ohlcv/batch` | FU-4.1 (C-13) |
| Sparkline stroke 2-state (pos/neg) | 3-state (pos/neg/flat trend-tinted) | FU-5.6 (C-33) |
| Sidebar hover `duration-0` | `transition-color-only duration-75` named token | F1 Tier-1 alignment (C-06) |
| PortfolioSwitcher placement | TopBar slot between search and IndexStrip | C-15 lock |
| DemoBadge placement | Inline with switcher chip | FU-1.5 (C-16) |
| AskAiPanel citation parser | Replaced by `<InlineCitationAnchor>` from F1; wrapped by `<AiContentRail>` | DISCUSS-6 + DISCUSS-12 (C-07, C-17) |

## 4. File-by-file change set (one commit per file group)

### 4.1 NEW — `apps/worldview-web/components/shell/IndexStrip.tsx`
Replaces the animated `TopBarMarquee`. Static 10-cell row.

- **Manifest** (locked): SPY, QQQ, IWM, DIA, VIX, TLT, **^TNX** (was USO), GLD, USO, BTC-USD
- **Per cell**: 60px wide, gap 8px (total ~680px max)
  - Ticker: `font-mono font-medium text-[11px] text-foreground`
  - Price: `font-mono tabular-nums text-[11px]` (compact >10K: `99K`, `1.2M`)
  - Chg%: `font-mono tabular-nums text-[10px]` colored per direction (deadband ±0.005%)
- **Click**: route to `/indices/{ticker}` (strip `^` from the URL form; query state stores the canonical with caret)
- **Hover**: Radix Tooltip after 300ms shows full name ("S&P 500" not "SPY")
- **Loading**: 10 placeholder cells with `bg-muted/30` skeleton (never collapse to zero — prevents layout shift)
- **Error**: cells keep last-known cached values; small `bg-warning` dot on MarketStatusPill
- **Narrow viewport**: at <1440px, drop tickers in priority order until row fits: `USO → GLD → BTC → DXY → TLT → DIA → VIX`. Hide entire strip below 1024px (mobile = v1.1)
- **Line budget**: ≤180

### 4.2 NEW — `apps/worldview-web/components/shell/PortfolioSwitcher.tsx`
Always-visible chip + dropdown popover. ROOT default per DISCUSS-1 (FU-1.1 "All Portfolios").

- **Chip** (collapsed state): `h-[24px]` width-fit-content, padding `px-2`, text `font-mono text-[11px]`. Label: "All Portfolios ▾" when ROOT active; portfolio name when single-portfolio selected. No border-radius.
- **Dropdown popover** (open state): 240px wide, Tier-2 animation (≤200ms opacity+scale), no shadow.
  - Header: "PORTFOLIOS" `text-[10px] uppercase tracking-wide text-muted-foreground`, padding `px-2 py-1.5`
  - Row per portfolio: 28px height; ticker icon (if synced) + name + total value mono-right-aligned + selected check
  - ROOT pinned to top, always visible, separator hairline below
  - Footer: "+ New portfolio" CTA → `/portfolio/new` (or modal — defer to v1.1)
- **Hotkey**: `Alt+P` toggles dropdown (or right-click on chip for shortcuts menu — v1.1)
- **`<DemoBadge />`** rendered to the immediate right of the chip when active portfolio has `kind === "demo"` (FU-1.5)
- **Line budget**: ≤200

### 4.3 EDIT — `apps/worldview-web/components/shell/TopBar.tsx`
Compose the 17 information slots, including the new switcher.

Left → right order:
1. Wordmark "Worldview" → button to `/dashboard`, `aria-label="Worldview — Home"`, focus T3
2. GlobalSearch trigger `⌘K Search…` (no change to GlobalSearch.tsx itself)
3. **NEW**: `<PortfolioSwitcher />`
4. **NEW**: `<DemoBadge />` (conditional)
5. **NEW**: `<IndexStrip />` (replaces TopBarMarquee)
6. `<UtcClock />` (no change)
7. `<MarketStatusPill />` (no change)
8. PortfolioRail box (PORT/Day/Tot) — drop `rounded-[2px]` (C-04). Keep border + bg-muted/20.
9. `<AskAiButton />` (no change)
10. `<RefreshAllButton />` (no change)
11. Alert bell — keep `rounded-full` badge (allowed F1 exception)
12. Avatar + dropdown menu

Logout handler in the dropdown calls `queryClient.clear()` + `hotkeyCtx.resetScopes()` before redirect (C-28). Wordmark gets `tabIndex={1}` + skip-to-content target.

**Line budget**: keep current ~250 LOC; after change ~280 LOC max.

### 4.4 EDIT — `apps/worldview-web/components/shell/CollapsibleSidebar.tsx`
Tighten to 200px, replace section gaps with hairlines.

- Width: `w-[200px]` expanded, `w-10` (40px) collapsed (current is 220 → 200 per §9.4)
- Nav row: `h-7` (28px), `px-2.5 gap-1.5`; icon `size-[14px] stroke-1.5`; label `text-[10px] font-medium`
- Active row: `bg-primary/10 text-primary border-l-2 border-primary`
- Section dividers: `border-t border-border-subtle` between Nav / Watchlist / Alarms / Settings clusters (replace any `mt-2` gap-band)
- Drag handle: keep existing min 160 / max 340; verify drag handle uses `cursor-col-resize`
- Collapsed state: only nav icons + Settings + bottom-chrome render; watchlist + alarms HIDE entirely; hover any icon → Radix Tooltip with full name (C-31)
- **localStorage sync**: subscribe to `storage` events for `sidebar.collapsed` key; last-write-wins across tabs (C-21)
- **Line budget**: minimal addition; current ~400 LOC stays

### 4.5 EDIT — `apps/worldview-web/components/shell/WatchlistPanel.tsx`
Add sparkline column, fix click target + endpoint + link.

- Wrap rows in `<div data-table-grid>` so they inherit `--row-h: 20px` (F1, C-01)
- Switcher header (`h-6`, "WATCHLIST  Tech ▾"): clicking opens a 200px popover listing user's watchlists + "+ New watchlist" CTA (C-30). Popover uses Tier-2 animation.
- Add-flow hotkey: `mod+shift+w` (FU-4.4) — registered in `useEffect` in this component
- Row layout (per F1 `<TableRow>` primitive):
  | Col | Width | Style |
  |-----|-------|-------|
  | Ticker | 44px | `font-mono text-[11px] text-foreground truncate` |
  | Price | flex-1 right | `font-mono tabular-nums text-[11px]` |
  | Chg% | 44px right | `font-mono tabular-nums text-[11px]` color-by-sign |
  | Sparkline | 40×16 | `<Sparkline data={...} trend="auto" />` from F1 primitive (3-state per FU-5.6) |
- **Click**: `router.push(\`/instruments/\${member.ticker}\`)` (NOT `entity_id`, C-08)
- **`+N more →`** link href: `/watchlists` (C-09 / FU-4.2)
- **Sparkline data source**: `useQuery({ queryKey: qk.instruments.ohlcvBatch([...tickers], "5m", 78), ... })` via existing `POST /v1/ohlcv/batch` endpoint (C-13 / FU-4.1)
- **Freshness indicator**: per-row dot via `<FreshnessDot status={member.freshness_status} />` from F1 primitive — server-driven (FU-4.1)
- **Loading**: 5 skeleton rows at 20px so sidebar height doesn't jump
- **Empty**: existing copy "Add symbols in Portfolio → Watchlists" (note: link target updated to `/watchlists`)
- **Line budget**: current ~300 LOC + ~60 = ~360 LOC

### 4.6 EDIT — `apps/worldview-web/components/shell/StatusBar.tsx`
Flip to 22px, swap border token, market-closed handling.

- Height: `h-[22px]` (was `h-6` = 24px) per §9.3
- Top border: `border-t border-border-subtle` (NOT `border-white/[0.06]`, C-02)
- Left cluster — 6 chord hints from `lib/hotkey-registry`; `<kbd>` glyph in `font-mono text-[9px] text-primary/70`; label `text-[10px] text-muted-foreground/50`; gap `gap-3`
- Right cluster — page label + WS dot + Freshness dot:
  - WS dot: `h-1.5 w-1.5 rounded-full`. Reads from `useAlertStream().connected`. green = live; amber = reconnecting; red = disconnected > 5s. Label `text-[10px] font-mono`.
  - Freshness dot: derives from cached quote `freshness_status` enum (server-driven). green/amber/muted per FU-4.1.
  - **Market-closed override**: when `useMarketStatus().status === "closed"`, freshness dot renders muted-foreground with label "MARKET CLOSED" — no false "stale 42h" (C-20)
- **Line budget**: current ~120 LOC; after change ~140 LOC

### 4.7 EDIT — `apps/worldview-web/components/shell/AskAiPanel.tsx`
Wrap with AiContentRail; consume InlineCitationAnchor; delete duplicate parser.

- Wrap the panel body with `<AiContentRail>` from F1 (left-2px accent-ai border per DISCUSS-12, C-07)
- Replace local `parseCitationResponse` (~80 LOC) and `renderWithCitations` (~110 LOC) with `<InlineCitationAnchor>` from F1 primitives per DISCUSS-6 (C-17)
- Net deletion: ~310 LOC (per cluster 03 finding). Validate by `wc -l` before/after.
- **Line budget**: dramatic reduction; verify final file <250 LOC

### 4.8 NEW STUB — `apps/worldview-web/app/(app)/watchlists/page.tsx`
Required for the `+N more →` link to not 404 (C-12).

- Minimal stub: server component renders `<WatchlistsPageStub />` (client component)
- Stub body: "Watchlists management" header + list of user's watchlists (uses existing `useWatchlists` hook)
- Clicking a watchlist shows its members in a read-only list
- "+ New watchlist" CTA opens a modal (defer the modal UX to the Watchlists wave; v1 just shows "Coming soon" toast)
- **Line budget**: ≤120 LOC stub; full page in a later wave

### 4.9 NEW STUB — `apps/worldview-web/app/(app)/indices/[ticker]/page.tsx`
Required for IndexStrip cell clicks to land somewhere (C-10).

- Server component awaiting `params: Promise<{ticker: string}>`
- Renders a thin client component that:
  - Fetches the index entity by ticker (via `/v1/entities/lookup?ticker=...` + `kind=index` filter)
  - Shows: ticker symbol, full name (e.g. "10-Year Treasury Yield"), latest value, daily change, 1Y chart (lightweight-charts)
  - No tabs — just a quote-style summary page
- 404 → render `<InstrumentNotFound>` from F1 (already exists post-F2)
- **Line budget**: ≤200 LOC stub; can be expanded in v1.1

### 4.10 DELETE — deprecated shell components (C-29)

After §4.1 lands and any remaining import sites are updated:

```bash
rm apps/worldview-web/components/shell/TopBarMarquee.tsx
rm apps/worldview-web/components/shell/MarqueeTickerChip.tsx
rm apps/worldview-web/components/shell/IndexTicker.tsx
```

Verify via `grep -rE "TopBarMarquee|MarqueeTickerChip|IndexTicker" apps/worldview-web/`
returns 0 hits (other than the deletion commit's own changelog).

### 4.11 EDIT — `apps/worldview-web/app/(app)/layout.tsx`
Add ForceUpdateBanner placement + skip-to-content + Sonner Toaster.

- ForceUpdateBanner renders ABOVE TopBar as `h-6` (24px) sticky notice strip when active. When inactive, occupies zero height (C-25).
- First focusable child of `<body>`: `<a href="#main" className="sr-only focus:not-sr-only">Skip to main content</a>` (C-27). Target `<main id="main">` on the page-content area.
- Sonner Toaster mounted at `z-60` top-right (C-26 / FU-10.3)
- **Idle-lock**: when `useIdleLock().locked === true`, set every shell-owned `refetchInterval` to `false` via a `useEffect` + `queryClient.setDefaultOptions({queries:{refetchInterval:false}})` (C-22)
- **Line budget**: current ~120 LOC + ~40 = ~160 LOC

## 5. Data fetching (qk.shell.* additions)

| Resource | New key | staleTime | refetchInterval | Owned by |
|----------|---------|-----------|------------------|----------|
| Index strip resolved entity IDs | `qk.shell.indexResolveIds()` | 30 min | — | IndexStrip.tsx |
| Index strip batch quotes | `qk.shell.indexQuotes()` | 0 | 15s (pause when idle-locked) | IndexStrip.tsx |
| Index strip intraday sparkline (each ticker) | reuse `qk.instruments.ohlcvBatch(tickers, "5m", 78)` | 60s | 60s | shared with watchlist |
| Portfolio switcher list | `qk.portfolios.list()` (existing) | 5 min | — | PortfolioSwitcher.tsx |
| Active portfolio summary | `qk.portfolios.summary(activeId)` (existing) | 30s | 30s | TopBar PortfolioRail |
| Watchlist members (active) | `qk.watchlists.members(activeId)` (existing — promote inline key) | 30s | 30s | WatchlistPanel.tsx |
| Watchlist member quotes | `qk.watchlists.quotes(memberTickers)` (existing) | 0 | 30s | WatchlistPanel.tsx |
| Watchlist member sparklines | `qk.instruments.ohlcvBatch(tickers, "5m", 78)` | 60s | 60s | shared |
| Pending alerts count + list | `qk.alerts.pendingCount() / list()` (existing) | 60s / 30s | 60s / 30s | AlarmsPanel + bell |
| Market session | `qk.market.status()` (existing) | 60s | 60s | MarketStatusPill + StatusBar |

## 6. Tests

### 6.1 Unit tests
- `IndexStrip.test.tsx` — renders 10 cells, narrow-viewport priority drop, click navigates to `/indices/{ticker}`
- `PortfolioSwitcher.test.tsx` — chip always visible (even with 1 portfolio), dropdown opens, ROOT pinned to top, DemoBadge appears when active is demo
- `WatchlistPanel.test.tsx` — sparkline renders trend-tinted, click → `/instruments/{ticker}`, `+N more` → `/watchlists`, `mod+shift+w` opens add modal
- `StatusBar.test.tsx` — market-closed dot label, WS dot color states, freshness server-driven
- `TopBar.test.tsx` — 17 slots present, logout calls `queryClient.clear()` + scope reset
- `layout.test.tsx` — skip-to-content link present and focusable, ForceUpdateBanner pushes content down

### 6.2 Playwright e2e
- `shell-navigation.spec.ts`: G+D / G+P / G+I / G+S chord nav lands on right routes
- `shell-watchlist-click.spec.ts`: clicking a watchlist row navigates to `/instruments/AAPL` (NOT a UUID)
- `shell-indexstrip-click.spec.ts`: clicking SPY cell navigates to `/indices/SPY`
- `shell-portfolio-switcher.spec.ts`: switcher always visible; dropdown opens; selecting changes the TopBar PortfolioRail values
- `shell-narrow-viewport.spec.ts`: at 1280px, USO ticker disappears from IndexStrip first
- `shell-density.spec.ts`: at 1440×900, TopBar contains ≥17 information slots (density floor canary per NFR-1 tier)

### 6.3 Architecture-test extensions
Add to `__tests__/architecture/no-off-palette-colors.test.ts`:
- Ban `border-white/\[` regex anywhere except palette source files (forces F1 token usage)
- Ban `TopBarMarquee|MarqueeTickerChip|IndexTicker` references in component files (catches dangling imports post-deletion)

## 7. Acceptance criteria

| # | Gate | Verification |
|---|------|--------------|
| 1 | `pnpm --filter worldview-web typecheck` | 0 errors |
| 2 | `pnpm --filter worldview-web test --run` | All green; new shell tests pass |
| 3 | `pnpm --filter worldview-web build` | Succeeds |
| 4 | `pnpm --filter worldview-web lint` | 0 errors |
| 5 | grep -rE "rounded-(sm\|md\|lg\|xl\|2xl)" apps/worldview-web/components/shell/ | 0 results |
| 6 | grep -rE "text-(sm\|base\|lg\|xl)" apps/worldview-web/components/shell/ | 0 results |
| 7 | grep -rE "border-white/\[" apps/worldview-web/components/shell/ | 0 results |
| 8 | grep "TopBarMarquee\|MarqueeTickerChip\|IndexTicker" apps/worldview-web/components/shell/ | 0 results |
| 9 | Playwright shell-navigation spec | PASSES |
| 10 | Playwright shell-watchlist-click spec | PASSES |
| 11 | Playwright shell-indexstrip-click spec | PASSES |
| 12 | Playwright shell-density spec | PASSES |
| 13 | Visual smoke at 1440×900: count visible TopBar information slots manually | ≥17 |
| 14 | Visual smoke at 1280×800: USO ticker hidden in IndexStrip | Confirmed |
| 15 | Toggle a demo portfolio in switcher | DemoBadge appears next to chip |
| 16 | Press `?` in any page | HotkeyCheatSheet renders all registered chords |
| 17 | Click logout → re-login as same user | TanStack cache cleared; no stale data flashes |
| 18 | Open two tabs, collapse sidebar in one | Other tab reflects within 100ms |
| 19 | AskAiPanel opens with new citation primitive | No `parseCitationResponse` function in source; `<InlineCitationAnchor>` renders |
| 20 | AskAiPanel visual | Left-2px accent-ai rail present |

## 8. Risk register

| Risk | Mitigation |
|------|------------|
| `/indices/{ticker}` route ships a stub but isn't fully designed → IndexStrip clicks land on a half-page | Stub is functional: shows ticker + value + 1Y chart. Acceptable for v1; full design in a later wave |
| `/watchlists` stub missing fields users expect | Stub is read-only list. "+New watchlist" shows toast "Coming soon". Acceptable for v1 |
| AskAiPanel refactor breaks existing chat citations | Ship behind a feature flag if needed; unit tests cover both old and new paths during transition |
| Deleting `TopBarMarquee` breaks something we don't know about | Grep first; if any unexpected references found, escalate before deleting |
| `useIdleLock` pausing refetch intervals interferes with watch-by-the-second traders | Idle-lock currently fires after 15min idle; market session is ≥6h; not a meaningful conflict |
| Sparkline data via `ohlcvBatch` exceeds 50-symbol limit when watchlist > 50 tickers | Watchlist cap is 50 per FU-4.7 implicit; if exceeded, batch in chunks of 50 |
| Sonner Toaster collision with FlashOverlay | Different z-indexes (Sonner z-60, FlashOverlay z-50); document in `lib/copy/toast.ts` |
| Multi-tab localStorage sync overflowing storage event listeners | Standard browser behaviour; ≤2 listeners per tab; no leak risk |

## 9. Files touched (consolidated)

```
NEW:
  apps/worldview-web/components/shell/IndexStrip.tsx                    (~180 LOC)
  apps/worldview-web/components/shell/PortfolioSwitcher.tsx             (~200 LOC)
  apps/worldview-web/app/(app)/watchlists/page.tsx                       (~120 LOC stub)
  apps/worldview-web/app/(app)/indices/[ticker]/page.tsx                (~200 LOC stub)
  apps/worldview-web/__tests__/shell/{IndexStrip,PortfolioSwitcher,WatchlistPanel,StatusBar,TopBar,layout}.test.tsx
  apps/worldview-web/tests/e2e/{shell-navigation,shell-watchlist-click,shell-indexstrip-click,shell-portfolio-switcher,shell-narrow-viewport,shell-density}.spec.ts

EDIT:
  apps/worldview-web/components/shell/TopBar.tsx                         (compose 17 slots; +30 LOC)
  apps/worldview-web/components/shell/CollapsibleSidebar.tsx              (200px width; hairline dividers; localStorage sync; +20 LOC)
  apps/worldview-web/components/shell/WatchlistPanel.tsx                  (data-table-grid; sparkline col; ticker href; ohlcvBatch; +60 LOC)
  apps/worldview-web/components/shell/StatusBar.tsx                       (22px; border-subtle; market-closed; +20 LOC)
  apps/worldview-web/components/shell/AskAiPanel.tsx                      (AiContentRail wrap; InlineCitationAnchor; −310 LOC)
  apps/worldview-web/app/(app)/layout.tsx                                  (ForceUpdateBanner; skip-link; Sonner; idle-lock pause; +40 LOC)
  apps/worldview-web/lib/query/keys.ts                                    (qk.shell.* + qk.instruments.ohlcvBatch additions)
  apps/worldview-web/__tests__/architecture/no-off-palette-colors.test.ts (2 new forbidden patterns)

DELETE:
  apps/worldview-web/components/shell/TopBarMarquee.tsx
  apps/worldview-web/components/shell/MarqueeTickerChip.tsx
  apps/worldview-web/components/shell/IndexTicker.tsx

NET LOC: roughly +400 new, −310 from AskAiPanel cleanup, −deleted files. Expected total: +200 LOC net.
```

## 10. Estimation

| Phase | Effort |
|-------|-------:|
| IndexStrip new component | 0.5d |
| PortfolioSwitcher new component | 0.75d |
| WatchlistPanel refactor (sparkline + ticker URLs + ohlcvBatch) | 0.75d |
| TopBar composition (17 slots) | 0.5d |
| CollapsibleSidebar tightening + localStorage sync | 0.5d |
| StatusBar 22px + market-closed handling | 0.25d |
| AskAiPanel citation refactor (-310 LOC) | 0.5d |
| `/watchlists` + `/indices/[ticker]` stub routes | 0.5d |
| layout.tsx ForceUpdateBanner + skip-link + Toaster + idle-lock pause | 0.5d |
| Delete deprecated components + grep cleanup | 0.25d |
| Unit + Playwright tests (12 specs) | 1d |
| Architecture-test extensions | 0.25d |
| **Total single-agent serial** | **~6 days** |

## 11. Rollback plan

Each PR is a discrete commit; revert per commit. The deletion commit
(§4.10) is the riskiest — revert restores the deprecated files and any
import sites that depended on them. Stash an unzipped tarball of the
deleted files in `/tmp/w1-deleted-backup.tgz` at the start of the delete
step as a belt-and-suspenders safety net.

## 12. Out of scope for Wave 1

- Watchlist drag-to-add from any page (FU-4.6 → v1.1)
- Multi-row tiled watchlists in sidebar (FU-4.7 → out of scope confirmed)
- Full `/watchlists` page (this wave ships a stub only)
- Full `/indices/[ticker]` page (this wave ships a stub only)
- Mobile responsive (FU-1.6 → v1.1)
- Workspace sharing via watchlist (v2)
- Custom IndexStrip ticker manifest per-user (v1.1)

## 13. Definition of done

- All 20 acceptance gates pass
- Wave 1 commits land on `feat/plan-0089-w1` (parent: F2 final commit)
- Visual smoke confirms Bloomberg-grade resemblance per §1 checklist
- Page 2 (Portfolio Overview) is unblocked: watchlist navigation works,
  PortfolioSwitcher exists for ROOT default, F1 primitives consumed at scale
