# PRD-0027 — Worldview Frontend MVP: Complete UI Design Specification

> **Status**: Draft (Revision 2.0) — 2026-04-12
> **Author**: Arnau Rodon
> **Revision History**: v1.0 initial draft → v2.0 comprehensive UX/data overhaul (professional design, full backend data surface, entity resolution, landing page redesign)
> **Dependencies**: PRD-0025 (auth foundation, Wave E pending), PRD-0026 (news intelligence APIs, draft)
> **Next**: `/design-ui` → pencil.dev canvas redesign (all pages) | then `/plan` → implementation waves

---

## 1. Problem Statement

### 1.1 The Market Gap

The financial intelligence platform market has four distinct tiers, none of which is satisfactory for the professional mid-market user:

| Platform | Price | Strengths | Fatal Gaps |
|----------|-------|-----------|-----------|
| **Bloomberg Terminal** | $32,000/yr | Comprehensive, real-time, institutional | Dated UX, inaccessible pricing, no AI copilot, no knowledge graphs |
| **LSEG Workspace** | $22,000–50,000/yr | Research-grade data | Same pricing and UX problems as Bloomberg |
| **Koyfin** | $0–299/yr | Strong fundamentals UI | No AI, no entity graphs, no prediction markets, no news intelligence scoring |
| **Finviz** | $0–39.99/mo | Powerful screener, heat maps | No AI, no knowledge graph, no fundamentals depth beyond screening |
| **TradingView Pro** | $0–59/mo | Excellent charts, community ideas | Shallow fundamentals, no AI research copilot, no entity graph |
| **Interactive Brokers** | Commission-based | Comprehensive TWS | Steep learning curve, built for trading not research, no AI |
| **ZeroTerminal** | Emerging | AI-native terminal | Early stage, limited data integrations |
| **Robinhood/Trading212** | Free | Beautiful consumer UX | Toy-level data depth |

The **professional mid-market** (research analysts, quant traders, active retail investors) has **no platform** combining: modern AI-native UX + deep fundamentals (18 sections) + news intelligence + entity knowledge graphs + prediction markets + configurable workspace. This gap is the Worldview opportunity.

### 1.2 Worldview's Differentiation

Worldview has already built the backend intelligence layer: 10 microservices delivering 18 fundamentals sections, NLP-scored news with market impact, entity knowledge graphs with relationship discovery and contradiction detection, prediction market integration, RAG chat with citations, and real-time alert streaming. The frontend must surface ALL of this capability in a professional, information-dense interface that rivals Bloomberg in depth while matching TradingView in modern UX.

**The design target**: Bloomberg depth × TradingView UX × ZeroTerminal AI integration × Finviz data density × Polymarket prediction — at $29/month.

### 1.3 Competitive Differentiation (6 Unique Capabilities)

No affordable platform ($0–$600/yr) combines ALL of:
1. **AI Research Copilot** — RAG chat, citation grounding, contradiction detection, thread history
2. **Entity Knowledge Graph** — company relationships, board connections, supply chains, competitor discovery
3. **Prediction Market Integration** — Polymarket odds alongside fundamentals (unique in affordable tier)
4. **News Intelligence** — NLP-scored articles with market impact windows, entity-linked, routing tier
5. **Configurable Multi-Panel Terminal** — Bloomberg-style workspace with drag-and-drop, ticker linking
6. **AI Daily Briefs** — personalized morning brief + per-instrument AI summary cached daily

---

### 1.4 Visual Identity System — Design Direction & Specification

> **Audit date**: 2026-04-13 · **Status**: Blocking — must be resolved before pencil.dev redesign
> **Reference**: `docs/ui/competitive-design-research.md` (full competitor analysis)

#### 1.4.1 Current Design Critique

An audit of the existing pencil.dev canvas (`apps/frontend/designs/worldview-mvp.pen`) reveals that
all 10 frames suffer from the same root causes. These issues make the designs indistinguishable from
a generic AI-generated Tailwind starter template — immediately recognizable as non-professional to
any analyst who has used Bloomberg, TradingView, or Koyfin.

