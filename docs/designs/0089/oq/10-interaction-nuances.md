# Cluster 10 — Interaction Nuances, Animation Policy, Empty/Loading/Error, Focus & Keyboard

> **Scope**: Cross-page contract for the small primitives every surface depends
> on: animation budget, hover, focus ring, keyboard navigation, chord scope,
> empty state, loading state, error state, tooltip, a11y.
> **Status**: PROPOSAL — needs user sign-off before primitives wave.
> **PRD**: PRD-0089 (NFR-6, NFR-10, NFR-11) + DESIGN_SYSTEM.md §6/§10.
> **Source files reviewed**:
> - `docs/specs/0089-platform-page-redesign.md` (NFR-6, OQ-D22)
> - `docs/ui/DESIGN_SYSTEM.md` §6 + §10
> - `apps/worldview-web/hooks/useChordHotkeys.ts` (280 LoC — full chord engine)
> - `apps/worldview-web/components/ui/{button,tabs,input,switch,checkbox,calendar,number-input,squarified-treemap,confirm-dialog}.tsx`
> - `apps/worldview-web/components/ui/dashboard-empty-state.tsx`
> - `apps/worldview-web/components/data/{InlineEmptyState,InlineErrorState,PanelHeader}.tsx`
> - All 11 design docs `docs/designs/0089/{00..10}-*.md` — §7 of each (Interaction model)

---

## 0. Cluster summary

PRD-0089 NFR-6 reads literally:

> **No animations on data surfaces (charts, tables, mini-bars). Transitions
> on layout-shift props banned.**

The 11 design docs interpret this inconsistently:
- `02-dashboard.md` allows a 100 ms `RowHoverToolbar` fade in.
- `01-global-shell.md` insists on `duration-0` for nav-item color flips.
- `08-screener.md` uses `animate-pulse` skeletons.
- `10-chat-ai.md` allows token streaming + `data-flashed` 600 ms toggle.
- `05-instrument-quote.md` allows a 9 px `⟳` spinner on brief generation.

Existing shadcn primitives ship Radix `data-state` animations (popover, tooltip,
dialog, sheet, accordion) that fire at 150-200 ms regardless of NFR-6 wording.

The cluster has two failure modes if not resolved:

1. **Over-restrictive reading**: agents strip every `transition-colors`,
   producing UI that flashes harshly on hover. Bloomberg actually has
   instant flips, but Linear / Notion / Finviz allow ≤100 ms color
   transitions and feel calmer.
2. **Under-restrictive reading**: agents add 200-300 ms fades on chart
   re-renders, row inserts, mini-bar fills — the exact jank NFR-6 was
   written to prevent.

This document defines what "animation" means precisely, what scope each
interaction primitive operates in, and what consistent copy/visual we
use for empty / loading / error across every surface.

---

## 1. Animation policy — strict but pragmatic

### 1.1 Definitions

| Term | Definition | Allowed? |
|------|-----------|----------|
| **Data animation** | Animating a value, position, or geometry on a data surface (chart line draw, bar fill, row insert slide, sparkline morph, treemap reflow) | NEVER |
| **State animation** | Animating an overlay coming on/off screen (popover, tooltip, dialog, sheet, accordion). Used at the `data-state=open/closed` boundary | ALLOWED (≤ 200 ms) |
| **Affordance animation** | Tiny color / opacity change to signal interactivity (hover, focus). 0-100 ms | ALLOWED (≤ 100 ms) |
| **Indicator animation** | Spinner, skeleton shimmer, pulse dot indicating ongoing work | ALLOWED, but limited |
| **Streaming animation** | LLM token-by-token reveal, alert SSE row insert. Conceptually data, but the user expects motion | ALLOWED, but no slide/fade — pure append |

### 1.2 "Data surface" — precise definition

A surface is a **data surface** iff it visualizes ANY of:
1. A numeric quantity that updates from the network (price, P&L, count, %).
2. A chart axis or candle/bar geometry.
3. A row/column inside a table/grid that carries financial data.
4. A graph node/edge layout (entity graph, treemap, heatmap cell).

By contrast, a surface is a **chrome surface** when it only contains:
- Navigation, modals, tooltips, popovers, drawers.
- Decorative borders / dividers / labels / hint text.
- The shell (sidebar, top bar, status bar).

### 1.3 Decision table

| Surface | Animation budget | Justification |
|---------|------------------|---------------|
| Chart re-render (zoom, pan, series change) | `duration-0` — instant | NFR-6 core case; jank source |
| Table row insert (SSE alert / new article) | NO slide-in. Render with `bg-primary/[0.06]` flash for 800 ms then settle (CSS `@keyframes` ALLOWED — see 1.4) | Visible signal that something changed, without jank |
| Mini-bar / sparkline first paint | Instant. No draw-in animation. | "fill from zero" reads as data uncertainty |
| Sparkline value tick update | Instant. Recompute polyline points; no morph. | |
| HeatCell color change on quote update | Instant. | Avoids drawing attention away from rapidly-updating panels |
| LivePriceBadge dot when fresh (<30s) | `animate-pulse` 2s loop ALLOWED — the dot is chrome, not data | Existing pattern (DESIGN_SYSTEM §6.11) |
| Hover background color flip | `transition-colors duration-100` | Avoids visual snap; under perception threshold of 150 ms |
| Hover row highlight | `transition-colors duration-100` | Same |
| Focus ring appear | `duration-100` ALLOWED | Same |
| Sidebar collapse | NO width transition. Snap. | Layout-shift property → NFR-6 ban |
| Tab switch (Quote / Financials / Intelligence) | NO content fade. Instant swap. | Layout-shift |
| Modal / Sheet / Dialog open | Radix default 150-200 ms ALLOWED | Chrome surface; users expect overlay motion |
| Popover / Tooltip open | Radix default ALLOWED, with 100-250 ms delay before show | Chrome |
| Accordion expand/collapse | Radix `animate-accordion-{up,down}` ALLOWED at 150 ms | Chrome (but data inside may shift — see 1.5) |
| Chat token streaming | Append only. No fade-in per token. | Already conventional; pulse cursor was REMOVED W6 |
| Brief banner spinner (`⟳ Generating…`) | `animate-spin` on the 9 px icon ALLOWED | Indicator animation |
| Skeleton shimmer (`animate-pulse`) | ALLOWED but use sparingly — only when the surface is genuinely loading. NEVER on cached data. | Indicator |
| `data-flashed` 600 ms (chat citation jump) | ALLOWED. Background flash, no geometry change. | Visual breadcrumb for jump-to-anchor |
| FlashOverlay (CRITICAL alert) | Full-screen 200 ms fade-in, hold 1500 ms, 400 ms fade-out | Already exists; intended attention grab |

