# Landing Page Redesign — Design Spec

> Date: 2026-06-23 · DESIGN ONLY (no implementation) · Untracked
> Scope: `apps/worldview-web` public route `/` (`app/page.tsx`)
> Grounded in: `docs/audits/2026-06-23-landing-page-investigation.md`, `docs/PRODUCT_CONTEXT.md`, `docs/ui/DESIGN_SYSTEM.md` (Terminal Dark), `docs/apps/worldview-web.md`
> Follow-up: implementable via `/implement-ui` (F-* wave). Reuses `capture-*.mjs` for screenshots.

---

## 0. Design thesis

The current page is structurally excellent (honest comparison, persona scenarios, pricing, FAQ, JSON-LD, a11y, Terminal-Dark compliant) but **tells rather than shows** the flagship capabilities. The redesign keeps every strong section and **inserts three "show, don't tell" showcases** plus a credibility section, sharpens the hero, refreshes stale copy/labels, and replaces hand-built mocks with **real product screenshots** captured from the running app.

Three flagship showcases (the differentiated, non-commodity core):

1. **Knowledge Graph + Weird Connections** — the signature feature (Apple → TSMC → ASML indirect path with weirdness sub-scores). Currently invisible. *Highest leverage.*
2. **Grounded chat with citation-confidence** — cited answers + green/amber/red confidence bar + grounding-veto + slash-commands (`/path`, `/quote`, `/compare`).
3. **Portfolio analytics** — equity curve, realized P&L, sector allocation (colour-blind-safe), cash-vs-invested exposure.

Plus a **"How it works"** architecture-credibility section tied to the CIKM framing (hybrid retrieval: AGE + pgvector + BM25 → RRF → grounded synthesis).

### Design-system guardrails (non-negotiable)
- Palette: `#09090B` bg, `#111113` card, `#18181B` muted, `#27272A` border; primary `#FFD60A` (black text on it); positive `#26A69A`, negative `#EF5350`, warning `#F59E0B`. Use semantic tokens (`bg-card`, `text-primary`, …) — **no raw hex** outside JSON-LD.
- Radius `rounded-[2px]` everywhere. IBM Plex Sans UI; **IBM Plex Mono + `tabular-nums` for every number/ticker/percent**.
- `muted-foreground` must stay at the AA-safe 55% lightness (never restore 46%). No `animate-pulse` on status dots; skeletons static.
- Server-rendered page; isolate interactivity (`"use client"`) to leaf components only — current pattern.
- shadcn/ui only (+ AG Grid/sigma where already whitelisted). New visuals are **screenshots in a `next/image` frame**, not new illustration styles.

---

## 1. Section-by-section structure (ordered top → bottom)

Legend: **KEEP** = ship as-is · **REFRESH** = copy/visual edit, same component · **NEW** = new component.

### S1 · LandingNav — REFRESH (SHOULD)
- **Purpose:** sticky nav + auth CTAs.
- **Change:** add an `Intelligence` anchor (`#intelligence`, points to S5 KG spotlight) between `Differentiators`→`Workflow`. Anchor order: Features · Intelligence · Chat · Workflow · Compare · Pricing · FAQ.
- **Layout:** unchanged (logo left, anchors center, `Sign in` ghost + `Get started` primary right).

### S2 · Hero — REFRESH (MUST: copy + visual)
- **Purpose:** name product, state specific value, 2 CTAs, prove it's real.
- **Layout:** keep 2-col `lg:grid-cols-[minmax(0,1fr),minmax(0,1.1fr)]`. Left = copy/CTAs. Right = **real product screenshot** (instrument Intelligence tab or dashboard) inside the existing window-chrome card frame, replacing the ASCII `<pre>`. Keep the amber radial glows + window dots + LIVE pill + bottom status row.
- **Headline (keep):** `Bloomberg-grade research,` / `without the Bloomberg bill.`
- **Subcopy (rewrite — replaces the generic "AI-powered" line):**
  > A finance terminal that fuses market data, impact-scored news, and an entity knowledge graph — with a grounded AI assistant that cites every claim and a graph that surfaces the connections you'd never think to search for.
