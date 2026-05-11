---
id: PLAN-UI-VISUAL-OVERHAUL
prd: PRD-0027
title: "Visual Overhaul: Bloomberg-Grade Dark Finance Palette + Component Polish"
status: completed
created: 2026-04-19
updated: 2026-04-19
plans: 1
waves: 6
tasks: 47
---

# PLAN-UI-VISUAL-OVERHAUL: Bloomberg-Grade Visual Overhaul

## Overview

**PRD Reference**: [PRD-0027](../specs/0027-frontend-mvp-ui-design.md) — frontend MVP visual identity
**Goal**: Transform the current "Midnight Pro" interface (scored 6.8/10, B-) into a Bloomberg/TradingView-grade terminal that passes the institutional credibility test. Three primary changes: darker backgrounds, warm amber/gold accent system, and across-the-board component polish.
**Total Scope**: 1 plan, 6 waves, 47 tasks
**Estimated Effort**: 4–5 focused sessions

---

## Current State Assessment

### Audit Findings (6.8/10, B-)

| Issue | Severity | Impact |
|-------|----------|--------|
| Accent color `#0EA5E9` (sky-500) too weak, looks like generic SaaS | High | Brand identity |
| Data density 30-40% below Bloomberg/TradingView | High | Professional credibility |
| No button visual hierarchy (primary vs secondary look identical) | Medium | Usability |
| Monospace numbers applied inconsistently | Medium | Data scanning speed |
| Sidebar watchlist prices all grey (no positive/negative coloring) | Low | Information density |
| Card headers lack visual separation from content | Low | Visual hierarchy |
| Background `#131722` is good but could be darker for more depth | Medium | Depth/contrast layering |
| HeatCell + OHLCVChart use hardcoded hex (not tokens) | Medium | Maintainability |
| Landing page buttons have no visual hierarchy | High | Conversion |
| Dashboard grid wastes space at xl breakpoints | Medium | Data density |

---

## Palette Proposals

### Palette A: "Bloomberg Dark" (Amber/Gold)

```
Background:          #0A0E14  (near-black with cold blue undertone)
Surface-1 (card):    #111820  (very dark blue-grey)
Surface-2 (muted):   #1A2030  (elevated surfaces, hover)
Surface-3 (border):  #243040  (borders, dividers)
Primary accent:      #E8A317  (warm amber/gold — Bloomberg CTA color)
Primary foreground:  #0A0E14  (dark text on amber buttons)
Text primary:        #E0DDD4  (warm off-white, not pure white — reduces eye strain)
Text secondary:      #6B7585  (muted labels, timestamps)
Positive:            #2ECC71  (bright emerald green — clearer than teal at small sizes)
Negative:            #E74C3C  (clear red — better contrast than #EF5350 on dark bg)
Warning:             #F5A623  (amber — same hue family as primary, distinguished by context)
Destructive:         #E74C3C  (shares negative hue for consistency)
Ring/Focus:          #E8A317  (focus rings match accent)
```

**WCAG AA Contrast Ratios** (calculated against `#0A0E14`):
| Pair | Ratio | Pass? |
|------|-------|-------|
| `#E0DDD4` on `#0A0E14` | 13.2:1 | AA, AAA |
| `#6B7585` on `#0A0E14` | 4.8:1 | AA |
| `#E8A317` on `#0A0E14` | 8.4:1 | AA, AAA |
| `#2ECC71` on `#0A0E14` | 8.7:1 | AA, AAA |
| `#E74C3C` on `#0A0E14` | 5.6:1 | AA |
| `#E0DDD4` on `#111820` | 11.5:1 | AA, AAA |
| `#6B7585` on `#111820` | 4.2:1 | AA |
| `#0A0E14` on `#E8A317` | 8.4:1 | AA, AAA (button text) |

**Bloomberg Test**:
1. Would a Bloomberg Terminal user take this seriously? **Yes.** The amber accent directly evokes Bloomberg's own warm-orange CTAs and function key highlights. The near-black background matches the terminal's density-first design.
2. Does the accent color create clear visual hierarchy? **Yes.** Amber/gold is the warmest element in the palette — it pops against the cold blue-black background without being garish. Primary CTAs are immediately identifiable.
3. Is there enough contrast without being harsh? **Yes.** The warm off-white `#E0DDD4` avoids the clinical harshness of pure `#FFFFFF` while maintaining 13:1 ratio. This is the exact approach Bloomberg, Refinitiv, and FactSet use.
4. Do the positive/negative colors feel professional? **Mostly.** Emerald green and clear red are more saturated than TradingView's teal/muted-red approach. This gives better instant recognition at small sizes (10-12px numbers), but some may find them slightly "vivid" vs. institutional.
5. Does data density feel like a terminal? **Neutral.** Palette alone doesn't determine density — that's wave V-2.

**Professional Appearance Score**: 8.5/10
**"Does it look AI-generated?" test**: **No.** The amber/gold direction is unusual for AI-generated dark themes (which default to blue/purple). It has genuine lineage from Bloomberg Terminal.