### 1.4 Mechanism — how the "row flash" works without violating NFR-6

```tsx
// Allowed pattern: background-color transition on row insert.
// NOT animating layout (width/height/position).
<tr
  className="transition-colors duration-700 data-[flashed=true]:bg-primary/[0.06]"
  data-flashed={isNew}
/>
```

A `setTimeout` clears `isNew` after 800 ms. The CSS transitions `background-color`
only — no `transform`, `width`, `height`, `top`, `left`. NFR-6 explicitly bans
"transitions on layout-shift props"; background-color is not layout-shift.

### 1.5 Accordion exception

Accordion content shifts table rows below it. Treat accordion expand/collapse
as a state animation only in chrome regions (filter panels, settings).
In `Holdings` or `Screener` rows, the accordion-expand is BANNED — use a
slide-over panel instead (already the v1 spec).

### 1.6 Prefers-reduced-motion

Every state/affordance animation must wrap in:

```css
@media (prefers-reduced-motion: no-preference) { /* the transition */ }
```

Or use Tailwind's `motion-safe:` modifier:

```tsx
className="motion-safe:transition-colors motion-safe:duration-100"
```

Architecture test (see §5) asserts: every `transition-*` or `animate-*` class
in components must be paired with `motion-safe:` OR appear in an allow-list
of skeleton/spinner files.

### 1.7 Recommended decision

**ADOPT** the table in §1.3. **REWRITE NFR-6** in PRD-0089 §6 from:

> No animations on data surfaces (charts, tables, mini-bars). Transitions on
> layout-shift props banned.

…to:

> NFR-6 (revised): Data-surface motion is restricted to:
> (a) ≤100 ms hover/focus color transitions,
> (b) 600-800 ms background-color flash for row insert/citation jump,
> (c) `animate-pulse` skeletons during genuine load,
> (d) `animate-spin` spinners on indicator icons.
> All other motion on data surfaces (geometry, layout, opacity-from-zero,
> transform) is banned. Chrome surfaces (modals, popovers, tooltips, sheets)
> follow Radix defaults (150-200 ms). All motion must honour
> `prefers-reduced-motion`.

---

## 2. Hover behaviour — cross-page contract

### 2.1 Pattern register (sourced from 11 design docs)

The design docs each pick their own hover background. We unify:

| Surface class | Background | Border | Cursor | Notes |
|---------------|-----------|--------|--------|-------|
| **Table row (clickable)** | `hover:bg-foreground/[0.03]` | none | `cursor-pointer` | Screener, Holdings, Transactions |
| **Table row (read-only)** | `hover:bg-foreground/[0.02]` | none | default | Earnings, Insider list |
| **List row (chat thread, watchlist)** | `hover:bg-muted/40` | none | `cursor-pointer` | |
| **Nav item (sidebar, tabs)** | `hover:bg-muted/40 hover:text-foreground` | none | `cursor-pointer` | DESIGN_SYSTEM §6.10 already canonical |
| **IndexStrip cell** | `hover:bg-muted/20` | none | `cursor-pointer` | |
| **Chip / pill** | `hover:bg-muted/60` | none | `cursor-pointer` | Filter chips, follow-up chips |
| **Sparkline** | NO hover state | — | default | Too small (40×16) for tooltip; chg% cell carries value |
| **HeatCell** | NO hover state — color already encodes data | — | inherit row | Cell is the data |
| **Inline citation `[cN]`** | `hover:underline` + 250 ms delay → HoverCard | — | `cursor-pointer` | shadcn HoverCard primitive |
| **Confidence-bar segment** | `hover:opacity-70` | — | `cursor-pointer` | Native `title=` |
| **Graph node / edge** | sigma.js handles internal hover (existing tooltips) | — | inherit | NodeTooltipPanel / EdgeTooltipPanel |
| **Brief preview** | `hover:bg-muted/30` on the row | — | `cursor-pointer` | Click expands |

**REJECTED alternatives**:
- `border-l-2 border-primary` on hover — causes a 2 px layout shift on every row hover; violates NFR-6 (transitions on layout-shift props).
- Hover `bg-muted/50+` — too aggressive at 11 px font density; row reads as "selected" not "hovered". Reserve `bg-muted/50+` for **selected** state.
- "Sparkline expands inline on hover" — banned. The sparkline is a teaser; the instrument detail page owns the rich chart. Expanding inline mutates layout.

### 2.2 Selection vs hover (terminal-grade distinction)

| State | Visual | Trigger |
|-------|--------|---------|
| Idle | (default row background) | — |
| Hover | `bg-foreground/[0.03]` | mouse-over |
| Keyboard focus | left-border 2 px primary + `bg-primary/[0.04]` | Tab or `j/k` |
| Selected (multi-select, checked) | `bg-primary/[0.08] shadow-[inset_2px_0_0_hsl(var(--primary))]` (existing DataTable pattern) | Click checkbox or Shift+↓ |
| Active (current selection in master/detail) | `bg-primary/[0.06]` + `border-l-2 border-primary` | Click or Enter |

The four levels must be visually distinguishable at 22 px row height
and 11 px text. Hover < Focus < Active < Selected in saturation.

### 2.3 Hover delay (cross-page consistent)