- **Eyebrow (keep):** `Market Intelligence Terminal` with live dot.
- **CTAs (keep):** `Open the terminal free` → `/register`; `Sign in` → `/login`. Sub-CTA: `No credit card · 5-minute setup · Connect EODHD or use sample data`.
- **Visual:** `hero-intelligence.png` (1.1 ratio, ~640×440 crop of the `/intelligence/[id]` graph + relations panel). Keep the bottom mono status row (`Markets open · S&P · VIX · time`) as a real chrome touch.

### S3 · LiveDataStrip — KEEP (NICE)
- "This is alive" band: 6 tickers + live dot. No change (mock data acceptable here; it's atmospheric).

### S4 · SectorHeatmapPreview — KEEP (NICE)
- 6 SPDR sector tiles, 7-step gradient. No change.

### S5 · Feature grid — NEW, replaces DifferentiatorsSection (MUST)
- **Purpose:** at-a-glance map of the 6 real surfaces — each tile is a one-line value prop + thumbnail + proof point. Replaces the 3-card differentiators (which over-indexed on prediction markets and never showed anything).
- **Layout:** `grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3` (6 tiles, 2 rows of 3). Each tile: lucide icon, title, one-line body, a 16:10 screenshot thumbnail (`rounded-[2px]`, `border-border/40`), and a mono proof-point footer. Hover: `hover:border-primary/30`.
- **Section heading:** eyebrow `Everything in one terminal` / H2 `Six surfaces. One coherent intelligence layer.`
- **Tiles (icon · title · body · proof · thumbnail):**
  1. `Network` — **Knowledge-graph intelligence** — "Entities, suppliers, executives and regulators as a queryable graph — plus path discovery between any two names." — `AGE graph · ~80K canonical entities · weirdness-ranked paths` — `feat-graph.png`
  2. `MessageSquare` — **Grounded AI chat** — "Cited answers with a per-source confidence bar; if it can't ground a claim, it says so." — `Hybrid RAG · citation confidence · slash-commands` — `feat-chat.png`
  3. `LineChart` — **Portfolio analytics** — "Equity curve, realized P&L, sector allocation and cash-vs-invested exposure against the same intelligence layer." — `Equity curve · realized P&L · colour-blind-safe` — `feat-portfolio.png`
  4. `SlidersHorizontal` — **Fundamentals screener** — "Faceted filters, saved screens, inline sparklines, CSV/Excel/PDF export." — `8K+ instruments · saved screens · 1-click export` — `feat-screener.png`
  5. `Newspaper` — **News intelligence** — "Impact-scored headlines across four price windows, ranked by a market + LLM + routing relevance blend." — `Impact windows t0/t1/t2/t5 · Top-Today ranking` — `feat-news.png`
  6. `LayoutGrid` — **Instrument detail** — "Quote, Financials and Intelligence in one 3-tab page — live quote, 52-wk range, fundamentals, indicators, entity graph." — `Quote · Financials · Intelligence` — `feat-instrument.png`
- **Note:** the first two tiles deep-link (anchor) down to S5b and S6 respectively, so the grid is also a table of contents for the showcases.

### S5b · Knowledge-Graph + Weird-Connections spotlight — NEW (MUST — flagship)
- **Purpose:** show the single most differentiated capability — indirect path discovery with weirdness scoring. This is the CIKM-novel angle and is currently *entirely absent* from the page.
- **Layout:** full-bleed band on `bg-card/30`. Two-column at `lg`: **left = real sigma.js graph screenshot** (`graph-spotlight.png`, the `/intelligence/[id]` or `/connections` view) in a window-chrome frame; **right = the path narrative card** built from static data.
- **Section heading:** eyebrow `Signature feature` / H2 `See connections you'd never think to search.` / sub: "Ask how two companies relate and the graph returns the actual chain — scored by how surprising it is."
- **Path narrative card (the Apple→TSMC→ASML story), `WeirdPathCard` (NEW, static):**
  - Query row (mono): `/path AAPL ASML` rendered as a slash-command chip.
  - Path chain (horizontal, mono tickers in `bg-primary/20` badges, arrows between):
    `AAPL ──supplied_by──▸ TSMC ──equipment_from──▸ ASML`
    with the 3 hops labelled (relation type under each arrow in `text-[10px] text-muted-foreground`).
  - **Weirdness sub-score breakdown** (4 mini-bars, reuse the §6.14 confidence-bar visual language but labelled): `Reliability 0.91` / `Unexpectedness 0.74` / `Semantic distance 0.68` / `Novelty 0.55` → composite `Weirdness 0.72` highlighted in primary. Each bar: green ≥0.7 / amber 0.4–0.7 / red <0.4, with redundant numeric label (colour-blind-safe, §6.11b).
  - One-line takeaway: "Apple's exposure to ASML's EUV lithography monopoly is two hops deep — invisible to a ticker-by-ticker scan."
- **Proof footer (mono):** `pgvector + AGE + BM25 hybrid retrieval · VLE path search 60–800ms · weirdness = reliability × unexpectedness × semantic-distance × novelty`.
- **Priority:** MUST. If only one new section ships, ship this one.

### S6 · Grounded-chat / citation-confidence showcase — REFRESH of AIDemoSection (MUST)
- **Purpose:** prove the chat is trustworthy (cited, confidence-scored, refuses to fabricate) and powerful (slash-commands). Keep the worked-example mock but add the missing trust + power signals.
- **Layout:** keep the centered chat-mock card (`max-w-3xl`). Three additions:
  1. **Fix the stale model label** — replace `llama-3.1-8b · grounded` with a neutral tag: `grounded · cited · hybrid-RAG` (avoid pinning a model string that goes stale; the audit confirms the live model has moved). If a model name is wanted, use the current chat model, not Llama 3.1 8B.
  2. **Add the citation confidence bar** below the answer — the §6.14 pattern: one segment per citation, green ≥0.7 / amber 0.4–0.7 / red <0.4, with `title=` tooltip + `sr-only` label per segment. Reuse the real `CitationBar` visual language (static data here).
  3. **Add a slash-command line** above the question, e.g. a chip row: `/quote` `/path` `/compare` `/news` `/portfolio`, and make the demo question use one: `/path NVDA TSM` → the cited answer.
- **Heading (keep):** eyebrow `AI grounded in your data` / H2 `Ask questions, get cited answers.` / sub: keep "Every claim links back to the article, filing, or paragraph it came from. If it can't ground a claim, it says so." (the grounding-veto line — already promised in FAQ #4, now make the demo say it too).
- **Disclaimer (keep):** "Sample answer based on representative data…".

### S7 · Workflow — REFRESH (SHOULD)
- **Purpose:** end-to-end narrative Discover → Analyze → Track → Act. Keep the vertical-stepper layout.
- **Copy retune (point at the now-richer surfaces):**
  - **Analyze** → mention the **3-tab instrument page** + the entity graph explicitly (currently vague). Surface label `Instrument · /instruments/{id}`.
  - **Act** → lead with **portfolio analytics** (equity curve, realized P&L, exposure), brokerage sync as the optional add-on, not the headline. Surface label `Portfolio · /portfolio`.
  - Discover / Track unchanged.

### S8 · How it works / under-the-hood — NEW (SHOULD — high value for a thesis product)
- **Purpose:** convert FAQ #1 into a confidence-building architecture moment; ties directly to the thesis/CIKM framing.
- **Layout:** `bg-background`, centered heading + a 4-tile row (`grid md:grid-cols-4`) of credibility points, optionally with a thin horizontal **retrieval-pipeline diagram** strip above them (mono boxes + arrows, no new lib — pure flex + Separator).
- **Heading:** eyebrow `Under the hood` / H2 `Built like infrastructure, not a demo.`
- **Pipeline strip (mono, static):** `Query ▸ [BM25 keyword] + [pgvector semantic] + [AGE graph] ▸ Reciprocal-Rank Fusion ▸ Grounded synthesis ▸ Cited answer`.
- **4 tiles:**
  1. `Boxes` — **10 event-driven microservices** — "Kafka outbox, idempotent consumers, at-least-once delivery — no dual-write bugs."
  2. `Server` — **Single S9 API gateway** — "55+ documented endpoints; the frontend never touches a backend service directly."
  3. `Lock` — **Externalized LLMs, your data stays yours** — "We send the prompt and store the response, nothing else. Brokerage sync is read-only."
  4. `Quote`/`Link2` — **Full citation chain** — "Every claim traces to a source document and offset — auditable end to end."

### S9 · ComparisonTable — REFRESH (SHOULD)
- **Purpose:** honest feature matrix vs Bloomberg / IBKR / TV / Finviz. Keep.
- **Changes:** (a) bump **"Configurable terminal workspace"** from `partial` → `yes` (workspace v2 with templates / symbol-linking / share-via-URL shipped — remove the "until workspace v2 ships" code comment); (b) add a **"Knowledge graph / path discovery"** row (Worldview `yes`, all others `no` — this is the strongest column to win); (c) bump the "as of 2026-05" footnote to 2026-06.

### S10 · TrustBadges — KEEP
- Data-source attributions. No change (EODHD / Finnhub / SEC EDGAR / Polymarket / TastyTrade).

### S11 · PricingTiers — KEEP
- Free / Pro / Enterprise + monthly/annual toggle. No change.

### S12 · Testimonials (persona scenarios) — KEEP
- 3 honest persona scenarios (swing trader / hedge analyst / quant). No change.

### S13 · FAQAccordion — REFRESH (SHOULD)
- Keep 10 Q&A + JSON-LD mirror. **Only edit if stale:** the model-accuracy answer (#4) is fine (no model name); no Llama string to fix here. Consider adding one Q on Weird Connections ("How does the graph find indirect relationships?") and mirror it into `FAQ_JSONLD`. If added, update `page.tsx` FAQ_JSONLD to keep visible/structured parity (Google penalises mismatch).

### S14 · FinalCTA — KEEP
- Closing "open the terminal" CTA.

### S15 · Footer — KEEP
- 5-col nav + status badge.

---

## 2. Component breakdown

### Keep as-is (8)
`LandingNav`*, `LiveDataStrip`, `SectorHeatmapPreview`, `TrustBadges`, `PricingTiers`, `Testimonials`, `FinalCTA`, `Footer`. (*LandingNav gets a 1-line anchor edit.)

### Refresh (existing components, copy/visual edits)
| Component | Edit | Type |
|-----------|------|------|
| `HeroSection.tsx` | swap ASCII `<pre>` → `next/image` screenshot in the existing card frame; rewrite subcopy | MUST |
| `AIDemoSection.tsx` | fix model label; add `CitationBar`; add slash-command chips; question → `/path NVDA TSM` | MUST |
| `WorkflowSection.tsx` | retune Analyze + Act copy/surface labels | SHOULD |
| `ComparisonTable.tsx` | workspace row → `yes`; add KG/path-discovery row; footnote date | SHOULD |
| `FAQAccordion.tsx` (+ `page.tsx` JSON-LD) | optional KG Q&A, keep parity | SHOULD |
| `page.tsx` | re-order imports/render; insert new sections; refresh `ORG_JSONLD.description` to drop "AI-powered", mention graph + cited chat | MUST |

### New components (props + data source)
| Component | File (proposed) | Props | Data source |
|-----------|-----------------|-------|-------------|
| `FeatureGrid` | `components/landing/FeatureGrid.tsx` | none (static `FEATURES` array of `{icon, title, body, proof, img, href}`) | **Static** + bundled screenshots |
| `KnowledgeGraphSpotlight` | `components/landing/KnowledgeGraphSpotlight.tsx` | none | **Static** (screenshot + hardcoded path/scores) |
| `WeirdPathCard` | `components/landing/WeirdPathCard.tsx` | `{ query, hops: {from,to,relation}[], scores: {label,value}[], composite, takeaway }` (static instance for AAPL→TSMC→ASML) | **Static** |
| `WeirdnessScoreBars` | `components/landing/WeirdnessScoreBars.tsx` | `{ scores: {label:string, value:number}[], composite:number }` | **Static** (reuses §6.14 band logic + §6.11b colour-blind pattern) |
| `HowItWorks` | `components/landing/HowItWorks.tsx` | none (static `PILLARS` + pipeline steps) | **Static** |
| `ProductShot` | `components/landing/ProductShot.tsx` | `{ src, alt, label, ratio?, live?: boolean }` | **Static** — reusable window-chrome `next/image` frame (window dots + mono label + optional LIVE pill); used by Hero, FeatureGrid tiles, KG spotlight |

**All new components are static / server-rendered.** No live S9 reads on the public landing route — keep TTFB fast and avoid auth/data coupling on the marketing page (consistent with the current zero-JS approach). The "live" feel comes from real screenshots + the existing `LiveDataStrip` atmospheric mock. (A future live `/v1/connections/weird` teaser is possible but explicitly **out of scope** — adds a network dependency and an empty-state risk to the hero funnel.)

### shadcn primitive reuse
`Card`/`CardContent` (tiles, narrative card), `Badge` (tickers, relation chips, slash-commands), `Separator` (pipeline arrows / dividers), `Tooltip` (confidence-bar segments — or native `title=` per §6.14), `Button` as `Link` (CTAs). `next/image` for all screenshots. No new shadcn installs required.

---

## 3. Copy (final, owner-editable)

**Hero**
- H1: `Bloomberg-grade research, without the Bloomberg bill.`
- Sub: `A finance terminal that fuses market data, impact-scored news, and an entity knowledge graph — with a grounded AI assistant that cites every claim and a graph that surfaces the connections you'd never think to search for.`

**Feature grid** — eyebrow `Everything in one terminal` · H2 `Six surfaces. One coherent intelligence layer.` (tile copy in S5 above).

**KG spotlight** — eyebrow `Signature feature` · H2 `See connections you'd never think to search.` · sub `Ask how two companies relate and the graph returns the actual chain — scored by how surprising it is.` · takeaway `Apple's exposure to ASML's EUV-lithography monopoly is two hops deep — invisible to a ticker-by-ticker scan.`

**Chat showcase** — eyebrow `AI grounded in your data` · H2 `Ask questions, get cited answers.` · sub `Every claim links back to the article, filing, or paragraph it came from. If it can't ground a claim, it says so.` · model tag `grounded · cited · hybrid-RAG` (replaces `llama-3.1-8b · grounded`).

**How it works** — eyebrow `Under the hood` · H2 `Built like infrastructure, not a demo.` (pillar copy in S8).

**`ORG_JSONLD.description` (refresh):** `Market intelligence terminal that fuses real-time market data, impact-scored news, and an entity knowledge graph with a grounded, citation-backed AI assistant. Knowledge-graph path discovery, portfolio analytics, and a fundamentals screener in one workspace.`

---

## 4. Screenshots / visuals plan

Capture from the running platform (`localhost:3001` after `make dev` + `make seed`) using the existing Playwright pattern in `capture-screenshots.mjs` (dev-login → client-side nav → snap; never `page.goto()` post-login). Add a **landing-specific script** `capture-landing-shots.mjs` that crops to marketing ratios and writes to `apps/worldview-web/public/landing/`.

| Asset | Source surface | Route / state | Crop | Used in |
|-------|----------------|---------------|------|---------|
| `hero-intelligence.png` | Instrument **Intelligence** tab (graph + relations) | `/instruments/{id}` → INTELLIGENCE, node selected | ~640×440 | Hero (S2) |
| `graph-spotlight.png` | Sigma.js graph (denser) | `/intelligence/{id}` or `/connections` | ~720×520 | KG spotlight (S5b) left col |
| `feat-graph.png` | same as graph-spotlight, tighter | `/intelligence/{id}` | 16:10 | FeatureGrid tile 1 |
| `feat-chat.png` | Chat with a cited answer + confidence bar visible | `/chat` (ask `/path NVDA TSM`) | 16:10 | FeatureGrid tile 2 |
| `feat-portfolio.png` | Portfolio overview (equity curve + allocation) | `/portfolio` | 16:10 | FeatureGrid tile 3 |
| `feat-screener.png` | Screener grid with filters + sparklines | `/screener` | 16:10 | FeatureGrid tile 4 |
| `feat-news.png` | News Top-Today with impact badges | `/news` (Top Today tab) | 16:10 | FeatureGrid tile 5 |
| `feat-instrument.png` | Instrument Quote tab (chart + fundamentals) | `/instruments/{id}` → QUOTE | 16:10 | FeatureGrid tile 6 |

Static (no screenshot): `WeirdPathCard`, `WeirdnessScoreBars`, `HowItWorks` pipeline, chat-demo `CitationBar` (hand-built mock — exact data is owner-controlled). Image policy: PNG, `deviceScaleFactor: 2` for retina, `next/image` with explicit width/height to prevent CLS, `alt` describing the surface, lazy-load all below-fold (Hero shot eager).

---

## 5. Full-page ASCII wireframe (top → bottom)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [WV] Worldview   Features · Intelligence · Chat · Workflow · Compare ·    │  S1 LandingNav (sticky)
│                  Pricing · FAQ            [ Sign in ]  [ Get started ▸ ]   │
├──────────────────────────────────────────────────────────────────────────┤
│  ● MARKET INTELLIGENCE TERMINAL                  ┌─────────────────────┐  │  S2 Hero (REFRESH)
│  Bloomberg-grade research,                       │ ● ● ●  intelligence ●│  │  left: copy+CTAs
│  without the Bloomberg bill.                     │  [ real screenshot:  │  │  right: ProductShot
│  A finance terminal that fuses market data,      │   sigma graph +      │  │  (hero-intelligence.png)
│  impact-scored news, and a knowledge graph…      │   relations panel ]  │  │
│  [ Open the terminal free ▸ ]  [ Sign in ]       │ ● Markets open · S&P │  │
│  No credit card · 5-min setup · sample data      └─────────────────────┘  │
├──────────────────────────────────────────────────────────────────────────┤
│  AAPL +1.2  MSFT -0.5  NVDA +3.4  TSLA -2.1  AMZN +0.8  META +1.1   ● LIVE │  S3 LiveDataStrip (KEEP)
├──────────────────────────────────────────────────────────────────────────┤
│  [XLK +1.3][XLF -0.4][XLE +2.1][XLV -0.2][XLY +0.6][XLI -1.0]   sectors    │  S4 SectorHeatmap (KEEP)
├──────────────────────────────────────────────────────────────────────────┤
│            EVERYTHING IN ONE TERMINAL                                      │  S5 FeatureGrid (NEW)
│         Six surfaces. One coherent intelligence layer.                     │  replaces Differentiators
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                          │  6 tiles, 2×3
│  │⬡ KG intel   │ │▣ Grounded   │ │📈 Portfolio │   each: icon/title/      │
│  │ [thumb]     │ │  chat[thumb]│ │  [thumb]    │   1-line/[thumb]/proof   │
│  └─────────────┘ └─────────────┘ └─────────────┘                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                          │
│  │⚙ Screener   │ │🗞 News intel │ │▦ Instrument │                          │
│  │ [thumb]     │ │  [thumb]    │ │  [thumb]    │                          │
│  └─────────────┘ └─────────────┘ └─────────────┘                          │
├──────────────────────────────────────────────────────────────────────────┤
│   SIGNATURE FEATURE                                  (id=intelligence)     │  S5b KG + Weird-Conn
│   See connections you'd never think to search.                             │  spotlight (NEW, MUST)
│  ┌────────────────────────┐   ┌──────────────────────────────────────┐   │
│  │ ● ● ●  connections     │   │  /path AAPL ASML                      │   │  left: graph-spotlight.png
│  │  [ real sigma.js       │   │  AAPL ─supplied_by▸ TSMC ─equip▸ ASML │   │  right: WeirdPathCard
│  │    graph screenshot ]  │   │  Reliability      ▓▓▓▓▓▓▓▓▓░ 0.91     │   │   + WeirdnessScoreBars
│  │                        │   │  Unexpectedness   ▓▓▓▓▓▓▓░░░ 0.74     │   │
│  │                        │   │  Semantic dist.   ▓▓▓▓▓▓░░░░ 0.68     │   │
│  │                        │   │  Novelty          ▓▓▓▓▓░░░░░ 0.55     │   │
│  │                        │   │  ▶ WEIRDNESS      ▓▓▓▓▓▓▓░░░ 0.72     │   │
│  └────────────────────────┘   │  "Apple's ASML exposure is 2 hops…"   │   │
│   pgvector + AGE + BM25 · VLE path 60–800ms · weirdness = r×u×s×n       │   │
├──────────────────────────────────────────────────────────────────────────┤
│            AI GROUNDED IN YOUR DATA                  (id=chat / #ai)        │  S6 Chat showcase
│         Ask questions, get cited answers.                                  │  (REFRESH AIDemoSection)
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │ ▣ AI Chat · Workspace            grounded · cited · hybrid-RAG     │    │  ← model label FIXED
│  │ [/quote] [/path] [/compare] [/news] [/portfolio]                  │    │  ← slash chips NEW
│  │ You:  /path NVDA TSM                                               │    │
│  │ AI:   NVDA −4.18% on May 14 … TSMC CoWoS constraint [1][2] …       │    │
│  │       Sources: [1] Bloomberg  [2] Worldview NLP  [3] SEC EDGAR     │    │
│  │       Confidence ▕███ green ███▏▕██ amber ██▏▕ red ▏               │    │  ← CitationBar NEW
│  └──────────────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────────────┤
│  HOW TRADERS USE WORLDVIEW    Discover → Analyze → Track → Act             │  S7 Workflow (REFRESH copy)
│  ① Discover  Screener…                                                     │
│  ② Analyze   3-tab instrument page + entity graph…                         │  ← retuned
│  ③ Track     Watchlists & alerts…                                          │
│  ④ Act       Portfolio analytics — equity curve, realized P&L, exposure…  │  ← retuned
├──────────────────────────────────────────────────────────────────────────┤
│  UNDER THE HOOD     Built like infrastructure, not a demo.                 │  S8 HowItWorks (NEW)
│  Query ▸ [BM25]+[pgvector]+[AGE] ▸ RRF ▸ grounded synthesis ▸ cited        │  pipeline strip
│  [▣ 10 microservices] [▣ S9 gateway] [▣ externalized LLMs] [▣ citations]   │  4 pillar tiles
├──────────────────────────────────────────────────────────────────────────┤
│  Feature              Worldview  Bloomberg  IBKR  TV  Finviz               │  S9 ComparisonTable
│  Knowledge graph / paths  ✓        ✗        ✗    ✗   ✗     ← NEW row        │  (REFRESH)
│  Configurable workspace   ✓ …                              ← partial→yes   │
│  … price row …                                       (as of 2026-06)       │
├──────────────────────────────────────────────────────────────────────────┤
│  Powered by  EODHD · Finnhub · SEC EDGAR · Polymarket · TastyTrade         │  S10 TrustBadges (KEEP)
├──────────────────────────────────────────────────────────────────────────┤
│  [ Free ]        [ Pro ★ ]        [ Enterprise ]      ◐ monthly/annual      │  S11 PricingTiers (KEEP)
├──────────────────────────────────────────────────────────────────────────┤
│  Persona scenarios: swing trader · hedge analyst · quant                   │  S12 Testimonials (KEEP)
├──────────────────────────────────────────────────────────────────────────┤
│  FAQ (10, +1 KG question)  ▸ expand                                        │  S13 FAQ (REFRESH)
├──────────────────────────────────────────────────────────────────────────┤
│  Open the terminal free ▸                                                  │  S14 FinalCTA (KEEP)
├──────────────────────────────────────────────────────────────────────────┤
│  Footer: 5-col nav · ● status                                              │  S15 Footer (KEEP)
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Implementation notes for the follow-up `/implement-ui` wave

- New render order in `page.tsx`: `LandingNav, HeroSection, LiveDataStrip, SectorHeatmapPreview, FeatureGrid, KnowledgeGraphSpotlight, AIDemoSection, WorkflowSection, HowItWorks, ComparisonTable, TrustBadges, PricingTiers, Testimonials, FAQAccordion, FinalCTA, Footer`.
- `DifferentiatorsSection.tsx` is superseded by `FeatureGrid` — delete its import + render (keep the file until the new grid passes review, then remove; do not leave dead imports).
- Tests (Vitest, per repo rule): each new component needs at minimum a render/happy-path test; `WeirdnessScoreBars` needs a `scoreBand()` unit test mirroring §6.14 thresholds (≥0.7 high, 0.4–0.7 medium, <0.4 low); a `page.test.tsx` assertion that the three flagship section headings + the KG/path comparison row render; assert the stale `llama-3.1-8b` string is **gone**.
- A11y: confidence/weirdness bars get `role="img"` + `aria-label` + redundant numeric labels (§6.11b); screenshots get descriptive `alt`; new nav anchor target has a matching `id`.
- Keep everything server-rendered; only `PricingTiers` and `FAQAccordion` remain `"use client"`. New sections are static → server components.
- Token compliance: no raw hex (lint ban) outside JSON-LD; `rounded-[2px]`; mono+`tabular-nums` for every number, ticker, and score.

---

## 7. pencil.dev canvas

Not produced this session — the pencil MCP server is not connected to a running editor (`get_editor_state` → "failed to connect to running Pencil app"). The ASCII wireframe (§5) + the component/props breakdown (§2) are sufficient to drive `/scaffold-frontend` or `/implement-ui`. If a pencil canvas is wanted later, open the editor and re-run with the C()-for-all-frame-children convention (project memory).
