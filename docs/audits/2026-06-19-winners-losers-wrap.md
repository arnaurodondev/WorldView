# Winners/Losers Row Layout Wrap Investigation
**Date**: 2026-06-19  
**Symptom**: Ticker content wraps to two lines in the dashboard winners/losers (top-movers) widgets.  
**Status**: Root cause identified. Fix ready for `/fix-bug`.

---

## 1. Component Map

| Tab | Component | File | Row height |
|-----|-----------|------|-----------|
| MARKET | `TopMovers` → `MoverRow` | `components/dashboard/TopMovers.tsx:383` | `h-[22px]` |
| WATCHLIST | `WatchlistMoversWidget` → `WatchlistMoverRow` | `features/dashboard/components/WatchlistMoverRow.tsx:70` | `h-7` (28px) |
| HOLDINGS | `HoldingsMoversWidget` → `MoverRow` | `components/dashboard/HoldingsMoversWidget.tsx:538` | `h-[22px]` |

All three are hosted inside `MoversWidgetTabs`, which lives in the dashboard grid cell  
`<div className="col-span-1 md:col-span-3 lg:col-span-3 ...">` — **3 of 12 columns**.

---

## 2. Container Width Budget

Grid: `grid-cols-12 gap-3 p-3`. Effective container per-viewport:

| Viewport | Grid avail | `lg:col-span-3` | Two-column half |
|----------|-----------|----------------|----------------|
| 1024 px | 868 px | **217 px** | 108 px |
| 1280 px | 1124 px | **281 px** | 140 px |
| 1440 px | 1284 px | **321 px** | 160 px |
| 1920 px | 1764 px | **441 px** | 220 px |

---

## 3. Fixed Slot Budget per Row Variant

### 3a. `TopMovers.MoverRow` (MARKET tab) — single-column
```
ticker: w-[44px] shrink-0
sparkline: shrink-0 (40px inline SVG)
price:  w-[60px] shrink-0
pct:    w-[52px] shrink-0
gap-1.5 × 4 = 24px
px-2 × 2 = 16px
─────────────────────────────────
Total fixed = 236 px
Name flex-1 budget = col_width − 236 px
```

| Viewport | Col width | Name budget |
|----------|-----------|-------------|
| 1024 px | 217 px | **−19 px** (overflow!) |
| 1280 px | 281 px | +45 px (OK) |
| 1440 px | 321 px | +85 px (OK) |

### 3b. `WatchlistMoverRow` / `HoldingsMoversWidget.MoverRow` — **two-column**
Each column is `flex-1` of the 3-column widget → each column ≈ `col_width / 2`.

```
(WatchlistMoverRow, no badge)
ticker:  w-[40px] shrink-0
price:   w-[52px] shrink-0
pct:     w-[52px] shrink-0
gaps + padding = ~34 px
────────────────────────────
Total fixed = 178 px

(WatchlistMoverRow, with badge+news)
+ dot:   6 px + news-icon+digit: ~24 px → Total = 217 px
```

| Viewport | Half-col | Deficit (no badge) | Deficit (badge) |
|----------|----------|--------------------|----------------|
| 1024 px | 108 px | **−70 px** | **−109 px** |
| 1280 px | 140 px | **−38 px** | **−77 px** |
| 1440 px | 160 px | **−18 px** | **−57 px** |
| 1920 px | 220 px | +42 px (OK) | +4 px (marginal) |

---

## 4. Root Causes

### RC-1 (P0) — Two-column half-column is too narrow for fixed slots (ALL viewport sizes < 1920 px)

**File/line**: `components/dashboard/WatchlistMoversWidget.tsx` ~line 503;  
`components/dashboard/HoldingsMoversWidget.tsx` ~line 450.

The two-column container `<div class="flex">` places each column at `flex-1` = ~50% of the
3-column widget. At 1280 px (the most common desktop width) each column is ~140 px. The fixed
slots alone (ticker 40 + price 52 + pct 52 + gaps + padding = 178 px) already exceed the column
width by **38 px** before the name even exists.

The `flex-1 min-w-0 truncate` name span collapses to 0 px correctly (truncate fires). But the
`shrink-0` price and pct spans still take 52 + 52 = 104 px of horizontal space. Together with
the ticker (40 px) the three shrink-0 slots sum to 144 px — already wider than the 140 px
column — causing **horizontal overflow past the column edge into the sibling column**.