| Element | Delay | Rationale |
|---------|-------|-----------|
| Row background flip | 0 ms (instant — `transition-colors duration-100`) | Affordance |
| Native `title=` tooltip | Browser default (~500 ms) | OS-level — we don't override |
| Custom Radix Tooltip | 300 ms | Linear convention; matches shadcn default |
| HoverCard (citation, peer) | 250 ms | Slightly faster — these reward exploration |
| Column-header full-name tooltip | 400 ms | Avoid noise while users scan many columns |

### 2.4 Pre-fetch on hover

`05-instrument-quote.md §7.2` declares: hover on peer row pre-fetches `page-bundle`
via `queryClient.prefetchQuery`. This is GOOD; we extend it cross-page:

| Hover target | Pre-fetch | TanStack key |
|--------------|-----------|--------------|
| Peer ticker | Instrument page bundle | `qk.instruments.pageBundle(entity_id)` |
| Watchlist row | (already done — quote in cache) | — |
| Screener row | Instrument page bundle | `qk.instruments.pageBundle(instrument_id)` |
| Graph node | Entity detail | `qk.kg.entityDetail(entity_id)` |
| Citation chip | Article detail | `qk.news.article(article_id)` |

Pre-fetch only on hover ≥ 200 ms (we use `onMouseEnter` + `setTimeout`),
so mouse-tracking across many rows doesn't fire 50 network calls.

---

## 3. Focus ring policy

### 3.1 Current state

Per `grep` of `components/ui/`:

| Primitive | Focus ring |
|-----------|-----------|
| Button | `ring-2 ring-ring ring-offset-2` |
| Tabs | `ring-2 ring-ring ring-offset-2` |
| Switch | `ring-2 ring-ring ring-offset-2` |
| Checkbox | `ring-2 ring-ring ring-offset-2` |
| Input | `ring-1 ring-ring` (no offset) |
| Slider thumb | `ring-1 ring-ring` |
| Calendar day | `ring-1 ring-primary` |
| Treemap cell | `ring-1 ring-primary` |
| NumberInput | `ring-1 ring-destructive` only when invalid |

Inconsistent. At 11 px font density, `ring-2` + `ring-offset-2` consumes
~4 px of perceived border on every focused element — too noisy.

### 3.2 Decision

**Adopt 3-tier focus ring matching the surface density**:

| Tier | Visual | Apply to |
|------|--------|----------|
| **Tier 1 (terminal-grade — primary tier)** | `outline-1 outline outline-primary outline-offset-[-1px]` (inset 1 px hairline) | Table rows, screener rows, all dense list rows, graph nodes |
| **Tier 2 (compact controls)** | `ring-1 ring-ring ring-offset-1` (1 px ring + 1 px offset) | Input, calendar day, slider thumb, NumberInput, single-select buttons inside dense bars |
| **Tier 3 (chrome controls)** | `ring-2 ring-ring ring-offset-2` (current) | Top-level Button (CTA primary/destructive), Tabs (page nav), Dialog buttons |

Three tiers are visually distinct: Tier 1 sits inside the cell (no layout
shift), Tier 2 is a compact halo, Tier 3 is the institutional default.

