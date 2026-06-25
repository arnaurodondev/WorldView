# Landing Page Investigation — Feature Representation Gap Analysis

> Date: 2026-06-23 · READ-ONLY investigation · No code changed
> Scope: `apps/worldview-web` public landing route (`/`)
> Concern: landing page is stale relative to the product's current flagship capabilities (KG intelligence, grounded RAG chat with citations, portfolio analytics/risk, screener, news intelligence, weird-connections).

---

## 1. What the landing page shows today

Single server-rendered route `apps/worldview-web/app/page.tsx` (last edited 2026-05-11; sub-components 2026-06-06). Built under PLAN-0052 Wave A, benchmarked against Bloomberg / IBKR / TradingView / Finviz. 14 sections, all in `apps/worldview-web/components/landing/`:

| # | Section | File | What it conveys today |
|---|---------|------|------------------------|
| 1 | LandingNav | `LandingNav.tsx` | Sticky nav; anchors: Differentiators, Workflow, AI, Compare, Pricing, FAQ; CTAs Sign in / Get started |
| 2 | HeroSection | `HeroSection.tsx:81` | Headline "Bloomberg-grade research, without the Bloomberg bill." Subcopy: "Real-time market signals, AI-powered news intelligence, and an entity knowledge graph." Right column = ASCII watchlist/quote terminal mock |
| 3 | LiveDataStrip | `LiveDataStrip.tsx` | 6 mock tickers with live-pulse dot |
| 4 | SectorHeatmapPreview | `SectorHeatmapPreview.tsx` | 6 SPDR sector tiles, 7-step gradient |
| 5 | DifferentiatorsSection | `DifferentiatorsSection.tsx:19` | 3 cards: News intelligence / Knowledge graph / Multi-source fusion |
| 6 | WorkflowSection | `WorkflowSection.tsx:16` | 4 steps Discover→Analyze→Track→Act (Screener / Instrument / Alerts / Portfolio) |
| 7 | AIDemoSection | `AIDemoSection.tsx:18` | Static RAG-chat mock: NVDA question + cited answer + 3-source list; model label `llama-3.1-8b · grounded` |
| 8 | ComparisonTable | `ComparisonTable.tsx:32` | 9-row feature matrix vs Bloomberg/IBKR/TV/Finviz + price row |
| 9 | TrustBadges | `TrustBadges.tsx` | Data-source attributions |
| 10 | PricingTiers | `PricingTiers.tsx` | Free / Pro / Enterprise + monthly/annual toggle |
| 11 | Testimonials | `Testimonials.tsx:16` | 3 honest persona "scenarios" (swing trader / hedge analyst / quant) |
| 12 | FAQAccordion | `FAQAccordion.tsx` | 10 Q&A (mirrored in JSON-LD `page.tsx:96`) |
| 13 | FinalCTA | `FinalCTA.tsx` | Closing "open the terminal" CTA |
| 14 | Footer | `Footer.tsx` | 5-column nav + status badge |

The page is **structurally strong**: good section order, honest comparison/testimonials, accessible, SEO JSON-LD, design-system compliant (Midnight/Terminal-Dark, sharp 2px radius, IBM Plex Mono, amber primary). The problem is **what it says**, not how it's built.

---

## 2. Gap analysis — current product vs. what the landing page represents

The product has shipped substantial Q2 capabilities (PLAN-0107 chat/citations, PLAN-0112 weird-connections, relation precision gates, news impact windows, instrument 3-tab redesign, portfolio redesign PRD-0108, workspace). The landing page predates most of this. Concrete gaps:

### MUST-FIX (flagship capabilities under-/mis-represented)

1. **Knowledge graph sold as a static claim, never shown.** DifferentiatorsSection mentions "queryable graph" but there is **no visual** of the Sigma.js entity graph, and the page never mentions the genuinely novel **Weird Connections / path-discovery** feature (`/connections`, `/intelligence/[entity_id]` — weirdness scoring: reliability × unexpectedness × semantic-distance × novelty). This is arguably the most differentiated thing the product does and it is invisible on the landing page.

