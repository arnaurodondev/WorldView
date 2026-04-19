# Competitive Financial Platform Design Research

> **Purpose**: Research document covering the design systems of 8 major financial platforms.
> Used to inform Worldview's typography, color, and layout decisions.
> **Researched**: 2026-04-13

---

## Platform-by-Platform Analysis

---

### 1. Bloomberg Terminal / Bloomberg Professional

**Background & Philosophy**

Bloomberg Terminal is the archetype of the dense professional terminal. Its design philosophy is
"conceal complexity from the user to prevent confusion or workflow disruption." Every design
decision optimises for information density and expert-user speed over discoverability. It is
deliberately NOT designed for newcomers — mastery is the assumed state.

**Typography**

| Role | Font | Notes |
|------|------|-------|
| Primary | **Bloomberg Prop Unicode N** (proportional) | Custom typeface commissioned from Matthew Carter (creator of Georgia, Verdana, Tahoma) |
| Monospaced | **Bloomberg Prop Unicode I** (mono) | Companion monospace cut of the same family |
| Special glyphs | Fraction glyphs to 1/64th granularity | Finance-specific additions for fixed-income pricing |

Bloomberg commissioned both cuts specifically for the Terminal. No other platform uses these fonts
commercially. The faces are available from Carter and Cone Type (findmyfont.com references them
under "CarterAndCone"). They are NOT available as web fonts.

**Color Palette**

| Role | Hex | Notes |
|------|-----|-------|
| Background | `#000000` | Pure black — the iconic Bloomberg terminal look |
| Default text (amber) | `#FB8B1E` | Warm amber — the brand-defining terminal color |
| Alternative amber | `#F39F41` | rgb(243,159,65) — slightly lighter variant seen in older terminals |
| Positive / up | `#4AF6C3` | Bright cyan-green (standard) |
| Negative / down | `#FF433D` | Vivid red |
| Accent / links | `#0068FF` | Royal blue |
| CVD scheme (up) | `#0068FF` | Blue replaces green for deuteranopia users |
| CVD scheme (down) | `#FF433D` | Red retained |

Source: color-hex.com/color-palette/111776 and Bloomberg's 2021 Color Accessibility article.

The Berg VS Code theme (jx22/berg) — a Bloomberg-inspired theme — uses:
- Background: `#000000`
- Primary foreground (amber): `#F49F31`
- Secondary foreground: `#D7D7D7`
- Sidebar/panel: `#202020`, `#282828`
- Error red: `#D54135`
- Green: `#5DC453`
- Cyan: `#4DC7F9`

**Layout Philosophy**

Dense terminal. Fixed-width character grid. Every pixel used. No whitespace as aesthetic — only
functional separation. Information hierarchy via color semantic (amber = neutral, red/green =
directional), not spacing or sizing. Windows snap into a tiled mosaic layout. Users build
"screens" (layouts) with F-key shortcuts.

**Navigation Pattern**

Command-line hybrid. Users type mnemonics (e.g., `AAPL US Equity GP <GO>`) to navigate. No
traditional sidebar — instead a function-key strip at the bottom and a persistent top toolbar
showing the current security context. Menus exist but are tertiary; power users never touch them.

**Data Presentation**

Pure tables everywhere. Monospaced alignment. Color-coded cells. No cards. No whitespace padding.
Row height is minimal. Charts exist but are secondary to tabular data.

**Key Differentiators**

- Custom professional typeface by Matthew Carter
- Amber on black: instantly recognisable brand identity
- CVD-accessible color schemes (2021 redesign)
- Information density that is genuinely unmatched
- Keyboard-first navigation — F1–F12 keys drive workflows

---

### 2. TradingView

**Background & Philosophy**

TradingView bridges the gap between professional tools and retail traders. Design is clean but
data-dense — "hybrid" in philosophy. Charts are the primary UI artifact; everything else
(watchlists, screener, news) supports chart analysis. The platform is also a social network for
chart ideas.

**Typography**

TradingView uses a system font stack with Trebuchet MS as one of the named families in their
charting library documentation. Their widget CSS allows `fontFamily` override. The platform
appears to use a grotesque sans-serif matching Trebuchet MS characteristics for UI elements.
The charting library documentation examples show default `fontSize` in pixels.

**Color Palette**