Since the column divs have no `overflow-hidden`, the overflowed text bleeds into the adjacent
Losers column. The 28 px / 22 px height is fixed so content cannot actually wrap vertically —
the visual "two lines" impression comes from the bleed making it look as if text from one row
is overlapping another row's baseline.

**Trigger entries**: ANY ticker when the browser window ≤ 1440 px on WATCHLIST/HOLDINGS tabs.
Badges (alert dot + news count) make it worse — they add another 30 px of fixed slots.

---

### RC-2 (P1) — TopMovers.MoverRow overflows at 1024 px (MARKET tab, narrow desktop/laptop)

**File/line**: `components/dashboard/TopMovers.tsx:401`

At `lg:col-span-3` on a 1024 px viewport the cell is ~217 px. The sparkline (40 px) is an
additional fixed slot absent from the two-column variants; total fixed = 236 px > 217 px.
The name truncates to 0 px correctly, but the right edge clips the pct column.

---

### RC-3 (P2) — Ticker span lacks `overflow-hidden` (all three variants)

**File/line**:  
- `TopMovers.tsx:411`: `<span className="w-[44px] shrink-0 font-mono text-[11px] tabular-nums text-foreground">`  
- `HoldingsMoversWidget.tsx:554`: `<span className="w-[40px] shrink-0 font-mono text-[11px] font-semibold tabular-nums text-foreground">`

The ticker span has a fixed `w-[N]px` but no `overflow-hidden`. The transform fallback path
(`r.name?.split(" ")[0]` — e.g. "Berkshire", 9 chars ≈ 59 px) produces a ticker-like string
that overflows the 40-44 px slot and visually bleeds into the name span. Since the name has
`overflow:hidden` (from `truncate`), the bleed makes it look like the ticker has pushed the name
off the line.

---

### RC-4 (P2) — `change_pct` and price use unbounded `toFixed(2)` / `formatPrice` inside fixed-width slots

**File/line**: `TopMovers.tsx:451-453`, `HoldingsMoversWidget.tsx:569-571`, `WatchlistMoverRow.tsx:149-151`

```tsx
// TopMovers.tsx:451
{isUp ? "+" : ""}{mover.change_pct.toFixed(2)}%
```

For meme-stock / short-squeeze events (e.g. GME +135 %) the rendered string `"+135.43%"` = 8 chars
at 11 px mono ≈ 54 px, which overflows the `w-[52px]` slot (52 px). With `text-right`, the text
aligns right within the 52 px box and the left edge bleeds into the price column. This is a
secondary effect that worsens the visual impression at extreme change values.

Similarly, `formatPrice` (full precision, no compact threshold) on a stock like NVR (~$8 000):
`"$8,000.00"` = 9 chars at 10 px mono ≈ 53 px, tight against `w-[60px]` (TopMovers) or
`w-[52px]` (two-column variants). BRK.A at ~$650 000 → `"$650,000.00"` = 11 chars ≈ 65 px,
definitely overflows `w-[60px]`.

---

## 5. Fix Recommendation (P0 — ready for `/fix-bug`)

### Fix A — Two-column variants: reduce to ONE price column; add `overflow-hidden` to the column divs

The two-column layout at `flex-1` is geometrically unsound: two 178 px payloads cannot fit in
a ~281 px widget. The design intent (5 gainers | 5 losers side-by-side) was designed for a wider
cell (previous `col-span-5`). Now at `col-span-3` the layout must shed width.

**Options (pick one):**

**A1 (preferred)** — Drop the price column from both two-column variants. Keep:
`ticker · name(truncate) · pct`. Saves 52 px per column.
```
Fixed = ticker(40) + pct(52) + gaps(12) + padding(16) = 120 px
Name budget at 1280 px = 140 − 120 = 20 px (truncated, shows ellipsis)
```
Still too tight on 1280 px. Add `overflow-hidden` to each column div to clip instead of bleed.
At 1440 px: 160 − 120 = 40 px for name. Reasonable.

**A2 (more info)** — Remove the side-by-side layout entirely. Show gainers list then losers list
sequentially (single column), halving the layout complexity. Each single-column row at full
~281 px easily fits ticker(40) + name(flex) + price(52) + pct(52) + gaps + padding = 178 px,
leaving 103 px for the name. Much more legible.

**A3 (minimal)** — Keep current layout but add `overflow-hidden` to each column div and add
`whitespace-nowrap overflow-hidden` to the ticker span. This clips the bleed but the name still
gets 0 px on 1280 px — the row looks very sparse. Not recommended as a standalone fix.

---