**Color**: `--ring` already resolves to `hsl(var(--primary))` in dark
theme. WCAG 3:1 contrast against `--background` = passes (Primary yellow
#FFD60A on background #0A0A0A = 14.6:1).

**Hairline alternative tested**: a single `border-l-2 border-primary` on
the focused row works visually but introduces a 2 px layout shift the
first time a row receives focus (the right-side cells nudge). Outline
(not border) avoids this — `outline` is rendered outside the box model.

### 3.3 Architecture rule

A `__tests__/architecture/focus-ring-tier.test.ts` (new) asserts every
component file that includes `focus-visible:` or `:focus-` selectors
specifies one of the three tier strings. CI gate: no ad-hoc `ring-3`
or `outline-4` anywhere.

---

## 4. Keyboard navigation matrix

### 4.1 Per-surface keyboard contract

| Surface | Tab | Enter | Esc | ↑/↓ | ←/→ | Space | j/k |
|---------|-----|-------|-----|-----|-----|-------|-----|
| **Table (Screener, Holdings, etc.)** | enters/exits the table | open row detail | clear filter, then unfocus | move row focus | (within row) move cell (where useful) | toggle checkbox if selectable | move row focus (vim alias) |
| **List (Watchlist, Threads)** | enter/exit | activate row | unfocus | move focus | — | — | move focus |
| **Tabs (Quote/Financials/Intelligence)** | enter/exit | activate | — | — | move tab selection | activate | — |
| **Chart (OHLCVChart)** | enter/exit | — | — | — | scroll x-axis 1 candle | toggle play/pause if streaming | — |
| **Modal / Sheet / Dialog** | cycle inside (focus trap) | submit / activate primary | close | next/prev field | — | activate | — |
| **Composer (chat)** | exit (advances to send) | send | dismiss autocomplete; else blur | (in autocomplete) move suggestion | — | — | — |
| **Hotkey cheat-sheet overlay** | — | — | close | move filter result | — | — | — |
| **Graph canvas (sigma.js)** | enter/exit (focus delegates to node-detail rail) | open node detail | clear selection | move highlighted node | — | — | — |
| **Filter Panel / Saved Screens dialog** | cycle | apply | close | move within list | — | toggle checkbox | — |

### 4.2 Rules

- **Tab** is ALWAYS a focus-advance, never a custom action. Custom actions
  (chord `t`, etc.) only fire outside text inputs (see chord engine).
- **Enter** activates the focused element. On a table row → navigate to
  detail. In an input → submit (or insert newline in textarea).
- **Esc** has a 3-step cascade:
  1. If a chord buffer is active → clear buffer.
  2. If a modal/sheet/popover/dropdown is open → close topmost.
  3. Otherwise → blur the current focus.
  Esc NEVER navigates back. (Browser back is `mod+[`.)
- **j/k** is registered ONLY on surfaces where it makes sense (lists,
  message stream, news rows). Page-scoped binding via `<HotkeyScope>`.
  Vim parity is opt-in per page, not universal.
- **↑/↓** is the canonical row-mover. j/k is an ALIAS, not a replacement.
- **Number row (`1`, `2`, ...)**:
  - On Quote tab → chart timeframe.
  - On Portfolio Overview → equity-curve period.
  - On Intelligence tab → graph depth (`1`/`2`/`3`).
  - On Workspace → activate panel N.
  Page-scoped via `<HotkeyScope page="...">` — never global.

### 4.3 Focus order

- `tabindex="0"` on every interactive cell. `tabindex="-1"` on rows the
  user must reach via arrow keys (table rows are NOT in tab order; they
  are reached via `Tab → table → ↓`).
- A "roving tabindex" pattern lives inside each table (only one row has
  `tabindex=0`; arrows move it).
- The page header (breadcrumb + tabs) is always tabbable FIRST.
- The composer textarea (chat) is always tabbable LAST on the chat page.

### 4.4 Screen reader contract

Every panel header gets `role="region" aria-label="<panel name>"` so
SR users can use landmarks. Tables get `role="table"` + `aria-rowcount`
(already on DataTable per DESIGN_SYSTEM §12.1). Chart fallback: every
chart includes an `aria-label` summary ("Apple price chart, 1 day,
opened 150.23, closed 152.45, range 149.10-153.20").

---

## 5. Chord scope conflicts (the gnarly cases)

### 5.1 Existing scope stack (verified in `useChordHotkeys.ts`)

```
modal > input > chart > table > page > global
```

A binding with `scope: "modal"` overrides a binding with same chord at
`scope: "page"` ONLY WHEN at least one modal is on the stack. Scope is
ref-counted via `pushScope` / `popScope` in `HotkeyContext.tsx`.

### 5.2 Conflicts identified in the 11 design docs

| Chord | Conflicts | Resolution |
|-------|-----------|-----------|
| `Q` / `F` / `I` | Instrument page tabs vs global "Q" if reserved | Instrument tabs are page-scoped (`page="/instruments/"`); no global `Q`. Confirmed safe. |
| `B` | Quote tab "Brief expand" vs Portfolio "Back to portfolio list" | Both are page-scoped (`/instruments/` vs `/portfolio`). Pathname matcher prevents collision. |
| `T` | Portfolio "Transactions tab" vs Intelligence "Type filter" | Both page-scoped. Pathname matcher disambiguates. |
| `/` | Global search focus vs Screener filter focus | RESOLVE: when pathname starts with `/screener`, the screener `/` binding registers at scope `page`, and global registers at `global`. Scope stack dictates `page > global` → screener wins on `/screener`. Confirmed safe by scope rules. |
| `R` | Many: Refresh / Reset filters / Regenerate brief | All page-scoped. `Shift+R` on Quote tab also page-scoped. No collision. |
| `?` | Global cheat sheet — never overridden | global only. Reserved. |
| `Esc` | Many — see §4.2 cascade | Handled inside the chord listener (clears buffer before lookup). |
| `mod+\` | Chat "Toggle context rail" vs hypothetical global panel | OQ-D18 already resolves: chat ContextRail wins inside `/chat`; no global mapping exists. |
| `mod+k` | cmdk Dialog listener (NOT registered in our registry) | Reserved — never register. |
| `mod+.` | Chat "Cancel streaming" | Chat-scoped. No collision. |
| `↑` in empty composer | Chat "Recall last message" vs page-level row mover | Composer is a text input → chord listener suspends except for modifier chords. The composer handles `↑` itself via React keydown on the textarea when value is empty. Bypasses the chord engine. |

### 5.3 New rules to add to `01-global-shell.md §7.1`

1. **Chord scope must be declared** at registration via the
   `<HotkeyScope scope="page" page="/portfolio">` wrapper. Manual
   `registry.register({scope: "page", page: "/x"})` is permitted only
   from inside a `useEffect` cleanup.
2. **Chord lookup is pathname-aware**: a `page`-scoped binding
   resolves ONLY when the current pathname starts with the declared
   path. The registry already does this; doc must spell it out.
3. **Esc fall-through**: the chord listener clears the buffer THEN
   looks up Esc bindings. Components that want Esc behavior must
   register `{chord: "escape", scope: "modal|page|..."}` — not bind
   their own `onKeyDown`.
4. **Modifier-bearing chords pass through text inputs** (e.g. `mod+k`,
   `mod+enter`). Single-letter chords NEVER fire inside text inputs.

---

## 6. Empty state taxonomy

### 6.1 Five distinct empty conditions

| Condition | Definition | Visual |
|-----------|-----------|--------|
| **Loading** | Network in flight; data not yet arrived | Skeleton OR `—` placeholder (see §7) |
| **Empty (data)** | Network succeeded, returned 0 rows / null record | `InlineEmptyState` muted line OR `DashboardEmptyState` block + CTA |
| **Empty (cold start)** | User hasn't done the setup step yet (no brokerage, no portfolio, no watchlist) | `DashboardEmptyState` block with primary CTA |
| **Error** | Network failed / 5xx / timeout | `InlineErrorState` with Retry link OR full-panel error card |
| **Permission denied** | 401 / 403 — auth issue | Bespoke "Session expired" copy with Sign-in CTA |
| **Coming soon** | Feature deferred (e.g. Pin in chat) | `text-muted-foreground` line + `(beta)` or `(coming soon)` tag |

### 6.2 Cross-surface copy library

Standardise the muted lines used today (which currently vary).

| Surface | Loading | Empty (data) | Empty (cold) | Error |
|---------|---------|--------------|--------------|-------|
| Holdings table | Skeleton rows (×16) | n/a (cold path below) | "Connect a brokerage to see holdings" + CTA | "Couldn't load holdings. Retry." inline banner |
| Watchlist (sidebar) | 5 × `Skeleton h-6` | "Add symbols in Portfolio → Watchlists" | (same as data) | last-known + 9 px warning badge |
| Screener results | 20 skeleton rows | "No instruments match these filters." + Reset CTA | (initial state shows top-50 S&P → never empty) | "Screener temporarily unavailable. {msg}. Retry." |
| AI brief banner | `BRIEF · Generating…` + `⟳` | "no news in last 90 days" muted | "Generate brief" CTA | "BRIEF · unavailable · Try again" |
| Insider activity | 5 × 18 px skeleton | "No insider activity in last 12 months." | (same) | "Failed to load insider activity. [retry]" |
| Earnings list | 4 × 18 px skeleton | "No earnings history (ETF / fund)." | (same) | "Failed to load earnings history." |
| Related headlines | 5 × 18 px skeleton | "No related news in last 30 days." | (same) | "Failed to load related headlines." |
| Entity graph | Spinning RefreshCw + "depth=N…" | "No relations for this entity at depth {d}. Try depth +1." | (same) | "Graph too large at depth 3 — try depth 2." (1-click switch) |
| Top relations | 6 × 18 px skeleton | "No direct relations." | (same) | "Relations unavailable" |
| Path insights | 2 × 38 px skeleton | "No multi-hop paths discovered." | (same) | "Path engine offline (AGE)" |
| Contradictions | 1 × 60 px skeleton | "No contradictions detected." (positive framing) | (same) | "Contradictions unavailable" |
| Chat threads | 5 × `Skeleton h-6` | "No conversations yet. Start by asking a question." | (same) | "Failed to load threads · Retry" |
| Chat stream | Accent rail + role glyph (no dots) | (single empty stream not possible) | (n/a) | `ChatErrorBanner` under turn + inline retry |
| Alerts list | Skeleton | "No alerts yet." + "Create your first alert" CTA | (same) | "Alerts feed unavailable. Reconnecting…" |
| Pre-market movers | "Market mover data loading…" | "No gainers" / "No losers" | (same) | inline retry |
| MetricGrid (Quote) | `—` in 8 cells + `placeholderData` from bundle | "Not available for this instrument type" muted | (same) | silent `—` per cell |
| MultiPeriodReturns | 7 × 56 px skeleton | "—" for missing periods | (same) | silent `—` |

### 6.3 Copy voice (terminal grade)

- Sentence case for first word, lowercase rest. `No alerts yet.` Not
  `No Alerts Yet`.
- No exclamation marks anywhere.
- Avoid "we" / "you" except in CTA copy. Empty messages describe data
  state, not user behavior. Bad: "You don't have any alerts yet." Good:
  "No alerts yet."
- CTA buttons: short verb-phrase. `Connect brokerage`. `Generate brief`.
  `Add symbols`. Not `Click here to connect a brokerage`.
- Error copy: state the problem first, then offer Retry. `Couldn't
  load holdings. Retry.` — not `Oops! Something went wrong.`

### 6.4 Library location

A new `lib/copy/empty-states.ts` exports a single object so every
component reads from the same dictionary. Architecture rule: components
may not inline empty/error strings; must import from `EMPTY_COPY`.

```ts
export const EMPTY_COPY = {
  holdings: { loading: "...", empty: "Connect a brokerage to see holdings", ... },
  watchlist: { ... },
  // ...
} as const;
```

Architecture test asserts: no `"No "` or `"Couldn't"` string literals in
components except via `EMPTY_COPY`.

---

## 7. Loading state policy (per-surface)

| Surface type | Loading visual | Rationale |
|--------------|----------------|-----------|
| **Table (initial)** | Skeleton rows (`bg-muted/30 animate-pulse`) matching final row height (22 px), count ≈ visible rows | DESIGN_SYSTEM §6.2 — already canonical |
| **Table (cell-level — quotes filling in)** | `—` em-dash per cell | Avoids spinning a per-cell shimmer; the user already sees the layout |
| **Chart (cold load)** | Gray-block placeholder at chart's reserved height; one centred 11 px muted line "Loading <symbol> price…" | Skeleton wave inside a chart reads as data |
| **Chart (refresh, cache-warmed)** | Show cached series; no overlay | `placeholderData` |
| **Sparkline** | Empty `<svg>` of correct dimensions | Prevent layout shift; no dotted line |
| **HeatCell** | Gray (`bg-muted/30`) cell; value text `—` | |
| **KPI tile** | Skeleton matching tile height (40-60 px) | |
| **Card / panel header** | Title visible (it's chrome); body skeleton | |
| **Modal / Dialog content** | Skeleton inside the modal body | |
| **Brief banner** | `BRIEF · Generating…` + `⟳ animate-spin` 9 px icon | Existing pattern |
| **Graph canvas** | Centred spinning RefreshCw 16 px + 11 px muted text "depth=N (loading)" | |
| **Streaming (chat)** | No skeleton — accent rail visible only; tokens append as they arrive | |

**Rules**:
- Skeleton MUST occupy the same width × height the loaded content will.
  Architecture rule: every `<Skeleton>` site has an explicit `className`
  including a width AND height (`h-6 w-full`).
- Never show a `Spinner` in a data area. Spinners only appear:
  (a) as the 9 px `⟳` icon on indicator labels (brief generating, retry),
  (b) as the centred 16 px on chart canvas during graph computation,
  (c) inside `<DestructiveButton>` while a destructive action is in flight.
- Loading state must not collapse the container — `min-h-{N}` matches
  the final content height.

---

## 8. Error state policy (per error class)

### 8.1 Visual taxonomy

| Visual | Where | Use for |
|--------|-------|---------|
| **Inline banner (within panel)** | Above the affected table/list | Per-panel network errors (Holdings, Screener, News) |
| **Page banner (top of route)** | Below TopBar | Page-level catastrophic error (route can't render anything useful) |
| **Toast (sonner)** | Bottom-right (currently configured) | Transient: action confirmations, non-blocking errors (e.g. "Saved to watchlist", "Copy failed") |
| **Inline `—` fallback** | Within the cell | Single-field failure that shouldn't disrupt layout (silent fail) |
| **Full-page error route** | `error.tsx` boundary | Unhandled exception inside React tree |
| **Status badge (warning dot)** | In panel/page header | Soft staleness ("Live prices unavailable" — using cache) |

### 8.2 Error-class → visual map

| Error class | Visual | Retry? | Copy template |
|-------------|--------|--------|---------------|
| Network timeout (transient) | Inline banner | Yes — primary | "Request timed out. Retry." |
| 5xx server error | Inline banner | Yes — primary | "{Surface} temporarily unavailable. Retry." |
| 4xx client error (validation) | Inline form error | No — fix input | "{Field}: {reason}" |
| 401 unauthorised | Page-level redirect to `/login` OR inline "Session expired" with Sign-in CTA | Implicit (re-auth) | "Your session expired" |
| 403 forbidden | Inline banner; no retry | No | "Not authorized to view this data" |
| 404 not found (route-level) | Full-page `not-found.tsx` | No | "{Resource} not found" |
| 404 not found (sub-resource) | `—` fallback or empty state | No (it's empty, not errored) | Use empty copy |
| WebSocket disconnect (transient) | Status badge `WS Offline` + small banner under composer (chat only) | Auto-retry (exponential backoff) | "Connection lost — reconnecting…" |
| Cache stale, refresh failed | Keep cache, show 9 px warning dot in header | Background auto-retry | "stale" badge in header |
| ABORTED (user cancelled) | No UI | No | — |
| 5xx on cosmetic surface (sparkline, peer pre-fetch) | Silent (no UI) | No | — |

### 8.3 Toast usage rules

Already adopted via `sonner` (verified `app/providers.tsx`). Confine
toasts to:
- Action confirmations: "Added to watchlist", "CSV downloaded".
- Non-blocking failures: "Copy failed — clipboard unavailable".
- Auto-dismiss at 4 s. Critical alerts use `FlashOverlay`, not toast.

Toasts MUST NOT be used for data-load errors — those go to inline banners
so the user can see the affected panel.

---

## 9. Tooltip primitives

### 9.1 Three variants

| Variant | Component | Delay | Use for |
|---------|-----------|-------|---------|
| **Native `title=`** | HTML attribute | OS default (~500 ms) | Truncated text full-form (column header, row label, sparkline title) |
| **Radix Tooltip (shadcn)** | `<Tooltip>` | 300 ms | Mouse-only hint over icon buttons, KPI explanations, badge meanings |
| **HoverCard** | shadcn `<HoverCard>` | 250 ms | Rich preview: citation hovercard (article excerpt), peer hovercard (mini-quote), entity hovercard (description + key metrics) |

### 9.2 Rules

- Single source of truth for delay: `lib/ui/tooltip-config.ts` exports
  `TOOLTIP_DELAY_MS = 300`, `HOVERCARD_DELAY_MS = 250`. Components
  read from this — never hardcode.
- Tooltip content ≤ 1 line. HoverCard content ≤ 240 chars + max 4 lines.
- Tooltips do NOT contain interactive elements. HoverCards MAY contain
  links / buttons (focus moves into the card when keyboard-activated).
- Position: Radix `side="top"` default; auto-flip via `collisionPadding`.
- For touch / mobile, HoverCard does not fire — users tap to navigate
  to the full surface (article detail / instrument page).

### 9.3 Citation hovercard (specific)

- 250 ms delay before show.
- Card body: 11 px source name, 11 px headline (max 1 line), 10 px
  excerpt (max 4 lines / 240 chars), 10 px `Open ↗` link, 10 px
  `Copy ref` button.
- Width: 320 px. Height: auto-cap at 160 px.
- Hover bridge: 100 ms grace period on `onMouseLeave` from anchor →
  card (so moving cursor between anchor and card doesn't dismiss).

---

## 10. Accessibility deltas vs current

### 10.1 WCAG 2.1 AA at 11 px

11 px body text at 4.5:1 contrast against background. Current palette:
- `--foreground` (white) on `--background` (#0A0A0A) = 19:1 → AAA.
- `--muted-foreground` (grey-500) on `--background` = 5.7:1 → AA passes.
- `--muted-foreground` on `--card` (#111) = 5.3:1 → AA passes.
- Yellow `--primary` (#FFD60A) on `--background` = 14.6:1 → AAA.

✅ All baseline text passes AA at 11 px. The `text-[9px]` chart axis
(DESIGN_SYSTEM §3.2) is the only exception and is explicitly documented
as "decorative — full data accessible via crosshair HUD".

### 10.2 Keyboard-only operation gates

A new Playwright spec `__tests__/playwright/a11y-keyboard.spec.ts`:
- Tab from initial focus to every primary control on every page.
- Assert focus ring visible (screenshot diff vs baseline).
- Assert Esc closes the topmost overlay.
- Assert `g d`, `g p`, `g i`, `g s` navigate to expected route.
- Assert no element is focusable but has no visible focus indicator.

### 10.3 Screen reader landmarks

Every page must have:
- `<header>` (TopBar)
- `<nav>` (sidebar)
- `<main>` (page content) with `aria-label="<page name>"`
- `<aside>` (right rail / sheet) if present
- `<footer>` (StatusBar)

Each panel uses `role="region" aria-label="<panel title>"`. Tables
already have `aria-rowcount` / `aria-colcount` via DataTable.

### 10.4 High-contrast mode

OUT OF SCOPE for v1. Document the gap in `docs/ui/DESIGN_SYSTEM.md §10`
and add to OQ list (§12 below). High-contrast media query
(`forced-colors: active`) will require palette override + border-only
styles for HeatCell, sparkline, confidence bar. Treat as v1.1.

### 10.5 `prefers-reduced-motion`

Every animation/transition wrapped via `motion-safe:` Tailwind modifier
OR inside a `@media (prefers-reduced-motion: no-preference)` block.
Architecture test enforces (see §11).

---

## 11. Cross-page contract tables

### 11.1 Per-surface hover/focus/loading/error matrix

| Surface | Hover | Selected | Focus ring tier | Loading | Empty | Error |
|---------|-------|----------|-----------------|---------|-------|-------|
| Holdings row | `bg-foreground/[0.03]` | `bg-primary/[0.06] inset-left-2` | T1 inset hairline | 16 × `h-[22px]` skeleton | n/a (cold path is brokerage CTA) | inline banner |
| Screener row | `bg-foreground/[0.03]` | `bg-primary/[0.06] inset-left-2` | T1 | 20 × skeleton | filter empty: `DashboardEmptyState` | full-panel error |
| Transactions row | `bg-foreground/[0.02]` | n/a (read-only) | T1 | skeleton rows | "No transactions matching filters." | inline banner |
| Watchlist row (sidebar) | `bg-muted/40` | n/a | T1 | 5 × `Skeleton h-6` | inline text "Add symbols…" | stale badge |
| IndexStrip cell | `bg-muted/20` | n/a | T1 | 10 placeholder cells | impossible | last-known + warning dot |
| News row (Intelligence / Quote) | `bg-muted/20` | (highlighted via j/k) `bg-primary/[0.04]` | T1 | 8 × `h-[18px]` skeleton | muted line "No articles…" | "Failed to load news. [Retry]" |
| Insider row | `bg-foreground/[0.02]` | n/a | T1 | 5 × skeleton | muted line | muted retry row |
| Earnings row | none | n/a | T1 | 4 × skeleton | muted line | muted line |
| Peer row | `bg-foreground/[0.03]` | n/a | T1 + pre-fetch | 5 × skeleton | muted line | muted line |
| Sparkline | NONE | n/a | n/a | empty svg | flat 1 px line | absent (silent) |
| HeatCell | NONE | n/a | n/a | `bg-muted/30` + `—` | n/a | silent `—` |
| Citation `[cN]` | `underline` + HoverCard | (data-flashed 600 ms) | T2 | n/a | n/a | text-only (no link) |
| Confidence segment | `opacity-70` | n/a | T2 | n/a | n/a | hide segment |
| Chat thread row | `bg-muted/40` | `bg-primary/[0.06]` | T1 | 5 × `Skeleton h-6` | muted "No conversations yet" | "Failed to load threads · Retry" |
| Chat message | NONE on body; citations have hover | (`data-flashed`) | T1 (when focused via j/k) | accent rail only during stream | n/a | `ChatErrorBanner` under turn |
| Graph node | sigma.js internal | sigma.js internal | T1 (via sigma a11y plugin) | `RefreshCw animate-spin` | "No relations…" + retry depth+1 | depth-aware error |
| Brief banner | `bg-muted/30` (when collapsed) | (when expanded) | T2 | `⟳ Generating…` 9 px spin | "no news in 90 days" | "Try again" link |
| MetricGrid cell | NONE | n/a | T2 (focused via tab) | `—` + `placeholderData` | "Not available for…" muted line | silent `—` |
| KPI tile | NONE | n/a | T2 | skeleton matching tile | n/a (always populated or `—`) | `(approx)` suffix |
| Filter chip | `bg-muted/60` | n/a | T2 | n/a | n/a | n/a |
| Tab (Q/F/I) | `bg-muted/40 text-foreground` | underline + `text-foreground` | T3 | n/a | n/a | n/a |
| Nav item (sidebar) | `bg-muted/40` | `bg-primary/[0.06] text-foreground` | T2 | n/a | n/a | n/a |
| Button (CTA) | `hover:bg-primary/90` | n/a | T3 | inline spinner if in flight | n/a | toast |
| Input | n/a | n/a | T2 | n/a | n/a | `aria-invalid` + destructive border |

### 11.2 Per-page hotkey availability

| Page | Page-scoped chords | Inherits |
|------|-------------------|----------|
| `/dashboard` | (none new) | global |
| `/portfolio` | `B T A W R / 1 2 3 4 5 0 c Esc` | global |
| `/portfolio/{id}` | `B T A W R / 1 2 3 4 5 0 c Esc` | global |
| `/instruments/{id}` | `Q F I` (tab switch) | global |
| `/instruments/{id}` Quote | `B D P 1 5 30 Shift+R` | page (`Q F I`) + global |
| `/instruments/{id}` Financials | `b d ←/→` (period nav) + `e` (export) | page + global |
| `/instruments/{id}` Intelligence | `j k Enter 1 2 3 t g r Esc` | page + global |
| `/screener` | `/ f s r e n Esc Enter ↑/↓ Shift+↓ ⌘↓` | global |
| `/workspace/{id}` | `1..9` (panel focus) + workspace-specific | global |
| `/alerts` | (none new) | global |
| `/chat` | `Enter Shift+Enter ⌘K ⌘N ⌘\ ⌘. Esc / ↑ [ ] j k` | global |

---

## 12. Recommended decisions table

| Topic | Recommendation | Confidence |
|-------|----------------|------------|
| Animation policy wording | REVISE NFR-6 per §1.7 (data vs chrome vs affordance, with explicit budgets) | HIGH |
| Hover background (clickable row) | `bg-foreground/[0.03]` cross-page; `transition-colors duration-100` | HIGH |
| Hover background (read-only row) | `bg-foreground/[0.02]` | HIGH |
| Sparkline hover | NONE (too small) | HIGH |
| Sparkline expand-on-hover | REJECT (NFR-6 layout-shift ban) | HIGH |
| Citation hover | HoverCard, 250 ms delay, 320 px width, max 4 lines | HIGH |
| Hover pre-fetch | enabled on peer / screener / graph / citation; 200 ms threshold | HIGH |
| Focus ring tier system | 3-tier (T1 inset hairline / T2 `ring-1` / T3 `ring-2`) | HIGH |
| Esc cascade | clear chord buffer → close topmost overlay → blur | HIGH |
| Tab key | focus-advance only; never custom action | HIGH |
| j/k navigation | opt-in per page (Intelligence news, chat messages); ↑/↓ canonical | HIGH |
| Number-row chords | page-scoped only, never global | HIGH |
| Chord scope contract (mandatory `<HotkeyScope>` wrapper) | adopt | HIGH |
| Empty state taxonomy (5 conditions) | adopt | HIGH |
| Empty copy dictionary (`lib/copy/empty-states.ts`) | adopt; architecture-test enforced | MED (slight refactor lift) |
| Loading state default | skeleton matching dimensions; `—` for cell-level | HIGH |
| Spinner usage | only 3 sites (brief indicator, graph canvas, destructive button) | HIGH |
| Error visual matrix | inline banner / page banner / toast / `—` / status badge | HIGH |
| Toast usage | sonner — confirmations + non-blocking failures only | HIGH |
| Toast retention | 4 s auto-dismiss | HIGH |
| Tooltip system | 3 variants (native `title`, Radix Tooltip 300 ms, HoverCard 250 ms) | HIGH |
| `prefers-reduced-motion` | required wrapper for every animation; arch test enforced | HIGH |
| High-contrast mode | OUT OF SCOPE v1; deferred to v1.1 | MED |

---

## 13. Architecture-test extensions

Add the following architecture tests (live in
`apps/worldview-web/__tests__/architecture/`):

| Test file | What it asserts |
|-----------|-----------------|
| `animation-policy.test.ts` | No `transition-{transform,width,height,top,left,right,bottom,margin,padding}` in `components/` (NFR-6 layout-shift ban). Permitted: `transition-colors`, `transition-opacity`. |
| `motion-safe-wrapper.test.ts` | Every `transition-*` or `animate-*` class must be paired with `motion-safe:` OR file is in the allowlist (skeletons, spinners, Radix overlays). |
| `focus-ring-tier.test.ts` | Every `focus-visible:ring-*` / `focus-visible:outline-*` matches one of the three documented tier strings. No ad-hoc `ring-3`, `ring-4`, `outline-2`. |
| `empty-copy-dictionary.test.ts` | No string literal in `components/` starts with `"No "` or `"Couldn't"` or `"Failed to"` — must import from `lib/copy/empty-states.ts`. |
| `hover-policy.test.ts` | Every `hover:bg-*` in `components/` matches one of: `hover:bg-foreground/[0.02]`, `hover:bg-foreground/[0.03]`, `hover:bg-muted/20`, `hover:bg-muted/40`, `hover:bg-muted/60`, `hover:bg-primary/90`. No ad-hoc opacities. |
| `chord-scope-declared.test.ts` | Every `registry.register(...)` call must be inside a component that is wrapped in `<HotkeyScope ...>` OR specifies an explicit `scope` + `page` in the call site (regex scan). |
| `tooltip-delay-source.test.ts` | No literal `delayDuration={N}` in components — must read from `TOOLTIP_DELAY_MS` constant. |
| `aria-landmark-coverage.test.ts` | Each top-level page file (`app/(app)/*/page.tsx`) renders at least one `<main>` element with an `aria-label`. |

Playwright spec additions:

| Test | What it asserts |
|------|-----------------|
| `a11y-keyboard.spec.ts` | Tab through every primary page; assert a focus indicator exists at every stop (visible outline). |
| `chord-navigation.spec.ts` | `g d` lands on /dashboard; `g p` on /portfolio; `Esc` closes open dialog. |
| `empty-state-coverage.spec.ts` | Seed an empty user; visit every primary page; assert the empty-state copy from the dictionary renders. |
| `error-state-coverage.spec.ts` | MSW intercepts all GETs → 500; visit each primary page; assert inline banner with Retry button. |

---

## 14. Follow-up OQs (out of this cluster's scope)

| ID | Question | Affects |
|----|----------|---------|
| OQ-10.1 | High-contrast mode strategy (palette override vs border-only) — v1.1? | DESIGN_SYSTEM §10 |
| OQ-10.2 | Should `j/k` be wired on EVERY list (Holdings, Screener, News) or only chat + news (current)? | All list surfaces |
| OQ-10.3 | Touch / tablet behaviour for HoverCard (currently disabled — is that ok, or do we need long-press to show?) | Citation, peer hovercards |
| OQ-10.4 | Should the row-insert "flash" (§1.4) ALSO apply on quote-tick HeatCell updates, or only on row-level adds? Heat color already encodes change — second signal might be noise. | HeatCell, alert SSE |
| OQ-10.5 | Toast position — confirm bottom-right (current sonner default) vs bottom-center (more centred for short messages) | `app/providers.tsx` |
| OQ-10.6 | Confirm 800 ms is the right "flash" duration for row inserts (Slack uses 600 ms, Linear 800 ms, Bloomberg pure instant) | `transition-colors duration-700` flash |
| OQ-10.7 | Should Esc on `/screener` clear ALL filters at once (currently only closes popovers / clears search), as a single-stroke "panic reset"? Productivity vs accidental-loss tradeoff. | Screener |
| OQ-10.8 | Cheat-sheet `?` overlay — should `Shift+?` work too (some keyboards require it), or only `?`? | Global |
| OQ-10.9 | Spinner color — currently `--primary` (yellow). Some teams prefer `--muted-foreground` (grey) for less attention. Decide once and lock. | Brief spinner, graph spinner, button spinner |
| OQ-10.10 | Should the Esc cascade ALSO unmount the chord-buffer scheduler (currently fires `clearBuffer` then falls through — verify behavior is exactly what the cascade describes in §4.2)? | `useChordHotkeys.ts` line 189 |

---

## 15. References

- PRD-0089 NFR-6, NFR-10, NFR-11 — `docs/specs/0089-platform-page-redesign.md` L91-103, L249-256
- DESIGN_SYSTEM §6 (UX patterns) — `docs/ui/DESIGN_SYSTEM.md` L288-619
- DESIGN_SYSTEM §10 (Accessibility) — `docs/ui/DESIGN_SYSTEM.md` L1091-1100
- Chord engine — `apps/worldview-web/hooks/useChordHotkeys.ts` (280 LoC)
- Scope context — `apps/worldview-web/contexts/HotkeyContext.tsx`
- Registry — `apps/worldview-web/lib/hotkey-registry.ts`
- Empty state primitives — `apps/worldview-web/components/ui/dashboard-empty-state.tsx`, `apps/worldview-web/components/data/{InlineEmptyState,InlineErrorState,PanelHeader}.tsx`
- Toast — `apps/worldview-web/app/providers.tsx` L130-150 (sonner)
- All 11 design docs — `docs/designs/0089/{00-backend-data-inventory,01-global-shell,02-dashboard,03-portfolio-overview,04-portfolio-detail,05-instrument-quote,06-instrument-financials,07-instrument-intelligence,08-screener,09-workspace-predictions-alerts,10-chat-ai}.md` — §7 of each
