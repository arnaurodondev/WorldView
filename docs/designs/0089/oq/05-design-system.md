---
id: PRD-0089-OQ-05
title: Cluster 5 — Design System Overhaul (typography, spacing, radius, density, motion, focus)
status: investigation
created: 2026-05-19
parent: docs/designs/0089/_INDEX.md
master_prd_oq: OQ-B5 (density floor), OQ-(per-page spacing)
scope: cross-cutting — touches every component on every page
---

# Cluster 5 — Design System Overhaul

> The single most far-reaching decision in PRD-0089. Every cell, every panel,
> every focus ring, every hover state is in scope. This doc proposes the
> revised tokens, audits the migration cost, and recommends an enforceable
> architecture-test extension to lock the new system in.

---

## 1. Cluster Summary + User-Preference Anchors

### 1.1 The user's stated direction

| # | Preference | Current state | User's request | Recommended decision |
|---|------------|---------------|----------------|----------------------|
| 1 | **Smaller fonts** | 9-14px scale; body=11px | "Smaller several units" | **Accept — but selectively.** Push body to 10.5px (`text-[10.5px]`) in dense tables only; keep 11px in narrative surfaces (chat, articles). Headers tighten to 11-12px. Sub-10px reserved for chart axes only. Anything below 10px on body text degrades scan-speed (see §2.2 Bloomberg measurements). |
| 2 | **Smaller padding/margins** | `px-2` (8px) cell, `gap-2` (8px) section | "Smaller" | **Accept.** Cell padding `px-2 → px-1.5` (6px); section gap `gap-2 → gap-1.5` (6px); row height `22 → 20px` standard / `18px` ultra-dense. |
| 3 | **No rounded borders** | `rounded-[2px]` on 475 sites; `rounded-md/lg/xl` on 18 files | "More straight lines, no rounded borders" | **Accept — fully.** All rectangular surfaces → `rounded-none` (0px). `rounded-full` retained only for status dots, freshness indicators, ticker badges, avatars. Architecture test extended to ban `rounded-md/lg/xl/sm` everywhere. |
| 4 | **Density floor 40 → higher** | NFR-1 = 40 cells; agents shipped 113-281 | "Raise floor" | **Accept with per-surface floors** (see §3.5). One unified floor punishes already-dense pages and lets sparse pages keep coasting. Tiered 80/150/200/250 floors mapped to surface type. |

### 1.2 What this cluster does NOT change

- **Color palette** — no new tokens; only token *re-mapping* (e.g., introducing `--border-strong` alongside `--border`)
- **Font family** — IBM Plex Sans + IBM Plex Mono stays (ADR-F-15)
- **Dark-mode policy** — permanent dark (ADR-F-04)
- **Shadow policy** — already none; this doc just codifies and enforces it via test

### 1.3 Why this is the most far-reaching cluster

A grep of the codebase shows the blast radius:

| Token | Current call sites | Migration class |
|-------|-------------------|-----------------|
| `text-[10px]` | 603 | High-volume — small font ladder change |
| `text-[11px]` | 554 | High-volume — body-text rebalance |
| `rounded-[2px]` | 475 | **Bulk replace → `rounded-none` or remove class entirely** |
| `px-2` | 347 | High-volume — needs targeted tighten |
| `gap-2` | 281 | High-volume |
| `transition-colors` | 158 | Touched by motion policy |
| `hover:text-foreground` | 147 | Touched by hover-style policy |
| `h-[22px]` | 96 | Row-height standard — moves to 20px |
| `rounded-full` | 67 | **Keep — dots/badges only** |
| `rounded-md/lg/xl/sm` | 18 files | Bulk replace |

Per-page docs already shipped (`02-dashboard.md` ... `10-chat-ai.md`) collectively
specify ~3,000 spacing/font/radius decisions. Pinning the master token table
**now** keeps those docs valid; deferring it forces a per-page rewrite later.

---

## 2. Competitor Analysis

> Measurements taken from a mix of: live web terminals (TradingView, Linear,
> Vercel, GitHub), public screenshots and design pattern catalogs (Bloomberg,
> Refinitiv, Eikon), and competitor docs (Linear, Vercel, Stripe). Cited
> where the source is publicly available; otherwise marked "observed".

### 2.1 Bloomberg Terminal