| Role | Hex | Notes |
|------|-----|-------|
| Background (dark) | `#131722` | Deep dark navy-black — "Mirage" in their palette |
| Accent / brand | `#2962FF` | "Dodger Blue" — primary interactive color |
| Primary text | `#D1D4DC` | Light grey — not pure white |
| Secondary text | `#787B86` | Muted grey for labels |
| Positive | `#26A69A` | Teal-green |
| Negative | `#EF5350` | Soft red |
| Panel background | `#1E222D` | Slightly lighter than main bg |
| Border | `#2A2E39` | Subtle divider |
| White (light mode bg) | `#FFFFFF` | |

Source: TradingView's documented core palette and CSS theming documentation.

**Layout Philosophy**

Chart-centric. The chart takes 70–80% of the screen. Side panels (watchlist, news, screener) are
collapsible. Top toolbar contains symbol search + interval + drawing tools. Dense but cleanly
organized. Not as extreme as Bloomberg — labels, tooltips, and hover states are all polished.

**Navigation Pattern**

Top navigation bar with tabs for: Chart, Screener, News, Markets, Ideas, Pine Editor.
Left sidebar: watchlist. Right sidebar: indicator panel. Bottom: symbol/order panel. All panels
are collapsible/resizable, giving users control over density.

**Data Presentation**

Charts first, tables second. Screener uses a compact table with small row heights. Market overview
uses sortable compact tables. Heatmap uses colored tiles (market cap-weighted). Color is used
heavily and consistently (green/teal = positive, red = negative).

**Key Differentiators**