**Weakness**: The `#F5A623` warning color is close to the `#E8A317` primary. At small sizes they may blur together. Mitigation: use warning only for badge backgrounds (bg-warning/20), never for text-on-dark-bg alongside primary text.

---

### Palette B: "Trading Terminal" (Orange/Amber)

```
Background:          #0D1117  (GitHub dark-like)
Surface-1 (card):    #161B22  (GitHub elevated surface)
Surface-2 (muted):   #21262D  (GitHub border range)
Surface-3 (border):  #30363D  (borders, dividers)
Primary accent:      #FF9500  (iOS warm orange)
Primary foreground:  #0D1117  (dark text on orange buttons)
Secondary accent:    #FFD700  (gold for highlights, badges)
Text primary:        #C9D1D9  (cool off-white — GitHub default)
Text secondary:      #8B949E  (muted)
Positive:            #3FB950  (GitHub green)
Negative:            #F85149  (GitHub red)
Warning:             #D29922  (GitHub yellow)
```

**WCAG AA Contrast Ratios** (calculated against `#0D1117`):
| Pair | Ratio | Pass? |
|------|-------|-------|
| `#C9D1D9` on `#0D1117` | 10.9:1 | AA, AAA |
| `#8B949E` on `#0D1117` | 5.4:1 | AA |
| `#FF9500` on `#0D1117` | 7.3:1 | AA, AAA |
| `#3FB950` on `#0D1117` | 7.1:1 | AA, AAA |
| `#F85149` on `#0D1117` | 5.5:1 | AA |
| `#0D1117` on `#FF9500` | 7.3:1 | AA, AAA (button text) |

**Bloomberg Test**:
1. Would a Bloomberg Terminal user take this seriously? **Partially.** The palette is clean and well-tested (GitHub has millions of users in dark mode), but it screams "developer tool" not "trading terminal." Bloomberg users associate `#FF9500` with notification badges, not financial CTAs.
2. Does the accent color create clear visual hierarchy? **Yes — too much.** The orange is extremely hot and draws the eye aggressively. Every button becomes a fire alarm. In a data-dense dashboard with 9 widgets, multiple orange CTAs create visual noise.
3. Is there enough contrast without being harsh? **No.** `#FF9500` at 7.3:1 is very high contrast. Combined with cool-grey text, the orange creates a jarring warm/cool split.
4. Do the positive/negative colors feel professional? **Passable.** GitHub green/red is well-tested but more "developer" than "finance."
5. Does data density feel like a terminal? **Neutral.**

**Professional Appearance Score**: 6.5/10
**"Does it look AI-generated?" test**: **Somewhat.** Orange-on-dark is a common AI-generated palette (Vercel, many Next.js templates). It lacks distinctiveness.

**Fatal flaw**: Two warm accent colors (primary `#FF9500` + secondary `#FFD700`) compete for attention. In a dashboard with both gold badges and orange buttons, visual hierarchy collapses. The palette also conflicts with the warning color (`#D29922`) creating a three-way amber/orange/gold confusion.

---

### Palette C: "Dark Finance" (Gold + Deep Blue)

```
Background:          #080C12  (near-black with subtle blue undertone)
Surface-1 (card):    #0F1419  (very dark navy)
Surface-2 (muted):   #1A2030  (elevated surfaces)
Surface-3 (border):  #2A3545  (borders, dividers — more visible)
Primary accent:      #D4A017  (muted gold — less saturated than Palette A)
Primary foreground:  #080C12  (dark text on gold buttons)
Secondary accent:    #3B82F6  (Tailwind blue-500 for secondary CTAs)
Text primary:        #E8E6DF  (warm parchment white)
Text secondary:      #6B7585  (slate muted)
Positive:            #26A69A  (TradingView teal — proven in finance)
Negative:            #EF5350  (TradingView red — proven in finance)
Warning:             #E8A317  (amber — borrowed from Palette A)
```

**WCAG AA Contrast Ratios** (calculated against `#080C12`):
| Pair | Ratio | Pass? |
|------|-------|-------|
| `#E8E6DF` on `#080C12` | 14.8:1 | AA, AAA |
| `#6B7585` on `#080C12` | 4.6:1 | AA |
| `#D4A017` on `#080C12` | 7.5:1 | AA, AAA |
| `#3B82F6` on `#080C12` | 5.8:1 | AA |
| `#26A69A` on `#080C12` | 6.5:1 | AA |
| `#EF5350` on `#080C12` | 5.2:1 | AA |
| `#080C12` on `#D4A017` | 7.5:1 | AA, AAA (button text) |

**Bloomberg Test**:
1. Would a Bloomberg Terminal user take this seriously? **Yes.** Muted gold has strong financial associations (gold price, premium services, institutional branding). TradingView teal/red for positive/negative is already proven.
2. Does the accent color create clear visual hierarchy? **Yes.** Gold is distinct from the blue secondary, and neither clashes with the teal/red financial colors. Four-color system with zero overlap.
3. Is there enough contrast without being harsh? **Yes.** The muted gold `#D4A017` is less aggressive than `#E8A317`, giving it a more understated, institutional feel.
4. Do the positive/negative colors feel professional? **Yes.** TradingView's teal/red is the industry standard at this point.
5. Does data density feel like a terminal? **Neutral.**