2. **Citation confidence is the chat differentiator and isn't shown.** AIDemoSection shows numbered citations (good) but omits the **citation confidence bar** (green ≥0.7 / amber 0.4–0.7 / red <0.4) and the **grounding-veto / "says so if it can't ground"** behaviour — the things that actually make the chat trustworthy. The FAQ describes it (`page.tsx:126`) but the visual demo doesn't.

3. **Chat slash-commands absent.** `/quote`, `/portfolio`, `/news`, `/path`, `/compare` are a concrete, demo-able power-user feature with zero landing presence.

4. **Portfolio analytics shown as a thin afterthought.** Workflow step 4 ("Act") reduces portfolio to "connect brokerage, track P&L." The real surface — equity curve, **realized P&L**, sector allocation (colour-blind-safe), cash-vs-invested exposure, day-P&L heatmaps, transaction history with filters/exports — is never showcased. No portfolio/analytics visual anywhere.

5. **Stale AI model label.** `AIDemoSection.tsx:91` advertises `llama-3.1-8b · grounded`. Per memory, live extraction/chat models have moved (gpt-oss-120b@medium; chat DeepSeek-class; judge DeepSeek V4 Flash). The visible model string is wrong and undersells the system.

6. **Hero subcopy is generic and trails the product.** "Real-time market signals, AI-powered news intelligence, and an entity knowledge graph" — omits the grounded/cited chat, the screener, portfolio analytics, and the weird-connections angle. "AI-powered" is exactly the commodity phrasing the differentiators section warns against.

### SHOULD-FIX (present but weak / stale)

7. **No real product screenshots.** Hero is an ASCII mock; AI demo is a hand-built card; there are no images of the actual dashboard, instrument 3-tab page, screener grid, KG graph, or portfolio. There ARE capture scripts in the repo (`capture-screenshots.mjs`, `capture-screenshots-v2.mjs`, `capture-thesis-screenshots.mjs`) — the assets exist or are easy to generate. For a "professional tool, not a toy" pitch, real screenshots beat ASCII.

8. **Screener undersold.** It appears only as Workflow step 1. The screener is a full surface (collapsible fundamental filters, saved screens, inline sparklines, CSV/Excel/PDF export, AG-Grid density) and deserves a feature tile, not one sentence.

9. **News intelligence: impact-window story incomplete.** Differentiator card mentions "t0/t1/t2/t5" but the page never shows the `ArticleImpactBadge` / Top-Today relevance ranking (0.5 market + 0.4 LLM + 0.1 routing) that's actually in product.

10. **Comparison table self-deprecates on a now-shipped feature.** "Configurable terminal workspace" is marked `partial` with a code comment saying to soften "until workspace v2 ships" (`ComparisonTable.tsx:79`) — the multi-panel workspace with templates, symbol-linking, and share-via-URL has since shipped; this row understates the product.

11. **Instrument 3-tab page (Quote / Financials / Intelligence) never named.** It's the analytical core (live quote badge, 52-wk range, expandable fundamentals, indicators, entity graph) and only appears as a passing line in Workflow step 2.

12. **No "how it works" architecture/credibility moment.** The thesis-grade differentiator — 10 microservices, event-driven, single S9 gateway, externalized LLMs, full citation chain — is buried in FAQ #1 instead of being a confidence-building section.

### NICE-TO-HAVE

13. Nav has no anchor to a graph/intelligence section (because none exists). Add once the KG section is added.
14. Comparison "as of 2026-05" footnote (`ComparisonTable.tsx:286`) needs a date bump after edits.
15. Prediction-markets is claimed as a differentiator row but is a minor surface; fine to keep but don't over-weight it relative to KG/chat/analytics.

---

## 3. Recommended landing-page structure

Keep the strong bones (nav, honest comparison, persona scenarios, pricing, FAQ, JSON-LD, design system). Re-sequence and **add three feature-showcase sections** so the flagship capabilities are *shown*, and refresh stale copy/labels. Ordered top→bottom:

1. **LandingNav** — add a "Intelligence" (or "Graph") anchor once §5 below exists. *(keep)*

2. **Hero (sharpen)** — keep headline "Bloomberg-grade research, without the Bloomberg bill." Rewrite subcopy to lead with the four pillars in product language:
   > "A finance terminal that fuses market data, impact-scored news, and a knowledge graph — with a grounded AI assistant that cites every claim."
   Replace (or supplement) the ASCII mock with a **real screenshot** of the instrument 3-tab page or dashboard. *(must-fix copy + visual)*

3. **LiveDataStrip + SectorHeatmapPreview** — keep as the "this is alive" band. *(keep)*

4. **Feature grid (NEW — replaces/expands Differentiators)** — 5–6 tiles, each with a one-line value prop + a real thumbnail:
   - **Knowledge-graph intelligence** — entity graph + path discovery; tease Weird Connections.
   - **Grounded AI chat** — cited answers + confidence bar + slash-commands.
   - **Portfolio analytics** — equity curve, realized P&L, sector/exposure, risk view.
   - **Fundamentals screener** — filters, saved screens, sparklines, exports.
   - **News intelligence** — impact windows (t0–t5), relevance ranking.
   - **Instrument detail** — Quote / Financials / Intelligence tabs.
   *(must-fix)*

5. **Knowledge-graph + Weird-Connections spotlight (NEW)** — the signature feature. A real Sigma.js graph screenshot + a "how are NVDA and TSMC related?" path example with the weirdness sub-scores. This is the strongest non-commodity differentiator and currently absent. *(must-fix)*

6. **AI demo (refresh)** — keep the cited-answer mock but **add the confidence bar**, show a **slash-command** (e.g. `/path NVDA TSM`), and **fix the model label** (remove `llama-3.1-8b`; use a neutral "grounded · cited" tag or the current model). *(must-fix)*

7. **Workflow (keep, retune)** — Discover→Analyze→Track→Act still works; update step copy so it points at the now-richer surfaces (Analyze → the 3-tab instrument page + graph; Act → the redesigned portfolio analytics, not just "connect brokerage"). *(should-fix)*

8. **How it works / under-the-hood (NEW, optional but high-value for a thesis product)** — 4 credibility points: 10 event-driven microservices · single S9 API gateway (55+ endpoints) · externalized LLMs / data sovereignty · full citation chain to source. Promotes FAQ #1 into a confidence section. *(nice-to-have, recommended)*

9. **ComparisonTable (keep, correct)** — bump "Configurable terminal workspace" to `yes`, refresh the "as of" date. *(should-fix)*

10. **TrustBadges → PricingTiers → Testimonials/Scenarios → FAQ → FinalCTA → Footer** — keep as-is; they're honest and well-built. Bump the FAQ model/data answers if any are stale. *(keep)*

### Design-system constraints to honour in any redesign
Terminal-Dark / Midnight Pro palette (#09090B bg, #FFD60A primary, teal/red semantic), shadcn/ui only, sharp 2px radius, IBM Plex Sans UI + IBM Plex Mono for all numbers (`tabular-nums`), finance-grade density. New showcase sections should use real screenshots captured with the existing `capture-*.mjs` scripts rather than new illustration styles, and stay server-rendered (isolate any interactivity as `"use client"` leaves, matching the current pattern).

---

## 4. Priority summary

- **Must-fix:** add KG/Weird-Connections spotlight; add a real feature grid covering chat-with-citations, portfolio analytics, screener, news, instrument tabs; sharpen hero subcopy; fix stale AI model label; add confidence bar + slash-command to the AI demo; replace ASCII hero mock with a real screenshot.
- **Should-fix:** correct the comparison-table "workspace" row; retune Workflow step copy; surface news impact windows visually; date-bump comparison footnote.
- **Nice-to-have:** "how it works" architecture section; nav anchor for the new graph section.

Suggested follow-up: `/design-ui` for the new feature-grid + KG spotlight + how-it-works sections, then `/implement-ui` to build them, reusing existing `capture-*.mjs` for screenshots.