| Signal | Current State | Professional Standard |
|--------|--------------|----------------------|
| **Background** | `slate-950` (#0f172a) — default Tailwind dark | Platform-specific (`#131722` TradingView, `#090E1B` Koyfin, `#000000` Bloomberg) |
| **Accent color** | `blue-500` (#3b82f6) — generic Tailwind blue | Platform-specific accent: amber (Bloomberg), sky cyan (TradingView `#2962FF`), violet (Koyfin) |
| **Typography** | System font stack (no custom font loaded) | Bloomberg: custom commissioned font; TradingView: custom chart font; Koyfin: DM Sans/Inter; all specify a deliberate font |
| **Positive color** | `green-600` (#16a34a) — saturated generic green | `#26A69A` TradingView teal-green / `#10B981` emerald — less saturated, more professional |
| **Negative color** | `red-500` (#ef4444) — generic red | `#EF5350` TradingView muted red / `#F43F5E` rose — subtle, not alarming |
| **Data density** | Company Detail page is ~30% empty space | Bloomberg/TradingView pack 80%+ of viewport with data |
| **Landing page** | Generic SaaS hero ("Terminal Grade." in blue) | No professional financial product hero uses stock blue text on dark — Bloomberg uses amber, Koyfin uses custom navy |
| **Sector heat tiles** | Bright saturated flat colors | Finviz/TradingView heat tiles use opacity/blended backgrounds, not solid saturated fills |
| **Screener table** | Generic shadcn table with default spacing | Professional screeners (Finviz, Koyfin) use 11–12px text, h-7 row height, tight padding |
| **Workspace** | Empty panels with minimal chrome | TradingView/Benzinga Pro have dense panel headers with symbol chip + timeframe + indicator controls inline |

**Root cause**: The PRD defined what data to show per page (correctly and in detail) but did NOT
specify a visual identity system — no font choice, no color rationale, no density philosophy.
Every design decision defaulted to Tailwind's generic dark starter. This must be corrected before
any further canvas work.

#### 1.4.2 Competitor Visual Fingerprints (Research Summary)

| Platform | Background | Accent | Positive | Negative | Font (UI) | Font (Data) | Density |
|----------|-----------|--------|----------|----------|-----------|-------------|---------|
| **Bloomberg** | `#000000` | `#FB8B1E` amber | `#4AF6C3` cyan-green | `#FF433D` | Custom Bloomberg Prop N | Custom Bloomberg Prop I (mono) | Maximum |
| **TradingView** | `#131722` | `#2962FF` | `#26A69A` teal | `#EF5350` | System (Trebuchet/system-ui) | Custom chart font | High |
| **Koyfin** | `#0D1421` | `#2563EB` | `#10B981` | `#F43F5E` | DM Sans / Inter | Mono | High |
| **Finviz** | `#111111` | `#2979FF` | `#00C805` | `#FF0000` | Arial | Arial | Maximum |
| **IB TWS** | `#121212` | Blue/Red semantic | `#00C805` | `#FF0000` | Arial (Java) | Arial | Maximum |
| **Robinhood** | `#000000` | `#B7DF2F` neon | `#00C805` | red | Inter | Inter (mono variant) | Low |

**Key insight**: Every platform that looks professional has made **deliberate, non-default choices**
for its background color, accent, and positive/negative colors. None use `blue-500` as accent.
None use `slate-950` as background. None use generic `green-600`/`red-500`.

#### 1.4.3 Three Design Direction Options

The following three directions are architecturally compatible with the existing Next.js + shadcn/ui
+ Tailwind v4 stack. All use free Google Fonts. Choose one direction — it will determine the
CSS variable system, font loading, and all future pencil.dev canvas colors.

---

**Direction A — "Amber Terminal"** (Bloomberg DNA)

> *"The original. Power users recognise it immediately."*

| Token | Hex | Usage |
|-------|-----|-------|
| `--background` | `#0A0A0A` | Page background |
| `--card` | `#141414` | Panel/card backgrounds |
| `--border` | `#2A2A2A` | Dividers, outlines |
| `--foreground` | `#E8E8E8` | Primary text |
| `--muted-foreground` | `#888888` | Labels, captions |
| `--primary` (accent) | `#F49F31` | Amber — CTAs, active states |
| `--positive` | `#4AF6C3` | Cyan-green (Bloomberg) — gains |
| `--negative` | `#FF433D` | Bloomberg red — losses |
| `--warning` | `#F49F31` | Same amber |

Font: **IBM Plex Mono** everywhere (terminal aesthetic — even UI text in mono).
Character: Maximum credibility. Instantly recognizable as a terminal. Steep learning curve.
Risk: Looks like a Bloomberg clone. Potential patent/trademark proximity concern. Very niche.

---

**Direction B — "Midnight Pro"** (TradingView DNA) ← **RECOMMENDED**

> *"The most imitated dark background in fintech — for a reason."*

| Token | Hex | Usage |
|-------|-----|-------|
| `--background` | `#131722` | TradingView's exact background — industry-recognised |
| `--card` | `#1E2329` | Panel/card backgrounds |
| `--muted` | `#2B3139` | Elevated surfaces, hover states |
| `--border` | `#2B3139` | Dividers |
| `--foreground` | `#D1D4DC` | TradingView's primary text — warm white, less harsh |
| `--muted-foreground` | `#787B86` | Labels, timestamps, axis captions |
| `--primary` (accent) | `#0EA5E9` | Sky-500 — distinctive, not generic blue, professional |
| `--positive` | `#26A69A` | TradingView teal-green — professional, not cartoon green |
| `--negative` | `#EF5350` | TradingView muted red — not alarming |
| `--warning` | `#F59E0B` | Amber-500 — alert highlights |

Font UI: **IBM Plex Sans** · Font Mono: **IBM Plex Mono**
Character: Professional, modern, immediately credible to any serious investor. Clean without
being corporate. Most likely to convert the thesis evaluation audience.
Strength: `#131722` is the proven benchmark. IBM Plex = IBM's design language = institutional.

---

**Direction C — "Deep Navy"** (Koyfin DNA with violet accent)

> *"Premium, distinctive, slightly unconventional — memorable."*

| Token | Hex | Usage |
|-------|-----|-------|
| `--background` | `#090E1B` | Deep navy — darker than TradingView, more premium |
| `--card` | `#0F1929` | Panel backgrounds |
| `--muted` | `#162035` | Elevated surfaces |
| `--border` | `#1E2E47` | Dividers |
| `--foreground` | `#E2E8F0` | Slate-200 equivalent — crisp |
| `--muted-foreground` | `#94A3B8` | Slate-400 |
| `--primary` (accent) | `#7C3AED` | Violet-600 — DISTINCTIVE (no other fin platform uses violet) |
| `--positive` | `#10B981` | Emerald-500 — cleaner than teal, still professional |
| `--negative` | `#F43F5E` | Rose-500 — softer than red |
| `--warning` | `#F59E0B` | Amber-500 |

Font UI: **Inter** · Font Mono: **JetBrains Mono**
Character: Most distinctive. Immediately separates from all competitors. Premium feel.
Risk: Violet accent is unusual in fintech — may feel "different" rather than "professional" to
traditional finance users. Best for innovation-oriented investor audience.

---

#### 1.4.4 Selected Direction: **B — "Midnight Pro"** (pending user confirmation)

**Rationale for recommending Direction B**:

1. `#131722` is battle-tested by TradingView (used by 50M+ traders). Any finance professional who
   has used TradingView will immediately recognise the palette as "serious trading tool."
2. IBM Plex Sans + IBM Plex Mono is an open-source IBM corporate typeface — the same company that
   built the first mainframes used by financial institutions. The "institutional DNA" is real.
3. `#0EA5E9` sky accent (vs generic `blue-500`) is 15% warmer and lighter — visually distinctive
   without being unusual. Finance-appropriate.
4. `#26A69A` teal-green positive: the most sophisticated positive color in the industry. Generic
   greens look like traffic lights. Teal reads as "financial instrument up."
5. Direction A (Amber) risks Bloomberg clone perception. Direction C (Violet) risks "too different"
   for traditional finance evaluators. Direction B threads the needle.

**Typography — Selected Stack**:

```css
/* Load in root layout.tsx via next/font/google */
import { IBM_Plex_Sans, IBM_Plex_Mono } from 'next/font/google'

const ibmPlexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700'],
  variable: '--font-sans',
})

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-mono',
})
```

```css
/* globals.css — font application */
body { font-family: var(--font-sans), system-ui, sans-serif; }
.font-mono, [data-numeric] { font-family: var(--font-mono), monospace; }
```

**CSS Variable Override** (update from current Tailwind defaults):

```css
:root.dark {
  /* Background stack */
  --background:        222 47% 11%;    /* #131722 — TradingView exact */
  --card:              215 28% 14%;    /* #1E2329 */
  --muted:             213 20% 19%;    /* #2B3139 */
  --popover:           222 47% 11%;    /* same as background */

  /* Text */
  --foreground:        220 14% 85%;    /* #D1D4DC — TradingView primary text */
  --card-foreground:   220 14% 85%;
  --muted-foreground:  220 9% 50%;     /* #787B86 */

  /* Interactive */
  --primary:           199 89% 48%;   /* #0EA5E9 sky-500 */
  --primary-foreground: 222 47% 11%;

  /* Structural */
  --border:            213 20% 19%;   /* #2B3139 */
  --input:             213 20% 19%;
  --ring:              199 89% 48%;
  --accent:            213 20% 19%;
  --destructive:       0 63% 62%;     /* #EF5350 */
  --destructive-foreground: 220 14% 85%;

  /* Financial domain */
  --positive:          174 42% 40%;   /* #26A69A teal-green */
  --negative:          0 63% 62%;     /* #EF5350 */
  --warning:           38 92% 50%;    /* #F59E0B */
  --neutral-value:     220 9% 50%;    /* #787B86 */
}
```

#### 1.4.5 Typography Scale (Updated)

| Use case | Font family | Class | Notes |
|----------|------------|-------|-------|
| Page title | IBM Plex Sans | `text-2xl font-semibold tracking-tight` | 24px/600 |
| Section heading | IBM Plex Sans | `text-base font-semibold tracking-tight` | 16px/600 |
| Card title | IBM Plex Sans | `text-sm font-medium` | 14px/500 |
| Body text | IBM Plex Sans | `text-sm` | 14px/400 |
| Label / caption | IBM Plex Sans | `text-xs text-muted-foreground` | 12px/400 |
| **Numeric value (large)** | **IBM Plex Mono** | `text-xl font-semibold tabular-nums` | 20px/600 |
| **Numeric value (table)** | **IBM Plex Mono** | `text-xs tabular-nums text-right` | 12px/400 |
| **Ticker symbol** | **IBM Plex Mono** | `text-sm font-semibold uppercase` | 14px/600 |
| **Price** | **IBM Plex Mono** | `text-4xl font-semibold tabular-nums` | Header price |
| Terminal/code | IBM Plex Mono | `text-xs leading-relaxed` | Morning brief, chat |

**Critical rule**: ALL numbers (prices, percentages, quantities) MUST use IBM Plex Mono.
This is the single highest-impact visual change from the current design.

#### 1.4.6 Design Density Targets by Page

| Page | Target Density | Reference Platform | Key Density Signal |
|------|---------------|-------------------|--------------------|
| Landing | Low-Medium | Koyfin landing | Hero 2-col, 6-card grid, comparison table |
| Dashboard | High | TradingView dashboard | Heat map 4×3, market chips scrolling, compact alert rows |
| Company Detail | High | Koyfin company detail | Full header row, 5-tab nav, data in every above-fold panel |
| Workspace | Maximum | Benzinga Pro / Bloomberg | Panel headers inline with symbol+controls, no wasted chrome |
| Screener | Maximum | Finviz Elite | 12px text, h-7 rows, 6+ visible columns above fold |
| Portfolio | High | Koyfin portfolio | Compact holdings table, strategy cards row |
| News | Medium | Seeking Alpha | Feed card list, relevance badge prominent |
| Chat | Low-Medium | Perplexity / ChatGPT | Clean conversation, citations expandable inline |

#### 1.4.7 Landing Page Visual Direction (Current Design: Critical Issues)

The current landing page design has several problems that make it look generic:

| Issue | Current | Fix |
|-------|---------|-----|
| Hero headline | "Terminal Grade." (blue gradient text) | Remove gradient. IBM Plex Sans, white, no color tricks. |
| Hero sub-headline | Generic SaaS copy | Keep current PRD copy — it's fine. Problem is visual, not textual. |
| Feature cards | Generic icon + title + blurb cards | Add screenshot thumbnails or SVG illustrations per feature |
| Comparison table | Generic shadcn table | Worldview row: `bg-[#0EA5E9]/10 border border-[#0EA5E9]` with sky accent |
| Pricing | Generic 3-card SaaS | Middle card (Pro): prominent border accent, "Most Popular" badge in sky |
| NavBar | Generic | Logo should be wordmark in IBM Plex Mono "WORLDVIEW" caps + subtle sky dot |
| Background | `slate-950` flat | Keep as `#131722`; NavBar `bg-[#131722]/80 backdrop-blur-md` |
| Trust bar | Bland icons | Use specific copy, not generic shield icons |

**Hero section visual target**: Think Koyfin's landing page — clean, dark, product screenshot
prominent, pricing clear. NOT a generic "dark SaaS template."

---

## 2. Target Users & Journeys

### 2.1 Primary Segments

| Segment | Primary Journeys | Pricing Tier |
|---------|-----------------|-------------|
| Research Analysts | Company Detail (all tabs), Chat, News Intelligence, Screener | Pro ($29/mo) |
| Quantitative Traders | Workspace terminal, Screener, Signals, Prediction Markets | Pro+ ($99/mo) |
| Active Retail Investors | Dashboard, Portfolio analytics, Company Detail, News | Pro ($29/mo) |
| Thesis Evaluators | All journeys — system capability demo | — |

### 2.2 Core User Journeys

| # | Journey | Key Pages |
|---|---------|-----------|
| J1 | Interactive Charts + Indicators | Company Detail → Overview tab + Chart with indicators |
| J2 | Full Fundamentals Research (18 sections) | Company Detail → Fundamentals tab |
| J3 | AI Research Chat with Citations | Chat, Company Detail → Chat tab |
| J4 | Morning Intelligence Brief | Dashboard → Morning Brief card |
| J5 | News Intelligence Feed | News → Top Today + Feed tabs |
| J6 | Multi-Panel Workspace Terminal | Workspace → configure panels, ticker link |
| J7 | Portfolio Strategy Analytics | Portfolio → strategy cards + holdings + analytics |
| J8 | Signal & Alert Monitoring | Dashboard, Workspace → Alerts panel |
| J9 | Entity Relationship Discovery | Company Detail → Intelligence tab → Knowledge Graph |
| J10 | Screener Discovery | Screener → 62+ metrics → Company Detail |

### 2.3 New User Onboarding Flow

```
Landing page (/)
  → "Start Free" CTA → /login
  → Zitadel OIDC PKCE → /callback → user provisioned (S1)
  → /dashboard
    → Morning Brief generating... (skeleton 3–5s)
    → Brief appears + Market Heat Map + Top Movers
    → User explores: add portfolio → company detail → workspace
```

---

## 3. Functional Requirements

### F-01 — Public Landing Page (Complete Professional Redesign)

Public route `/` — high-conversion marketing page. All sections are Server Components except NavBar.

**NavBar** (`"use client"`): Logo | "Sign In" button | GitHub icon link. Sticky, `backdrop-blur-md bg-background/80 border-b border-border`. Redirects authenticated users to `/dashboard`.

**Hero Section** (2-column layout):
- Left column:
  - Eyebrow: `"The Bloomberg Alternative"` — small badge, muted, uppercase
  - H1: `"Bloomberg-Grade Research. Without the Bloomberg Bill."`
  - Sub-headline: `"Fuse structured market data, AI-powered knowledge graphs, and prediction markets into one configurable research terminal — for $29/month."`
  - CTAs: `[Start for Free]` (primary) `[Watch Demo]` (outline) + "No credit card required" micro-copy
  - Social proof: avatars of 3 fictitious user types + "Trusted by research analysts & quant traders"
- Right column: Animated product screenshot carousel (3 images: Workspace, Company Detail, Dashboard) with auto-advance 4s + dot navigation

**Social Proof Stats Bar** (4 stat cards, `bg-card border-border`):
- "10M+" — OHLCV data points ingested
- "18" — fundamentals sections per company
- "500K+" — knowledge graph relations
- "< 5s" — AI answer with citations

**Feature Spotlight Section** (full-width, `bg-card`):
- Left (60%): Product screenshot of 4-panel Workspace with callout annotations:
  - Arrow → Chart panel: "Multi-timeframe OHLCV charts (1m–1M)"
  - Arrow → News panel: "AI-scored news with market impact windows"
  - Arrow → Alerts: "Real-time HIGH/CRITICAL alert stream"
  - Arrow → Chat: "RAG chat grounded in company filings"
- Right (40%):
  - `"Your Research Terminal. Your Rules."`
  - 3 bullets: "Drag-and-drop 11 panel types" | "Ticker-linked panels sync instantly" | "Layouts saved automatically"

**Features Grid** (3×2 cards with lucide icons, reordered by impact):
1. LayoutDashboard: **"Configurable Workspace Terminal"** — 11 panel types, drag-and-drop, ticker linking
2. BrainCircuit: **"AI Research Copilot"** — RAG chat, citations, contradiction detection, thread history
3. Network: **"Entity Knowledge Graph"** — company relations, board connections, supply chain, competitor discovery
4. Newspaper: **"News Intelligence"** — NLP-scored articles, entity-linked, market impact scoring
5. BarChart2: **"18-Section Fundamentals"** — income statement through insider transactions
6. Gauge: **"Prediction Markets"** — Polymarket odds alongside fundamentals

**Competitive Comparison Table** (`ComparisonTable` component):
Headers: Platform | Price | Charts | Deep Fundamentals | AI Copilot | Knowledge Graph | Prediction Markets | News Scoring

| Platform | Price | Charts | Fundamentals | AI | KG | Prediction | News |
|----------|-------|--------|--------------|----|----|-----------|----|
| Bloomberg | $32K/yr | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Koyfin | $0–299/mo | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Finviz | $0–40/mo | ✓ | Partial | ✗ | ✗ | ✗ | ✗ |
| TradingView | $0–59/mo | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Worldview** | **$0–99/mo** | **✓** | **✓** | **✓** | **✓** | **✓** | **✓** |

Note: ✓ = included, ✗ = not available. Worldview row highlighted with `bg-primary/10 border border-primary`.

**How It Works** (3 steps with step numbers + connector lines):
1. `Search` — "Search any company, ticker, or entity"
2. `Analyze` — "Get AI intelligence brief, entity graph, fundamentals, and news impact in one view"
3. `Act` — "Configure your workspace, set alerts, chat with your data, screen opportunities"

**Trust Bar** (3 items, horizontal strip, `bg-muted`):
- Shield: "Local-first — your data never leaves your infrastructure"
- Quote: "Every AI answer is citation-grounded — no hallucinations, source-backed"
- Lock: "GDPR-aware — no PII sold, no data resold, no tracking"

**Pricing Section** (3 cards):

Free ($0/forever):
- Dashboard + Morning Brief (1/day)
- 1 portfolio, up to 10 holdings
- Market news feed (basic)
- Screener (max 3 filters)
- Watchlist (10 entities)
- AI chat (20 messages/day)
- CTA: `[Get Started Free]`

Pro ($29/month, highlighted "Most Popular"):
- Everything in Free, plus:
- Configurable Workspace (11 panels, unlimited layouts)
- Entity Knowledge Graph (full)
- 5 portfolios, unlimited holdings
- Unlimited AI chat with citations
- Prediction markets panel
- News intelligence (PRD-0026)
- Brokerage sync (PLAN-0022)
- CTA: `[Open Pro Trial]`

Pro+ ($99/month):
- Everything in Pro, plus:
- Unlimited portfolios + strategies
- API access (v2 roadmap)
- Priority data refresh (5s vs 30s)
- Custom alert rules (v2 roadmap)
- Multi-seat (v2 roadmap)
- CTA: `[Contact Us]`

**FAQ Section** (4 questions, shadcn Accordion):
1. "How is my financial data protected?" → Local-first architecture: all data stays in your Docker environment. Zitadel OIDC handles auth tokens. No portfolio data is transmitted to third parties.
2. "Are AI answers reliable — will it make up numbers?" → Every AI claim includes source citations (document title, date, excerpt). The system detects contradictions between sources and flags them. No ungrounded generation.
3. "What data sources power Worldview?" → EODHD (18-section fundamentals + OHLCV), SEC EDGAR (10-K/10-Q/8-K filings), Finnhub + NewsAPI (news), Polymarket (prediction markets).
4. "Can I trial it without committing?" → Free tier requires no credit card. Full platform accessible from the first login.

**CTA Section**: "Start your research in minutes." + `[Get Started Free]` (large, centered)

**Footer**: Logo | Privacy | Terms | GitHub link | © 2026 Worldview | `[💬 Send Feedback]` button (opens FeedbackDialog)

---

### F-02 — Authentication Flow

*(Unchanged from v1.0)* — Zitadel OIDC PKCE at `/login`, callback at `/callback`, access_token in React context, refresh_token in httpOnly cookie, protected routes redirect to `/login`.

---

### F-03 — Dashboard with AI Morning Brief (Enhanced)

Protected route `/dashboard`.

**Layout**:
```
[MorningBriefCard ─────────────────── full width]
──────────────────────────────────────────────────
[PortfolioSummaryCard 1/3] [MarketHeatmapCard 2/3]
──────────────────────────────────────────────────
[TopMoversCard 1/3] [TopSignalsCard 1/3] [WatchlistNewsCard 1/3]
──────────────────────────────────────────────────
[EconomicCalendarCard 1/2] [QuickStatsBar 1/2]
[RecentAlertsCard ─────── full width]
```

**MorningBriefCard**: `GET /v1/briefings/morning`. Skeleton 3–5s cold. BrainCircuit icon + generated_at + model badge + brief text (5–8 sentences). Error → "Good morning. AI brief temporarily unavailable." static fallback + Retry.

**PortfolioSummaryCard** (enhanced):
- Total Value (large mono), Daily P&L (colored), Unrealized P&L, Holdings count
- Mini sparkline: 5-day portfolio value trend (computed client-side: holdings × last 5 days of quotes from `POST /v1/quotes/batch`)
- "View Portfolio →" link

**MarketHeatmapCard** (NEW — Finviz-inspired):
- 11 sector tiles in a grid layout (`grid-cols-4 gap-1`)
- Each tile: sector name + daily % change text + colored background from HeatScale
- Data source: Fetch quotes for sector ETFs: `POST /v1/quotes/batch` with `{instrument_ids: [XLK, XLF, XLE, XLV, XLY, XLI, XLU, XLRE, XLB, XLP, XLC]}` (resolved by symbol via S3 instruments)
- HeatScale (7 steps): `< -3%` (deep red) | `-3 to -1.5%` (red) | `-1.5 to -0.5%` (orange-red) | `-0.5 to +0.5%` (slate) | `+0.5 to +1.5%` (light green) | `+1.5 to +3%` (green) | `> +3%` (bright green)
- Click tile → Screener pre-filtered by sector
- TanStack Query staleTime: 60s (quotes refresh automatically)

**TopMoversCard** (NEW):
- Two sub-columns: "Top Gainers" | "Top Losers" (5 rows each)
- Data: `POST /v1/quotes/batch` for all watchlist instruments → sort by daily change %
- Row: `[Ticker] [Name truncated] [change colored]`
- Empty state: "Add instruments to your watchlist to see movers"
- TanStack Query staleTime: 30s

**TopSignalsCard**: S10 `GET /v1/alerts/pending?limit=5&min_severity=medium`. Live via `useAlertStream`.

**WatchlistNewsCard**: `GET /v1/news/relevant?limit=5`. 5 ArticleCard rows.

**EconomicCalendarCard** (NEW):
- "Macro Events" heading + S7 icon
- Data: `GET /v1/temporal-events?active_only=false&limit=5` sorted by active_from
- Row: lifecycle_phase badge (PENDING/ACTIVE/RESIDUAL) | title (truncated 60 chars) | active_from → active_until range
- Empty state: "No upcoming macro events"

**QuickStatsBar**: S3 quotes for SPY, QQQ, DIA, VIX (if available). Horizontal scrolling chips with LivePriceBadge.

**RecentAlertsCard**: Last 5 alerts with SeverityBadge. Acknowledge button per row.

---

### F-04 — Configurable Multi-Panel Workspace (Enhanced)

Protected route `/workspace`.

**`react-grid-layout` configuration**: 12-column grid, rowHeight=80px. Draggable by `.panel-drag-handle`. Resizable. Breakpoints: lg(1200), md(996), sm(768 — drag disabled).

**Default layout (lg)**:
```
┌──────────────────────┬─────────────────────┐
│  ChartPanel          │  NewsFeedPanel       │
│  6 cols × 6 rows     │  6 cols × 6 rows    │
├──────────────────────┼─────────────────────┤
│  AlertsPanel         │  ChatPanel           │
│  6 cols × 5 rows     │  6 cols × 5 rows    │
└──────────────────────┴─────────────────────┘
```

**Panel Types (11 total)**:
| Panel | Key Features | Data Source |
|-------|-------------|-------------|
| ChartPanel | OHLCVChart + ticker search + timeframe (1m–1M) + technical indicators (MA50/MA200/Volume) | S3 OHLCV `/v1/ohlcv/{id}` |
| NewsFeedPanel | ArticleCard list, linked to ticker, sort by relevance/date | S9 `/v1/news/relevant` or `/v1/entities/{id}/articles` |
| AlertsPanel | Real-time WS stream, severity filter chips, acknowledge per row | S10 WS + `/v1/alerts/pending` |
| FundamentalsPanel | Key metrics strip (6 metrics) for active ticker | S3 `/v1/fundamentals/{id}/highlights` |
| ChatPanel | Full ChatUI, pre-seeded with active ticker, SSE streaming + citations | S8 SSE via S9 `/v1/chat/stream` |
| PredictionMarketsPanel | Open markets with probability bars + probability history sparkline | S3 `/v1/signals/prediction-markets` |
| ScreenerPanel | 3-filter mini screener + 5-result list (sortable) | S3 `/v1/fundamentals/screen` |
| EntityGraphPanel | Force-directed sigma.js graph for active ticker's entity | S7 `/v1/entities/{entity_id}/graph` |
| HeatmapPanel (NEW) | Market sector heat map — same as Dashboard widget | S3 quotes batch (sector ETFs) |
| PortfolioSummaryPanel (NEW) | Live total value + daily P&L + top 3 holdings | S1 portfolios + S3 quotes batch |
| MacroEventsPanel (NEW) | Active/upcoming temporal events list | S7 `/v1/temporal-events` |

**PanelWrapper** controls: drag handle bar + panel label + active ticker chip + [Link toggle] + [Minimize] + [Close]. Per-panel `react-error-boundary` — panel error shows ErrorCard + Retry without affecting other panels.

**WorkspaceTickerContext**: `activeTicker` (string) + `setActiveTicker`. Updated by ChartPanel on ticker change. Consumed by all linked panels. Panels with Link toggle = on react to context changes.

**Layout persistence**: `localStorage` key `worldview:workspace:layout:{user_id}`. Auto-saved via `onLayoutChange`. "Reset to Default" button in top-right controls bar.

**"Open in Workspace" behavior** (ADR-F-12 resolution):
```typescript
// Invoked from Company Detail header button
function openInWorkspace(ticker: string, instrumentId: string) {
  localStorage.setItem('worldview:workspace:pending-ticker', JSON.stringify({ ticker, instrumentId }));
  router.push('/workspace');
}

// WorkspaceGrid useEffect on mount (runs once)
useEffect(() => {
  const raw = localStorage.getItem('worldview:workspace:pending-ticker');
  if (raw) {
    localStorage.removeItem('worldview:workspace:pending-ticker');
    const { ticker } = JSON.parse(raw);
    setActiveTicker(ticker);
    // Ensure at least a ChartPanel exists in current layout
    if (!currentLayout.find(p => p.type === 'ChartPanel')) {
      addPanel({ type: 'ChartPanel', w: 6, h: 6, x: 0, y: 0 });
    }
  }
}, []);
```

---

### F-05 — Company Detail (5 Tabs, Professional Data Surface)

Protected route `/companies/[instrument_id]`.

**Resolution on Page Mount** (Server Component `page.tsx`):
1. Prefetch `GET /v1/instruments/{instrument_id}/context` → `InstrumentContext` (see §6.5)
2. `InstrumentContext` provides: `symbol`, `exchange`, `sector`, `industry`, `country`, `entity_id | null`, `flags`
3. If `entity_id` is null: S7-dependent panels (EntityGraph, Contradictions, Similar, Claims, Events) show "Entity data not available for this instrument" empty state (not an error)
4. Pass `entity_id` via `HydrationBoundary` to all client components

**Header (Professional)**:
```
Row 1: [Company Logo 40px clearbit] [Company Name text-2xl bold] [TICKER badge primary]
        [EXCHANGE badge secondary] [SECTOR badge muted] [INDUSTRY text-xs muted]

Row 2: [Live Price text-4xl font-mono] [PriceChange daily%] [Volume: X.XM]
        [Avg Vol: X.XM] [Market Cap: $XX.XB]

Row 3: [52-Week Range Visual Bar — current price position between low/high]
       [52w Low: $XXX] ←──[●]──────────→ [52w High: $XXX]

Row 4: [★ Add to Watchlist] [Open in Workspace ↗] [Share]
```

Data sources for header:
- Logo: `https://logo.clearbit.com/{domain}` where domain from S3 `company_profile.data.WebURL`
- Price/Volume: S3 `GET /v1/quotes/{instrument_id}` (staleTime 5s, LivePriceBadge)
- Market Cap: S3 `/v1/fundamentals/{id}/highlights` → `data.MarketCapitalization`
- 52w High/Low: S3 `/v1/fundamentals/{id}/highlights` → `data.52WeekHigh`, `data.52WeekLow`
- Avg Volume: S3 `/v1/fundamentals/{id}/highlights` → `data.AverageDailyVolumeRolling`
- Sector/Industry: `InstrumentContext.security.sector`, `.industry`
- Watchlist toggle: `POST /v1/watchlists/{id}/members` with `entity_id` (from context)

**OHLCVChart** (full width, 420px height, `"use client"`):
- Timeframe tabs: `1D | 1W | 1M | 3M | 1Y | All` → drives `start`/`end` params to `GET /v1/ohlcv/{id}`
- Overlays (toggle buttons above chart): MA50 | MA200 | Volume bars
- Chart range shared with News tab: `[startDate, endDate]` state at page level
- TanStack Query staleTime: by timeframe (1D=30s, 1W=5min, 1M=15min, 1Y=1h)

**FundamentalsBar**: 6 metric pills. "⚙ Customize" Popover with checkbox list. Metrics from S3 highlights section. `localStorage` key `worldview:fundamentals-bar:{user_id}`.

**Tabs** (shadcn `Tabs`, URL hash: `#overview`, `#news`, `#fundamentals`, `#intelligence`, `#chat`):

---

#### Overview Tab

```
[InstrumentBriefCard — full width]
──────────────────────────────────
[AnalystConsensusCard 1/2] [KeyMetrics 3×3 grid 1/2]
──────────────────────────────────
[52WeekRangeBar + TechnicalSnapshotStrip — full width]
──────────────────────────────────
[EarningsCountdownCard 1/3] [VolumeTrendMini 1/3] [ShortInterestCard 1/3]
```

**InstrumentBriefCard**: `GET /v1/briefings/instrument/{id}`. Skeleton (3–5s cold). Error → "AI analysis temporarily unavailable." + Retry.

**AnalystConsensusCard**: S3 `GET /v1/fundamentals/{id}/analyst-consensus` → `data`:
- Target price range bar: min/mean/max with colored segments
- Consensus: `StrongBuy (N) | Buy (N) | Hold (N) | Sell (N) | StrongSell (N)` pill chips
- Mean target vs current price → upside % badge

**KeyMetrics 3×3 grid** (from S3 highlights):
- P/E Ratio | P/B Ratio | P/S TTM | Forward P/E | EV/EBITDA | PEG Ratio | ROE TTM | Dividend Yield | Beta

**52WeekRangeBar**: Visual slider. Computed: `position = (current - low52w) / (high52w - low52w)`. Shows current price dot on track.

**TechnicalSnapshotStrip** (from S3 technicals_snapshot): Beta | MA50 vs Price (↑/↓ badge) | MA200 vs Price (↑/↓ badge) | RSI (14) | Short Interest %

**EarningsCountdownCard**: From S3 earnings_trend — next expected earnings date, days until, EPS estimate. "Q3 2026 Earnings est. July 24 (23 days)".

**VolumeTrendMini**: Mini bar chart (last 5 trading days volume vs avg volume). S3 OHLCV last 30 bars.

---

#### News Tab

*(Largely from v1.0, enhanced:)*

- EntityNewsPanel: S6 `GET /v1/entities/{entity_id}/articles?limit=20` (requires entity_id from context)
- Date range from chart timeframe state
- Sort: "By Relevance" | "By Date"
- ArticleCard: title (linked, new tab) | source + routing tier badge | timestamp | RelevanceBadge | ImpactSparkline (expandable)
- LIGHT tier: `opacity-60`, italic source
- "Load 20 more" infinite scroll
- Fallback (entity_id null): show `GET /v1/news/relevant?limit=20` instead with note "Showing general news — entity linking unavailable"

---

#### Fundamentals Tab (Complete Redesign — All 18 S3 Sections)

5 accordion groups with Period toggle (Annual | Quarterly | Snapshot) at group level:

**Group 1: "Income & Growth"** (sections: `income_statement`, `highlights`)
- Revenue TTM, Gross Profit TTM, Operating Income, Net Income TTM, EPS TTM, EBITDA TTM, Profit Margin, Operating Margin
- Revenue trend chart: bar chart (8 periods — last 8 quarters or 5 years)
- Period table: sortable by period_end, `font-mono tabular-nums text-right`

**Group 2: "Balance Sheet & Capital Structure"** (sections: `balance_sheet`, `share_statistics`, `outstanding_shares`)
- Total Assets, Total Equity, Cash & Equivalents, Total Debt, Long-Term Debt, Net Debt
- Shares Outstanding, Float, Short Interest %, Insider Ownership %, Institutional Ownership %
- Period table + leverage ratio computation: Debt/Equity, Net Debt/EBITDA

**Group 3: "Cash Flow"** (sections: `cash_flow`, `splits_dividends`, `dividend_history`)
- Operating Cash Flow, Free Cash Flow, CapEx, Dividends Paid, D&A
- FCF trend chart (8 periods)
- Dividend history: timeline chart if `DividendShare > 0`; split history table if any splits
- Payout Ratio from `highlights.PayoutRatio`

**Group 4: "Valuation & Analyst View"** (sections: `valuation_ratios`, `analyst_consensus`, `earnings_history`, `earnings_trend`, `earnings_annual_trend`)
- Valuation metrics table: P/E, Forward P/E, P/B, P/S, EV/Revenue, EV/EBITDA, EV/FCF, PEG, Enterprise Value
- Analyst consensus detailed card (same as Overview but with trend history if available)
- EPS actual vs estimate chart: 8-quarter bar chart with estimate as line overlay. Columns: Period | EPS Estimate | EPS Actual | Surprise % (colored)
- Earnings trend: analyst EPS estimates for next 4 quarters

**Group 5: "Company & Ownership"** (sections: `company_profile`, `institutional_holders`, `fund_holders`, `insider_transactions_snapshot`)
- Company Profile: description (500-char expand/collapse) | CEO + other executives | Founded year | HQ address | Website link | SIC code | Industry | Employees
- Institutional Holders table (top 10): Institution Name | Shares Held | % Float | Change Shares | Change % | Date
- Fund Holders table (top 5): Fund Name | Shares | % Float | Date
- Insider Transactions table (last 20): Insider Name | Role | Transaction Type (BUY/SELL/GIFT) | Shares | Value | Filing Date | Transaction Date

---

#### Intelligence Tab (Enhanced)

```
[EntityGraph sigma.js — 60% width, 500px height] | [SidePanel 40%]
                                                   | [SimilarCompaniesPanel]
                                                   | [ContradictionsPanel]
                                                   | [PredictionMarketsPanel with sparkline]
──────────────────────────────────────────────────────────────────
[RecentClaimsPanel — full width, collapsible]
[TemporalEventsPanel — full width, collapsible]
```

**EntityGraph** (unchanged from v1.0): sigma.js + graphology + ForceAtlas2. Node types: company=blue, person=green, event=amber, fund=purple. Confidence slider. 2-hop/3-hop toggle. Double-click → navigate.

**SimilarCompaniesPanel**: 5 items from S7 `POST /v1/entities/similar`. Row: Ticker | Name | ANN Score badge | "competes_with" badge if `has_competes_with_relation`.

**ContradictionsPanel**: S7 `GET /v1/entities/{entity_id}/contradictions`. Only shown if data exists. Each: claim A vs B text | strength badge (STRONG/MODERATE/WEAK) | detected_at.

**PredictionMarketsPanel**: Open Polymarket markets via S3 `GET /v1/signals/prediction-markets?status=open&query={ticker}`. Each: question | outcome probability bars | volume_24h | close_time. Probability history sparkline via `GET /v1/signals/prediction-markets/{market_id}/history?limit=20`.

**RecentClaimsPanel** (NEW): S7 `POST /v1/claims/search` body: `{entity_ids: [entity_id], top_k: 10}`.
- Each claim: claim_type chip | polarity badge (POSITIVE/NEGATIVE/NEUTRAL) | claim_text (truncated 120 chars) | extraction_confidence bar | doc_id date
- Empty: "No temporal claims extracted for this entity"

**TemporalEventsPanel** (NEW): S7 `POST /v1/events/search` body: `{entity_ids: [entity_id], top_k: 10}`.
- Each event: event_type chip | event_subtype | event_text | event_date | confidence bar
- structured_data rendered as key-value pairs if present
- Empty: "No events extracted for this entity"

---

#### Chat Tab

- Full-height ChatUI (min-height 400px, `"use client"`)
- Pre-seeded system context: "User is analyzing {company_name} ({ticker}) — sector: {sector}"
- Full SSE streaming, citations, contradiction alerts
- Entity IDs pre-wired: `entity_ids: [entity_id]` if not null

---

### F-06 — Companies List Page

*(Unchanged from v1.0)* — Debounced search, filter chips (asset class, exchange, has_ohlcv, has_fundamentals), sortable table, watchlist toggle, pagination 50/page.

---

### F-07 — Portfolio Page (Complete Strategy-Centric Redesign)

Protected route `/portfolio`.

**Layout**:
```
[Page Title "My Strategies"] [+ Create Strategy button]
──────────────────────────────────────────────────────
[StrategyCard grid: 3 per row, each card shows mini overview]
──────────────────────────────────────────────────────
[StrategyDetail panel — appears below selected card]
  [Tabs: Holdings | Transactions | Analytics | Watchlists | Settings]
──────────────────────────────────────────────────────
[Brokerage Connections section]
```

**StrategyCard grid**: Each card (`bg-card border-border rounded-lg p-4 cursor-pointer hover:border-primary`):
- Strategy name (bold) + currency badge
- Total Value (`font-mono text-xl`) + Daily P&L (colored)
- Holdings count badge + "Active since" date
- 5-day sparkline (client-computed from top holding prices)
- Active card: highlighted `border-primary`

**"Create Strategy" button** → Sheet:
- Name input (required, max 60 chars)
- Currency selector (USD default)
- Optional description
- Submit → `POST /v1/portfolios` → optimistic update

---

#### Holdings Tab

**Performance Header** (for selected portfolio):
```
[Total Value $XX,XXX.XX large mono] [Daily P&L ±$XXX.XX colored]
[Total Return % since inception] [Unrealized P&L $] [Realized P&L $]
[Holdings: N] [Last updated: X min ago]
```

**RiskMetricsStrip**: Beta (portfolio weighted) | Concentration Score (HHI) | Sector Count | Top Position Weight %

**HoldingsTable** (Professional, `CompactTable` style):
| ★ | Ticker | Company | Sector | Qty | Avg Cost | Current | Unreal. $ | Unreal. % | Daily % | Weight % | Actions |
|-|-|-|-|-|-|-|-|-|-|-|-|
- Sector from S3 security (via context endpoint per instrument)
- Current price from `POST /v1/quotes/batch` (all instruments at once, staleTime 30s)
- Unrealized P&L: `(current - avg_cost) × qty`
- Weight %: `holding_value / total_portfolio_value × 100`
- Colors: Unreal./Daily columns use HeatCell component
- Actions column: `[+ Add] [− Sell] [✕ Close]` icon buttons → AddTransactionSheet pre-filled

**AddTransactionSheet** (shadcn Sheet, side="right", width 480px):
- "Add Transaction" heading
- Portfolio: auto-selected (current)
- Ticker search: debounced input → `GET /v1/instruments?query=` → dropdown with symbol | name | exchange
- Type: RadioGroup — BUY | SELL | DIVIDEND (with icons)
- Executed At: DatePicker (calendar component, defaults to today)
- Quantity: NumberInput, decimal allowed, 4 decimal places
- Price per unit: NumberInput with currency prefix
- Fees: NumberInput (default 0)
- Currency: select (defaults to portfolio currency)
- External Reference: optional text (for brokerage dedup)
- Submit → `POST /v1/transactions` → invalidate holdings + transactions queries

---

#### Transactions Tab

- DateRangePicker: defaults to last 30 days
- Type filter chips: All | BUY | SELL | DIVIDEND
- Table: Date | Type badge | Ticker | Qty (mono) | Price (mono) | Fees | Net Amount | External Ref
- Paginated 20/page with load-more
- "Export CSV" button: client-side generation of CSV from current filter result

---

#### Analytics Tab

**SectorAllocationChart**: Donut chart (chart.js or recharts, dark theme).
- Data: group holdings by S3 security.sector, sum holding value
- Legend: sector name | value | percentage
- Empty state: "Add holdings to see sector allocation"

**TopHoldingsChart**: Horizontal bar chart (top 5 by weight %).
- Each bar: Ticker | Company (truncated) | weight % + value

**ConcentrationScore**:
- HHI score (sum of weight_i²) displayed as gauge arc: 0–1000 (Low) | 1000–2500 (Moderate) | 2500+ (High)
- Text: "Your portfolio is [Highly/Moderately/Low] concentrated"
- Top 3 largest positions listed

---

#### Watchlists Tab

- Watchlist cards: name | member count | "Expand" toggle
- Expanded: member list with entity names + live quotes (S3 batch)
- Add/remove members: entity search input → `POST/DELETE /v1/watchlists/{id}/members`
- Create watchlist: "+ New Watchlist" → dialog
- Delete watchlist: trash icon → confirmation dialog

---

#### Settings Tab (Per Portfolio)

- Rename portfolio: input + save
- Currency: currently display-only (changing currency out of scope)
- Archive portfolio: dangerous action with confirmation dialog
- Alert Preferences: toggle per alert_type; entity suppressions list
- Email Preferences: weekly digest toggle + day/hour picker

---

### F-08 — News Page (2 Tabs)

*(Unchanged from v1.0)* — Feed tab (chronological from S5/S9) + Top Today tab (ranked by display_relevance_score from PRD-0026 with placeholder if not deployed).

---

### F-09 — Screener Page (Enhanced)

Protected route `/screener`.

- Dynamic filter builder from `GET /v1/fundamentals/screen/fields` (62+ metrics)
- Filter rows: [Metric dropdown with search] + [Operator ≥/≤/between] + [Value inputs] + [Remove ×]
- **Sector filter** (NEW): Additional sector dropdown from S3 screener's `sector` filter field
- "Add Filter" + Sort controls + "Run Screener" button
- Results table: Ticker | Company | Exchange | Sector | Industry | dynamic metric columns with HeatCell coloring. 50/page, total count.
- Row click → `/companies/{instrument_id}`
- Save/Load to localStorage `worldview:screener:saved:{user_id}`
- **"Open All in Workspace Screener Panel"** (NEW): button that sends results to a ScreenerPanel in Workspace

---

### F-10 — Chat Page (Thread-Based with Search)

Protected route `/chat`.

**Thread Sidebar (260px)**:
- "New Chat" button (primary, top)
- **Thread search** (NEW): `SearchIcon` + input (debounced 200ms). Client-side filter on `thread.title`. Shows "No conversations match" if no results.
- Thread list: title (40-char truncated) + relative date + message_count badge + [Delete on hover]
- Active thread: `bg-primary/10 text-primary`
- Data: `GET /v1/threads` (TanStack Query staleTime 30s)

**Message Thread**:
- User messages: right-aligned, `bg-primary/20`
- Assistant messages: left-aligned, `bg-card`:
  - Streaming body (blinking cursor in streaming state)
  - Intent badge chip (FACTUAL_LOOKUP | COMPARISON | FINANCIAL_DATA | PORTFOLIO | REASONING | SIGNAL_INTEL | GENERAL)
  - Provider badge + latency muted text
  - CitationList: `[1]`, `[2]` inline markers, expandable citation cards (title + source + date + excerpt)
  - ContradictionAlert: amber border if contradictions detected
  - **Copy button** (NEW): clipboard icon → copies message text
  - **Thumbs up/down** (NEW): feedback buttons → logged via `POST /v1/feedback`

**Input Area** (sticky bottom):
- Multi-line textarea (auto-grow up to 5 lines), Enter=send, Shift+Enter=newline
- Send button (disabled during streaming), Abort button (AbortController)
- Entity context pills: up to 5 entities pre-wired (removed via × on pill)

---

### F-11 — Login + Callback

*(Unchanged)* — `/login` public, `/callback` PKCE exchange.

---

### F-12 — Map Page (Stub)

*(Unchanged)* — Globe icon + "Coming Soon" badge + 3 preview bullets.

---

### F-13 — Command Palette

*(Unchanged from v1.0)* — `Cmd+K` / `Ctrl+K` → cmdk modal. Search: tickers, pages, threads. Recent 5 companies.

---

### F-14 — Real-Time Alerts (Global)

*(Unchanged from v1.0)* — WebSocket + FlashOverlay + TopBar badge.

---

### F-15 — Global Feedback Widget (NEW)

**FeedbackWidget**: Fixed position, bottom-right, `z-50`. `MessageCircle` icon (24px) in circular button (`bg-card border border-border w-10 h-10 rounded-full shadow-lg hover:bg-muted`).

**FeedbackDialog** (shadcn Dialog):
- Title: "Share Feedback"
- Description: "Help us improve Worldview — bugs, ideas, design, data quality."
- Category select (required): `Bug Report | Feature Request | Design Feedback | Data Quality Issue | Other`
- Title input (optional, max 100 chars): e.g., "Chart tooltip shows wrong date"
- Description textarea (required, max 2000 chars): placeholder "Describe the issue or suggestion..."
- Submit button → `POST /v1/feedback` (S9 structlog endpoint, no DB):
  - Success: Dialog closes + toast "Feedback received — thank you!"
  - Error: Toast error "Failed to send. Please try again."
- Cancel button

---

### F-16 — Professional Data Density & Keyboard Shortcuts (NEW)

**HeatCell component**: `<td>` or `<div>` with background from HeatScale (7-step gradient: `bg-[hsl(...)]` computed from `value` percent input). Used in Screener results, Portfolio holdings daily change, Dashboard top movers.

**Sparkline component**: 20px tall inline SVG mini-chart. Props: `data: number[]` (5–20 points), `color: "positive"|"negative"|"neutral"`. No axes, no labels, just the trend line. Used in: StrategyCards (portfolio value trend), WatchlistRows (5-day price history), TopMovers.

**LivePriceBadge component**: `[● price]` — dot color: green if `(now - quote.updated_at) < 30s`, yellow if `< 5min`, red if `>= 5min` or WS disconnected. Animated pulse on green.

**CompactTable component**: wrapper `<table>` with `text-xs leading-tight`. Row height `h-8`. Number cells: `font-mono tabular-nums text-right`. Header: `text-[10px] uppercase tracking-wider text-muted-foreground`. Used in: Holdings table, Fundamentals tables, Insider transactions.

**Global Keyboard Shortcuts** (via `react-hotkeys-hook` or inline useEffect):
| Shortcut | Action |
|----------|--------|
| `g d` | Navigate to /dashboard |
| `g w` | Navigate to /workspace |
| `g c` | Navigate to /companies |
| `g p` | Navigate to /portfolio |
| `g n` | Navigate to /news |
| `g s` | Navigate to /screener |
| `g h` | Navigate to /chat |
| `Cmd/Ctrl+K` | Open CommandPalette |
| `Escape` | Close modals / dismiss FlashOverlay |

Keyboard shortcut hint in TopBar: `⌘K` badge (muted, small).

---

## 4. Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| First Contentful Paint | < 1.5s (Lighthouse) |
| Largest Contentful Paint | < 2.5s |
| Morning brief (cold) | < 5s P95 |
| Instrument brief (cold) | < 5s P95 |
| Quote freshness | 5s staleTime (matches S3 Valkey cache) |
| WebSocket reconnect | ≤ 30s max backoff (exponential 1s→30s) |
| Bundle size (initial, gzipped) | < 500KB total, < 200KB main bundle |
| WCAG accessibility | 2.1 AA (contrast ≥4.5:1, full keyboard nav) |
| Concurrent users | 50 (thesis scope) |
| Theme | Dark only — `class="dark"` permanent (ADR-F-04) |
| Information density | Compact tables (text-xs, h-8 rows) for data-heavy pages |

---

## 5. Out of Scope

| Feature | Reason |
|---------|--------|
| Light/dark theme toggle | Dark-only enforced (ADR-F-04) |
| Mobile-native app | Responsive web only |
| Backtesting / paper trading | No simulation engine; deferred |
| Social features | Content moderation; deferred |
| Alternative data sources | No new provider integrations in MVP |
| Team/multi-seat features | Single-user MVP focus (v2 roadmap) |
| Map page full implementation | S7 geographic UI deferred; stub only |
| API key generation | Deferred to v2 |
| Billing/payment integration | Pricing section is display-only for MVP |
| Equity curve historical chart | Requires client-side reconstruction from full transaction history; deferred to v2 |
| Options chain / order book | Trading execution not in scope |
| Real-time L2 data | Daily OHLCV only; no sub-second data |

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change Type | What Changes |
|---------|------------|-------------|
| **S8 RAG/Chat** | New endpoints | `GET /api/v1/briefings/morning` + `GET /api/v1/briefings/instrument/{id}` |
| **S9 API Gateway** | New proxy routes + composition | 20+ new routes (see §6.2); briefings + feedback + instrument context |
| **Frontend (`apps/frontend/`)** | Full replacement | React 18/Vite → Next.js 15 App Router + shadcn/ui |
| S1, S3, S5, S6, S7, S10 | No change | Existing endpoints consumed via new S9 proxy routes |

**Break surface**: No backend endpoints modified. S8 and S9 gain additive routes. Frontend is a full replacement (ADR-F-03). No Kafka events, no DB schema changes, no Alembic migrations.

---

### 6.2 New API Endpoints

#### S8: New Briefing Endpoints

**`GET /api/v1/briefings/instrument/{instrument_id}`**
- Auth: `X-Internal-JWT` required
- Response: `{instrument_id, brief, generated_at, cache_hit, model_provider}`
- Rate limit: 60 req/min per tenant
- Cache: Valkey `s8:v1:brief:instrument:{id}:{date_utc}` TTL 24h
- **On LLM failure: do NOT write to cache — failed briefs are never cached. Retry always hits a fresh LLM call.**

**`GET /api/v1/briefings/morning`**
- Auth: `user_id` + `tenant_id` from JWT
- Response: `{user_id, brief, generated_at, cache_hit, context_summary, model_provider}`
- Rate limit: 10 req/min per user
- Cache: Valkey `s8:v1:brief:morning:{user_id}:{date_utc}` TTL 24h
- **On LLM failure: do NOT write to cache.**

> **Disambiguation**: The existing `POST /internal/v1/briefings` (PRD-0016, S10 email digest) remains unchanged at that path. The new endpoints use `GET /api/v1/briefings/*` prefix for frontend users.

#### S9: New Composition Endpoint

**`GET /v1/instruments/{instrument_id}/context`**
- **Purpose**: Single call to resolve instrument data + entity_id for the Company Detail page. Aggregates S3 instrument, S3 security (sector/industry/country), and S1 entity_id.
- **Auth**: Required
- **Response**:
  | Field | Type | Nullable | Source |
  |-------|------|----------|--------|
  | `instrument_id` | UUID | no | S3 |
  | `symbol` | string | no | S3 |
  | `exchange` | string | no | S3 |
  | `is_active` | boolean | no | S3 |
  | `flags.has_ohlcv` | boolean | no | S3 |
  | `flags.has_quotes` | boolean | no | S3 |
  | `flags.has_fundamentals` | boolean | no | S3 |
  | `security.security_id` | UUID | no | S3 |
  | `security.name` | string | no | S3 |
  | `security.sector` | string | yes | S3 |
  | `security.industry` | string | yes | S3 |
  | `security.country` | string | yes | S3 |
  | `security.figi` | string | yes | S3 |
  | `security.isin` | string | yes | S3 |
  | `security.currency` | string | yes | S3 |
  | `entity_id` | UUID | **yes** | S1 InstrumentRef (null if not in KG) |
- **Error responses**: 404 (instrument not found in S3)
- **Implementation**: S9 parallel calls: `S3.GET /api/v1/instruments/{id}` + `S1.GET /api/v1/instruments/{id}` → merge. If S1 returns 404, entity_id = null (not an error).

#### S9: New Briefing Proxy Routes

**`GET /v1/briefings/instrument/{instrument_id}`** — Authenticated proxy to S8. Rate limit: 60 req/min per tenant.

**`GET /v1/briefings/morning`** — Authenticated proxy to S8. Rate limit: 10 req/min per user.

#### S9: New Proxy Routes (S3 — not yet proxied)

| S9 Route | Proxies To |
|----------|-----------|
| `GET /v1/instruments` | S3 `GET /api/v1/instruments` (query params forwarded) |
| `GET /v1/instruments/{id}` | S3 `GET /api/v1/instruments/{id}` |
| `GET /v1/ohlcv/{instrument_id}` | S3 `GET /api/v1/ohlcv/{id}` (query params: timeframe, start, end) |
| `POST /v1/quotes/batch` | S3 `POST /api/v1/quotes/batch` |
| `GET /v1/quotes/{instrument_id}` | S3 `GET /api/v1/quotes/{id}` |
| `GET /v1/fundamentals/{instrument_id}` | S3 `GET /api/v1/fundamentals/{id}` |
| `GET /v1/fundamentals/{instrument_id}/{section}` | S3 `GET /api/v1/fundamentals/{id}/{section}` |
| `GET /v1/securities/{security_id}` | S3 `GET /api/v1/securities/{id}` |

#### S9: New Proxy Routes (S6 NLP Pipeline — not yet proxied)

| S9 Route | Proxies To |
|----------|-----------|
| `GET /v1/entities` | S6 `GET /api/v1/entities` (query `q`, limit, offset) |
| `GET /v1/entities/{entity_id}` | S6 `GET /api/v1/entities/{id}` |
| `GET /v1/entities/{entity_id}/articles` | S6 `GET /api/v1/entities/{id}/articles` |
| `GET /v1/signals` | S6 `GET /api/v1/signals` (query params forwarded) |

#### S9: New Proxy Routes (S7 Knowledge Graph — not yet proxied)

| S9 Route | Proxies To |
|----------|-----------|
| `GET /v1/entities/{entity_id}/graph` | S7 `GET /api/v1/entities/{id}/graph` |
| `GET /v1/entities/{entity_id}/contradictions` | S7 `GET /api/v1/entities/{id}/contradictions` |
| `POST /v1/claims/search` | S7 `POST /api/v1/claims/search` |
| `POST /v1/events/search` | S7 `POST /api/v1/events/search` |
| `GET /v1/temporal-events` | S7 `GET /api/v1/temporal-events` |

#### S9: New Feedback Endpoint

**`POST /v1/feedback`**
- **Auth**: Required
- **Body**: `{category: string, title: string | null, description: string}` (max 2000 chars)
- **Response**: `{status: "received"}`
- **Implementation**: S9 structlog only (no DB). Log level `info`, fields: `user_id`, `tenant_id`, `category`, `title`, `description_chars`, `submitted_at`.
- **No downstream call required** — S9 handles entirely.

---

### 6.3 Event Changes

**None.** No new Kafka events. Frontend is a pure REST consumer via S9.

---

### 6.4 Database Changes

**None for frontend.** Briefings cached exclusively in Valkey. Feedback logged via structlog only. No new DB tables.

---

### 6.5 Domain Model Changes

#### `InstrumentBriefResult` (new, S8 frozen dataclass)
| Attribute | Type | Required | Validation |
|-----------|------|----------|------------|
| `instrument_id` | UUID | yes | UUIDv7 |
| `brief` | str | yes | 50–2000 chars |
| `generated_at` | datetime | yes | UTC-aware |
| `cache_hit` | bool | yes | — |
| `model_provider` | str | yes | deepinfra/openrouter/ollama |

#### `MorningBriefResult` (new, S8 frozen dataclass)
| Attribute | Type | Required | Validation |
|-----------|------|----------|------------|
| `user_id` | UUID | yes | UUIDv7 |
| `brief` | str | yes | 50–3000 chars |
| `generated_at` | datetime | yes | UTC-aware |
| `cache_hit` | bool | yes | — |
| `context_summary` | dict | yes | `{portfolio_instruments: int, watchlist_entities: int, news_articles_sampled: int}` |
| `model_provider` | str | yes | enum |

#### `InstrumentContext` (new, S9 composition response)
| Attribute | Type | Required | Note |
|-----------|------|----------|------|
| `instrument_id` | UUID | yes | From S3 |
| `symbol` | str | yes | Trading symbol |
| `exchange` | str | yes | Exchange code |
| `is_active` | bool | yes | From S3 |
| `flags` | dict | yes | `{has_ohlcv, has_quotes, has_fundamentals}` |
| `security` | dict | yes | `{security_id, name, sector, industry, country, figi, isin, currency}` — all nullable except security_id and name |
| `entity_id` | UUID | **no (nullable)** | From S1 InstrumentRef.entity_id. Null if instrument not resolved to S7 KG entity. |

#### New S8 Use Cases
- `GenerateInstrumentBriefUseCase` — cache check → parallel retrieval (S3 highlights + S6 chunks + S7 graph + S6 signals) → LLM → cache write on success only → return
- `GenerateMorningBriefUseCase` — cache check → parallel retrieval (S1 portfolio + S3 quotes + S6 news + S6 signals + S7 events) → LLM → cache write on success only → return
- Both use `ReadOnlyUnitOfWork` (R27 compliance)

---

### 6.6 Frontend Specification

#### 6.6.A Architecture & Directory Structure

**Stack**: Next.js 15 App Router | shadcn/ui | Tailwind CSS v4 | TanStack Query 5 | lightweight-charts 4 | `react-grid-layout` | sigma.js + graphology | cmdk | react-hotkeys-hook | pnpm (exact versions, no `^`)

**Route structure**:
```
/                               Landing (public)
/login                          Login (public)
/callback                       OIDC callback (public)
/(protected)/dashboard          Dashboard
/(protected)/workspace          Workspace terminal
/(protected)/companies          Companies list
/(protected)/companies/[id]     Company detail (id = instrument_id)
/(protected)/portfolio          Portfolio strategies
/(protected)/news               News (2 tabs)
/(protected)/screener           Screener
/(protected)/chat               Chat (thread history)
/(protected)/map                Map stub
```

**Navigation sidebar** (AppSidebar Server Component, 220px):
```
[Logo + "Worldview"]
Dashboard        /dashboard
Workspace        /workspace   ← NEW
Companies        /companies
Portfolio        /portfolio
News             /news
Screener         /screener
Chat             /chat
Map              /map
─────────────────
[g+key hint strip: g+d, g+w, g+c ...]
[Avatar] [email] [Logout]
```

**TopBar** (`"use client"`): `[Page title] ... [⌘K hint] [WS status dot] [Alerts badge] [Avatar dropdown]`

**FeedbackWidget**: Fixed bottom-right. Rendered in root `(protected)/layout.tsx`.

#### 6.6.B Landing Page Layout

See full section specs in §3 F-01. Key layout order:
1. NavBar (sticky)
2. Hero (2-col)
3. SocialProofStatsBar
4. FeatureSpotlight (full-width)
5. FeaturesGrid (6 cards)
6. ComparisonTable
7. HowItWorks (3 steps)
8. TrustBar
9. PricingSection (3 cards with feature lists)
10. FAQSection (4 accordion questions)
11. CTASection
12. Footer

#### 6.6.C Dashboard Layout

See §3 F-03 for full widget specs.

#### 6.6.D Workspace Layout

See §3 F-04. 11 panel types. Open-in-Workspace behavior fully specified.

#### 6.6.E Company Detail Layout

See §3 F-05. Server Component prefetch `InstrumentContext`. Header with full data. 5 tabs with comprehensive data from all 18 S3 sections, S6 entity news, S7 graph/claims/events.

#### 6.6.F Companies List

See §3 F-06. Unchanged from v1.0.

#### 6.6.G Portfolio Layout

See §3 F-07. Strategy cards → Holdings | Transactions | Analytics | Watchlists | Settings tabs.

#### 6.6.H News

See §3 F-08. Feed + Top Today tabs.

#### 6.6.I Screener

See §3 F-09. Enhanced with sector filter + open-in-workspace action.

#### 6.6.J Chat

See §3 F-10. Thread search + copy button + citation cards.

#### 6.6.K Map Stub

*(Unchanged)* — Globe icon + "Coming Soon".

---

### 6.7 Data Flow — Key Flows

#### Flow 1: Company Detail Mount (entity resolution)

```
User navigates to /companies/{instrument_id}
Server Component page.tsx:
  prefetchQuery(['instrument-context', id]) → GET /v1/instruments/{id}/context
    S9: parallel:
      S3.GET /api/v1/instruments/{instrument_id} → instrument + flags + security_id
      S3.GET /api/v1/securities/{security_id} → sector, industry, country
      S1.GET /api/v1/instruments/{instrument_id} → entity_id (may be null)
    → merge → InstrumentContext { instrument_id, symbol, exchange, flags, security, entity_id }
  HydrationBoundary wraps client component with InstrumentContext
Client component:
  entity_id present → wire S7/S6 panels
  entity_id null → show "Entity data not available" in Intelligence tab
```

#### Flow 2: Morning Brief (Dashboard Mount)

```
Dashboard mount → useMorningBrief() → GET /v1/briefings/morning
S9 → S8: check Valkey s8:v1:brief:morning:{user_id}:{date_utc}
  Cache miss → GenerateMorningBriefUseCase:
    asyncio.gather:
      S1 portfolios → top 5 holdings
      S1 watchlists → entity list
      S3 quotes/batch → overnight changes
      S6 news (top 3, 48h, watchlist-filtered)
      S6 signals (HIGH/CRITICAL, 24h)
      S7 temporal-events (ACTIVE, global scope)
    → LLM → cache write (SUCCESS ONLY) → return
  Cache hit → <50ms
  LLM failure → raise ProviderUnavailableError → 503 → frontend static fallback
  NOTE: Failed briefs are NEVER written to Valkey cache.
```

#### Flow 3: Instrument Brief (Company Detail Mount)

```
CompanyDetail mount → useInstrumentBrief(instrumentId)
GET /v1/briefings/instrument/{id}
S8: cache check → miss → GenerateInstrumentBriefUseCase:
  asyncio.gather:
    S3 fundamentals/{id}/highlights
    S6 vector search (entity-scoped top-3 chunks)
    S7 graph 1-hop (entity_id if available)
    S6 signals (entity_id, limit 3)
  → LLM → cache write (SUCCESS ONLY) → return
NOTE: If entity_id null, skip S7/entity-scoped S6 calls.
```

#### Flow 4: Workspace Ticker Linking

```
User opens /workspace → WorkspaceGrid renders layout from localStorage
  Check localStorage 'worldview:workspace:pending-ticker' → if present:
    setActiveTicker(pending.ticker)
    remove from localStorage
    ensure ChartPanel in layout
ChartPanel ticker changes → WorkspaceTickerContext.setActiveTicker
All linked panels refetch for new ticker
AlertsPanel: NOT linked (user-global stream)
OnLayoutChange → localStorage.setItem (auto-saved)
```

#### Flow 5: Portfolio Holdings with Live Quotes

```
Portfolio page → fetch holdings for selected portfolio:
  GET /v1/portfolios/{id}/holdings → list[{instrument_id, quantity, average_cost}]
  Extract all instrument_ids
  POST /v1/quotes/batch {instrument_ids: [...]} → {instrument_id: QuoteResponse}
  For each holding: current_value = quote.last * quantity
  unrealized_pnl = (quote.last - average_cost) * quantity
  total_portfolio_value = sum(current_values)
  weight_pct = current_value / total_portfolio_value * 100
  Sector: GET /v1/instruments/{id}/context per instrument (batch with Promise.all, cached)
  → render HoldingsTable
```

---

## 7. Architecture Decisions

### ADR-F-01 through ADR-F-05 (existing)
See `docs/ui/frontend-migration.md` §1.

### ADR-F-06: Landing Page at `/` — App at `/dashboard` *(unchanged)*

### ADR-F-07: Workspace State via React Context + localStorage *(unchanged)*

### ADR-F-08: Entity Graph — sigma.js over D3.js *(unchanged)*

### ADR-F-09: Morning Brief — On-Demand, Demand-Driven *(unchanged)*

### ADR-F-10: Briefing Cache — Valkey Only, 24h TTL *(unchanged)*
**Addition**: Failed briefs (LLM unavailable, timeout) are **never** written to cache. The cache key is only set on successful generation. Retry always invokes the LLM fresh.

### ADR-F-11: Command Palette via cmdk *(unchanged)*

### ADR-F-12: entity_id ≠ instrument_id — Resolution via S9 Composition (NEW)

**Context**: S3 uses `instrument_id` (UUID) as primary key for trading instruments. S7 uses `entity_id` (UUID) as primary key for canonical knowledge graph entities. S1 `InstrumentRef` bridges them via `entity_id: UUID | null` field (populated by S6 entity resolution pipeline, nullable).

**Decision**: `instrument_id` and `entity_id` are **distinct UUIDs** from different namespaces. They are NOT unified. Making them equal would break S7 (which has entities for persons, funds, events — not just financial instruments).

**Resolution pattern**: The new `GET /v1/instruments/{instrument_id}/context` S9 composition endpoint returns both in a single call. The Company Detail page always fetches context first and passes `entity_id` (which may be null) to all S7-dependent components.

**Frontend contract**:
- URLs always use `instrument_id` (from S3/S1)
- Watchlist members store `entity_id` (from S7)
- All S7 graph/KG API calls use `entity_id`
- All S3 OHLCV/fundamentals/quotes calls use `instrument_id`
- If `entity_id` is null: S7 panels show graceful empty state, not an error

### ADR-F-13: Professional Data Density — Compact Table Design (NEW)

**Decision**: Financial data tables use compact density: `text-xs leading-tight`, row height `h-8 min-h-[2rem]`, monospace numerics right-aligned (`font-mono tabular-nums text-right`). This matches Finviz/Bloomberg information density vs. consumer-grade spacious tables.

**Rationale**: Research users need to compare many rows simultaneously without scrolling. Compact tables double the visible rows vs. standard shadcn table defaults.

### ADR-F-14: HeatCell Color Scale — 7-Step Financial Heat Map (NEW)

**Decision**: Percentage change values (daily % change, unrealized P&L %, screener metric deviations) use a 7-step color scale applied as background-color on table cells and sector heat map tiles.

**Scale** (CSS variable computation):
```
< -3%: bg-red-900/80
-3 to -1.5%: bg-red-700/60
-1.5 to -0.5%: bg-red-500/40
-0.5 to +0.5%: bg-slate-700/30 (neutral)
+0.5 to +1.5%: bg-green-500/40
+1.5 to +3%: bg-green-700/60
> +3%: bg-green-500/80
```

**Rationale**: Matches Finviz and Bloomberg heat map conventions. Users can immediately scan P&L/change tables without reading every number.

---

## 8. Security Analysis

### 8.1 Auth Security *(unchanged)*

access_token: React memory only. refresh_token: httpOnly SameSite=Strict cookie. 401 → auto-refresh → retry → logout on failure.

### 8.2 XSS Prevention *(unchanged)*

No `dangerouslySetInnerHTML`. Chat responses: plain text. Article titles: text nodes. Company logos: clearbit CDN, domain from S3 only (not user input).

### 8.3 Open Redirect *(unchanged)*

Next.js `router.push()` with internal paths only. No iframes.

### 8.4 Multi-Tenant Isolation *(unchanged)*

All calls include `Authorization: Bearer`. S9 extracts `tenant_id` from JWT.

### 8.5 Feedback Endpoint (NEW)

`POST /v1/feedback`: Auth required (limits abuse to authenticated users). Input validation: category is enum, description max 2000 chars. Content logged via structlog only — no external calls, no DB writes, no XSS vector (plain text logged, not rendered).

### 8.6 Entity_id Resolution

`GET /v1/instruments/{id}/context` requires auth. S1 and S3 calls use service-to-service tokens inside S9. `entity_id` returned is a UUID from the knowledge graph — no user input involved.

---

## 9. Failure Modes

| Component | Failure | User Experience | Recovery |
|-----------|---------|-----------------|---------|
| Morning Brief — LLM down | 503 from S8 | Static fallback text + Retry button. Brief never cached on failure. | Retry re-invokes LLM (cache miss guaranteed) |
| Instrument Brief — LLM down | 503 | "AI analysis unavailable" + Retry | Same as above |
| InstrumentContext — S1 unavailable | S9 partial response | entity_id = null → Intelligence tab shows empty state | Retry on tab switch |
| InstrumentContext — S3 unavailable | 503 | Company Detail shows error page | TanStack Query 3 retries |
| Market HeatMap — quotes unavailable | S3 quotes 503 | Tiles show "--" text, no color | 30s TanStack retry |
| Portfolio sector lookup — S3 slow | N instrument context calls slow | Holdings show "—" for Sector column | Requests are batched + cached |
| WebSocket disconnects | Network / S10 restart | TopBar dot yellow → backoff reconnect | Auto-reconnect 1s→30s |
| react-grid-layout localStorage | Corrupted JSON | try/catch → reset to default layout | "Reset Layout" always available |
| Workspace panel error | Single panel 5xx | Panel shows ErrorCard + Retry | Per-panel error boundary |
| Feedback POST fails | S9 structlog failure | Toast error "Failed to send. Try again." | Manual retry (dialog stays open) |
| entity_id null (instrument not in KG) | Not an error — expected state | Intelligence tab: "Entity data not available for this instrument" | No recovery needed |

---

## 10. Scalability & Performance

### 10.1 Bundle Size Strategy

- `react-grid-layout` (~20KB gzipped): workspace route only (code splitting)
- `sigma.js` + `graphology` (~80KB gzipped): dynamic import with `next/dynamic` — Intelligence tab only
- `lightweight-charts` (~45KB gzipped): dynamic import
- `react-hotkeys-hook`: minimal (~3KB)
- Landing page: zero heavy library JS (all Server Components)
- Target: initial bundle < 200KB gzipped

### 10.2 Data Fetching Strategy

- `HydrationBoundary` on CompanyDetail (prefetch InstrumentContext) and Portfolio
- TanStack Query staleTime: quotes=5s, holdings=30s, fundamentals=15min, threads=30s, temporal-events=5min
- Portfolio: single `POST /v1/quotes/batch` for ALL holdings (not N individual calls)
- InstrumentContext: TanStack cache prevents re-fetching when user switches tabs on same company
- MarketHeatmap: sector ETF quotes batched in single request (11 instruments)

### 10.3 Workspace Performance

- `react-grid-layout` CSS transforms for drag (GPU-accelerated)
- Panels wrapped in `React.memo` — cross-panel re-renders prevented
- EntityGraphPanel: sigma.js WebGL handles 100 nodes at 60fps

### 10.4 Holdings Sector Resolution

When Portfolio page loads holdings (may be 20–50 instruments): use `Promise.all` for context fetches but limit concurrency to 5 with a semaphore to avoid overwhelming S9. Cache: TanStack Query caches each `[instrument-context, id]` — tab switches and re-renders don't re-fetch.

---

## 11. Test Strategy

### 11.1 Unit Tests (Vitest + React Testing Library)

| Test | Component | What It Verifies | Priority |
|------|-----------|-----------------|---------|
| `test_morning_brief_card_skeleton` | MorningBriefCard | Skeleton while loading | HIGH |
| `test_morning_brief_card_static_fallback` | MorningBriefCard | 503 → static fallback + Retry | HIGH |
| `test_instrument_brief_skeleton_to_text` | InstrumentBriefCard | Skeleton → text transition | HIGH |
| `test_heat_cell_7_step_colors` | HeatCell | -3% → red-900, +3% → green-500 | HIGH |
| `test_sparkline_renders_svg` | Sparkline | SVG path rendered for data array | MEDIUM |
| `test_live_price_badge_stale_yellow` | LivePriceBadge | >30s old → yellow dot | HIGH |
| `test_flash_overlay_escape_dismisses` | FlashOverlay | Escape → onDismiss | HIGH |
| `test_comparison_table_worldview_highlight` | ComparisonTable | Worldview row has primary border class | MEDIUM |
| `test_workspace_grid_default_layout` | WorkspaceGrid | 4 panels in default config | HIGH |
| `test_workspace_pending_ticker_applied` | WorkspaceGrid | localStorage pending-ticker → setActiveTicker | HIGH |
| `test_workspace_layout_saves_localstorage` | WorkspaceGrid | onLayoutChange → localStorage.setItem | HIGH |
| `test_panel_wrapper_close_removes` | PanelWrapper | Close → panel removed | MEDIUM |
| `test_auth_layout_redirects_unauthenticated` | (protected)/layout | user=null → /login | HIGH |
| `test_feedback_dialog_submit` | FeedbackDialog | Submit → POST /v1/feedback called | HIGH |
| `test_feedback_dialog_validation` | FeedbackDialog | Empty description → submit disabled | MEDIUM |
| `test_holdings_pnl_computation` | HoldingsTable | unrealized = (price - avg_cost) × qty | HIGH |
| `test_holdings_weight_pct` | HoldingsTable | weight = value / total | HIGH |
| `test_thread_search_client_filter` | ChatSidebar | Search input filters thread.title | MEDIUM |
| `test_instrument_context_entity_null` | IntelligenceTab | entity_id=null → empty state shown | HIGH |
| `test_company_header_52w_range` | CompanyHeader | 52w range bar renders current price position | MEDIUM |
| `test_market_heatmap_color_negative` | MarketHeatmapCard | negative daily % → red tile | HIGH |
| `test_strategy_card_grid` | PortfolioPage | 3 strategies render as 3 cards | MEDIUM |
| `test_add_transaction_sheet_submit` | AddTransactionSheet | Form submit → POST /v1/transactions | HIGH |

### 11.2 Integration Tests (MSW + Vitest)

| Test | Mocked APIs | What It Verifies |
|------|------------|-----------------|
| `test_dashboard_all_widgets` | morning, alerts, portfolios, quotes, news, temporal-events | All 6 widgets render |
| `test_company_detail_context_resolution` | instruments/context, quotes, fundamentals/highlights | Header renders with sector, entity_id passed to tabs |
| `test_company_detail_entity_id_null` | instruments/context returns entity_id=null | Intelligence tab shows empty state (not error) |
| `test_company_detail_all_5_tabs` | context, briefings/instrument, graph, contradictions, news | All 5 tabs mount without errors |
| `test_workspace_ticker_linking` | ohlcv, news/relevant | Ticker change in ChartPanel propagates to NewsFeedPanel |
| `test_workspace_open_from_company` | — | pending-ticker localStorage → activeTicker set on mount |
| `test_portfolio_quotes_batch` | portfolios, holdings, quotes/batch | Single batch call for all holding quotes |
| `test_portfolio_sector_allocation_chart` | context per instrument | Donut chart groups by sector |
| `test_portfolio_add_transaction` | transactions POST | Sheet form submit → POST + cache invalidate |
| `test_news_top_today_filters` | news/top | Filter params sent correctly |
| `test_screener_run_result` | screen/fields, screen | Results render + row click navigates |
| `test_chat_sse_streaming_tokens` | chat/stream | Tokens stream, citations appear |
| `test_feedback_widget_submit` | feedback POST | Category + description → POST /v1/feedback |
| `test_market_heatmap_quotes_batch` | quotes/batch (sector ETFs) | 11 tiles render with correct colors |

### 11.3 E2E Tests (Playwright)

| Test | What It Verifies |
|------|-----------------|
| `test_landing_comparison_table` | ComparisonTable renders with Worldview row highlighted |
| `test_landing_pricing_feature_lists` | Each pricing card shows feature bullet list |
| `test_landing_faq_accordion` | Click question → answer expands |
| `test_landing_trust_bar_visible` | 3 trust items render below HowItWorks |
| `test_login_redirects_to_dashboard` | Full OIDC (mocked) → dashboard with morning brief skeleton |
| `test_company_search_to_detail` | Search "AAPL" → click → company detail with 5 tabs |
| `test_company_open_in_workspace` | Click "Open in Workspace" → navigate → ChartPanel shows AAPL |
| `test_workspace_add_panel` | "+ Add Panel" → select Heatmap → panel appears |
| `test_workspace_drag_persists` | Drag panel → reload → same position |
| `test_portfolio_strategy_selection` | Click strategy card → holdings tab renders |
| `test_portfolio_add_transaction_flow` | Open sheet → fill form → submit → holdings updated |
| `test_chat_thread_search` | Type in search → threads filter by title |
| `test_alert_flash_overlay` | Mock WS CRITICAL → overlay appears → Escape dismisses |
| `test_fundamentals_group5_company_profile` | Fundamentals tab → Group 5 → description + CEO visible |
| `test_screener_heat_cell_colors` | Screener results → daily change % cells have background color |
| `test_feedback_widget_submit` | Click feedback button → fill form → submit → toast appears |

---

## 12. Dependencies & Migration

### 12.1 Dependencies on Other Plans

| Plan | Required For | Status |
|------|-------------|--------|
| PLAN-0025 Wave E (frontend auth) | LoginPage, CallbackPage, AuthContext, WS auth | Pending — Wave A blocked until complete |
| PRD-0026 (news intelligence APIs) | News Top Today tab, RelevanceBadge, ImpactSparkline | Draft — UI built with placeholder; wired on PRD-0026 completion |
| PLAN-0022 Wave 9 (brokerage) | BrokerageConnectionPanel | Near-complete — Portfolio page stubs if not done |

### 12.2 Frontend Migration Steps

1. Delete Vite: `vite.config.ts`, `index.html`, `src/main.tsx`, `deploy/nginx.conf`, `react-router-dom`
2. Scaffold Next.js 15 in `apps/frontend/` (ADR-F-03 in-place)
3. Install packages (see §12.3)
4. Port components: OHLCVChart, ChatUI, AlertCard, FlashOverlay, NewsList, PredictionMarketsPanel
5. Rename `VITE_API_BASE_URL` → `NEXT_PUBLIC_API_BASE_URL`
6. Replace Dockerfile: nginx static → `node:alpine next start`
7. Add `next.config.ts` rewrites + `NEXT_PUBLIC_WS_BASE_URL`

### 12.3 New npm Dependencies

| Package | Purpose | Size |
|---------|---------|------|
| `next@15.x` | Framework | — |
| `tailwindcss@4.x` | Styling | — |
| `@tailwindcss/postcss` | Tailwind v4 plugin | — |
| `class-variance-authority` | shadcn variants | ~3KB |
| `clsx` + `tailwind-merge` | className util | ~2KB |
| `lucide-react` | Icons | ~5KB (tree-shaken) |
| `react-grid-layout` | Workspace drag-and-drop | ~20KB |
| `sigma` | WebGL graph renderer | ~60KB |
| `graphology` | Graph model | ~20KB |
| `@react-sigma/core` | React/sigma integration | ~10KB |
| `graphology-layout-forceatlas2` | Force layout | ~15KB |
| `cmdk` | Command palette | ~10KB |
| `react-hotkeys-hook` | Keyboard shortcuts | ~3KB |
| `recharts` | Portfolio donut + bar charts | ~40KB (code-split) |

### 12.4 Architecture Compliance Gate

| Rule | Applies? | Design Decision | Compliant? |
|------|----------|----------------|-----------|
| R14 — Frontend → S9 only | YES | All API calls go through S9 `/api/*` | ✅ PASS |
| R8 — No secrets in code | YES | `NEXT_PUBLIC_*` env vars only | ✅ PASS |
| R10 — UUIDv7 | YES | S8 briefing entities use `common.ids.new_uuid7()` | ✅ PASS |
| R11 — UTC timestamps | YES | S8 `generated_at` uses `common.time.utc_now()` | ✅ PASS |
| R25 — API layer uses only use cases | YES | New S8 endpoints use use cases | ✅ PASS |
| R27 — ReadOnly UoW for reads | YES | Both brief use cases are read-only | ✅ PASS |
| ADR-F-04 — Dark theme only | YES | `class="dark"` permanent | ✅ PASS |
| ADR-F-12 — entity_id resolution | YES | Via `/v1/instruments/{id}/context` composition | ✅ PASS |

---

## 13. Observability

### 13.1 S8 Briefing Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `s8_briefing_instrument_generated_total` | Counter | Instrument briefs generated (cache misses) |
| `s8_briefing_instrument_cache_hits_total` | Counter | Cache hits |
| `s8_briefing_morning_generated_total` | Counter | Morning briefs generated |
| `s8_briefing_morning_cache_hits_total` | Counter | Morning brief cache hits |
| `s8_briefing_generation_latency_seconds` | Histogram | p50/p95/p99 |
| `s8_briefing_llm_provider_total{provider}` | Counter | By provider: deepinfra/openrouter/ollama |
| `s8_briefing_errors_total{error_type}` | Counter | LLM_UNAVAILABLE, INSTRUMENT_NOT_FOUND |

### 13.2 S9 Feedback Metric

| Metric | Type | Description |
|--------|------|-------------|
| `s9_feedback_submitted_total{category}` | Counter | Feedback submissions by category |

### 13.3 Structured Logs

```json
{"event": "instrument_brief_generated", "instrument_id": "...", "cache_hit": false, "latency_ms": 2341, "provider": "deepinfra"}
{"event": "morning_brief_generated", "user_id": "...", "cache_hit": true, "latency_ms": 12}
{"event": "brief_generation_failed", "type": "instrument", "error": "LLM_UNAVAILABLE", "instrument_id": "...", "cached": false}
{"event": "feedback_submitted", "user_id": "...", "tenant_id": "...", "category": "Feature Request", "description_chars": 340}
```

### 13.4 Frontend Observability

- Next.js Web Vitals via `instrumentation.ts`
- Error boundaries per page section → structured error logging
- TanStack Query `onError` callbacks with endpoint URL + status code

---

## 14. Open Questions

| # | Question | Classification | Status |
|---|----------|---------------|--------|
| OQ-1 | Clearbit logo API rate limits on free tier? | DEFERRED | Use `logo.clearbit.com`. Fallback: ticker initials avatar component. |
| OQ-2 | react-grid-layout touch support for tablet? | DEFERRED | Library supports touch; test on iPad for thesis demo. |
| OQ-3 | sigma.js performance for 200+ node entity graphs? | DEFERRED | Default S7 `limit=100`; WebGL handles 100 nodes at 60fps. |
| OQ-4 | Landing page final copy? | DEFERRED | Headlines specified in §3 F-01; refined during `/design-ui` session. |
| OQ-5 | Billing integration for pricing tiers? | DEFERRED | Pricing section display-only for MVP. No payment integration. |
| OQ-6 | QuickStatsBar — VIX available in EODHD free tier? | DEFERRED | Use SPY, QQQ, DIA (confirmed). VIX: conditional on EODHD availability. |
| OQ-7 | Morning brief 10s timeout: abort or show partial? | DEFERRED | After 10s: show static fallback + "Generating in background..." Retry. |
| OQ-8 | Chat thread title auto-generation | RESOLVED | Client-side: `message.slice(0, 40) + "..."`. No new endpoint. |
| OQ-9 | entity_id resolution | **RESOLVED** | `GET /v1/instruments/{id}/context` composition endpoint. entity_id nullable. If null, S7 panels show graceful empty state. See ADR-F-12. |
| OQ-10 | "Open in Workspace" behavior | **RESOLVED** | localStorage pending-ticker pattern. See §3 F-04 and ADR-F-12. |
| OQ-11 | Portfolio equity curve chart | DEFERRED | Requires client-side reconstruction from full transaction history × OHLCV. Deferred to v2; see §5 Out of Scope. |
| OQ-12 | recharts vs chart.js for portfolio donut/bar charts? | DEFERRED | recharts chosen (React-native, smaller bundle for code-split usage). |
| OQ-13 | Sector ETF list for heat map | DEFERRED | Use: XLK, XLF, XLE, XLV, XLY, XLI, XLU, XLRE, XLB, XLP, XLC (11 SPDRs). Resolve via S3 `GET /v1/instruments?query=XLK` etc. on first load. Cache sector→instrument_id mapping in localStorage. |
| **OQ-14** | **Design direction: A (Amber Terminal), B (Midnight Pro), or C (Deep Navy)?** | **BLOCKING** | **Unresolved. See §1.4.3. Recommendation: Direction B. Must select before pencil.dev redesign.** |
| **OQ-15** | **Font confirmation: IBM Plex Sans + IBM Plex Mono vs alternatives?** | **BLOCKING** | **Unresolved. Recommended: IBM Plex stack (§1.4.4). Alternatives: Inter + JetBrains Mono (Direction C).** |

---

## 15. Implementation Order

### Wave A — Foundation (prerequisite for all)

- Next.js 15 scaffold (delete Vite, install Next.js + Tailwind + shadcn/ui)
- Root layout, globals.css, AppSidebar, TopBar, FeedbackWidget (F-15)
- AuthContext + authClient.ts (from PLAN-0025 Wave E spec)
- LoginPage + CallbackPage
- Protected route guard `(protected)/layout.tsx`
- Global keyboard shortcuts (F-16)
- HeatCell, Sparkline, LivePriceBadge, CompactTable base components

### Wave B — Core Pages + Briefing Backend

- S8: `GenerateInstrumentBriefUseCase` + `GenerateMorningBriefUseCase` + endpoints + Valkey caching (fail-safe: never cache on LLM failure)
- S9: all new proxy routes from §6.2 (S3, S6, S7 proxies + `/v1/instruments/{id}/context` composition + `/v1/feedback` + briefing routes)
- Dashboard page (MorningBriefCard + 6 widgets including MarketHeatmapCard + TopMoversCard + EconomicCalendarCard)
- Company Detail: header (with InstrumentContext resolution) + chart + FundamentalsBar + tab structure skeleton
- InstrumentBriefCard component

### Wave C — Intelligence Components

- OHLCVChart port + technical overlays (MA50/MA200/Volume toggle)
- FundamentalsAccordion (5 groups, all 18 S3 sections mapped)
- EntityGraph (sigma.js) + SimilarCompaniesPanel + ContradictionsPanel + ClaimsPanel + TemporalEventsPanel
- EntityNewsPanel + RelevanceBadge + ImpactSparkline
- AlertStreamContext + WebSocket + FlashOverlay + SeverityBadge
- Company Detail all 5 tabs wired with InstrumentContext entity_id

### Wave D — Workspace

- WorkspaceGrid (react-grid-layout) + WorkspaceTickerContext
- All 11 panel types
- PanelWrapper + PanelPicker modal
- Layout persistence + "Open in Workspace" behavior
- Per-panel error boundaries

### Wave E — Portfolio + Supporting Pages

- Portfolio page: StrategyCard grid + AddTransactionSheet + HoldingsTable + Analytics tab + sector allocation chart
- Companies list page
- News page (Feed + Top Today)
- Screener page (with HeatCell results + sector filter)
- Chat page (thread sidebar + search + streaming + copy button)
- Map stub

### Wave F — Landing Page + Polish

- Landing page (all 12 sections: NavBar → ComparisonTable → TrustBar → Pricing with feature lists → FAQ → Footer)
- CommandPalette (Cmd+K)
- All empty/error/loading states verified across all pages
- Accessibility audit (keyboard nav, contrast ≥4.5:1, aria-labels)
- Vitest unit test suite
- Playwright E2E tests
- Dockerfile update (next start)

### Dependency Graph

```
Wave A (scaffold + auth + base components)
  → Wave B (briefing backend + S9 routes + dashboard + company header)
     → Wave C (intelligence components — EntityGraph, news, chart indicators)
        → Wave D (workspace — needs EntityGraph from C)
     → Wave E (portfolio + supporting pages — needs auth + S9 routes from B)
        → Wave F (landing page + polish — needs everything from A-E)

PLAN-0025 Wave E → Wave A (auth prerequisite)
PRD-0026 → Wave C (EntityNewsPanel Top Today tab wiring)
PLAN-0022 Wave 9 → Wave E (BrokerageConnectionPanel in Portfolio settings)
```

---

### ADR-F-15: Typography — IBM Plex Sans + IBM Plex Mono (NEW)

**Context**: Current design uses system font stack. Professional financial platforms all use
deliberate custom typography. System fonts signal "prototype" or "developer tool."

**Decision**: Adopt **IBM Plex Sans** (UI text) + **IBM Plex Mono** (ALL numeric data, tickers,
prices, percentages). Both are Google Fonts — free, CDN-cached, next/font/google compatible.

**Rationale**:
- IBM Plex is an open-source corporate typeface from the company that built financial mainframes.
  The institutional DNA is authentic, not decorative.
- The Sans/Mono pairing is designed to work together — consistent x-height, same proportional
  metrics. Mixed font stacks from different type families look mismatched.
- IBM Plex Mono has excellent tabular figure support at small sizes (11–13px) — critical for
  dense financial tables.
- Alternative (Inter + JetBrains Mono) is acceptable if Direction C (Deep Navy) is chosen.

**Implementation**: Load via `next/font/google` in root layout. Apply via CSS variables:
`--font-sans: IBM Plex Sans; --font-mono: IBM Plex Mono`.

**Applied to**: ALL components. Enforcement: ESLint `no-restricted-syntax` rule to ban
`font-family` hardcoding in className strings (use Tailwind `font-sans` / `font-mono` instead).

---

### ADR-F-16: Color System — Direction B "Midnight Pro" (pending confirmation) (NEW)

**Context**: Current color system uses Tailwind defaults (slate-950 background, blue-500 accent).
These are identical to every AI-generated dark mode SaaS template and immediately signal
non-professional to finance users who have used Bloomberg or TradingView.

**Decision** (pending OQ-14 resolution): Direction B "Midnight Pro":
- Background: `#131722` (TradingView's exact background)
- Accent: `#0EA5E9` sky-500 (distinctive from generic `blue-500`)
- Positive: `#26A69A` teal-green (industry standard for financial up)
- Negative: `#EF5350` (TradingView's muted red)
- Font primary text: `#D1D4DC` (warm white, vs harsh `#F8FAFC`)

**Rationale**: See §1.4.4. `#131722` is validated by 50M+ TradingView users as the canonical
professional fintech dark background. Sky accent is distinctive from generic blue. Teal-green
is universally recognized as "financial instrument up" without reading cartoon green.

**Implementation**: Override CSS variables in `globals.css`. All components use CSS variables
(shadcn/ui convention) — no hardcoded hex in component files. Pre-configure Tailwind
`extend.colors` to expose `positive`, `negative`, `warning` as design tokens.

---

## 16. Appendix A — Complete Backend API Surface

> **Purpose**: Every HTTP endpoint available via S9 API Gateway, organized by the UI page that
> consumes it. Enables designers and implementers to know exactly what data is available.
> **Source**: Audited 2026-04-13. See `/docs/services/api-gateway.md` for full routing table.

All frontend calls route through S9 at `http://localhost:8000/v1/*`. Direct backend calls are prohibited (Rule R14).

### 16.1 Authentication (All pages)

| Method | S9 Route | Description | Auth |
|--------|----------|-------------|------|
| GET | `/v1/auth/login` | Initiate PKCE → Zitadel redirect | No |
| GET | `/v1/auth/callback` | Exchange code → tokens, provision S1 user | No |
| POST | `/v1/auth/refresh` | Rotate access_token | No |
| POST | `/v1/auth/logout` | Revoke + clear cookies | No |
| GET | `/v1/auth/me` | Current user profile `{user_id, email, tenant_id, roles}` | JWT |

### 16.2 Dashboard Page Endpoints

| Method | S9 Route | Widget | Backend | staleTime |
|--------|----------|--------|---------|-----------|
| GET | `/v1/briefings/morning` | MorningBriefCard | S8 + Valkey 24h | 24h (manual refetch) |
| GET | `/v1/portfolios?limit=1` | PortfolioSummaryCard | S1 | 30s |
| GET | `/v1/portfolios/{id}/holdings` | PortfolioSummaryCard | S1 | 30s |
| POST | `/v1/quotes/batch` | PortfolioSummaryCard + MarketHeatmapCard + TopMoversCard | S3 Valkey 5s | 30s (batch) |
| GET | `/v1/news/relevant?limit=5` | WatchlistNewsCard | S5+S6 | 30s |
| GET | `/v1/alerts/pending?limit=5&min_severity=medium` | TopSignalsCard + RecentAlertsCard | S10 | 30s |
| GET | `/v1/temporal-events?active_only=false&limit=5` | EconomicCalendarCard | S7 | 5min |
| WS | `/v1/alerts/stream` | Alert badges, FlashOverlay | S10 | Real-time |
| GET | `/v1/watchlists` | TopMoversCard (instruments) | S1 | 30s |

**Sector ETF batch** (MarketHeatmapCard): POST `/v1/quotes/batch` with these 11 instrument IDs
(resolved once on mount via `GET /v1/instruments?query=XLK` etc.): XLK, XLF, XLE, XLV, XLY, XLI, XLU, XLRE, XLB, XLP, XLC.

### 16.3 Company Detail Page Endpoints

| Method | S9 Route | Section | Backend | staleTime |
|--------|----------|---------|---------|-----------|
| GET | `/v1/instruments/{id}/context` | Entity resolution (page mount) | S9 composition (S3+S1) | 1h |
| GET | `/v1/quotes/{instrument_id}` | Header live price | S3 Valkey 5s | 5s |
| GET | `/v1/fundamentals/{id}/highlights` | Header (MarketCap, 52w, AvgVol) | S3 | 5min |
| GET | `/v1/briefings/instrument/{id}` | InstrumentBriefCard | S8 Valkey 24h | 24h |
| GET | `/v1/fundamentals/{id}/analyst-consensus` | AnalystConsensusCard | S3 | 15min |
| GET | `/v1/ohlcv/{id}` | OHLCVChart | S3 | 1min–1h (by timeframe) |
| GET | `/v1/fundamentals/{id}/income-statement` | Fundamentals Group 1 | S3 | 15min |
| GET | `/v1/fundamentals/{id}/highlights` | Fundamentals Group 1 | S3 | 15min |
| GET | `/v1/fundamentals/{id}/balance-sheet` | Fundamentals Group 2 | S3 | 15min |
| GET | `/v1/fundamentals/{id}/cash-flow` | Fundamentals Group 3 | S3 | 15min |
| GET | `/v1/fundamentals/{id}/valuation` | Fundamentals Group 4 | S3 | 15min |
| GET | `/v1/fundamentals/{id}/earnings` | Fundamentals Group 4 (EPS chart) | S3 | 15min |
| GET | `/v1/fundamentals/{id}/company-profile` | Fundamentals Group 5 | S3 | 1h |
| GET | `/v1/fundamentals/{id}/institutional-holders` | Fundamentals Group 5 | S3 | 1h |
| GET | `/v1/fundamentals/{id}/fund-holders` | Fundamentals Group 5 | S3 | 1h |
| GET | `/v1/fundamentals/{id}/insider-transactions-snapshot` | Fundamentals Group 5 | S3 | 1h |
| GET | `/v1/fundamentals/timeseries` | Revenue trend + FCF trend | S3 | 1h |
| GET | `/v1/entities/{entity_id}/graph` | EntityGraph (Intelligence tab) | S7 | 5min |
| GET | `/v1/entities/{entity_id}/contradictions` | ContradictionsPanel | S7 | 5min |
| POST | `/v1/entities/similar` | SimilarCompaniesPanel | S7 | 5min |
| POST | `/v1/claims/search` | RecentClaimsPanel | S7 | 5min |
| POST | `/v1/events/search` | TemporalEventsPanel | S7 | 5min |
| GET | `/v1/entities/{entity_id}/articles` | News tab EntityNewsPanel | S6 | 30s |
| GET | `/v1/signals/prediction-markets?query={ticker}` | PredictionMarketsPanel | S3 | 15s |
| GET | `/v1/signals/prediction-markets/{market_id}/history` | PredictionMarkets sparkline | S3 | 1min |
| POST | `/v1/watchlists/{id}/members` | ★ Add to Watchlist | S1 | — |
| DELETE | `/v1/watchlists/{id}/members/{entity_id}` | ★ Remove from Watchlist | S1 | — |

### 16.4 Workspace Page Endpoints

Each panel type has its own endpoint set. Panels only fetch when linked:

| Panel | Endpoint(s) | Backend |
|-------|------------|---------|
| ChartPanel | `GET /v1/ohlcv/{id}?timeframe&start&end` | S3 |
| NewsFeedPanel | `GET /v1/entities/{entity_id}/articles` or `/v1/news/relevant` | S6 / S5+S6 |
| AlertsPanel | WS `/v1/alerts/stream` + `GET /v1/alerts/pending` | S10 |
| FundamentalsPanel | `GET /v1/fundamentals/{id}/highlights` | S3 |
| ChatPanel | `POST /v1/chat/stream` (SSE), `POST /v1/threads` | S8 |
| PredictionMarketsPanel | `GET /v1/signals/prediction-markets` | S3 |
| ScreenerPanel | `POST /v1/fundamentals/screen`, `GET /v1/fundamentals/screen/fields` | S3 |
| EntityGraphPanel | `GET /v1/entities/{entity_id}/graph` | S7 |
| HeatmapPanel | `POST /v1/quotes/batch` (sector ETFs) | S3 |
| PortfolioSummaryPanel | `GET /v1/portfolios`, `POST /v1/quotes/batch` | S1 + S3 |
| MacroEventsPanel | `GET /v1/temporal-events?limit=10` | S7 |

**Alert acknowledge**: `DELETE /v1/alerts/{alert_id}/ack`

### 16.5 Portfolio Page Endpoints

| Method | S9 Route | Usage | staleTime |
|--------|----------|-------|-----------|
| GET | `/v1/portfolios` | List strategy cards | 30s |
| POST | `/v1/portfolios` | Create strategy | — |
| PUT | `/v1/portfolios/{id}` | Rename | — |
| DELETE | `/v1/portfolios/{id}` | Archive | — |
| GET | `/v1/portfolios/{id}/holdings` | HoldingsTable | 30s |
| POST | `/v1/transactions` | Add transaction | — |
| GET | `/v1/transactions?limit=20&offset=N` | Transactions tab | 30s |
| POST | `/v1/quotes/batch` | Current prices for all holdings | 30s |
| GET | `/v1/instruments/{id}/context` | Sector per holding | 1h (cached) |
| GET | `/v1/watchlists` | Watchlists tab | 30s |
| POST | `/v1/watchlists` | Create watchlist | — |
| DELETE | `/v1/watchlists/{id}` | Delete watchlist | — |
| POST | `/v1/watchlists/{id}/members` | Add entity | — |
| DELETE | `/v1/watchlists/{id}/members/{entity_id}` | Remove entity | — |
| GET | `/v1/alert-preferences` | Settings tab | 5min |
| PUT | `/v1/alert-preferences/{alert_type}` | Update preference | — |
| GET | `/v1/brokerage-connections` | Brokerage panel | 30s |
| POST | `/v1/brokerage-connections` | Connect brokerage | — |
| DELETE | `/v1/brokerage-connections/{id}` | Disconnect | — |

### 16.6 Screener Page Endpoints

| Method | S9 Route | Usage |
|--------|----------|-------|
| GET | `/v1/fundamentals/screen/fields` | Dynamic filter builder (62+ metrics) |
| POST | `/v1/fundamentals/screen` | Run screener (body: `{filters[], sort_by, sort_order, limit, offset}`) |

### 16.7 News Page Endpoints

| Method | S9 Route | Usage | Tab |
|--------|----------|-------|-----|
| GET | `/v1/news/relevant?limit=20&offset=N` | News feed chronological | Feed tab |
| GET | `/v1/news/top?limit=20` | Top ranked by display_relevance_score | Top Today tab |
| GET | `/v1/signals?min_impact_score=0.5&limit=20` | Impact-scored signals | Feed tab signals panel |

### 16.8 Chat Page Endpoints

| Method | S9 Route | Usage |
|--------|----------|-------|
| GET | `/v1/threads?limit=20&offset=N` | Thread sidebar list |
| POST | `/v1/threads` | Create new thread |
| GET | `/v1/threads/{thread_id}` | Load thread messages |
| DELETE | `/v1/threads/{thread_id}` | Delete thread |
| POST | `/v1/chat/stream` | SSE streaming completion |
| POST | `/v1/chat` | Sync completion (fallback) |

### 16.9 Companies List Page Endpoints

| Method | S9 Route | Usage |
|--------|----------|-------|
| GET | `/v1/instruments?query=&limit=50&offset=N` | Search + pagination |
| GET | `/v1/instruments?has_ohlcv=true` | Filter by OHLCV availability |
| GET | `/v1/instruments?has_fundamentals=true` | Filter by fundamentals |
| GET | `/v1/instruments?exchange=NYSE&limit=50` | Filter by exchange |
| POST | `/v1/watchlists/{id}/members` | Watchlist toggle |

### 16.10 Global / Cross-Page Endpoints

| Method | S9 Route | Usage | Where Used |
|--------|----------|-------|------------|
| GET | `/v1/instruments?query={q}&limit=10` | Ticker search autocomplete | CommandPalette, AddTransactionSheet, ChartPanel |
| POST | `/v1/feedback` | User feedback | FeedbackWidget (all pages) |
| GET | `/v1/instruments/{id}` | Instrument detail | CompanyDetail page.tsx server component |
| WS | `/v1/alerts/stream` | Real-time alerts + FlashOverlay | Root layout (all protected pages) |
| GET | `/v1/entities?q={query}&limit=10` | Entity search | CommandPalette, entity context pills |

### 16.11 Key Data Shapes (Quick Reference)

**Quote** (S3 `GET /v1/quotes/{id}`):
```json
{ "instrument_id": "uuid", "symbol": "AAPL", "last": 173.42, "change": 1.23, "change_pct": 0.72,
  "volume": 52000000, "avg_volume": 61000000, "updated_at": "2026-04-13T14:32:00Z" }
```

**Highlights** (S3 `GET /v1/fundamentals/{id}/highlights`):
```json
{ "MarketCapitalization": 2700000000000, "PERatio": 28.4, "52WeekHigh": 199.62,
  "52WeekLow": 124.17, "AverageDailyVolumeRolling": 61000000, "EPS": 6.13 }
```

**InstrumentContext** (S9 composition):
```json
{ "instrument_id": "uuid7", "symbol": "AAPL", "exchange": "NASDAQ", "is_active": true,
  "flags": {"has_ohlcv": true, "has_quotes": true, "has_fundamentals": true},
  "security": {"name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics",
    "country": "USA", "currency": "USD"},
  "entity_id": "uuid7 | null" }
```

**Alert** (S10):
```json
{ "alert_id": "uuid", "severity": "HIGH", "title": "AAPL earnings beat", "body": "...",
  "entity_id": "uuid", "created_at": "...", "acknowledged": false }
```

**Article** (S5+S6):
```json
{ "id": "uuid", "title": "...", "source": "Reuters", "published_at": "...",
  "url": "...", "entity_mentions": ["uuid1"], "display_relevance_score": 0.83,
  "routing_tier": "SIGNAL" | "STANDARD" | "LIGHT" }
```

---

*PRD-0027 — Worldview Frontend MVP. Status: Draft (v2.1 — Visual Identity Revision). Date: 2026-04-13.*
*Next step: Resolve OQ-14 (design direction A/B/C) → `/design-ui` to create revised pencil.dev canvas.*
*Priority pages for canvas redesign: Landing Page, Dashboard, Company Detail, Workspace.*