### Fix B — `TopMovers.MoverRow`: drop sparkline on narrow widths OR shrink fixed slots

The MARKET tab single-column row at 281 px with 236 px fixed leaves 45 px for name — workable.
At 1024 px (217 px col) it overflows 19 px. Two options:

**B1 (preferred)** — Add `overflow-hidden` to the outer row div and clamp:
```tsx
// current (TopMovers.tsx:401)
className="flex h-[22px] cursor-pointer items-center gap-1.5 px-2 ..."
// fixed:
className="flex h-[22px] min-w-0 cursor-pointer items-center gap-1.5 px-2 overflow-hidden ..."
```
This clips the horizontal overflow within the 22 px row instead of bleeding it.
The % column will be hidden at 1024 px, but the row stays on one visual line.

**B2** — Use responsive hiding for the sparkline: `hidden md:block` on the sparkline span.
At 1024 px (md breakpoint) this reclaims 40 px, leaving 217 − 196 = 21 px for name.

---

### Fix C — Ticker span: add `overflow-hidden` (all three variants)

```tsx
// TopMovers.tsx:411 — current
<span className="w-[44px] shrink-0 font-mono text-[11px] tabular-nums text-foreground">
// fixed:
<span className="w-[44px] shrink-0 overflow-hidden font-mono text-[11px] tabular-nums text-foreground">
```
Same for `HoldingsMoversWidget.tsx:554` (`w-[40px]`).  
`WatchlistMoverRow.tsx:103` already has correct width; same fix applies.

---

### Fix D — `change_pct` formatting: cap extreme moves

Replace `mover.change_pct.toFixed(2)%` with a bounded formatter in all three row components:

```tsx
// Replace raw .toFixed(2) with a clamped formatter, e.g.:
function formatChangePct(pct: number): string {
  const abs = Math.abs(pct);
  if (abs >= 1000) return `${pct > 0 ? "+" : ""}${(pct/1000).toFixed(1)}K%`;
  if (abs >= 100)  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;  // 1 decimal saves 1 char
  return `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`;
}
```
At 2 decimals, `+100.0%` = 7 chars fits w-[52px]; `+135.4%` = 7 chars fits; `+999.9%` = 7 chars fits.
This saves the column on all but the most extreme crypto moves.

---

### Fix E — Price: switch to `formatPriceCompact` in row contexts

```tsx
// current (all three variants)
{formatPrice(mover.price)}   // "$650,000.00" = 11 chars, overflows w-[52px]
// fixed:
{formatPriceCompact(mover.price)}  // "$650.00K" = 8 chars, fits
```
`formatPriceCompact` = `formatCompactCurrency(v, "USD")` which already exists in `lib/format.ts:340`.
For stocks < $1 M it falls back to `formatPrice` (e.g. "$182.34") — no change for normal stocks.
For high-price stocks (NVR ~$8k, BRK.A ~$650k) it switches to `"$8.00K"` / `"$650.00K"`.

---

## 6. Priority Order for `/fix-bug`

| # | Fix | Impact | Risk |
|---|-----|--------|------|
| 1 | **C**: `overflow-hidden` on ticker spans | Eliminates text bleed from long fallback tickers | Trivial — 2 lines changed |
| 2 | **B1**: `overflow-hidden` on TopMovers MoverRow outer div | Prevents horizontal overflow at 1024 px | Trivial — 1 class added |
| 3 | **E**: `formatPriceCompact` for price in all row variants | Cuts 2-4 chars from high-price stocks | Low — cosmetic change, existing util |
| 4 | **D**: bounded `formatChangePct` helper | Cuts 1 char from >100% moves | Low — isolated helper |
| 5 | **A2**: collapse two-column layout to single-column | Eliminates the structural overflow permanently | Medium — layout change, update tests |

Fixes 1-4 are safe, mechanical, and recoverable. Fix 5 is the definitive structural solution
but changes the widget's visual language; it should be paired with design sign-off.

---

## 7. What NOT to do

- Do NOT add `whitespace-nowrap` to the name span — it already has it (from `truncate`).
- Do NOT add `min-w-0` to the outer row div — it won't help (the outer div is already block-level inside a block container, so it takes full column width).
- Do NOT remove `shrink-0` from price/pct spans — that would make them shrink together and misalign column numeric values across rows (tabular-nums won't align if widths vary).
- Do NOT increase the fixed slot widths (`w-[60px]` → `w-[80px]`) — the slots are already the binding constraint. Making them larger worsens overflow.