- `#131722` dark navy background — widely imitated across the industry
- Teal-green (#26A69A) instead of saturated green — feels more professional, less garish
- Blue accent (#2962FF) for interactive elements — consistent and high-contrast
- Chart library available as an embeddable SDK — extremely wide adoption
- Custom CSS theming API exposed for embedding partners

---

### 3. Koyfin

**Background & Philosophy**

Koyfin positions itself as "Bloomberg for the rest of us" — a Bloomberg Terminal alternative for
serious individual investors and buy-side analysts. Their design is more modern and approachable
than Bloomberg but denser than retail apps like Robinhood. Dark mode was historically called
"Midnight Blue" and is now simply "Dark Mode" (as of February 2026 theme update).

**Typography**

Koyfin appears to use a geometric or humanist sans-serif for UI (consistent with DM Sans or Inter
characteristics based on the visual weight and proportions seen in screenshots). Their workspace
customization panels and dashboards show clean, compact sans-serif text at small sizes (10-12px).

**Color Palette (Dark Mode)**

Koyfin's dark mode ("Midnight Blue") is a dark navy palette distinct from TradingView's
near-black approach:

| Role | Estimated | Notes |
|------|-----------|-------|
| Background | Dark navy ~`#0D1421` | Deep navy, not black |
| Panel background | ~`#131C2E` | Slightly lighter navy |
| Card surface | ~`#1A2438` | Elevated card layer |
| Primary text | ~`#E2E8F0` | Warm white |
| Secondary text | ~`#94A3B8` | Muted slate |
| Accent (blue) | ~`#3B82F6` | Blue interactive |
| Positive | `#22C55E` | Green |
| Negative | `#EF4444` | Red |

Note: Koyfin does not publicly document their design tokens. These are approximations from visual
inspection of publicly available screenshots.

**Layout Philosophy**

Dashboard-first. Users build custom dashboards from a library of widgets (charts, tables, data
panels). Layout is grid-based and user-configurable. Denser than consumer apps but less extreme
than Bloomberg. Sidebar navigation is persistent.

**Navigation Pattern**

Left sidebar with sections: Dashboard, Equity, Macro, ETF, News, Portfolio. Top bar shows
current symbol context. Tab-based navigation within sections. Mobile also supported.

**Data Presentation**

Mix of charts and tables. Fundamental data in compact tables. Charting for price/macro data.
Custom dashboards allow mixing chart types, tables, and data cards. Color coding consistent with
industry norms (green/red).

**Key Differentiators**

- Highly customizable dashboard system (closest Bloomberg equivalent in UX model)
- "Midnight Blue" navy dark theme — warmer than TradingView's cold dark
- Macro data coverage beyond individual equities (GDP, rates, commodities)
- Bloomberg-style command bar (`/` to search any data series)

---

### 4. Finviz

**Background & Philosophy**

Finviz (Financial Visualizations) is a data-forward screener and market visualizer. Design
philosophy is utilitarian — maximum data per pixel. The classic Finviz look (since 2007) uses
default system fonts on a white background with color-coded data tables. The newer "Modern" theme
is cleaner but still dense.

**Typography**

Classic theme: System fonts, Arial/Helvetica stack. Small font sizes (11-12px) with tight row
heights — prioritising data density over readability comfort.
Modern theme: Updated sans-serif, larger minimum size, more breathing room — but still dense
compared to consumer apps.

**Color Palette (Classic / Dark variant)**

| Role | Hex | Notes |
|------|-----|-------|
| Background (light/classic) | `#FFFFFF` | White — original Finviz look |
| Background (dark) | `#111111` – `#1A1A1A` | Deep dark grey/black |
| Positive heat | `#1F9943` – `#25A244` | Forest green |
| Strong positive | `#068727` | Darker green for large gains |
| Negative heat | `#D22027` | Red |
| Strong negative | `#A01A1F` | Dark red for large losses |
| Neutral | `#888888` | Grey for flat/unchanged |
| Accent | `#2979FF` | Blue for links/interactive |
| Heat map — extreme positive | `#007D34` | Deep emerald |
| Heat map — extreme negative | `#9B0000` | Dark crimson |

**Layout Philosophy**

Pure data density. The screener shows 20+ columns in a compact table. The heat map packs hundreds
of stocks into a single viewport using market-cap-weighted tile sizing. No cards, no whitespace
padding for aesthetic purposes. Filters are exposed, not hidden behind modals.

**Navigation Pattern**

Top navigation bar: Screener, Maps, Groups, News, Portfolio, Insider, Futures, Forex.
Simple, flat nav — no mega-menus, no sidebar. Secondary filters exposed inline.

**Data Presentation**

Tables (screener), heat maps (sector/market), and simple charts (stock pages). Tables are the
core interaction model. Heat map tiles sized by market cap, colored by % change. Charts are
functional, not polished. Candlestick + technical indicator overlays.

**Key Differentiators**

- Heat map is the most imitated component in fintech
- Most data per viewport of any commercial financial platform
- Zero UX fluff — every pixel is data
- Screener filter system is industry-leading in flexibility
- Classic "no-design" look is actually a feature: signals focus on data over aesthetics

---

### 5. Interactive Brokers TWS (Trader Workstation)

**Background & Philosophy**

TWS is a professional-grade desktop trading platform built primarily in Java (Swing UI). Design
philosophy is pure function over form — TWS was designed by and for professional traders who
measure performance in milliseconds and information density. The UI has evolved incrementally over
20+ years without a ground-up redesign.

**Typography**

Java Swing defaults: System font stack, typically Arial or a system sans-serif. Fixed-width
monospace used in order entry fields and numeric columns. The IBKR Desktop (newer Electron-based
app) uses cleaner sans-serif with improved contrast.

**Color Palette (TWS System Colors)**

TWS uses a documented color key for semantic meaning:

| Role | Color | Notes |
|------|-------|-------|
| Ask price | Red | Asks are always red |
| Bid price | Blue | Bids are always blue |
| Last price (up) | Green | |
| Last price (down) | Red | |
| Order pending | Yellow | |
| Order filled | Cyan/Teal | |
| Order cancelled | Grey | |
| Dark mode background | `#121212` – `#1A1A1A` | |
| Light mode background | `#F5F5F5` – `#FFFFFF` | |

Users can further customize column colors per their preferences.

**Layout Philosophy**

Workspace-based tiling. Users create "layouts" (named workspaces) and snap panels together.
Panels include: Market Scanner, Watchlist, Order Entry, Portfolio, Charts, Options Chains, News.
Color-grouping links windows: panels in the same color group share the active symbol context.

**Navigation Pattern**

Menu-bar driven (File, Edit, View, Account, Trade). Bottom tabs for workspace switching. No
persistent sidebar. Windows-style MDI (Multiple Document Interface) — panels float or tile
within the workspace frame.

**Data Presentation**

Dense tables with color-coded cells. Bid/ask/last prices in dedicated columns. P&L computed
in real-time per row. Options chains use a distinctive two-sided table (calls left, puts right).
Charts are functional candlestick with indicator overlays.

**Key Differentiators**

- Color-linked window groups for symbol context synchronization
- Bid=blue / Ask=red is an industry convention originating from TWS
- Scroll wheels control quantity/price in order entry
- Market Scanner is the professional alternative to Finviz's screener
- TWS API is one of the most-used brokerage APIs for algorithmic trading

---

### 6. Robinhood (Mobile + Web)

**Background & Philosophy**

Robinhood pioneered zero-commission retail investing with a radically simplified, consumer-first
design philosophy. Their original design (2013–2021) emphasized green, minimalism, and approachability.
The 2024 redesign (Porto Rocha brand refresh) repositioned toward a more mature, sophisticated
aesthetic — "less is more," "bold and cutting-edge, but sophisticated and focused."

**Typography**

| Era | Font | Notes |
|-----|------|-------|
| Original (2013–2021) | Roboto Flex | Variable weight/width; used in conjunction with Google Material Design guidelines |
| Current (2024+) | **Inter** | Modern, professional grotesque; 85px/700 for hero headings; 14px/400 for body |

Numeric data: `tabular-nums` enforced throughout. The design system mandates Inter with specific
weight scales and tabular number rendering.

**Color Palette (Current — 2024+)**

| Role | Hex | Notes |
|------|-----|-------|
| Background | `#000000` | Pure black — "mandated dark primary surface" |
| Primary text | `#FFFFFF` | White |
| Accent | `#B7DF2F` | "Robin Neon" — bright yellow-green, brand-defining |
| Historical green | `#00C805` | Original Robinhood green, still used in some contexts |
| Negative | `#FF5000` | Orange-red (distinct from traditional red) |
| Neutral | `#8C8C8C` | Muted grey |
| Card surface | `#111111` | Near-black card |

**Layout Philosophy**

Consumer-clean. Minimal visual noise. Progressive disclosure — show high-level data first, details
on drill-down. Mobile-first with web adaptation. Cards are the primary layout unit. Generous
whitespace even in data views.

**Navigation Pattern**

Bottom tab bar on mobile: Home, Investing, Chat, Account. Web uses left sidebar with similar
sections. Search is prominent. No information density at the navigation level — nav is simple.

**Data Presentation**

Line charts (not candlesticks) by default — simpler, less intimidating for retail. Price change
shown as large headline number with Robin Neon green/red color coding. Portfolio shown as total
value + %change. Holdings in simple card list. News as clean article cards.

**Key Differentiators**

- Robin Neon (#B7DF2F) is the most distinctive accent color in retail fintech
- Pure black (#000000) background — more extreme than TradingView's navy
- Inter font with weight 700 at 85px for hero values — aggressive typographic confidence
- No candlesticks: line charts reduce cognitive load for retail
- 4px grid system enforced across all components

---

### 7. Seeking Alpha

**Background & Philosophy**

Seeking Alpha is a financial news and analysis platform, primarily editorial rather than trading.
Design philosophy: "A Sharp Eye" — every design element incorporates a sharp geometric feature.
Monochromatic base with orange accent. Emphasis on reading experience and portfolio monitoring
over trading execution.

**Typography**

Seeking Alpha uses a clean sans-serif for UI elements and a readable serif or slab-serif for
long-form article bodies (editorial standard). The overall visual language targets financial
professionals who consume large amounts of written analysis.

**Color Palette**

| Role | Color | Notes |
|------|-------|-------|
| Accent | Orange | Brand energy color — "infuses a sense of energy and focus" |
| Base | Monochromatic | Black/white/grey foundation |
| Positive | Green | Standard |
| Negative | Red | Standard |
| Dark mode | Available | Dark + light mode supported |

Note: Seeking Alpha does not publish detailed design tokens. The 87 Studio case study confirms
the orange accent and monochromatic base strategy but does not give hex values.

**Layout Philosophy**

Editorial-first, hybrid density. The logged-out experience is a news/content portal. The
logged-in experience adds a dashboard: portfolio tracker, ratings feed, news. Layout is
sidebar-nav + content area — familiar editorial pattern. Not a terminal.

**Navigation Pattern**

Left sidebar: My Portfolio, My Feed, Markets, News, Screener, Ratings, Analysis.
Top bar: Search, notifications, account. Tab-based content switching within sections.
Customizable sidebar collapse.

**Data Presentation**

Article cards (editorial primary). Quant ratings as badge-style components. Portfolio data in
simple tables. Stock pages combine price chart (simple line/candlestick) with news, financials,
and analyst ratings panels. Heavy use of "Quant Score" visual components.

**Key Differentiators**

- Editorial quality long-form analysis alongside data
- "Quant Score" system with visual rating indicators
- Customizable side navigation (user-configured sections)
- Orange accent on monochromatic base — unusual in fintech
- Overlay system for secondary information without navigation

---

### 8. Benzinga Pro / Benzinga

**Background & Philosophy**

Benzinga Pro is an alert-driven news and sentiment platform for active traders. Design philosophy
prioritises real-time information delivery: news alerts, market scanners, options flow. The
interface is modular workspace — users configure their screen layout like a trading terminal.

**Typography**

System sans-serif with adjustable text size. User-controlled headline height. Prioritises
readability at high information velocity (news flowing in real time).

**Color Palette**

| Role | Color | Notes |
|------|-------|-------|
| Default theme | Dark | Default is dark — easiest on eyes for long sessions |
| Alternative themes | Light, High Contrast, Antique | User-selectable |
| Ticker up | Green | Standard |
| Ticker down | Red | Standard |
| Alert highlight | Yellow/amber | Breaking news highlight color |

**Layout Philosophy**

Modular workspace. Up to 4 screen panels per workspace. Multiple named workspaces switchable by
tabs. Module-based: News Feed, Options Flow, Squawk Audio, Scanner, Charts, Calendar.
Drag-and-drop panel configuration. Primarily text/list-based (news is text, not visual).

**Navigation Pattern**

Top workspace tabs. Left/top module selector. Each workspace is independently configured.
Fast module linking — panels share symbol context automatically.

**Data Presentation**

Primarily text streams (news headlines as live feed). Options flow as dense table (ticker,
strike, expiry, premium, type). Scanner as sortable table. Audio squawk for hands-free
monitoring. Charts via TradingView integration.

**Key Differentiators**

- Real-time audio squawk (spoken market alerts)
- Options flow scanner — unique to this tier of platform
- Workspaces as named configurations (not just layouts)
- Speed-optimized news delivery (millisecond timestamps)
- Module linking for multi-panel symbol synchronization

---

## Synthesis: Cross-Platform Patterns

### Information Density Spectrum

```
Consumer          Hybrid            Professional Terminal
|-------|----------|---------|----------|---------|
Robinhood   Seeking Alpha  Koyfin  TradingView  Bloomberg
                           Finviz   Benzinga     IB TWS
```

### Color Convention Universality

These conventions appear across ALL 8 platforms without exception:

| Semantic | Color | Notes |
|----------|-------|-------|
| Positive / up | Green | Varies: `#00C805`, `#26A69A`, `#22C55E`, `#25A244` |
| Negative / down | Red | Varies: `#EF5350`, `#EF4444`, `#D22027`, `#FF433D` |
| Bid price | Blue | IB TWS convention |
| Ask price | Red | IB TWS convention |
| Alert / warning | Yellow/amber | Bloomberg, Benzinga |

NEVER break these conventions in a professional financial UI. They are muscle memory for
professional users.

### Dark Background Taxonomy

| Approach | Example | Background Hex | Character |
|----------|---------|---------------|-----------|
| Pure Black | Robinhood (2024), Bloomberg | `#000000` | Maximum contrast, stark |
| Dark Navy-Black | TradingView | `#131722` | Cold, professional, most imitated |
| Deep Navy | Koyfin (Midnight Blue) | ~`#0D1421` | Warmer, more approachable |
| Dark Charcoal | IB TWS dark, Benzinga dark | `#121212`–`#1A1A1A` | Neutral, balanced |
| White (light) | Finviz classic, Seeking Alpha | `#FFFFFF` | Legacy/editorial |

---

## Recommendations

---

### Recommendation 1: Font Choices for a Professional Financial Terminal

**Primary (UI) Font — Top Pick: IBM Plex Sans**

Rationale:
- Designed explicitly for UI environments at IBM, used in IBM Carbon Design System
- Corporate authority + humanist warmth — same balance as Inter but with more technical identity
- Available in 8 weights (Light through ExtraBold)
- Open-source, self-hostable (critical for financial products — no CDN dependency)
- Pairs perfectly with IBM Plex Mono (same design DNA)
- Used: Carbon Design System (enterprise), Linear (tech), Wealthsimple (fintech)

Alternative primary: **Inter**
- The most battle-tested UI font of 2020–2026
- Excellent at 12–14px in dark environments
- Tabular numerals via `font-variant-numeric: tabular-nums`
- Used: Robinhood, Notion, GitHub, Vercel — slightly overused in SaaS but still excellent
- Roboto as fallback (Google Material; used in older Robinhood)

**Monospace (Data / Numbers) Font — Top Pick: IBM Plex Mono**

Rationale:
- Perfect semantic pairing with IBM Plex Sans (same proportions, same weight system)
- True monospace with strong tabular alignment
- Open-source — no licensing risk
- "Technical authority" aesthetic without being a developer-tool cliché
- Used: IBM Carbon Design System, financial dashboards, code-adjacent UIs

Close second: **JetBrains Mono**
- Excellent at small sizes (10–12px)
- Slightly more character than IBM Plex Mono
- Distinguished terminal aesthetic
- Open-source

Consider: **Berkeley Mono** (commercial, ~$75 one-time)
- Designed for professional terminal/dashboard use
- Extraordinary legibility at 11–13px
- "Objectivity of machine-readable typefaces of the 70s with humanist sans-serif qualities"
- Would signal premium positioning; not open-source

**Recommended Font Stack**

```css
/* Primary UI text */
font-family: 'IBM Plex Sans', Inter, system-ui, -apple-system, sans-serif;

/* Monospace / data / numbers */
font-family: 'IBM Plex Mono', 'JetBrains Mono', 'Consolas', monospace;
```

**Type Scale for Financial Terminal**

| Role | Size | Weight | Font | Variant |
|------|------|--------|------|---------|
| Hero price | 28–36px | 700 | IBM Plex Mono | tabular-nums |
| Page title | 20px | 600 | IBM Plex Sans | |
| Section heading | 14px | 600 | IBM Plex Sans | uppercase, tracking |
| Body / article | 14px | 400 | IBM Plex Sans | |
| Table cell text | 13px | 400 | IBM Plex Sans | |
| Table cell number | 13px | 500 | IBM Plex Mono | tabular-nums |
| Label / caption | 11px | 400 | IBM Plex Sans | uppercase, tracking-wide |
| Axis label | 10px | 400 | IBM Plex Sans | |

---

### Recommendation 2: Color Palette — Professional (Non-AI-Generated)

These palettes are hand-curated from real platform analysis. They are deliberately NOT generic
Tailwind defaults or AI colour-wheel outputs.

---

#### Option A: "Midnight Terminal" (TradingView-Adjacent, Most Professional)

Inspired by TradingView's palette, refined for a slightly warmer, less cold feel.

```
Background:       #0D1117   Deep cool grey-black (GitHub Dark equivalent)
Panel surface:    #161B22   Slightly lighter (GitHub Dark inert panels)
Card surface:     #21262D   Elevated card (border-subtle territory)
Border:           #30363D   Dividers, outlines
Primary text:     #E6EDF3   Off-white (not pure white — reduces harshness)
Secondary text:   #8B949E   Muted grey (labels, captions)
Disabled text:    #484F58   Very muted (placeholders, disabled states)
Accent (blue):    #2F81F7   Adjusted blue — bright but not electric
Accent hover:     #388BFD   Slightly lighter on hover
Positive:         #3FB950   Desaturated green (not garish)
Positive strong:  #2EA043   Darker green for backgrounds
Negative:         #F85149   Soft red (not pure #FF0000)
Negative strong:  #DA3633   Darker red for backgrounds
Warning:          #D29922   Amber (alert states)
Info:             #388BFD   Same as accent
```

Rationale: GitHub Dark is the most battle-tested dark palette for dense information display.
It was designed after years of A/B testing on code (the densest text content). Financial
terminals have similar requirements.

---

#### Option B: "Deep Navy Pro" (Koyfin-Adjacent, Premium Feel)

Warmer and more distinctly "finance" — navy evokes Bloomberg, Wall Street, institutional trust.

```
Background:       #090E1B   Near-black navy
Panel surface:    #0F1929   Deep navy panel
Card surface:     #162035   Mid navy card
Border:           #1E2E47   Navy border
Primary text:     #E2E8F0   Slate-100 equivalent
Secondary text:   #94A3B8   Slate-400 equivalent
Disabled text:    #475569   Slate-600 equivalent
Accent (cyan):    #06B6D4   Cyan-500 — high contrast on navy
Accent hover:     #22D3EE   Cyan-400
Positive:         #10B981   Emerald-500
Positive bg:      #064E3B   Dark emerald tint
Negative:         #F43F5E   Rose-500
Negative bg:      #4C0519   Dark rose tint
Warning:          #F59E0B   Amber-500
Chart line 1:     #3B82F6   Blue
Chart line 2:     #8B5CF6   Purple
Chart line 3:     #EC4899   Pink
```

Rationale: Navy-on-cyan is an underused combination in fintech that still reads as deeply
professional. Cyan accent on navy background has excellent contrast and avoids the now-cliché
"blue on dark grey" pattern. The emerald positive/rose negative are more sophisticated than
generic green/red.

---

#### Option C: "Amber Terminal" (Bloomberg-Adjacent, Maximum Terminal Credibility)

The most opinionated choice — signals deliberate terminal aesthetic, not SaaS-ification.

```
Background:       #000000   Pure black (the Bloomberg choice)
Panel surface:    #111111   Near-black panels
Card surface:     #1A1A1A   Dark grey card
Border:           #2A2A2A   Subtle dark border
Primary text:     #E8E8E8   Off-white (not #FFFFFF — avoids halation)
Amber text:       #F49F31   Bloomberg amber (Berg theme verified)
Secondary text:   #8A8A8A   Muted grey
Accent (amber):   #FB8B1E   Bloomberg orange-amber (verified from color-hex)
Accent blue:      #4D9FFF   Lighter blue (readable on pure black)
Positive:         #4AF6C3   Bloomberg cyan-green (from their palette)
Negative:         #FF433D   Bloomberg red (from their palette)
Warning:          #FFD166   Yellow-amber warning
Info cyan:        #4DC7F9   Bright cyan (Berg theme verified)
```

Rationale: Deliberately evokes Bloomberg Terminal while being implementable as a web UI.
The amber accent on pure black is the highest-credibility signal for professional users.
Risk: can feel anachronistic or intimidating to non-professional users.

---

### Recommendation 3: UI Style Directions

---

#### Direction 1: "Terminal Pro" (Bloomberg / IB TWS inspiration)

Core principles:
- Pure black or near-black background
- Monospace font for ALL data (not just numbers — full terminal aesthetic)
- Amber or cyan accent — strong terminal signal
- Maximum information density (8–10px labels, 12px body, tight row heights)
- No card borders — panels defined by background color difference only
- No animations except real-time data updates (chart ticks, price flashes)
- Keyboard-first design with visible shortcut hints
- Grid-based tiled layout with resizable/movable panels

Best for: Professional traders, buy-side analysts, power users. Makes the product
feel like serious infrastructure.

Risk: Intimidating to non-experts. Requires onboarding investment.

---

#### Direction 2: "Modern Pro" (TradingView / Koyfin inspiration)

Core principles:
- Dark navy (#131722 or #0D1421) — not pure black
- IBM Plex Sans for UI text, IBM Plex Mono for numbers only
- Blue accent (either #2962FF TradingView blue or #06B6D4 cyan)
- Professional data density — compact tables but with readable line heights
- Cards with subtle borders and slight elevation (1px border, no drop shadows)
- Moderate animation: skeleton loaders, chart transitions, panel slide-in
- Sidebar navigation with icon + label
- Color-coded data with teal/green positive, red negative, amber warning

Best for: Serious individual investors, quant-adjacent professionals, fintech-savvy users.
Feels modern and premium without being intimidating.

Risk: Can feel similar to many SaaS products if executed without distinctiveness.

---

#### Direction 3: "Hybrid Institutional" (Bloomberg-meets-Modern)

Core principles:
- Deep navy (#0D1117 or #090E1B) background
- IBM Plex Sans + IBM Plex Mono pairing — the technical credibility signal
- Amber (#F49F31) as the primary accent — nods to Bloomberg without copying it
- Two-tier density: terminal-dense for data views, modern-spaced for editorial/analysis
- Heat cells for data tables (7-step red/green scale, subdued)
- Functional animation only: live price flash on update, chart crosshair
- Command palette (⌘K) as primary navigation for power users
- Subtle Bloomberg-style color semantic: amber=neutral, green=up, red=down, cyan=alert

Best for: The specific Worldview target — serious research platform that respects user
expertise without requiring Bloomberg training. Signals authority, not approachability.

Risk: Amber accent may feel unusual to users expecting blue. Needs strong implementation
to avoid feeling like a Bloomberg clone.

---

### Current Worldview Color System Assessment

The existing DESIGN_SYSTEM.md defines:

- Background: `222.2 84% 4.9%` (HSL) ≈ `#050C1A` — very dark navy-black
- Primary: `217.2 91.2% 59.8%` (HSL) ≈ `#3B82F6` — blue-500
- Positive: `142.1 76.2% 36.3%` (HSL) ≈ `#22C55E` — green-600 (solid)
- Negative: `0 72.2% 50.6%` (HSL) ≈ `#E53E3E` — red-500 (solid)
- Font: System font stack (no custom font specified)

**Assessment**: The palette is functionally correct but anonymous — it looks like a
Tailwind default dark template. It lacks a distinctive professional identity.

**Top upgrade recommendation**: Add IBM Plex Sans + IBM Plex Mono as named fonts (free,
open-source, self-hostable), and shift the accent from generic blue to either:
- The deep cyan (#06B6D4) of Direction 2 — more distinctive
- The amber (#F49F31) of Direction 3 — more professional/institutional

---

## Quick Reference: All Platforms at a Glance

| Platform | Primary Font | Background | Accent | Density |
|----------|-------------|------------|--------|---------|
| Bloomberg | Bloomberg Prop (custom/Matthew Carter) | `#000000` | `#FB8B1E` (amber) | Maximum |
| TradingView | System/Trebuchet MS | `#131722` | `#2962FF` (blue) | High |
| Koyfin | Sans-serif (similar to DM Sans/Inter) | ~`#0D1421` | ~`#3B82F6` (blue) | High |
| Finviz | Arial / system | `#FFFFFF` or `#111111` | `#2979FF` (blue) | Maximum |
| IB TWS | Arial / Java system | `#121212` | Bid=blue / Ask=red | Maximum |
| Robinhood | **Inter** | `#000000` | `#B7DF2F` (neon) | Low |
| Seeking Alpha | Sans-serif + editorial serif | White/dark | Orange | Medium |
| Benzinga Pro | System sans-serif | Dark (navy) | Green/red/amber | High |

---

## Sources

Research conducted 2026-04-13. Key references:

- Bloomberg color accessibility article: [Designing the Terminal for Color Accessibility](https://www.bloomberg.com/company/stories/designing-the-terminal-for-color-accessibility/)
- Bloomberg Prop font: [findmyfont.com — CarterAndCone](https://www.findmyfont.com/fonts/font-preview?fset=CarterAndCone&ffam=&fid=d810ff2c8adba7a86d3656229d96e781)
- Bloomberg color palette: [color-hex.com/color-palette/111776](https://www.color-hex.com/color-palette/111776)
- Bloomberg VS Code theme (Berg): [github.com/jx22/berg](https://github.com/jx22/berg)
- TradingView CSS theming docs: [tradingview.com/charting-library-docs/latest/customization/styles/](https://www.tradingview.com/charting-library-docs/latest/customization/styles/)
- Robinhood visual identity redesign: [robinhood.com/us/en/newsroom/a-new-visual-identity/](https://robinhood.com/us/en/newsroom/a-new-visual-identity/)
- Robinhood + Material Design: [design.google/library/robinhood-investing-material](https://design.google/library/robinhood-investing-material)
- Seeking Alpha design case study: [87-studio.com/work/seeking-alpha](https://www.87-studio.com/work/seeking-alpha)
- Fintech typography guide: [Typography Selection for Fintech](https://medium.com/@tamannasamantaray00/typography-selection-for-fintech-product-design-system-series-62ba0ba7c4bf)
- Financial reporting fonts: [Best Fonts for Financial Reporting — Inforiver](https://inforiver.com/blog/general/best-fonts-financial-reporting/)
- Data visualization fonts: [Datawrapper Font Guide](https://www.datawrapper.de/blog/fonts-for-data-visualization)
- IBM Plex overview: [ibm.com/plex](https://www.ibm.com/plex/)
- IBM Carbon design: [github.com/carbon-design-system/carbon](https://github.com/carbon-design-system/carbon/blob/main/docs/guides/ibm-plex.md)
- Berkeley Mono: [berkeleygraphics.com](https://berkeleygraphics.com/typefaces/berkeley-mono/)
- Benzinga Pro review: [daytradereview.com/benzinga-pro-review/](https://daytradereview.com/benzinga-pro-review/)
- Fintech platform palettes: [produkto.io/color-palettes/fintech-platform](https://produkto.io/color-palettes/fintech-platform)
- Financial dashboard palettes: [phoenixstrategy.group/blog/best-color-palettes-for-financial-dashboards](https://www.phoenixstrategy.group/blog/best-color-palettes-for-financial-dashboards)