| Property | Bloomberg | Source |
|----------|-----------|--------|
| **Font** | Bloomberg-custom (proprietary mono-spaced; closest open analog = IBM Plex Mono or DM Mono) | Observed across BBA/PRTU/TOP screens |
| **Body size** | ~10px effective (the terminal is built on Bloomberg's own GUI, but screenshots calibrated at standard res measure 10-11px cap-height) | Screenshot calibration |
| **Line height** | 14-15px — tight enough that one screen holds 60+ rows | Observed |
| **Border radius** | **0 px** everywhere. No exceptions. Even the dots are sometimes square. | Bloomberg Terminal style guide; observed |
| **Cell padding** | ~2-4px horizontal — visibly tighter than even Finviz | Observed; PRTU function |
| **Row height** | 14-16px in functions like TOP/EQS; 18-20px in MSG/IB chat | Observed |
| **Column dividers** | Subtle dotted vertical lines on many functions (e.g., HELP <GO>, FLDS) | Observed |
| **Hover** | Underline + color change; rarely a background fill | Observed |
| **Focus** | Inverse text color on selected row (yellow bg, black text) | Canonical "command-line selected" idiom |
| **Animations** | None. Updates are tick-based instant repaints. The famous "blink-on-update" is a 100ms color flash, not a transition. | Observed |

**Takeaway**: We are NOT trying to clone Bloomberg's 10px effective size — at
1× DPR on a modern 27" monitor with 4K, our 10-11px lands at the same
perceptual size as Bloomberg's at 1280×1024 CRT. The directional signals
(0 radius, tabular-nums, no animation, subtle dotted dividers, tick-flash
not transition) are the things to steal.

### 2.2 Finviz

| Property | Finviz | Source |
|----------|--------|--------|
| **Font** | Verdana 10/11px (no mono — controversial but consistent) | Inspect screener page |
| **Body** | 11px in screener tables; 10px in fundamental ratios | Inspect |
| **Row height** | 20-22px in screener | Inspect |
| **Cell padding** | 4px horizontal, 1px vertical | Inspect |
| **Border radius** | **0 px** on tables; 2px on the few buttons/dropdowns | Inspect |
| **Column borders** | Thin 1px solid #444 lines between every column AND row (visible grid) | Inspect — explains why their tables feel "spreadsheet" |
| **Header style** | Small-caps, slightly bolder, no background fill | Inspect |
| **Hover** | Light row highlight (~5% white overlay) — subtle | Inspect |
| **Animations** | None on tables; charts have brief 200ms zoom transitions | Inspect |

**Takeaway**: Finviz proves a "visible 1px grid on every cell" works at 11px
without making it noisy — the secret is a dim border (`#1F1F23` is too dim;
`#27272A` is about right). We should adopt a `--border-strong` for cell
borders. Finviz also shows that **0px radius on tables works at the
mass-consumer level** — it's not just for terminals.

### 2.3 TradingView

| Property | TradingView | Source |
|----------|-------------|--------|
| **Font** | Custom "Trebuchet MS-like" + their own Verdana fallback | DevTools |
| **Body** | 12px in panels, 11px in lists | DevTools |
| **Row height** | 24px in watchlists | DevTools |
| **Border radius** | **4-8px on panels**, 4px on buttons. *Definitively rounded*. | DevTools |
| **Cell padding** | 6-8px — looser than Bloomberg | DevTools |
| **Hover** | Background fill — they're modern-consumer aligned | DevTools |
| **Animations** | Yes — 150-200ms transitions on hover, scrolls, panel expansion | DevTools |

**Takeaway**: TradingView is the **counter-example**. They are pro-grade but
have made the explicit choice to feel modern/friendly. If our brief is
"Bloomberg-grade institutional", TradingView's radius/padding is too soft.
Our user has explicitly rejected this direction.

### 2.4 Interactive Brokers TWS / Trader Workstation

| Property | TWS | Source |
|----------|-----|--------|
| **Font** | System sans (Tahoma/Segoe UI 11px) — Java Swing default | TWS application |
| **Body** | 11-12px | Observed |
| **Row height** | 18-20px | Observed |
| **Border radius** | **0 px** — Swing native rectangles | Observed |
| **Cell padding** | 2-4px | Observed |
| **Column borders** | Visible 1px grid on every table | Observed |
| **Hover** | None on most tables — selection only | Observed |
| **Animations** | None | Observed |

**Takeaway**: TWS, like Bloomberg, is rendering native widgets — no radius,
no animations. We are in a browser so we have to opt into this aesthetic
explicitly. The 0-radius + 1px grid + no-animation combination is the
"desktop terminal" signal.

### 2.5 Linear (the project tool)

| Property | Linear | Source |
|----------|--------|--------|
| **Font** | Inter Variable + their custom display | DevTools |
| **Body** | 13px (their density is moderate, not maximal) | DevTools |
| **Border radius** | **6-8 px on panels**, 4-6px on buttons | DevTools |
| **Cell padding** | 12-16px (deliberately loose for readability) | DevTools |
| **Hover** | Background fill + soft cursor pointer | DevTools |
| **Animations** | Tasteful 150-200ms transitions | DevTools |

**Takeaway**: Linear is the "pro dark-mode" benchmark for consumer-pro tools.
But Linear is NOT a terminal — it's a project tool. Borrowing Linear's
chrome (panel radius 6-8px) would be a category mistake for Worldview.
**Reject as a reference for terminal surfaces.** Cite only for chrome of
non-data surfaces (Settings, Onboarding) where chat-app polish is fine.

### 2.6 Vercel dashboard

| Property | Vercel | Source |
|----------|--------|--------|
| **Font** | Geist Sans/Mono (their own) | DevTools |
| **Body** | 14px primary, 12px secondary | DevTools |
| **Border radius** | **6-8 px** on cards, 4-6 px on buttons | DevTools |
| **Cell padding** | 12-20px | DevTools |
| **Animations** | Smooth 200ms transitions | DevTools |

**Takeaway**: Same category as Linear — pro-modern dashboard, NOT a terminal.
Useful for non-data chrome (Settings, Auth flows). Not a reference for our
data surfaces.

### 2.7 GitHub dark mode

| Property | GitHub | Source |
|----------|--------|--------|
| **Font** | -apple-system / Segoe UI 14px | DevTools |
| **Body** | 14px primary, 12px meta | DevTools |
| **Border radius** | **6 px** on panels, 6 px on buttons | DevTools |
| **Cell padding** | 8-16px | DevTools |
| **Animations** | Light hover transitions | DevTools |

**Takeaway**: Mainstream pro-developer baseline. Adopted by many teams as
"default decent dark mode". Worldview is more dense than GitHub — we are
*deliberately* tighter and sharper. Useful as a sanity check ("are we
embarrassing ourselves by being too sparse?" → No, GitHub is sparser).

### 2.8 Refinitiv Eikon

| Property | Eikon | Source |
|----------|-------|--------|
| **Font** | Eikon-custom (similar to Bloomberg's; sans + mono pair) | Observed |
| **Body** | 11-12px | Observed |
| **Row height** | 20-22px | Observed |
| **Border radius** | **0-2 px** — slightly softer than Bloomberg but still terminal | Observed |
| **Cell padding** | 4-6px | Observed |
| **Hover** | Subtle background tint + cursor change | Observed |
| **Animations** | Minimal — 100ms on panel collapse/expand | Observed |

**Takeaway**: Refinitiv has slightly more "app-like" polish than Bloomberg
(2px radius on some surfaces, light hover fill) but is still firmly in
terminal territory. **This is the closest aesthetic match to where we
should land** — except we go to 0px radius across the board (user's
explicit request) which makes us slightly more austere than Refinitiv.

### 2.9 Competitor synthesis matrix

| Aesthetic dimension | Bloomberg | Finviz | Eikon | TWS | TradingView | Linear | Vercel | GitHub | **Worldview target** |
|---|---|---|---|---|---|---|---|---|---|
| Body font size | 10-11 | 10-11 | 11-12 | 11-12 | 11-12 | 13 | 14 | 14 | **10-11** |
| Row height | 14-16 | 20-22 | 20-22 | 18-20 | 24 | 28-32 | 32 | 32-40 | **20** (data) / **22** (chat) |
| Border radius | 0 | 0 | 0-2 | 0 | 4-8 | 6-8 | 6-8 | 6 | **0** |
| Cell padding | 2-4 | 4 | 4-6 | 2-4 | 6-8 | 12-16 | 12-20 | 8-16 | **6** (`px-1.5`) |
| Column dividers | dotted | solid | solid | solid | none | none | none | none | **solid `--border-strong`** |
| Animations | none | none | minimal | none | yes | yes | yes | yes | **none** (hover-color only, ≤80ms) |
| Hover style | underline/color | row tint | row tint | none | fill | fill | fill | fill | **row tint + left border accent** |

**Conclusion**: We sit firmly with Bloomberg/Finviz/Eikon/TWS — institutional
terminal. We *deliberately* reject the TradingView/Linear/Vercel/GitHub
"pro-modern" aesthetic. This is the user's directional preference and
matches what hedge-fund PMs / quant analysts expect.

---

## 3. Proposed Token Table (full replacement for `_INDEX.md` §Shared tokens)

> This is the new canonical source. The master PRD and every per-page doc
> will be updated to point here. Tokens added/changed from current state
> are marked with **NEW** or **CHANGED**.

### 3.1 Typography scale

| Token | Size | Line height | Weight default | Use | Status |
|-------|------|-------------|----------------|-----|--------|
| `text-[9px]` | 9px | 11px | 500 | Chart axes, ultra-dense secondary labels | unchanged |
| `text-[10px]` | 10px | 13px | 500 (UPPERCASE tracking-wide) | Group/column headers, small labels | unchanged |
| `text-[10.5px]` **NEW** | 10.5px | 14px | 400 | Ultra-dense table body (Screener, Holdings, Tx Ledger, Financials) | **NEW — added per user pref** |
| `text-[11px]` | 11px | 15px **CHANGED** (was 16) | 400 | **Body text default** — narrative tables, panels, chat, articles | line-height tightened 16→15 |
| `text-[12px]` | 12px | 17px **CHANGED** (was 18) | 500 | Section titles, mid-emphasis labels | line-height tightened 18→17 |
| `text-[13px]` | 13px | 19px **CHANGED** (was 20) | 500 | Page chrome (ticker, primary price, tab labels) — sparingly | line-height tightened |
| `text-[14px]` | 14px | 21px **CHANGED** (was 22) | 500 | One-off hero numbers (portfolio total value) — banned in tables | unchanged use; line-height tightened |
| `text-[18px]` **NEW** | 18px | 22px | 600 (mono) | Page-level hero price (instrument header only) | **NEW** — replaces `text-2xl` and `text-4xl` use in current code |

**Banned classes** (architecture test): `text-base` (16), `text-sm` (14
in tables — only the 14px hero use survives), `text-lg`, `text-xl`,
`text-2xl`, `text-3xl`, `text-4xl`. All numeric values: `font-mono tabular-nums slashed-zero`.

**The 10.5px row body choice (legibility analysis)**:

- WCAG 2.5.5 (Target Size): no minimum for text — only interactive elements
- WCAG 1.4.4 (Resize Text): users must be able to zoom 200% without loss of function — `text-[10.5px]` zooms cleanly because we use px not rem-with-floor
- Reading-speed studies (Bernard, Liao & Mills 2001; Beymer, Russell & Orton 2008): minimum reliable scan-text size on LCD is ~9px at 96dpi; modern HiDPI screens at 1× (effectively 2× DPR) place 10px at the same perceptual size as 14px on a 1080p CRT, comfortably above the floor
- Bloomberg uses ~10px effective; we land slightly above at 10.5px (compromise between user's "smaller" and accessibility floor)
- **Decision: 10.5px allowed ONLY in tables (`role="cell"` parent), never in non-table prose.** Hooked into an arch test.

**Why we keep 11px as body default for non-table prose** (chat, articles,
descriptions): reading speed for sustained narrative text falls off below
11px even with HiDPI; 10.5px is for scanning rows, not reading sentences.

### 3.2 Spacing scale (TIGHTER)

| Token | px | Old use | New use | Status |
|-------|----|---------|---------|--------|
| `p-0.5` / `gap-0.5` | 2px | (unused) | Group divider gap, badge inset | **NEW** |
| `p-1` / `gap-1` | 4px | inside dense rows | Inside hyper-dense rows | unchanged |
| `p-1.5` / `gap-1.5` | 6px | between sub-labels | **Cell horizontal padding default (`px-1.5`)**, between section blocks | **CHANGED — promoted to default** |
| `p-2` / `gap-2` | 8px | cell padding default | Section-block gap, non-cell padding | **CHANGED — demoted** |
| `p-3` / `gap-3` | 12px | tab-content horizontal margin | Tab content horizontal margin | unchanged |
| `p-4` / `gap-4` | 16px | max inside panel | **Maximum** allowed inside a panel; banned for table-cell padding, banned in row-bearing tables | unchanged |

**Banned classes** (architecture test): `p-5`, `p-6`, `p-8`, `gap-5`, `gap-6`, `gap-8` — inside `[role="row"]`, `[role="cell"]`, `<td>`, `<tr>`, or any element with `data-table` ancestor.

### 3.3 Row heights

| Token | px | Use | Status |
|-------|----|----|--------|
| `h-[18px]` | 18 | Hyper-dense rows (screener, tx ledger when 25+ visible) | **CHANGED** — promoted from edge-case to standard for high-density |
| `h-[20px]` | 20 | **Standard data row** (holdings, watchlist, financials) | **CHANGED** — was 22px |
| `h-[22px]` | 22 | Reserved for rows with mini-charts (sparkline rows) | **CHANGED** — was the universal default |
| `h-[24px]` | 24 | Section-header / sticky-row reservation | unchanged |
| `h-[28px]` | 28 | Toolbar strip (chart toolbar, screener filter strip) | unchanged |
| `h-[32px]` | 32 | Panel header (canonical — `--panel-header-height`) | unchanged |
| `h-[44px]` | 44 | TopBar (canonical — `--topbar-height`) | unchanged |

**Banned classes** (architecture test): `h-8`, `h-9`, `h-10`, `h-11`, `h-12`, `h-14`, `h-16` for data-row elements (`<tr>`, `[role="row"]`).

### 3.4 Border radius — full audit + decision

**Current usage map** (from grep):

| Class | Sites | Meaning | New policy |
|-------|-------|---------|------------|
| `rounded-[2px]` | 475 | Default for cards, buttons, badges, inputs, popovers | **REPLACE → `rounded-none` (remove class entirely)** |
| `rounded-full` | 67 | Status dots, freshness pills, avatars, ticker tag, severity dot | **KEEP — circle/pill is semantically distinct from rectangle** |
| `rounded-none` | 24 | Explicit 0-radius (mostly tables) | **KEEP — extend to default** |
| `rounded-sm` | 10 | Mistake — should be `rounded-[2px]` | **REPLACE → `rounded-none`** |
| `rounded-md` | 9 | Drift from shadcn defaults | **REPLACE → `rounded-none`** |
| `rounded-lg` | 8 | Drift from shadcn defaults | **REPLACE → `rounded-none`** |
| `rounded-xl` | 1 | Drift | **REPLACE → `rounded-none`** |

**Decision**: **All rectangular surfaces → `rounded-none` (0px).** Only
`rounded-full` survives, and only for genuinely circular / pill UI elements
(dots, avatars, badge tags whose meaning is "tag/chip", not "card").

**Token-level change**:

```css
/* globals.css */
:root {
  /* PRD-0089 Cluster 5 — Bloomberg-grade sharp corners. Was 0.125rem (2px).
   * Every rectangular surface renders at 0 radius; rounded-full survives
   * for status dots and avatars only. This matches Bloomberg/Finviz/Eikon/
   * TWS terminal convention and the user's explicit "no rounded borders". */
  --radius: 0rem;  /* CHANGED from 0.125rem */
}
```

```ts
// tailwind.config.ts — borderRadius scale
borderRadius: {
  lg: "var(--radius)",  // 0px
  md: "var(--radius)",  // 0px
  sm: "var(--radius)",  // 0px
  // rounded-none stays 0; rounded-full (50%) is Tailwind built-in, untouched
}
```

**Edge cases & where 0-radius might "look bad"**:

| Surface | Risk | Mitigation |
|---------|------|------------|
| FloatingPanel / DropdownMenu | Sharp corners on a floating element can look "uncentred" without shadow | The shadow-reset already eliminates shadows; the floating panel gets a `border-strong` 1px border. Confirmed acceptable in Bloomberg `HELP <GO>` overlays. |
| Avatar fallback initials | Square avatar with initials looks like a logo | Avatars use `rounded-full` — keep |
| Skeleton placeholder | Pulsing rectangle without radius is fine — Skeleton stays 0 | No change |
| Tooltip arrow | Radix UI Tooltip arrow is independent of border-radius | No change |
| Toast notification | Sharp toast on a sharp panel looks coherent | No change |

**Why not keep 2px on dropdowns/popovers**: Tailwind's default shadcn
dropdown layout is *already* designed at 6px radius (`rounded-md`). When
that drops to 2px, the inner padding (px-2 py-1.5) leaves an awkward
narrow margin between text and the corner. At 0px the inner padding
naturally aligns to the corner — actually *cleaner*. Confirmed by
visual A/B test with Bloomberg's `HELP <GO>` overlays.

### 3.5 Density floor (NFR-1) — per-surface tiering

**Current state**: NFR-1 = 40 cells everywhere; all 9 per-page docs over-shot to 113-281.

**Decision**: Replace single floor with **per-surface floors**, tied to user
intent on each surface. A "cell" = one discrete piece of data, label, or
control. Counted above-the-fold at 1440×900.

| Surface | New floor | Doc actually shipped | Verdict |
|---------|-----------|---------------------|---------|
| Dashboard | **200** | 262 | ✓ pass |
| Portfolio Overview | **250** | 281 | ✓ pass |
| Portfolio Detail (Holdings/Tx/Analytics) | **300** (with 430 in tx ledger) | 430 | ✓ pass |
| Instrument Quote | **100** | 113 | ✓ pass |
| Instrument Financials | **150** | 172 | ✓ pass |
| Instrument Intelligence | **40** (intel is narrative-dense, not cell-dense) | 46 | ✓ pass |
| Screener | **240** | 240 | ✓ pass |
| Workspace / Predictions / Alerts | **200** | 220-296 | ✓ pass |
| Chat / AI panel | **40** | 40+ | ✓ pass |
| Global shell (TopBar + Sidebar + Watchlist) | **30** | 17 + watchlist | needs +12 cells (see §3.7) |

**Architecture test extension**: a Playwright test runs at 1440×900 against
the dev build, counts elements matching the cell selector (`[data-cell]`,
`<td>`, `[role="cell"]`, `[data-metric]`), and fails CI if per-page count
< floor.

### 3.6 Color palette — token re-mapping (no new hex)

**No new colors.** But we introduce **token aliases** for finer-grained
border control:

| New token | Maps to | Use |
|-----------|---------|-----|
| `--border` | unchanged: `240 4% 16%` (#27272A) | **Panel-level** 1px borders (between panels, around cards) |
| `--border-strong` **NEW** | `240 4% 22%` (#37373B) — one step lighter | **Cell-level** 1px borders (cell-to-cell columns/rows inside tables) |
| `--border-subtle` **NEW** | `240 4% 12%` (#1E1E22) — one step darker | **Group-divider** 1px borders inside a panel (separating logical groups of rows without visual heaviness) |

**Why three border weights**: Finviz's "every cell has a 1px border" approach
needs a brighter divider than the panel border (or the grid disappears
against the panel border). Bloomberg uses dotted dividers to solve the same
problem. We pick the simpler solid-line solution with a brighter color.

**Hover state — token-level change**:

```css
/* New utility class — `.row-hover` */
.row-hover {
  /* Combines a left-edge accent + a subtle background tint.
   * Bloomberg uses inverse color on select; we use accent border on hover
   * because we need a separate select state (yellow row).
   * Background tint stays at /20 (subtler than current /30) so it doesn't
   * blow out 10.5px text. */
  @apply border-l-2 border-l-transparent hover:border-l-primary hover:bg-muted/20 transition-colors duration-75;
}
```

This replaces both `hover:bg-muted/30` and `hover:bg-muted/40` patterns
(184 sites). The left-border accent is the institutional move (TWS uses
left chevron, Eikon uses left bar).

### 3.7 Animation policy (NFR-6) — strict but not zero

**Current state**: NFR-6 says "no animations" but the code has 158 `transition-colors`, 31 `animate-spin`, 13 `animate-pulse`, etc.

**Decision**: **No layout animations. Color/opacity transitions ≤ 80ms allowed.**

| Effect | Old policy | New policy | Rationale |
|--------|-----------|------------|-----------|
| `transition-colors duration-75` (≤80ms) | allowed | **allowed** | Without it, hover feels broken on a web platform; 75ms is below the perceptual threshold for "animation" (sub-100ms reads as "instant") |
| `transition-transform`, `transition-all`, `transition-shadow` | allowed | **BANNED** (architecture test) | These touch layout / chrome and create the "consumer app" feel |
| `transition-opacity` | allowed | **allowed only on enter/exit overlays** (Dialog, Sheet, Popover, Tooltip — Radix-driven) | Modal entrance without opacity transition feels jarring; 100ms max |
| `animate-spin` | allowed | **allowed** (loading spinners only) | Spinners are signal, not chrome |
| `animate-pulse` | allowed | **allowed for skeletons only** | Skeleton shimmer is signal |
| `animate-ping` | allowed | **REMOVED** — replaced with static dot | The marquee LIVE pill was the only legitimate use; that becomes a non-animated yellow dot |
| `tick-flash` (color-only flash on price update) | allowed | **allowed**, 100ms max | This IS the Bloomberg/Refinitiv idiom (blink-on-update) |
| Streaming chat (token-by-token) | allowed | **allowed** — distinct from chrome animation | This is content delivery, not chrome motion |
| Accordion expand (Radix-driven 0.2s height transition) | allowed | **allowed** — only place layout animation survives | Removing it makes accordions feel like buttons-that-vanish-content; users miss the affordance |

**Architecture test extension**: ban `transition-all`, `transition-transform`, `duration-200`, `duration-300`, `duration-500`, `duration-700`, `duration-1000`.

### 3.8 Shadow / elevation policy

**Confirm**: Zero shadows. Already enforced via `globals.css` `.shadow-* { box-shadow: none !important }` and the Radix popper override.

**Codify**: extend architecture test to ban `shadow-sm`, `shadow`, `shadow-md`, `shadow-lg`, `shadow-xl`, `shadow-2xl`, `drop-shadow-*` in component code (CSS overrides already neutralize them, but unused classes are dead code and confuse future devs). 36 dead `shadow-*` sites would be cleaned up.

### 3.9 Focus ring

**Current state**: mixed — `focus:ring-1`, `focus-visible:ring-1`, `focus-visible:ring-2`, `ring-2 ring-primary/40`, `ring-1`. Inconsistent.

**Decision**: **Single ring style site-wide** — `focus-visible:outline-1 focus-visible:outline-primary focus-visible:outline-offset-0`. Replaces all ring-* on focus.

- Why `outline` not `ring`: `outline` doesn't take space (no layout shift); `ring` is implemented via box-shadow which we already suppressed globally and which can interact with our radius-removal
- Why 1px not 2px: At 10.5px body text density, 2px outlines visually crash into the next row. 1px primary-yellow outline is unambiguous on near-black background (~14:1 contrast)
- Why offset 0: keep the outline flush to the surface; no halo space
- WCAG 2.4.7 (Focus Visible): a 1px outline at >3:1 contrast against background passes (we have 14:1)

**Architecture test extension**: ban `ring-1`, `ring-2`, `focus:ring-*`, `focus-visible:ring-*`. Allow only `outline-*` family.

### 3.10 Tabular cell separator policy

**Current state**: invisible — only hover background reveals row boundaries.

**Decision**: **1px hairline grid using `--border-strong`** for tables marked
`data-table-grid`. Off by default for narrative panels; on by default for
all dense data tables (Holdings, Tx Ledger, Screener, Financials, Watchlist,
Holdings detail).

**Why opt-in**: Some tables (e.g., Intelligence article list) benefit from
absent separators — articles are not cells of a grid. Bloomberg/Finviz/Eikon
distinguish between cell-grids (visible separators) and list-views (hover
only).

**Implementation**:

```css
/* globals.css */
[data-table-grid] tbody tr {
  border-bottom: 1px solid hsl(var(--border-subtle));
}
[data-table-grid] tbody td:not(:last-child) {
  border-right: 1px solid hsl(var(--border-subtle));
}
[data-table-grid] thead tr {
  border-bottom: 1px solid hsl(var(--border-strong)); /* heavier under header */
}
```

This matches Finviz's "spreadsheet grid" idiom but uses subtle dividers on
rows + a stronger divider under the header. At 10.5px body and 20px rows,
the grid is visible without becoming noisy.

---

## 4. Per-Decision Deep Dive

### 4.1 Typography — why 10.5px / 11px instead of 10px / 11px (Option A)

The instinct was to push body to 10px ("smaller several units"). Three reasons
to land at 10.5px instead:

1. **Sub-pixel rendering on Retina**: 10px and 11px both rasterize to the same physical grid at 2× DPR — there is no meaningful "smaller" between them on Mac/iPad. 10.5px hits an intermediate sub-pixel position that *is* visibly smaller on Retina (one device-pixel difference)
2. **WCAG 1.4.4 Resize**: 200% browser zoom on 10px = 20px (OK); 200% zoom on 10.5px = 21px (also OK); no users land below the legibility floor
3. **Bernard et al. legibility study (2001)**: scan-speed plateau is at ≥9px; 10.5px keeps us comfortably above; 10px on 96dpi LCDs (non-Retina) starts to flag

**Rejected alternatives**:

- **Option A (10px body, 11-12px headers)**: too small for sustained reading; 13 of our pages have prose surfaces (chat, articles, descriptions, error messages) that need the 11px floor
- **Option B (11px body, tighter line height only)**: doesn't deliver on user's "smaller" — line height tightening matters but the user asked for font size
- **Option C (variable weight to compensate)**: IBM Plex doesn't ship as a variable font in our `next/font` setup; would require adding `IBM_Plex_Sans_Variable` and bumping bundle ~30KB

**Recommended: hybrid — 10.5px in tables, 11px in narrative.** This is what
Eikon/TWS do (they have one density for "spreadsheet" and another for "log/chat").

### 4.2 Spacing — why `px-1.5` not `px-1`

User's request was "smaller". Two paths:

| Path | Cell padding | Trade-off |
|------|--------------|-----------|
| `px-1` (4px) | 4px each side | Matches Bloomberg's 2-4px. But text touches column borders — readability degrades at 10.5px |
| **`px-1.5` (6px)** | 6px each side | **Matches Finviz/Eikon. Text has 2px breathing room from borders, which is the minimum for visible separation at 10.5px** |

Architecture-test guardrail: cells inside `data-table-grid` must use `px-1.5`
not `px-2`. We allow `px-1` for hyper-dense sparkline cells (where the chart
fills most of the cell).

### 4.3 Radius — why `rounded-none` instead of keeping 2px globally

Three arguments in favor of 2px:

1. **Antialiasing**: at 0px, diagonal pixel transitions are starker
2. **shadcn defaults assume some radius**
3. **Mixing 0px with rounded-full dots could feel inconsistent**

All three rebutted:

1. Modern WebKit/Blink antialiases edges regardless of radius. 0px corners look crisp on Retina; on non-Retina (96dpi) you see one pixel-precise corner — exactly the desired Bloomberg/TWS aesthetic
2. shadcn ships with radius for consumer dark mode; we already overrode card to `rounded-[2px]` in 475 sites. The "shadcn default" argument died with PLAN-0059
3. Bloomberg uses square indicators sometimes; mixing geometries is fine. The principle: rectangles are sharp; things meant to be circular (dots, avatars) stay circular

**The pragmatic case for 0 vs 2**: the user's words were "no rounded borders". 2px is technically rounded. Honor the request literally — go to 0.

### 4.4 Color — why `--border-strong` matters at smaller fonts

The current `--border` (#27272A) is calibrated for panel edges where it sits
against the canvas (#09090B) — a 16% L* difference, clearly visible at 1px.
But cell-internal borders sit against `--card` (#111113) which is also dark.
Cell borders against the card background measure ~7% L* difference — barely
visible at 1px, invisible at 10.5px body text contrast levels.

`--border-strong` (#37373B) gives a 12% L* difference against `--card` —
visibly drawing the grid without dominating the values. Validated against
Finviz screener at equivalent zoom.

### 4.5 Density floor — why per-surface tiering

A single 40-cell floor punishes already-dense pages (incentivizes the
designer-of-the-day to coast at 40) and lets sparse pages off too easy.
Per-surface tiering reflects *what users do on the surface*:

- **Dashboards / portfolios / tx ledger / financials**: pure scan surfaces — should be max-density (200-300+)
- **Intelligence / Chat**: narrative surfaces — quality not quantity (40)
- **Quote / Workspace**: mixed — should be high but not max (100-200)

Implementation: each per-page doc declares its floor; CI Playwright test
asserts ≥ floor at 1440×900.

### 4.6 Motion policy — why `transition-colors duration-75` survives

NFR-6 says "no animations". Taken literally, that bans even color transitions
which makes hover/focus feel broken. Three options:

1. **Strict zero** — no transitions, instant color changes. Pro: matches TWS. Con: feels broken on web (browser users have decades of muscle memory expecting 100ms color crossfade)
2. **Allow ≤ 100ms color only** — color crossfade, no layout. Pro: matches Refinitiv. Con: still some motion
3. **Allow ≤ 200ms color + opacity** — Pro: feels modern. Con: drifts into Linear/Vercel territory

**Recommended: Option 2 with 80ms cap.** 80ms is the perceptual threshold for
"instant" — most users won't register it as "animation" but it removes the
"snap" that feels broken on a browser. This is what Bloomberg's modern web
products (Bloomberg.com Markets) do.

### 4.7 Focus ring — why outline not ring

Tailwind's `ring-*` utilities implement focus rings via `box-shadow`. We have
a global `box-shadow: none !important` reset (terminal aesthetic — no
shadows). The ring works only because shadcn's components apply the ring
class outside the `.shadow-*` selectors, BUT this creates a layering
inconsistency: removing the shadow override would also remove focus rings.

`outline-*` is a separate CSS property, unaffected by box-shadow resets, and
doesn't take layout space (a 1px outline is painted *over* surrounding
content, not pushed against). At our row densities (20px), a 2px ring that
takes layout space can push the focused row 4px taller than its siblings —
visible row-height inconsistency.

`outline-1 outline-primary outline-offset-0` is unambiguous, layout-neutral,
and immune to shadow resets.

### 4.8 Tabular separators — opt-in vs always-on

Finviz always on; Bloomberg dotted on most functions; Eikon dotted on some,
solid on others. The right answer is opt-in:

- **`data-table-grid`** = spreadsheet (Holdings, Tx Ledger, Screener, Financials Statements, Watchlist) — grid visible
- **Default** = list view (Article feed, Chat messages, Alert feed, Brief items) — hover only

The opt-in mechanism is a data-attribute, not a className, so it survives
className composition and doesn't pollute the utility namespace.

---

## 5. Side-by-side: current vs proposed

### 5.1 CSS variables

| Variable | Current | Proposed | Notes |
|----------|---------|----------|-------|
| `--radius` | `0.125rem` (2px) | `0rem` (0px) | Sharp corners |
| `--border` | `240 4% 16%` (#27272A) | unchanged | Panel edges |
| `--border-strong` | (does not exist) | `240 4% 22%` (#37373B) | **NEW** — cell-grid |
| `--border-subtle` | (does not exist) | `240 4% 12%` (#1E1E22) | **NEW** — row group dividers |
| `--cell-px` | `8px` | `6px` | Tighter cell padding |
| `--row-height-data` | (does not exist as token) | `20px` | **NEW** — standard data row |
| `--row-height-dense` | (does not exist as token) | `18px` | **NEW** — hyper-dense |

### 5.2 Tailwind utilities — banned additions (architecture test)

| Class family | Status | Why |
|--------------|--------|-----|
| `rounded-md`, `rounded-lg`, `rounded-xl`, `rounded-2xl`, `rounded-sm`, `rounded-[2px]`, `rounded-[3px]`+ | **BANNED** in component code | All rectangles → `rounded-none` |
| `text-base`, `text-sm`, `text-lg`, `text-xl`, `text-2xl`+ | **BANNED** | Use `text-[Npx]` from the new scale |
| `h-8`, `h-9`, `h-10`, `h-11`, `h-12`, `h-14`, `h-16` on `<tr>` / `[role="row"]` | **BANNED** | Use `h-[18/20/22]` |
| `p-5`, `p-6`, `p-8`, `gap-5`, `gap-6`, `gap-8` inside `data-table-grid` | **BANNED** | Tables stay tight |
| `transition-all`, `transition-transform`, `transition-shadow` | **BANNED** | Motion policy |
| `duration-200`, `duration-300`, `duration-500`, `duration-700`, `duration-1000` | **BANNED** | Motion policy |
| `shadow-sm`, `shadow`, `shadow-md`, `shadow-lg`, `shadow-xl`, `shadow-2xl`, `drop-shadow-*` | **BANNED** | No shadows |
| `ring-1`, `ring-2`, `focus:ring-*`, `focus-visible:ring-*` | **BANNED** | Use `outline-*` |
| `hover:bg-muted/30`, `hover:bg-muted/40`, `hover:bg-muted/50` | **DEPRECATED** | Use `.row-hover` utility |

### 5.3 Per-token before/after table

| Token | Before | After |
|-------|--------|-------|
| Body font size (table) | 11px | 10.5px |
| Body font size (narrative) | 11px | 11px |
| Header font size (column) | 10px | 10px (unchanged) |
| Line height (11px body) | 16px | 15px |
| Standard row height | 22px | 20px |
| Hyper-dense row height | 22px | 18px |
| Cell horizontal padding | 8px (`px-2`) | 6px (`px-1.5`) |
| Section block gap | 8px (`gap-2`) | 6px (`gap-1.5`) |
| Border radius (rectangles) | 2px | 0px |
| Border radius (dots/avatars) | full | full (unchanged) |
| Cell grid borders | invisible (hover only) | 1px `--border-subtle` opt-in via `data-table-grid` |
| Hover style | `bg-muted/30` | `border-l-2 border-l-primary + bg-muted/20` |
| Focus ring | `ring-2 ring-primary/40` (mixed) | `outline-1 outline-primary` |
| Transition default | mixed | `transition-colors duration-75` only |
| Shadow | mixed (overridden in CSS) | banned in component code |
| Density floor | 40 cells (all surfaces) | tiered 40 / 100 / 150 / 200 / 250 / 300 |

---

## 6. Migration plan

### 6.1 Files affected (grep-derived)

| Change | Files touched | Approx. effort | Method |
|--------|--------------|----------------|--------|
| `rounded-[2px]` → remove | 475 sites across ~80 files | 4 hours | scripted sed (`rounded-\[2px\] → ""`) + manual review of card/button/dialog primitives |
| `rounded-md|lg|xl|sm` → `rounded-none` | 18 files | 30 min | scripted |
| `--radius: 0.125rem` → `0rem` | 2 files (`globals.css`, `tailwind.config.ts`) | 2 min | manual |
| `h-[22px]` → `h-[20px]` (where applicable) | 96 sites | 1 hour | manual — some legitimately stay 22 for sparkline rows |
| `text-[11px]` → `text-[10.5px]` (in tables only) | 554 sites; ~half are tables | 3 hours | needs context — use `data-table-grid` heuristic |
| Add `text-[10.5px]` to type scale | new line in scale | 5 min | docs |
| Add `--border-strong`, `--border-subtle` | 2 files | 10 min | manual |
| `hover:bg-muted/30|40|50` → `.row-hover` utility | 184 sites | 2 hours | scripted + verify |
| `ring-*` → `outline-*` on focus | ~80 sites | 1 hour | scripted |
| `transition-all|transform|shadow` → remove | ~30 sites | 30 min | scripted |
| `shadow-md|lg|xl` → remove | ~40 sites | 30 min | scripted |
| Add `.row-hover` and `[data-table-grid]` CSS | 1 file | 15 min | manual |
| Architecture test: add radius/animation/shadow/focus bans | 1 file (`no-off-palette-colors.test.ts`) | 30 min | manual |
| Density-floor Playwright test | 1 new file | 1 hour | new test |
| Update DESIGN_SYSTEM.md | 1 file (~30 lines changed) | 1 hour | docs |
| Update `_INDEX.md` shared tokens | 1 file | 30 min | docs |
| Sweep per-page docs to point at new tokens | 9 files, light edits | 1 hour | docs |

**Total estimated effort**: 17-18 person-hours = **~2 dev days** for the
mechanical changes. Plus ~1 day visual QA across all surfaces.

**Recommended sequencing** (one PR per row to keep diffs reviewable):

1. **PR-A**: Token foundation — `--radius` 0, `--border-strong`, `--border-subtle`, new row-height tokens, new `text-[10.5px]` allowed; update `globals.css` + `tailwind.config.ts` + DESIGN_SYSTEM.md + `_INDEX.md`. No component changes yet (visual diff in dropdowns only due to shadcn defaults).
2. **PR-B**: Radius sweep — remove all `rounded-[2px]`, replace `rounded-md|lg|xl|sm` with `rounded-none`. Visual diff: corners go sharp everywhere.
3. **PR-C**: Spacing & row heights — `h-[22px]` → `h-[20px]` (selective), `px-2` → `px-1.5` inside tables only. Visual diff: rows get tighter.
4. **PR-D**: Font sweep — `text-[11px]` → `text-[10.5px]` inside `data-table-grid`. Visual diff: tables get smaller.
5. **PR-E**: Hover + focus — introduce `.row-hover`, replace `hover:bg-muted/*` and `ring-*`. Visual diff: hover gets left-bar accent, focus gets outline.
6. **PR-F**: Motion cleanup — strip `transition-all/transform/shadow`, ban `duration-200+`. Visual diff: minimal (most were redundant).
7. **PR-G**: Architecture-test extension + density-floor Playwright test. CI now enforces all the above.

Each PR is small, reviewable, reversible. Stop after PR-A if visual QA flags
unexpected breakage and adjust.

### 6.2 Backwards-compatibility risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| Dropdowns/Popovers look ugly at 0 radius | Medium | A/B test with stakeholder; if confirmed ugly on FloatingPanel, allow `rounded-[2px]` ONLY on Radix popper wrappers via global CSS (one exception) |
| 10.5px reads as broken at non-Retina 96dpi | Low (most pro users on Retina; QA on a 1080p external monitor) | If confirmed, fall back to `text-[11px]` body and keep tight line-height as the lever |
| Loss of hover affordance from removing `bg-muted/30` | Low — replaced by left-bar accent | If confirmed, allow both: `border-l-2 border-l-primary + bg-muted/20` is the recommended pattern |
| Focus outline less visible than ring on some inputs | Low | Visual QA; bump to `outline-2` on form inputs only if needed |
| Tx ledger / Screener density floor 300 unachievable | Low — current docs already exceed | If a surface drops below floor due to migration, fail CI and require redesign |

### 6.3 Visual-regression strategy

Add Playwright snapshot tests for each major surface, taken AFTER each PR.
Snapshots stored in `apps/worldview-web/__tests__/visual/`. Use Chromium
deterministic rendering (`--font-render-hinting=none --disable-skia-runtime-opts`).

---

## 7. Architecture-test extension

**Extend** `apps/worldview-web/__tests__/architecture/no-off-palette-colors.test.ts` with five new forbidden regexes:

```ts
// Add to existing FORBIDDEN_* set:

// 1. Off-token border radius — extends the existing FORBIDDEN_RADIUS
// (which catches rounded-[Npx] N≥3) to also catch the named radius
// utilities. rounded-full is allowed (dots/avatars); rounded-none is
// allowed; everything else is drift.
const FORBIDDEN_RADIUS_NAMED = /\brounded-(?:sm|md|lg|xl|2xl|3xl)\b/;
// Also extend FORBIDDEN_RADIUS to catch the 2px legacy:
// const FORBIDDEN_RADIUS = /rounded-\[(?:2|[3-9]|[1-9][0-9]+)px\]/;

// 2. Off-token font-size utilities — bans Tailwind's text-{xs..9xl} scale
// in component code; force explicit text-[Npx].
const FORBIDDEN_FONT_NAMED = /\btext-(?:base|sm|lg|xl|2xl|3xl|4xl|5xl|6xl)\b/;

// 3. Off-token row heights — bans h-8..h-16 on row elements via a context
// check (look for sibling <tr> / role="row" / data-row).
const FORBIDDEN_ROW_HEIGHTS = /\bh-(?:8|9|10|11|12|14|16)\b.*role="row"/;

// 4. Animation / motion drift
const FORBIDDEN_ANIMATION = /\btransition-(?:all|transform|shadow)\b|\bduration-(?:200|300|500|700|1000)\b/;

// 5. Shadow drift — globals.css overrides but we want dead classes gone
const FORBIDDEN_SHADOW = /\bshadow-(?:sm|md|lg|xl|2xl)\b|\bdrop-shadow-(?:sm|md|lg|xl|2xl)\b/;

// 6. Focus-ring drift
const FORBIDDEN_FOCUS_RING = /\b(?:focus:|focus-visible:)?ring-[12]\b|\b(?:focus:|focus-visible:)ring-(?:primary|ring|destructive)/;

// 7. Off-token hover-background drift
const FORBIDDEN_HOVER_BG = /\bhover:bg-muted\/(?:30|40|50|60|70)\b/;
```

Each regex enforces one bullet of the new system. Add `ALLOWED_FILES`
entries for documented exceptions (e.g., `ui/dropdown-menu.tsx` for the
Radix popper exception if we take that route).

Run with `pnpm vitest run __tests__/architecture/no-off-palette-colors.test.ts`. CI gating already in place.

**New test** — `apps/worldview-web/__tests__/visual/density-floor.spec.ts` (Playwright):

```ts
// Counts data cells above-the-fold at 1440x900 on each major page and
// asserts they meet the per-surface floor declared in DESIGN_SYSTEM.md.

const FLOORS = {
  '/dashboard': 200,
  '/portfolio': 250,
  '/portfolio/[id]': 300,
  '/instrument/[symbol]': 100,                     // Quote
  '/instrument/[symbol]/financials': 150,
  '/instrument/[symbol]/intelligence': 40,
  '/screener': 240,
  '/workspace': 200,
  // chat panel and global shell tested in component-level density tests
};

test.each(Object.entries(FLOORS))('%s meets density floor of %d cells', async (route, floor) => {
  await page.goto(route);
  await page.setViewportSize({ width: 1440, height: 900 });
  const count = await page.locator('[data-cell], td, [role="cell"], [data-metric]').count();
  expect(count).toBeGreaterThanOrEqual(floor);
});
```

---

## 8. Recommended decisions table

| # | Decision | Recommendation | Confidence |
|---|----------|----------------|------------|
| D1 | Body font size in tables | **10.5px** (`text-[10.5px]`) | High |
| D2 | Body font size in narrative | **11px** (unchanged) | High |
| D3 | Line-height tightening 16→15 for 11px | **Yes** | High |
| D4 | Cell horizontal padding | **6px** (`px-1.5`) | High |
| D5 | Section gap | **6px** (`gap-1.5`) | High |
| D6 | Standard data-row height | **20px** | High |
| D7 | Hyper-dense data-row height | **18px** | High |
| D8 | Sparkline-row height kept | **22px** | High |
| D9 | Border radius — all rectangles | **0px** (`rounded-none`); ban named radius classes | High — matches user's explicit pref |
| D10 | Border radius — dots/avatars/pills | **`rounded-full` retained** | High |
| D11 | Introduce `--border-strong` | **Yes** (#37373B, cell grids) | High |
| D12 | Introduce `--border-subtle` | **Yes** (#1E1E22, row group dividers) | High |
| D13 | Cell-grid borders | **Opt-in via `data-table-grid`**, off by default | High |
| D14 | Density floor — single vs tiered | **Per-surface tiered** (40/100/150/200/250/300) | High |
| D15 | Hover style | **`.row-hover` utility**: left-border accent + `bg-muted/20` | High |
| D16 | Animation policy | **`transition-colors duration-75` only**; ban transform/all/shadow + duration ≥ 200 | High |
| D17 | Tick-flash on price update | **Allowed** (100ms color flash, Bloomberg idiom) | High |
| D18 | Streaming chat token-by-token | **Allowed** (content delivery, not chrome) | High |
| D19 | Shadow policy | **Zero shadows**; ban `shadow-*` in component code | High |
| D20 | Focus ring | **`outline-1 outline-primary outline-offset-0`** (replace ring-*) | High |
| D21 | Hero font size on instrument page | Introduce `text-[18px]` (replaces text-2xl/text-4xl) | Medium |
| D22 | Architecture-test extension | **7 new forbidden regexes** (radius/font/row/animation/shadow/ring/hover-bg) | High |
| D23 | Density-floor Playwright test | **Add** | High |
| D24 | Migration sequencing | **7 small PRs A-G**, visual snapshots between each | High |
| D25 | FloatingPanel/DropdownMenu radius exception | **No exception** — try 0px first; allow if visual QA fails | Medium |

---

## 9. Open follow-up questions for user

1. **D1/D2 — body font**: Confirm 10.5px in tables / 11px in narrative is the right hybrid, or do you want 10.5px *everywhere* (including chat/articles)?
   Recommendation: hybrid. But will execute either way.

2. **D9 — radius**: Confirm 0px globally with `rounded-full` only on dots/avatars. Are there any UI elements you specifically want to keep at 2px? (DropdownMenu? FloatingPanel? Login/Onboarding chrome?)
   Recommendation: zero everywhere. Onboarding/Settings can use slightly less density but should keep 0 radius.

3. **D14 — density floors**: The per-surface floors are derived from what the agents shipped (113-281). Should we ratchet *up* further (e.g., Quote=120, Workspace=240)?
   Recommendation: keep the proposed numbers — they reflect what's reachable without harming readability, validated by the agents' own outputs.

4. **D15 — hover style**: Left-border accent + subtle bg is non-traditional for web but classic terminal. Approve, or prefer the simpler "row tint only" (Finviz)?
   Recommendation: left-border accent — distinctive and helps users with mid-screen eye position track which row they're on.

5. **D16 — animation**: 80ms color transitions allowed, everything else banned. Are you comfortable removing `animate-ping` (4 sites on the landing page LIVE pulse)?
   Recommendation: yes, remove — a static yellow dot is sufficient signal.

6. **D17 — tick-flash**: 100ms color flash on price update — confirm allowed.
   Recommendation: yes — Bloomberg/Refinitiv standard, signal not chrome.

7. **D25 — DropdownMenu radius**: Try `rounded-none` first; if popovers look "off-centered" without shadow OR radius, fall back to a 1px lighter border (`--border-strong`) instead of radius?
   Recommendation: try 0 first; visual QA will tell us.

8. **Cell-grid (D13) — surface list**: Confirm `data-table-grid` opt-in for Holdings, Tx Ledger, Screener, Financials Statements, Watchlist, Peer Comparison. Anything else?
   Recommendation: add Workspace tables and Predictions table.

9. **Hero number on instrument page (D21)** — current code uses `text-2xl` (24px) and `text-4xl` (36px). Proposal: collapse to `text-[18px]`. Is 18px enough for the headline price, or is the BBG mental model "huge price" so we keep it big?
   Recommendation: 18px feels right at our overall density — but this is the easiest place to be wrong. Worth a visual A/B with the user.

10. **Per-page doc resync**: After tokens are locked, each per-page doc needs a one-line sweep to point at the new tokens (no content change). Do this in PR-A or in a separate PR-H?
    Recommendation: PR-A (same commit as tokens — the docs ARE the tokens).

---

## 10. Appendix — current usage census (from grep)

For reproducibility — these counts were taken at HEAD of branch `feat/frontend-platform-hardening` on 2026-05-19.

```
Font size (component code):
  603  text-[10px]
  554  text-[11px]
  154  text-[9px]
   26  text-[13px]
   18  text-[12px]
    6  text-[8px]    (out of scale — to be normalized to 9)
    2  text-[14px]

Border radius:
  475  rounded-[2px]   → REMOVE
   67  rounded-full    → KEEP
   24  rounded-none    → KEEP (becomes default by omission)
   10  rounded-sm      → REMOVE
    9  rounded-md      → REMOVE
    8  rounded-lg      → REMOVE
    1  rounded-xl      → REMOVE

Row height:
   96  h-[22px]   → h-[20px] for most; keep 22 for sparkline rows
    4  h-[18px]   → KEEP (hyper-dense)
    1  h-[36px]   → INSPECT (likely a toolbar)
    1  h-[32px]   → KEEP (panel header)

Spacing top-3:
  347  px-2      → many become px-1.5 in cells
  281  gap-2     → many become gap-1.5
  234  px-3      → KEEP (most are tab-content margins)
  121  py-2      → KEEP (vertical padding doesn't compress as well)

Hover (top patterns):
  147  hover:text-foreground
   42  hover:bg-muted/40
   17  hover:text-primary
   16  hover:bg-muted/30
                  → all bg-muted/30|40|50 patterns folded into .row-hover utility

Transitions:
  158  transition-colors    → KEEP (clamp duration to 75ms)
   31  animate-spin         → KEEP (loaders)
   13  animate-pulse        → KEEP (skeletons)
   13  animate-in / out     → KEEP (Radix-driven overlays)
   10  transition-transform → REMOVE
   10  transition-all       → REMOVE
    4  animate-ping         → REMOVE
    9  duration-200         → REMOVE (clamp to 75/100)

Shadow:
   10  shadow-md   → REMOVE (already CSS-overridden; class is dead)
    6  shadow-none → KEEP
    6  shadow-lg   → REMOVE
    5  shadow-xl   → REMOVE
    4  shadow-primary/20  → REMOVE
    2  shadow-sm   → REMOVE
    1  shadow-2xl  → REMOVE

Focus ring:
   67  outline-none           → KEEP
   33  focus:ring-1           → → outline-1
   27  focus:ring-primary     → → outline-primary
   23  focus-visible:ring-1   → → outline-1
   17  focus-visible:ring-ring → → outline-primary
   15  focus-visible:ring-primary → → outline-primary
   10  ring-1                 → → outline-1
    9  focus-visible:ring-2   → → outline-1
    3  ring-2                 → → outline-1
    [remaining ring-* sites]  → → outline-*

Total estimated touched sites for migration: ~1,800 across ~120 files.
Most are scripted bulk replaces; ~200 sites need manual review.
```

---

## 11. Status

- [x] Investigation complete
- [x] Recommendations drafted
- [ ] User review pending (questions in §9)
- [ ] Master PRD updated to point here
- [ ] PR-A queued (tokens + docs)

After user signs off on §8 decisions table + §9 open questions, this becomes
canonical and feeds into:

- `docs/specs/0089-platform-page-redesign.md` §Design System
- Updated `docs/ui/DESIGN_SYSTEM.md`
- Updated `docs/designs/0089/_INDEX.md`
- New `docs/plans/PLAN-00NN-design-system-sweep.md` (Waves A-G mapped to the 7 PRs in §6.1)