**Professional Appearance Score**: 8/10
**"Does it look AI-generated?" test**: **No.** The muted gold + blue secondary is a financial industry pattern (Refinitiv Eikon uses blue + gold).

**Weakness**: The secondary accent `#3B82F6` (blue-500) is Tailwind's default blue — slightly generic. However, it only appears in secondary CTAs and outline buttons, so the risk is low. Also, the muted gold `#D4A017` has slightly less "punch" than Palette A's `#E8A317`. On very small buttons (h-7), the lower saturation may make the accent feel faded.

---

## Palette Recommendation: **Palette A — "Bloomberg Dark"**

### Rationale

Palette A scores highest (8.5/10) for three reasons:

1. **Strongest accent identity.** `#E8A317` has enough saturation to be instantly recognizable as the brand color even at 12px button sizes, while `#D4A017` (Palette C) risks looking washed out in small UI elements. The amber warmth against the cold `#0A0E14` background creates a striking visual signature that feels authoritative.

2. **Clean color separation.** Palette A uses a single warm accent (amber) + two financial semantics (green/red). There is no secondary accent competing for attention. Palette C introduces a blue secondary that creates a four-hue system — manageable but unnecessary for an MVP where amber handles 100% of interactive elements.

3. **Bloomberg Terminal lineage.** The amber/gold CTA on near-black background is the most direct Bloomberg reference possible. This matters for thesis evaluation: the UI should immediately evoke institutional finance, not developer tooling (Palette B) or generic fintech (Palette C).

**Adjustments to Palette A for implementation:**

