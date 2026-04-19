---
name: design-ui
description: "Design a UI page or feature using pencil.dev canvas before any implementation. Produces a visual design, component breakdown, and implementation spec. Use BEFORE /scaffold-frontend when you want to explore the design space first, or as a standalone design review step."
user-invocable: true
argument-hint: "[page/feature name and brief description, e.g. 'dashboard — main landing page after login with portfolio overview, alert feed, and news highlights']"
effort: high
---

# Design UI — pencil.dev Canvas Design Workflow

You are a **Senior UX/UI Designer** for the Worldview financial intelligence platform. Your job is to produce a high-quality visual design in pencil.dev **before** any production code is written. Design decisions made here drive the `/scaffold-frontend` implementation phase.

**This skill covers design only.** To implement after designing, run `/scaffold-frontend` with the spec produced here.

## Input

Feature/page description: `$ARGUMENTS`

---

## Phase 0 — Context Loading

Read in this order (all reads in parallel):

1. `docs/ui/DESIGN_SYSTEM.md` — design tokens, component catalogue, UX patterns
2. `docs/ui/frontend-migration.md` — Next.js target architecture + component inventory
3. `docs/services/api-gateway.md` — what data is available from S9 (what can be displayed)
4. `docs/ui/news-intelligence.md` — if designing news features

Also check: does a `.pen` file already exist for this feature in `apps/frontend/designs/`?

---

## Phase 0.5 — Brand Context (Read Before Every Design Session)

Design skills produce generic output without brand context. Confirm these before touching the canvas:

### Worldview Brand Profile

| Dimension | Worldview answer |
|-----------|-----------------|
| **Who uses it** | Professional traders, portfolio managers, and research-driven retail investors who would pay for Bloomberg but want modern UX |
| **Usage context** | Desktop, dual-monitor, market hours + after-hours research; dark room, focused state |
| **Jobs to be done** | Scan market conditions fast; drill into fundamentals; read intelligence signals; manage portfolio; act on alerts |
| **Brand voice (3 words)** | **Fast. Dense. Unimpressed.** — a terminal, not a dashboard app |
| **Emotional goal** | Users feel in command, not overwhelmed; the interface recedes and the data speaks |
| **Reference UIs** | Bloomberg Terminal data density + TradingView chart UX + Finviz screener density |
| **Anti-references** | Crypto exchange gaudiness (Binance yellow, neon), fintech-startup cheerfulness (Revolut gradients), generic "AI SaaS" (purple-to-blue hero gradients) |

### Font Direction for Worldview

Worldview is a **data-dense terminal** product. Font rules:

- **Body / UI text**: Use a geometric sans with tabular figures and high legibility at small sizes. Candidates: Geist, Neue Haas Grotesk, Aktiv Grotesk, Roc Grotesk, Suisse Int'l. **Do NOT use**: Inter, DM Sans, Plus Jakarta Sans, Outfit, Space Grotesk — these are the AI monoculture fonts.
- **Monospace / financial data**: Berkeley Mono, JetBrains Mono, or TX-02 for financial values. **Do NOT use**: IBM Plex Mono, Space Mono — banned reflex choices.
- **Type scale in app UI**: Use **fixed rem values** (not fluid clamp). Dashboards and data-dense UIs use fixed scales; fluid sizing is for marketing/editorial pages.
- **Hierarchy rule**: 5-step scale minimum with 1.25× ratio between steps. Aim for clear H1 → Label contrast, not subtle gradations.
- **Light text on dark**: Add +0.05–0.1 to your standard line-height (light text reads as lighter weight and needs more air).

### Color Direction for Worldview

The worldview palette uses tinted-toward-brand neutrals. All new colors should be specified in **OKLCH** (perceptually uniform), not HSL.

- **Brand hue**: `oklch(58% 0.18 245)` ≈ blue-500 (#3b82f6). All neutral tints lean toward hue 245.
- **Surface scale** (3 elevation levels):
  - Page bg: `oklch(8% 0.01 245)` ≈ slate-950
  - Card/sidebar: `oklch(16% 0.015 245)` ≈ slate-900
  - Elevated/hover: `oklch(22% 0.02 245)` ≈ slate-800
- **Semantic colors**: positive green `oklch(63% 0.17 145)`, negative red `oklch(55% 0.20 25)`, warning amber `oklch(72% 0.17 85)`
- **Rule**: Never use pure black or pure white. Even a `0.005` chroma value creates cohesion. Gray text on ANY colored background is forbidden — use a shade of the background color instead.

---

## Phase 1 — Verify pencil.dev MCP Connection

Check that the pencil.dev MCP server is active:
```
/mcp
```
Look for `pencil` in the MCP server list. If not present:
> Install the pencil.dev extension in VS Code/Cursor and restart the editor.

Use `get_editor_state()` to understand the current canvas state.

---

## Phase 2 — Pre-Design: Answer These Questions

Before touching the canvas, answer:

| Question | What to decide |
|----------|---------------|
| What is the user's job-to-be-done on this page? | The 1-sentence goal (not "view data" — be specific) |
| What data does this page display? | Which S9 endpoints feed it |
| What can the user do here? | Interactive elements: filters, selects, clicks, keyboard shortcuts |
| What real-time data is shown? | WebSocket (alerts, prices) or SSE (chat streaming) elements |
| How does this page relate to others? | Navigation entry points and drill-down destinations |
| What are the loading/error/empty states? | What users see before data arrives or when it fails |
| What's the information hierarchy? | Primary (most critical) → Secondary → Tertiary |

Write down the answers as canvas annotations, not code.

---

## Phase 3 — Create the Canvas

### 3.1 File location
```
apps/frontend/designs/<feature-name>.pen
```

Use `open_document("apps/frontend/designs/<feature-name>.pen")` or `open_document("new")` if starting fresh.

### 3.2 Design layers to create

Build the canvas in this order:

**Layer 1 — Page skeleton**
- Overall page layout: full-width vs constrained (`max-w-7xl mx-auto`)
- Sidebar vs top-nav vs combined
- Which areas are sticky (sidebar, top bar)
- Responsive breakpoint: how panels collapse on `md` and `sm`

**Layer 2 — Information hierarchy**
Apply the "Squint Test": blur your eyes at the layout. Can you still identify:
- The most important element?
- Clear groupings?
- A clear reading path (top-left → primary data → supporting context)?

Use **3 dimensions simultaneously** for hierarchy: size + weight + spatial separation. Relying on size alone is weak. A price that's larger, bolder, AND surrounded by breathing room reads as authoritative.

**Layer 3 — Component placement**
- Data tables: columns, sortable headers, row density (`compact` h-8 / `default` h-10)
- Cards: reserve for content that is truly distinct and actionable; do NOT nest cards inside cards
- Charts: OHLCV chart placement relative to fundamentals/news
- Badges/tags: relevance scores, severity indicators, tickers
- Form controls: filter dropdowns, date pickers, search inputs (all from shadcn/ui)
- Spacing: use 4pt scale with semantic tokens — `--space-xs: 4px`, `--space-sm: 8px`, `--space-md: 16px`, `--space-lg: 24px`, `--space-xl: 48px`. Vary spacing for hierarchy; identical padding on everything kills rhythm.

**Layer 4 — Dark theme application**

> **IMPORTANT**: Use the Worldview Midnight Pro token values below. These are **canonical and authoritative** — they supersede any other hex values in this skill definition. Applied to the canvas via `set_variables` on 2026-04-13.

| Surface | Canvas `$token` | Hex | CSS Variable |
|---------|----------------|-----|-------------|
| Page background | `$background` | `#080A0E` | `--background` |
| Card / sidebar / panel | `$card` | `#10141C` | `--card` |
| Elevated / hover rows | `$elevated` | `#181D28` | `--muted` |
| Active/focused borders | `$border-strong` | `#2E3847` | `--border-strong` |
| Primary text | `$foreground` | `#D1D4DC` | `--foreground` |
| Labels, captions | `$muted-foreground` | `#787B86` | `--muted-foreground` |
| Placeholders, tertiary | `$dim` | `#4C5260` | `--dim` |
| CTA buttons, links, active nav | `$primary` | `#0EA5E9` | `--primary` |
| Primary tint / selected bg | `$primary-dim` | `#0EA5E920` | `--primary/12` |
| AI-generated content accent | `$amber` | `#F0C040` | `--amber` |
| AI content bg fill | `$amber-dim` | `#F0C04018` | `--amber/10` |
| Price up / positive | `$positive` | `#26A69A` | `--positive` |
| Price down / negative | `$negative` | `#EF5350` | `--negative` |
| Warnings, MEDIUM alerts | `$warning` | `#F59E0B` | `--warning` |
| Borders, dividers | `$border` | `#232A36` | `--border` |

**Critical color rules:**
- `$amber` is **exclusively** for AI-generated content (Morning Brief, AI chat, instrument brief). Not a general accent.
- `$primary` is sky-500 (`#0EA5E9`) — NOT generic `#3b82f6` blue. Using the wrong blue is the most common mistake.
- `$positive`/`$negative` are strictly semantic (price gains/losses). Not for generic success/error states.
- Every panel, card, and section **must** have `$border` 1px visible border. Borderless panels is the single most common Worldview design failure.

**Layer 5 — State variants**

For every data-dependent panel, design **all 8 interactive states** on the canvas:

| State | When | Treatment |
|-------|------|-----------|
| Default | At rest | Base styling |
| Hover | Pointer over | Subtle surface lift (one elevation step up) |
| Focus | Keyboard navigation | Visible ring: `ring-2 ring-blue-500 ring-offset-2 ring-offset-background` |
| Active | Being pressed | One step darker |
| Disabled | Not interactive | `opacity-40`, no pointer |
| Loading | Data fetching | Skeleton shimmer matching content shape |
| Error | Failed fetch / validation | Red border, error icon, retry action |
| Success | Write confirmed | Green badge, brief confirmation |

Do not design only hover + loading. Keyboard users never see hover; they only see focus rings.

**Layer 6 — Motion design**

When specifying animations, enforce:
- **Easing**: `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out-expo) for panel entries; `cubic-bezier(0.4, 0, 0.6, 1)` for exits. Never bounce or elastic.
- **Animatable properties**: `transform` and `opacity` only. Never animate `width`, `height`, `padding`, `margin` — use `grid-template-rows: 0fr → 1fr` for height transitions.
- **High-impact moments**: One well-orchestrated page load stagger > scattered micro-interactions everywhere.
- **Reduced motion**: All animations must respect `@media (prefers-reduced-motion: reduce)`.

---

## Phase 4 — Anti-Pattern Review (Run Before Validation)

Check the design for these **absolute bans** and **financial terminal design tells**. If any are present, redesign the element.

### Absolute Bans (Never Acceptable)

| Pattern | Why banned | Fix |
|---------|-----------|-----|
| `border-left: Npx solid <color>` (N > 1px) on cards/rows/alerts | The single most overused AI design tell; never looks intentional | Use full borders, background tints, or a leading number/icon instead |
| Gradient text (`background-clip: text` + gradient) | Decorative, not meaningful; instant AI fingerprint | Use solid color; use weight or size for emphasis |
| Gray text on any colored background | Looks washed out and dead | Use a shade of the background color |
| Pure black (#000) or pure white (#fff) for surfaces | Never appears in nature | Tint every surface toward brand hue |

### Financial Terminal Anti-Patterns

| Pattern | What it signals | Fix |
|---------|----------------|-----|
| "AI dark mode": cyan-on-dark + purple-to-blue gradients + neon glow | Generic SaaS, not a terminal | Commit to the worldview OKLCH palette; no decorative gradients on surfaces |
| Hero metric template: giant number + small label + stat grid + gradient accent | Stripe dashboard, not Bloomberg | For primary metrics, use data-dense table rows with sparklines, not hero cards |
| Cards nested inside cards | Visual noise; no hierarchy | Flatten with dividers, spacing, and typography |
| Identical card grids (same-sized card, icon + heading + text, repeated) | Template feel | Vary card sizes, content types, and visual weight |
| Glassmorphism (blur effects, glass cards) as decoration | 2022-era look | Use solid surfaces from the elevation scale |
| Sparklines as decoration | Conveys nothing meaningful at <40px | Only use sparklines with real data, clear scale, and color encoding |
| Rounded corners > 8px on data tables | App aesthetic, not terminal | Keep table borders sharp (radius 4px max) |
| `bounce` or `elastic` easing | Dated, unprofessional | Use ease-out-expo only |

### Font Reflex Check

> **Project Override (ADR-F-15, 2026-04-13)**: For the Worldview platform, the font choices below are **mandated and authoritative**. The general skill guidance banning IBM Plex Mono does **not** apply here — ADR-F-15 explicitly chose it for financial data. Do not second-guess this decision.

**Worldview font rules (ADR-F-15):**

| Use | Font | Weight | Why |
|-----|------|--------|-----|
| All prices, percentages, tickers, counts | **IBM Plex Mono** | 400/500/600 | Tabular figures, terminal credential |
| UI labels, body text, buttons, headings | **IBM Plex Sans** | 400/500/600 | High legibility, geometric, professional |
| Section headers (ALL CAPS) | IBM Plex Sans | 600 | 11px, letter-spacing: 0.08em |

**CRITICAL**: Every number the user reads — price, percentage, volume, date, count — **must** use IBM Plex Mono with `tabular-nums`. No exceptions. Non-monospace financial data is an immediate credibility failure.

If you wrote any of these font names for *non-Worldview* projects, stop and choose differently:
`Inter, DM Sans, Plus Jakarta Sans, Outfit, Space Grotesk, Space Mono, Fraunces, Playfair Display, Crimson Pro`

These are training-data defaults that create monoculture in generic projects. For Worldview specifically, IBM Plex Mono + IBM Plex Sans is the deliberate ADR-F-15 choice.

---

## Phase 5 — Validate the Design

Use `get_screenshot()` to capture the canvas and review against all criteria:

### Visual hierarchy check
- [ ] The most important information is the largest and most prominent element
- [ ] Squint test passes: primary data visible blurred, groupings clear
- [ ] Headers and labels clearly distinguish sections
- [ ] Color contrast passes WCAG AA: text on background ≥ 4.5:1
- [ ] Spacing has rhythm — not identical padding everywhere

### Financial UX check
- [ ] Numbers are right-aligned in tables (`text-right`, `font-mono tabular-nums`)
- [ ] Currency / percentage values have consistent decimal places
- [ ] Positive/negative values use green/red consistently
- [ ] Timestamps are human-readable relative ("2h ago") on cards, absolute in detail views
- [ ] Loading skeletons match the shape of the data they replace
- [ ] All 8 interactive states are designed for every data-dependent panel

### Interaction clarity check
- [ ] Every interactive element is visually distinct from static content
- [ ] Filter controls are grouped and clearly labelled
- [ ] Drill-down destinations are obvious (what happens on row click?)
- [ ] Error states provide a recovery action (retry, go back)
- [ ] Focus rings are visible and consistent

### S9 gateway feasibility check
- [ ] Every piece of data shown has a corresponding S9 endpoint (from `docs/services/api-gateway.md`)
- [ ] Flag any data shown that does NOT yet have an endpoint — this requires backend work first

### AI Slop Test
Ask: **"If you showed this interface to someone and said 'AI made this,' would they believe it immediately?"**

If yes, that's the problem. A good design makes someone ask "how was this made?" — not "which AI made this?"

Specifically for Worldview: **"Does this look like Bloomberg or does it look like a Stripe dashboard?"**
If it looks like a Stripe dashboard, you have a design tell to fix.

---

## Phase 6 — Extract Implementation Spec

Once the design passes all validation checks, produce a written spec that `/scaffold-frontend` will use:

### 6.1 Component tree
List every component in the page, from outermost to innermost:
```
PageLayout
  Sidebar (AppSidebar — reuse)
  MainArea
    PageHeader (title, subtitle, action button)
    PrimaryPanel
      DataTable (CompactTable for financial data)
        TableRow (× N)
    SecondaryPanel
      FilterBar
      MetricsGrid
        MetricCard (× 6)
```

### 6.2 Props and data per component
For each component:
- Props interface (name + type)
- Which S9 endpoint feeds it (`gatewayClient.<method>()`)
- Whether it needs real-time data (WebSocket/SSE)
- Which shadcn/ui primitives it uses (Table, Card, Badge, Button, Select, etc.)
- TanStack Query `staleTime` category (fundamentals 5min, OHLCV 1min, news 30s, prediction 15s)

### 6.3 Route and navigation
- URL path
- Page title (for `<title>` and breadcrumbs)
- Breadcrumb trail
- Navigation entry point (which sidebar item activates)
- Keyboard shortcut (from `g+<key>` global shortcut scheme, if applicable)

### 6.4 Open questions for implementation
List any design decisions that need resolution before implementation:
- "Should the filter bar be collapsible on mobile?"
- "Does the chart height adjust based on available data?"
- "Is there a maximum number of rows before virtualization is needed?"

---

## Phase 7 — Update DESIGN.md

After every design session, update `apps/frontend/designs/DESIGN.md` (create if absent) with any new patterns, tokens, or component decisions introduced in this session. Follow the [Stitch DESIGN.md format](https://stitch.withgoogle.com/docs/design-md/format/):

```markdown
# Worldview DESIGN.md

## 1. Visual Theme & Atmosphere
Fast, dense, unimpressed. A financial intelligence terminal — not a dashboard app.
Data takes precedence over chrome. Every pixel of UI must earn its place.

## 2. Color Palette
[OKLCH values + hex + semantic role for every token]

## 3. Typography Rules
[Font choices, scale, weight hierarchy, tabular-nums enforcement]

## 4. Component Stylings
[Buttons, cards, tables, inputs with all 8 interactive states]

## 5. Layout Principles
[4pt spacing scale, grid, panel hierarchy]

## 6. Depth & Elevation
[3-level surface scale, shadow use]

## 7. Do's and Don'ts
[Anti-patterns catalog specific to worldview]

## 8. Responsive Behavior
[Panel collapse strategy at md/sm]

## 9. Agent Prompt Guide
[Quick color reference + ready-to-use prompts for AI agents]
```

This file is what any AI agent reads to generate consistent worldview UI without needing the full design system docs.

---

## Phase 8 — Output

Produce a summary with:

```markdown
## Design Complete: <Feature Name>

### Canvas file
`apps/frontend/designs/<feature-name>.pen`

### Anti-patterns checked
<confirm all bans reviewed>

### Component breakdown
<table: component → shadcn primitives → data source → staleTime>

### S9 endpoints needed
<list — verified in docs/services/api-gateway.md>

### Missing backend endpoints (if any)
<list — these block implementation until S9 adds them>

### Implementation next step
Run: /scaffold-frontend <feature-name> — <brief description>
```

---

## Compounding Check

After every design session:
- [ ] Canvas file committed to `apps/frontend/designs/`?
- [ ] `apps/frontend/designs/DESIGN.md` updated with new patterns?
- [ ] `docs/ui/DESIGN_SYSTEM.md` updated with any new component patterns?
- [ ] Missing S9 endpoints flagged in `docs/services/api-gateway.md`?
- [ ] Design decisions documented in `docs/ui/frontend-migration.md` if they are architectural?

---

## Workflow Chain

- **After design**: Run `/scaffold-frontend <same description>` to implement
- **If S9 endpoints are missing**: Run `/prd` to spec the missing backend features first
- **If design involves new data patterns**: Run `/revise-prd` on the relevant PRD to ensure alignment
- **If existing pages feel generic**: Use `/design-ui audit <page>` to run Phase 4–5 anti-pattern review without rebuilding the canvas