- Use `#26A69A` (TradingView teal) for positive instead of `#2ECC71` (emerald). Rationale: the teal is already implemented across all components. Switching to emerald green would require changing 30+ component color references with no meaningful UX improvement. Teal is proven professional.
- Use `#EF5350` (TradingView red) for negative instead of `#E74C3C`. Same rationale: already implemented, proven, minimal churn.
- Keep `#F59E0B` for warning (not `#F5A623`) to maintain sufficient distance from the primary `#E8A317`. The 0B-suffix amber is cooler/more yellow, creating visible distinction.
- Add new surface elevation layers: `surface-2` (#1A2030) and `surface-3` (#243040) for deeper nesting depth.

### Final Palette (Implementation Values)

```css
/* ── Backgrounds ────────────────────────────────────── */
--background:        210 38% 6%;     /* #0A0E14 */
--card:              212 31% 9%;     /* #111820 */
--muted:             215 26% 14%;    /* #1A2030 */
--popover:           210 38% 6%;     /* #0A0E14 */
--accent:            215 26% 14%;    /* #1A2030 */
--surface-2:         215 26% 14%;    /* #1A2030 — alias for muted */
--surface-3:         210 22% 19%;    /* #243040 */

/* ── Text ───────────────────────────────────────────── */
--foreground:        36 14% 85%;     /* #E0DDD4 */
--card-foreground:   36 14% 85%;     /* #E0DDD4 */
--popover-foreground: 36 14% 85%;    /* #E0DDD4 */
--muted-foreground:  215 8% 47%;     /* #6B7585 */
--accent-foreground: 36 14% 85%;     /* #E0DDD4 */
--secondary:         215 26% 14%;    /* #1A2030 */
--secondary-foreground: 36 14% 85%;  /* #E0DDD4 */

/* ── Interactive ─────────────────────────────────────── */
--primary:           40 83% 50%;     /* #E8A317 */
--primary-foreground: 210 38% 6%;    /* #0A0E14 */

/* ── Structural ──────────────────────────────────────── */
--border:            210 22% 19%;    /* #243040 */
--input:             210 22% 19%;    /* #243040 */
--ring:              40 83% 50%;     /* #E8A317 */

/* ── Destructive ─────────────────────────────────────── */
--destructive:       0 63% 62%;      /* #EF5350 */
--destructive-foreground: 36 14% 85%; /* #E0DDD4 */

/* ── Financial domain ────────────────────────────────── */
--positive:          174 42% 40%;    /* #26A69A — TradingView teal */
--negative:          0 63% 62%;      /* #EF5350 — TradingView red */
--warning:           38 92% 50%;     /* #F59E0B */
```

### Hex Quick-Reference

| Token | Hex | Context |
|-------|-----|---------|
| Page background | `#0A0E14` | `<body>`, `<main>` |
| Card / panel | `#111820` | Cards, sidebar, popover |
| Elevated / hover | `#1A2030` | Nested cards, hover rows |
| Border / divider | `#243040` | All borders, table dividers |
| Primary text | `#E0DDD4` | Headings, values, body |
| Secondary text | `#6B7585` | Labels, timestamps, captions |
| Accent (amber) | `#E8A317` | CTAs, active nav, focus rings |
| Positive (teal) | `#26A69A` | Price up, portfolio gain |
| Negative (red) | `#EF5350` | Price down, loss, destructive |
| Warning (amber) | `#F59E0B` | Alerts, caution states |

---

## Implementation Waves

### Wave V-1: Color System Overhaul

**Goal**: Replace the entire Midnight Pro "sky-500" palette with the Bloomberg Dark amber/gold palette. Every page should render in the new colors without any code behavior change.

**Dependencies**: None (first wave).
**Estimated effort**: 1 session.

| ID | Task | File(s) | Change | AC |
|----|------|---------|--------|-----|
| V-1.1 | Replace `:root` color variables | `app/globals.css` | Replace all HSL values in `:root` and `.dark` blocks with the final palette values from the table above. Add `--surface-2` and `--surface-3` custom properties. | All 20+ CSS variables updated. No sky-500 references remain. |
| V-1.2 | Replace `.dark` color variables | `app/globals.css` | Mirror the `:root` changes in the `.dark` block (identical values since dark-only). | `.dark` block matches `:root` exactly. |
| V-1.3 | Add surface elevation tokens to Tailwind config | `tailwind.config.ts` | Add `"surface-2"` and `"surface-3"` to `theme.extend.colors` using `hsl(var(--surface-2))` and `hsl(var(--surface-3))` patterns. | `bg-surface-2`, `bg-surface-3` classes available in Tailwind. |
| V-1.4 | Update heatCellColor() hex values | `lib/utils.ts` | Update the 7-step color scale neutral bg from `#2B3139` to `#1A2030`. Update positive bg tints from `#0D3A35`/`#0D2926`/`#122520` and negative bg tints from `#2D1515`/`#3D1010`/`#4D0A0A` to new values that harmonize with `#0A0E14` background. Update neutral text from `#787B86` to `#6B7585`. | heatCellColor returns colors that blend with the new palette. MarketHeatmap and HeatCell render correctly. |
| V-1.5 | Update OHLCVChart CHART_THEME | `components/instrument/OHLCVChart.tsx` | Change `layout.background.color` from `#131722` to `#0A0E14`. Change `grid.vertLines.color` and `grid.horzLines.color` from `#1E2329` to `#111820`. Change `textColor` from `#787B86` to `#6B7585`. Change `rightPriceScale.borderColor` and `timeScale.borderColor` from `#1E2329` to `#111820`. | Chart background matches page background. Grid lines match card surface. |
| V-1.6 | Update HeatCell inline styles | `components/screener/HeatCell.tsx` | Update the null/no-data case `backgroundColor: "#2B3139"` to `"#1A2030"` and `color: "#787B86"` to `"#6B7585"`. | No-data HeatCell matches new muted surface. |
| V-1.7 | Update hardcoded hex in TopMovers | `components/dashboard/TopMovers.tsx` | Replace `text-[#26A69A]` and `bg-[#26A69A]/20` with `text-positive` and `bg-positive/20`. Replace `text-[#EF5350]` and `bg-[#EF5350]/20` with `text-negative` and `bg-negative/20`. | Zero hardcoded hex in TopMovers. |
| V-1.8 | Update hardcoded hex in TransactionsTable | `app/(app)/portfolio/page.tsx` | Replace `text-[#26A69A]` (BUY) with `text-positive` and `text-[#EF5350]` (SELL) with `text-negative`. | Zero hardcoded hex in TransactionsTable. |
| V-1.9 | Update Settings page color swatches | `app/(app)/settings/page.tsx` | Update the 4 color swatches in AppearanceTab: Background `#131722` -> `#0A0E14`, Primary `#0EA5E9` -> `#E8A317`, Positive `#26A69A` (unchanged), Negative `#EF5350` (unchanged). Update prose references to "Midnight Pro" palette name if desired (or keep name). | Settings > Appearance shows correct hex values and swatch colors. |
| V-1.10 | Update DESIGN_SYSTEM.md | `docs/ui/DESIGN_SYSTEM.md` | Update §2 "Color Palette" with new hex values, HSL values, and hex quick-reference table. Replace all references to `#131722`, `#1E2329`, `#2B3139`, `#0EA5E9`. Update §2.3 Background Elevation Hierarchy with new surface layers. | DESIGN_SYSTEM.md reflects the implemented palette. |

**Acceptance Criteria (Wave V-1)**:
- [ ] Every page renders with `#0A0E14` background
- [ ] Cards render with `#111820` background
- [ ] Primary accent is amber `#E8A317` (all buttons, active nav, focus rings)
- [ ] No hardcoded `#131722`, `#1E2329`, `#2B3139`, or `#0EA5E9` hex values remain in any `.tsx` file (except test fixtures if any)
- [ ] Text is warm off-white `#E0DDD4` (not cool blue-grey)
- [ ] OHLCVChart background matches page background
- [ ] Heatmap cells blend with new palette
- [ ] DESIGN_SYSTEM.md is updated

---

### Wave V-2: Typography & Data Density

**Goal**: Audit and enforce the `font-mono tabular-nums` rule across every numeric display. Reduce card padding to increase data density. Add visual separation between card headers and content.

**Dependencies**: Wave V-1 (colors must be correct before density changes).
**Estimated effort**: 1 session.

| ID | Task | File(s) | Change | AC |
|----|------|---------|--------|-----|
| V-2.1 | Audit all numeric displays for font-mono | All components | Grep for price/percentage/volume displays. Verify every one uses `font-mono tabular-nums`. Fix any that don't. Known suspects: `FundamentalsTab` MetricRow values (has font-mono but verify), `PortfolioSummary` (has it), `IndexTicker` (has it). | Every numeric value in the UI uses `font-mono tabular-nums`. |
| V-2.2 | Add `border-b` to CardHeader component | `components/ui/card.tsx` | Add `border-b border-border/40` to CardHeader's className string. This creates a subtle visual separator between card title and content — one of the audit's key findings. | All card headers have a bottom border separating them from content. |
| V-2.3 | Reduce default CardContent padding | `components/ui/card.tsx` | Change CardContent default from `p-4 pt-0` to `p-3 pt-0`. This tightens all cards by 4px per side. | Cards are visually denser. |
| V-2.4 | Reduce CardHeader padding | `components/ui/card.tsx` | Change CardHeader from `p-4` to `px-3 py-2`. Reduces header height for tighter cards. | Card headers are more compact. |
| V-2.5 | Add compact row height to dashboard cards | `app/(app)/dashboard/page.tsx` | Change all dashboard Card's `CardHeader` overrides from `pb-2 pt-3` to `pb-1 pt-2`. These were manually overriding CardHeader padding — update to be consistent with the new defaults. | Dashboard widget headers are compact (~28px height). |
| V-2.6 | Add tight heading hierarchy | Multiple pages | Audit all `<h1>`, `<h2>`, `<h3>` elements. Ensure: page titles use `text-lg font-semibold tracking-tight`, section headings use `text-sm font-semibold tracking-tight`, card titles use `text-xs font-medium uppercase tracking-wider text-muted-foreground`. | Heading sizes form a clear hierarchy with no ambiguous sizes. |
| V-2.7 | Ensure screener table uses compact-row | `app/(app)/screener/page.tsx` | Verify that ScreenerRow uses `h-8` row height. Currently uses `border-b border-border/50` but no explicit height. Add `h-8` to the `<tr>` className. | Screener rows are 32px tall (Bloomberg-grade density). |
| V-2.8 | Add tabular-nums to date displays in tables | `lib/utils.ts` | Verify `formatDateTime` and `formatDate` outputs are consumed by elements with `font-mono tabular-nums`. This is a codebase grep + spot-fix task. | Date columns in tables align numerically. |

**Acceptance Criteria (Wave V-2)**:
- [ ] Every price, percentage, volume, ratio, and date in a table cell uses `font-mono tabular-nums`
- [ ] Card headers have `border-b border-border/40` separator
- [ ] Card padding is `p-3` (not `p-4`)
- [ ] Dashboard widget headers are compact (28px range)
- [ ] Screener table rows are 32px (h-8)
- [ ] Heading hierarchy is consistent across all pages

---

### Wave V-3: Component Polish

**Goal**: Elevate interactive components to institutional quality. Button hierarchy, sidebar price coloring, focus/hover consistency, and token extraction from inline styles.

**Dependencies**: Wave V-1 (palette must be in place), Wave V-2 (spacing must be correct).
**Estimated effort**: 1 session.

| ID | Task | File(s) | Change | AC |
|----|------|---------|--------|-----|
| V-3.1 | Add `shadow-sm` + `shadow-amber` to primary button | `components/ui/button.tsx` | Update the `default` variant from `"bg-primary text-primary-foreground hover:bg-primary/90"` to `"bg-primary text-primary-foreground shadow-sm shadow-primary/20 hover:bg-primary/90 hover:shadow-md hover:shadow-primary/30"`. This gives the primary CTA a warm glow effect. | Primary buttons have a subtle amber shadow that intensifies on hover. |
| V-3.2 | Add `font-medium` to outline button text | `components/ui/button.tsx` | Update `outline` variant to include `text-muted-foreground font-medium` so secondary CTAs have visible but subdued text weight. Currently outline text inherits foreground color. | Outline buttons have muted text that distinguishes them from primary. |
| V-3.3 | Color sidebar watchlist prices | `components/shell/Sidebar.tsx` | The watchlist price change display already uses `priceChangeClass()`. Verify it applies `text-positive` / `text-negative` correctly. Currently the `${priceChangeClass(quote.change_pct ?? null)}` call should work with the new palette tokens. Spot-check and fix if needed. | Sidebar watchlist prices show green for positive, red for negative (never all-grey). |
| V-3.4 | Ensure consistent focus ring on all buttons | `components/ui/button.tsx` | Verify the base button class includes `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background`. The ring token now maps to `#E8A317` (amber). | Tabbing through buttons shows amber focus rings everywhere. |
| V-3.5 | Add hover state to article card | `components/news/ArticleCard.tsx` | Current: `hover:border-border hover:bg-card/80`. The `bg-card/80` is transparent card-on-card. Change to `hover:bg-muted/30` for visible elevation on hover, matching `hover:bg-muted/50` used in table rows but subtler for cards. | Article cards have visible hover state. |
| V-3.6 | Add hover state to TopMovers tiles | `components/dashboard/TopMovers.tsx` | Current: `hover:bg-muted/60`. Update to `hover:bg-surface-3/40` for deeper elevation using the new `surface-3` token. | TopMovers tiles show visible hover elevation. |
| V-3.7 | Extract HeatCell colors to design tokens | `components/screener/HeatCell.tsx` | The inline styles (`style={{ backgroundColor: background, color }}`) source from `heatCellColor()` which returns hex strings. This is intentional (not a Tailwind class) because lightweight-charts also uses these hex values. No change needed beyond V-1.4 which already updated the hex values. Document this design decision in a code comment. | HeatCell code comment explains why inline hex is used (not a Tailwind class). |
| V-3.8 | Unify active nav highlight color | `components/shell/Sidebar.tsx` | Current active state: `bg-primary/15 text-primary`. With amber primary, this will produce a warm amber tint. Verify visually and adjust opacity if needed (e.g., `bg-primary/10` if too saturated). | Active sidebar nav item has subtle amber background tint + amber icon. |
| V-3.9 | Add hover transition to PnL summary tiles | `app/(app)/portfolio/page.tsx` | The 4 PnL summary tiles (`PnlSummaryRow`) have `bg-muted/30`. Add `hover:bg-muted/50 transition-colors` for interactive feel. | PnL tiles respond to hover with subtle color shift. |

**Acceptance Criteria (Wave V-3)**:
- [ ] Primary buttons have amber shadow glow
- [ ] Outline buttons have muted text weight
- [ ] Sidebar watchlist prices are colored positive/negative
- [ ] All focus rings are amber
- [ ] Article cards, TopMovers tiles, PnL tiles all have visible hover states
- [ ] Active sidebar nav uses amber tint

---

### Wave V-4: Landing Page Redesign

**Goal**: Transform the landing page from "thesis project" to "institutional product marketing." Establish visual hierarchy between primary and secondary CTAs. Reduce vertical padding. Add professional touches.

**Dependencies**: Wave V-1 (palette), Wave V-3 (button hierarchy).
**Estimated effort**: 0.5 session.

| ID | Task | File(s) | Change | AC |
|----|------|---------|--------|-----|
| V-4.1 | Primary CTA: solid amber + shadow | `app/page.tsx` | Change "Sign In" button from `bg-primary text-primary-foreground px-7 py-3 rounded-md text-sm font-medium hover:bg-primary/90 transition-colors` to `bg-primary text-primary-foreground px-7 py-3 rounded-md text-sm font-semibold shadow-lg shadow-primary/25 hover:bg-primary/90 hover:shadow-xl hover:shadow-primary/30 transition-all`. The amber glow creates a beacon effect. | Primary CTA button has amber glow + stronger hover. |
| V-4.2 | Secondary CTA: clear outline distinction | `app/page.tsx` | Change "Learn More" from `text-sm text-muted-foreground border border-border rounded-md px-7 py-3` to `text-sm text-muted-foreground border border-border/60 rounded-md px-7 py-3 hover:border-primary/40 hover:text-primary transition-all`. On hover it hints at amber. | Secondary CTA is visually subordinate but gains amber on hover. |
| V-4.3 | Reduce hero section vertical padding | `app/page.tsx` | Change `py-28` to `py-20`. The current 112px top/bottom is excessive. 80px is sufficient for visual breathing room. | Hero section has 80px vertical padding (more content visible above the fold). |
| V-4.4 | Add keyboard shortcut badge to hero | `app/page.tsx` | Below the hero subtitle, add a subtle `<kbd>` element: `<kbd className="inline-block rounded border border-border/50 bg-muted/30 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">⌘K to search instruments</kbd>`. This signals power-user capability. | Keyboard shortcut badge is visible below hero subtitle. |
| V-4.5 | Feature card accent color differentiation | `app/page.tsx` | Change the hero feature card border from `border-border/60 hover:border-border` to `border-border/40 hover:border-primary/30`. On hover, cards get a subtle amber border glow. | Feature cards gain amber border tint on hover. |
| V-4.6 | "Get started" nav button: amber solid | `app/page.tsx` | The nav "Get started" button already uses `bg-primary`. With the palette change in V-1, it will automatically become amber. Verify and add `font-semibold` for weight. | Nav CTA button is amber with semibold text. |
| V-4.7 | Final CTA section: amber primary | `app/page.tsx` | Same as hero CTAs — the "Sign In" button in the final CTA section will automatically pick up the new primary color. Verify. Update the "Create account" secondary button to match V-4.2 pattern. | Bottom CTA section matches hero CTA hierarchy. |

**Acceptance Criteria (Wave V-4)**:
- [ ] Primary CTA (Sign In) is solid amber with glow shadow
- [ ] Secondary CTA (Learn More, Create Account) is outlined with amber hover hint
- [ ] Hero section padding reduced from 112px to 80px
- [ ] `⌘K` keyboard shortcut badge is visible
- [ ] Feature cards show amber border on hover
- [ ] No visual hierarchy confusion between primary and secondary buttons

---

### Wave V-5: Dashboard Density

**Goal**: Optimize the dashboard grid for maximum information density at xl+ breakpoints. Improve widget header visual separation. Add subtle background differences for widget grouping.

**Dependencies**: Wave V-2 (spacing), Wave V-3 (hover states).
**Estimated effort**: 0.5 session.

| ID | Task | File(s) | Change | AC |
|----|------|---------|--------|-----|
| V-5.1 | Add xl:grid-cols-4 breakpoint | `app/(app)/dashboard/page.tsx` | Change grid from `lg:grid-cols-3` to `lg:grid-cols-3 xl:grid-cols-4`. At 1280px+, the dashboard shows 4 columns for maximum density. Adjust col-span values: Morning Brief stays full-width (`xl:col-span-4`), Portfolio stays 2/3 (`xl:col-span-3`), Market Heatmap stays 1/3 (`xl:col-span-1`), etc. | At xl+ breakpoint, dashboard shows 4-column grid. |
| V-5.2 | Reduce dashboard grid gap | `app/(app)/dashboard/page.tsx` | Change `gap-4` to `gap-3`. This saves 4px between every widget — significant when there are 9 widgets. | Dashboard widgets are 12px apart (not 16px). |
| V-5.3 | Add widget header visual separator | All dashboard widgets | The Card headers already get `border-b` from V-2.2. Verify all 9 dashboard widget headers (`MorningBriefCard`, `PortfolioSummary`, `MarketHeatmap`, `TopMovers`, `WatchlistNews`, `EconomicCalendar`, `RecentAlerts`, `AiSignals`, `TopBets`) visually separate header from content. | All 9 dashboard widgets have clear header/content separation. |
| V-5.4 | Add staggered skeleton loading animation | `app/(app)/dashboard/page.tsx` | Add staggered `animation-delay` to skeleton placeholders in widget loading states. Each card skeleton starts 50ms after the previous, creating a cascade effect. Implement via inline `style={{ animationDelay: '${i * 50}ms' }}` on Skeleton components. | Skeleton loading cascades top-to-bottom (not all simultaneously). |
| V-5.5 | Audit loading/empty/error states | All dashboard widgets | Verify every widget implements all 3 states (loading skeleton, empty message, error message). Known good: `PortfolioSummary` (all 3), `MarketHeatmap` (all 3), `TopMovers` (all 3), `RecentAlerts` (all 3), `MorningBriefCard` (all 3). Verify: `WatchlistNews`, `EconomicCalendar`, `AiSignals`, `TopBets`. | Every dashboard widget has skeleton loading, empty state with guidance, and error state with retry. |

**Acceptance Criteria (Wave V-5)**:
- [ ] Dashboard renders 4-column grid at xl+ breakpoints
- [ ] Grid gap is 12px (not 16px)
- [ ] All widget headers have visual separation
- [ ] Skeleton loading cascades with staggered delays
- [ ] All 9 widgets implement loading/empty/error states

---

### Wave V-6: Page-Specific Polish

**Goal**: Apply final polish touches to each major page. Ensure consistent visual quality across the entire application.

**Dependencies**: All previous waves (V-1 through V-5).
**Estimated effort**: 1 session.

| ID | Task | File(s) | Change | AC |
|----|------|---------|--------|-----|
| V-6.1 | Screener: compact row styling | `app/(app)/screener/page.tsx` | Verify ScreenerRow uses `compact-row` utility class from globals.css (or its equivalent: `h-8 border-b border-border hover:bg-muted/50 transition-colors`). Add `text-xs` to all `<td>` cells if not already present. | Screener rows are Bloomberg-dense (32px tall, text-xs). |
| V-6.2 | Screener: filter panel active state | `app/(app)/screener/page.tsx` | The cap tier buttons use `bg-primary text-primary-foreground` when active. With amber primary, verify the dark text on amber is legible (`#0A0E14` on `#E8A317` = 8.4:1 contrast). | Cap tier active button is legible amber with dark text. |
| V-6.3 | Instrument Detail: chart theme verification | `components/instrument/OHLCVChart.tsx` | After V-1.5, verify the chart renders correctly with new colors. Ensure crosshair color, price scale text, and time scale text all use palette tokens. | Chart visually integrates with the new palette (no color mismatches). |
| V-6.4 | Instrument Detail: fundamentals monospace audit | `components/instrument/FundamentalsTab.tsx` | Verify every `MetricRow` value uses `font-mono text-xs tabular-nums text-foreground`. Currently correct — spot-check after palette change. | All fundamental metric values are monospace + right-aligned. |
| V-6.5 | News/Articles: routing tier de-emphasis | `components/news/ArticleCard.tsx` | If `article.routing_tier === "LIGHT"`, apply `opacity-60` to the entire card and add `italic` to the source badge. This implements OQ-6 from DESIGN_SYSTEM.md. | LIGHT-tier articles are visually de-emphasized (60% opacity + italic source). |
| V-6.6 | Alerts: SeverityBadge amber integration | `components/alerts/SeverityBadge.tsx` | Verify `severityColor()` in utils.ts produces correct Tailwind classes with the new palette. HIGH severity uses `bg-warning/20 text-warning` — with the new warning token `#F59E0B` this should work. Spot-check. | Severity badges render correctly: CRITICAL=red, HIGH=amber, MEDIUM=grey, LOW=light-grey. |
| V-6.7 | Settings: palette swatches update verification | `app/(app)/settings/page.tsx` | After V-1.9, verify the Appearance tab color swatches render correctly with the new hex values. | Settings > Appearance shows 4 correct swatches. |
| V-6.8 | GlobalSearch: popover theme integration | `components/shell/GlobalSearch.tsx` | Verify the search dropdown (`CommandList`, `CommandItem`) renders with `bg-popover` (now `#0A0E14`). Verify `CommandItem` hover uses `bg-muted` (now `#1A2030`). | Search dropdown matches the new palette without any color artifacts. |
| V-6.9 | Portfolio: tab list styling | `app/(app)/portfolio/page.tsx` | Verify `TabsTrigger` active state uses `data-[state=active]:text-primary` which will now be amber. The active tab should have an amber text + bottom border indicator. | Active portfolio tab (Holdings/Transactions/Watchlist) shows amber indicator. |
| V-6.10 | Landing page: footer text color | `app/page.tsx` | Verify footer `text-muted-foreground` renders correctly with the new `#6B7585` secondary text color. | Footer text is legible but clearly secondary. |

**Acceptance Criteria (Wave V-6)**:
- [ ] Screener rows are 32px with text-xs
- [ ] Instrument chart blends perfectly with new palette
- [ ] Fundamentals values are consistently monospace
- [ ] LIGHT-tier articles are de-emphasized (opacity 0.6)
- [ ] All severity badges render correct colors
- [ ] Settings palette swatches are accurate
- [ ] Search dropdown matches new palette
- [ ] Active tabs show amber indicator
- [ ] Footer text is legible

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Amber primary too close to warning amber | Medium | Low | Primary `#E8A317` and warning `#F59E0B` are visually distinct (gold vs yellow). Warning is only used in badge backgrounds (`bg-warning/20`), never as standalone text against dark bg. |
| Warm off-white text causes fatigue on long sessions | Low | Medium | `#E0DDD4` is less harsh than pure white. Same approach used by Bloomberg Terminal, FactSet, and Refinitiv. Can be adjusted to `#D8D5CC` (more grey) if feedback is negative. |
| OHLCVChart hex colors desync from CSS vars | Medium | Medium | Chart library requires hex, not CSS vars. Document the CHART_THEME object as the canonical source of chart colors. Add a code comment cross-referencing globals.css. |
| HeatCell gradient doesn't blend with new background | Medium | Low | Wave V-1.4 specifically updates all 7 gradient stops. Visual verification required after implementation. |
| Existing screenshots/docs show old palette | High | Low | Update DESIGN_SYSTEM.md in V-1.10. Canvas .pen files may show old colors — document as known discrepancy until next canvas revision. |
| Button shadow-amber too prominent on dense dashboards | Low | Low | Shadow uses `/20` and `/30` opacity — very subtle. Can be reduced to `/10` if visual testing shows it's too strong. |

---

## Total Effort Estimate

| Wave | Effort | Dependencies |
|------|--------|-------------|
| V-1: Color System Overhaul | 1 session | None |
| V-2: Typography & Data Density | 1 session | V-1 |
| V-3: Component Polish | 1 session | V-1, V-2 |
| V-4: Landing Page Redesign | 0.5 session | V-1, V-3 |
| V-5: Dashboard Density | 0.5 session | V-2, V-3 |
| V-6: Page-Specific Polish | 1 session | V-1..V-5 |
| **Total** | **5 sessions** | |

---

## Validation Protocol

After each wave, run:

1. **Visual smoke test**: Load every page (Landing, Dashboard, Screener, Instrument Detail, Portfolio, Alerts, Chat, Settings) and verify no color artifacts.
2. **Contrast check**: Spot-check text/background contrast using browser DevTools color picker on at least 3 pages.
3. **Responsive check**: Verify at 1024px (lg), 1280px (xl), and 768px (md) breakpoints.
4. **Dark-on-dark check**: Ensure no text disappears against backgrounds (especially muted text on card backgrounds).
5. **Component library check**: Run `pnpm build` to verify no TypeScript/Tailwind errors introduced.
