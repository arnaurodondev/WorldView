# PRD-0089 Screener — Bloomberg Competitive Vision

> **Report type**: cross-cutting competitive-strategy lens (read-only).
> **Scope**: the PRD-0089 equity screener as a Bloomberg-EQS-class product with
> an intelligence layer. The other PRD-0089 audit agents verify per-item state;
> this report owns the holistic "how do we excel and compete against Bloomberg"
> question.
> **Author**: competitive-strategy investigation agent, 2026-06-16.
> **Worktree**: `worldview-wt-md-reliability` @ HEAD `2e447e8be`.

---

## TL;DR — the one-paragraph thesis

We will **never** out-breadth Bloomberg, and we should stop pretending that is
the game. Bloomberg has ~30 years of point-in-time global data, a formula
builder, BQL, and 5,000+ fields. Capital IQ and FactSet have similar depth.
Koyfin already gives retail "Bloomberg-level" data at 5,900+ criteria for
$50/month. On the **classic fundamentals/returns/analyst/ownership screening
axis we are a fast-follower, not a leader, and that is fine** — those are
table stakes. The single axis where Worldview can win, and where Bloomberg EQS
is *structurally* absent, is the **intelligence-native screen**: filtering and
ranking the equity universe by what the *news/LLM pipeline knows* — narrative
volume, LLM relevance, contradiction signals, active alerts, and AI-brief
existence — and then **explaining in natural language why each name surfaced**.
That is the killer demo Bloomberg cannot run today, and it maps almost exactly
onto the work that is currently **deferred** (§1 L-5b → IB-L5). The strategic
recommendation is to treat the deferred intelligence layer (L-5b + IB-L5) and
natural-language screen building (already half-built via `nl-translate`) as the
**P0 differentiators**, and treat the remaining classic columns (IB-L3/L4) as
P1 table-stakes that make the product credible but do not win deals.

---

## §1. What we have today (and what is planned)

### §1.1 Classic screening capabilities — shipped

The screener backend (S3 / market-data, `query_screen` +
`POST /v1/fundamentals/screen`, surfaced through S9) exposes **38–39 static
screen fields** registered in
`services/market-data/src/market_data/app.py::_get_static_screen_fields()` and
in `screen_field_metadata`. By category:

| Category | Fields | Status |
|---|---|---|
| **Valuation** | P/E, EV/EBITDA, Price/Book | shipped |
| **Profitability** | gross / net / operating margin, ROE | shipped |
| **Capital structure / liquidity** | debt/equity, current ratio | shipped |
| **Size / income** | market cap, revenue, dividend yield | shipped |
| **Attributes (L-1)** | country (ISO3), exchange, has_fundamentals, has_ohlcv | shipped |
| **Fundamentals snapshot (L-2)** | EPS TTM, avg vol 30d, FCF, FCF margin, interest coverage, net-debt/EBITDA, credit rating | shipped backend; IB-L2 frontend shipped |
| **Analyst / ownership (L-4a)** | analyst target price, consensus rating, institutional ownership %, short % | shipped backend; **IB-L4 frontend deferred** |
| **Returns / technical (L-3)** | 1M/3M/6M/YTD/1Y/3Y return, dist-from-52w-high, dist-from-52w-low | shipped backend (nightly worker 02:00 UTC); **IB-L3 frontend deferred** |
| **Insider (L-4b)** | insider_net_buy_90d | shipped backend (nightly 03:00 UTC); **universe = 3 tickers until budget approval** |
| **Calendar (L-5c)** | next_earnings_date, next_dividend_date | shipped backend |

Front-end: dense Bloomberg-grade chrome shipped in Wave I-A —
`ScreenerHeader → PresetBar → (NL input) → FilterChipStrip → 20px AG-Grid →
LoadMoreBar`, 240 cells above the fold at 1440×900, 14-default-column cap,
sparkline TREND column, 7 system presets (`All / Large Cap / Dividend / Value /
Growth / Profitable / US Equities Only`), localStorage saved screens,
column-settings popover, export menu, page-scoped hotkeys. Components live in
`apps/worldview-web/components/screener/`.

### §1.2 The differentiator — the intelligence layer

This is the part Bloomberg EQS does not have. The pipeline already produces, per
instrument, rollups exposed by **four internal REST endpoints (L-5a, shipped)**:

- S6 nlp-pipeline `…/news-rollup-7d` → `news_count_7d`, `llm_relevance_7d_max`,
  `display_relevance_7d_weighted` (the OQ-8 weighted blend of market + LLM +
  routing relevance).
- S7 knowledge-graph `…/intelligence-rollup-7d` → `recent_contradiction_count`
  (the contradiction-detection signal — names where the KG holds conflicting
  claims).
- S10 alert `…/active-alert-flag` → `has_active_alert`.
- S8 rag-chat `…/ai-brief-flag` → `has_ai_brief`.

The frontend `IntelligenceFilterGroup.tsx` already scaffolds **7 intelligence
filter rows** (news count 7d, AI brief, active alert, contradictions, LLM
relevance, upcoming earnings, upcoming dividend) — rendered today with a
`BackendPendingBadge` because the **S3-side sync worker (L-5b) that
materializes those 6 rollup fields into `instrument_fundamentals_snapshot` is
deferred** (DEFERRED-WORK-PLAN §1). The UI scaffold is done; the data plumbing
is the missing piece.

### §1.3 Natural-language screen building — half-built

`POST /v1/screener/nl-translate` (PLAN-0091, schema in
`services/api-gateway/src/api_gateway/schemas/screener.py`, route in
`routes/market.py`) already translates a natural-language phrase into a
`ScreenFilter` set + explanation, constrained by the `screen_field_metadata`
allowlist. This is a *strategic asset that is currently underexploited* — the
NL input component is not consistently mounted on the page, but the backend
capability is live and tested.

---

## §2. The competition (web-researched, cited)

### §2.1 Bloomberg Terminal — EQS

- **EQS** ("Equity Screening") is launched by typing `EQS`. Users add criteria
  from a screening-criteria panel or an "Add criteria" field, with an
  "Advanced search" for refinement. A **Formula** builder ("top left of the
  screen") allows powerful custom screening criteria. ([Bocconi LibGuide][1],
  [Bloomberg equities essentials][2])
- **BQL (Bloomberg Query Language)** lets users screen *custom universes* with
  expressions like `filter(members('SPX Index'), cur_mkt_cap > 10B)`, and query
  **custom data fields** (CDE) as if they were native fields. This is a
  programmable, composable screening layer far beyond a fixed field list.
  ([BQL gitbook][3], [BQL notes][4])
- EQS supports **save/recall of screens** and is embedded in the broader
  terminal (link out to DES, FA, GP, news, etc.). ([Bloomberg ref][5])
- **AI / news**: Bloomberg shipped **AI-Powered News Summaries** (Jan 2025, 3
  bullets atop news), is rolling out an **AI document-search/analysis tool**
  (earnings transcripts, research) by end-2025, and runs **BloombergGPT**
  (50B-param finance LLM) for sentiment, NER, classification, QA. A market-
  sentiment ML model has existed since 2009. ([itBrew terminal AI][6],
  [Bloomberg gen-AI summaries][7], [BloombergGPT][8])
- **Cost**: ~**$31,980/user/year** for a single terminal in 2025 (multi-terminal
  ~$28,320/yr each). ([NeuGroup][9], [costbench][10])

**Critical observation**: Bloomberg's AI investments are about *summarizing and
searching news/documents you already pulled up*. They are **not exposed as
screen predicates**. You cannot type into EQS "show me S&P names with rising
narrative volume this week AND an unresolved contradiction in the knowledge
graph." Bloomberg's sentiment model produces a score, but screening *the
universe* by an LLM-derived narrative signal is not an EQS primitive. That is
the structural gap.

### §2.2 Capital IQ / FactSet

- **Capital IQ**: filter companies/transactions by industry, geography, and
  financials; **custom data points and formulas**; **save screens + set alerts
  on screen-result changes**; Compustat point-in-time data; percentile/peer
  analysis (min / 25th / median / mean / 75th / max across a peer set for
  comps). ([FasterCapital][11], [WallStreetPrep comps][12])
- **FactSet**: comparable depth; competes head-to-head with Capital IQ on data
  breadth and modeling integration. ([PeerSpot FactSet vs CapIQ][13])
- Takeaway: **percentile/peer-relative columns and alert-on-screen-change are
  standard at the institutional tier.** We have neither yet — these are
  table-stakes gaps, not differentiators.

### §2.3 Koyfin / TIKR / Finviz (the "affordable Bloomberg" tier)

- **Koyfin**: 500+ metrics, **5,900+ screening criteria** on "Bloomberg-level"
  data, 10+ yrs history, global coverage. The price/breadth leader for retail+
  prosumer. ([Koyfin best screeners][14])
- **TIKR**: 100,000+ global stocks, ~335 metrics, 10 yrs history + 5 yrs
  estimates; best for global fundamental investors. ([TIKR vs Finviz][15])
- **Finviz**: US-only, fewer metrics, but **best-in-class visual screening**
  (heatmaps, pattern/technical filters) for short-term traders. ([TraderHQ
  Koyfin vs Finviz][16], [amsflow][17])
- Takeaway: the "cheap broad screener" niche is **already saturated**. Koyfin
  wins on breadth-for-price; Finviz wins on visual speed. We do not beat either
  on raw field count, and we should not try.

---

## §3. Gap analysis — honest matrix

Legend: 🟢 ahead / 🟡 parity (or planned-to-parity) / 🔴 behind.

| Axis | Bloomberg EQS | CapIQ/FactSet | Koyfin/TIKR/Finviz | **Worldview** | Verdict |
|---|---|---|---|---|---|
| Raw field count / breadth | 5,000+ | thousands | 300–5,900 | ~39 | 🔴 **behind — do not contest** |
| Point-in-time / 10yr history | yes | yes (Compustat) | 10yr | snapshot + nightly returns | 🔴 behind |
| Global coverage | full | full | global (Koyfin/TIKR) | US-leaning, ISO3 attribute exists | 🔴 behind |
| Formula / custom-field builder (BQL/CDE) | yes | yes | partial | no (fixed allowlist) | 🔴 behind |
| AND/OR/NOT criteria builder | yes | yes | partial | **explicitly deferred to v2** | 🔴 behind (table-stakes) |
| Returns / 52w-distance filters | yes | yes | yes | backend done, **frontend deferred (IB-L3)** | 🟡 parity-when-shipped |
| Analyst / insider / ownership filters | yes | yes | yes | backend done, **frontend deferred (IB-L4)** | 🟡 parity-when-shipped |
| Peer / percentile-relative columns | yes | **yes (core)** | partial | **none** | 🔴 behind (table-stakes) |
| Save / share / server-persist screens | yes | yes | yes | **localStorage only** (server defer L-7) | 🟡 behind on share |
| Alert-on-screen-result-change | partial | **yes** | partial | **none** (have alert *flag* as a column) | 🔴 behind (table-stakes) |
| Visual screening (heatmap/sparkline) | partial | partial | **Finviz wins** | sparkline TREND col, HeatCell | 🟡 parity-ish |
| Natural-language screen building | no (BQL is code, not NL) | no | no | **`nl-translate` shipped backend** | 🟢 **ahead (latent)** |
| **Screen by news/narrative volume** | **no** | no | no | scaffolded, **L-5b deferred** | 🟢 **ahead (the moat)** |
| **Screen by LLM relevance** | no | no | no | scaffolded, L-5b deferred | 🟢 **ahead** |
| **Screen by KG contradiction signal** | **no** | no | no | scaffolded, L-5b deferred | 🟢 **ahead (unique)** |
| **Screen by has-active-alert / has-AI-brief** | no | no (alerts ≠ screen filter) | no | scaffolded, L-5b deferred | 🟢 **ahead** |
| Explainability ("why did this surface") | minimal | minimal | minimal | **NL explanation + AI brief + chat** | 🟢 **ahead (latent)** |
| Price | $32k/user/yr | enterprise | $0–$50/mo | thesis/free-tier | 🟢 ahead on price |
| Speed / latency / UX cohesion | heavy, keyboard-dense | heavy | light | **20px dense + fast** | 🟡 competitive |

**The honest summary**: of ~20 axes, we are 🔴 behind on ~8 (all
breadth/depth/builder/table-stakes), 🟡 at-or-near parity on ~6 (mostly
"shipped backend, deferred frontend"), and 🟢 genuinely ahead on **6 — and all
6 are in the intelligence/NL/explainability cluster.** Our entire defensible
position is one cluster. Everything else is either a fast-follow or a
non-contest.

---

## §4. The winning thesis + roadmap

### §4.1 The strategic claim

> Bloomberg/CapIQ/FactSet/Koyfin let you screen on **what is true about a
> company's numbers**. Worldview *also* lets you screen on **what the market is
> currently saying, believing, and contradicting about a company** — and then
> tells you, in plain language, **why each name surfaced**.

That is a category Bloomberg structurally cannot enter cheaply: it requires an
LLM/NLP pipeline + knowledge graph + alert system *feeding the screener as
first-class predicates*. We already built the pipeline. The screener integration
is the last mile, and most of it is the **deferred** work.

### §4.2 The three killer screens Bloomberg literally cannot run

These are the demo. Each is impossible in EQS today:

1. **"Narrative breakouts"** — `news_count_7d ≥ 5 AND llm_relevance_7d_max ≥
   0.7`, sorted by `display_relevance_7d_weighted desc`. *"Which names is the
   market suddenly paying high-quality attention to this week?"* Pure EQS has no
   `news_count_7d` predicate.

2. **"Contradiction watch"** — `recent_contradiction_count ≥ 1` intersected with
   a fundamentals filter (e.g. `ROE ≥ 15%`). *"Show me high-ROE names where the
   knowledge graph holds conflicting claims right now."* Unique to us — the KG
   contradiction signal does not exist in any competitor.

3. **"Already-flagged movers"** — `has_active_alert = true AND return_1m ≤ -10%`.
   *"Names my alert system already fired on AND that are down sharply — the
   screen pre-joined to my watchlist intelligence."* Bloomberg keeps alerts and
   screens in separate silos.

A fourth, once IB-L5 + IB-L3 + IB-L5 land: **"High-quality compounders with
momentum and a story"** (`ROE≥15% AND FCF_margin≥15% AND net_debt/EBITDA≤2 AND
1Y_RTN≥0 AND news_count_7d≥1`) — already specified as preset T-IB-21. This is
the screen that fuses both halves of the product and is the strongest single
sales artifact.

### §4.3 The demo that sells it

A 90-second flow that no competitor can reproduce:
1. Type into the **NL input**: *"profitable large-cap tech that's getting a lot
   of news this week and has a contradiction flag."* → `nl-translate` returns
   filters + an explanation chip.
2. Results render in the dense grid with a **NEWS 7D** and **BRIEF SCORE**
   column lit up.
3. Hover a row → **RowHoverToolbar** → "Why did this surface?" → the **AI brief**
   / chat layer answers in plain language, citing the underlying articles and
   the contradicting claims.
4. Click "Alert me when this screen changes" (table-stakes alert-on-screen).

Steps 1, 2, 3 are the moat (NL + intelligence columns + explainability).
Step 4 is the table-stake that makes it feel professional.

### §4.4 Prioritized roadmap — differentiators vs table-stakes

**P0 — DIFFERENTIATORS (build these first; they are the moat):**

| Item | Source | Why it wins | Effort |
|---|---|---|---|
| **L-5b intelligence sync worker** | DEFERRED §1 | Unblocks *all* intelligence screening; without it the moat is a disabled badge | ~3 eng-days |
| **IB-L5 frontend** (flip 7 rows, NEWS 7D + BRIEF SCORE cols) | DEFERRED §2.6 | Makes killer screens 1–3 real | ~1 eng-day (gated on L-5b) |
| **Promote NL screen building to first-class** | `nl-translate` shipped | Already built; mount the NL input prominently, make it the default entry. Highest ROI — capability exists, just under-surfaced | ~0.5–1 eng-day |
| **Explainability surface** ("why did this surface?") | AI brief + chat (S8) + RowHoverToolbar | The single thing that converts a screener into an *intelligence* product | ~1–2 eng-days |

**P1 — TABLE-STAKES (make us credible; do not skip, but they don't win):**

| Item | Source | Why needed | Effort |
|---|---|---|---|
| **IB-L3 frontend** (returns + 52w distance) | DEFERRED §2.4 | "within 5% of 52w high, +1Y return" is the most-requested PM screen; backend already done | ~1 eng-day |
| **IB-L4 frontend** (analyst/insider/ownership) | DEFERRED §2.5 | "insider buying + analyst upside" is Bloomberg muscle-memory parity | ~1 eng-day |
| **L-4b insider universe activation** | DEFERRED §3 | Without it IB-L4 insider column shows 3 tickers (looks broken). Needs EODHD budget decision | ~0.5 eng-day + budget |
| **Server-persist + shareable screens** (L-7) | I-plan §2 / OQ-1 | CapIQ/Koyfin parity; also unlocks the workspace screener panel and team/demo sharing | ~1–2 eng-days |
| **Alert-on-screen-result-change** | not yet planned | CapIQ has it; it's also the natural bridge between our alert service and the screener | ~2 eng-days |
| **Peer / percentile-relative columns** | not yet planned | The one CapIQ table-stake we're fully missing; high analyst value | ~2–3 eng-days |

**P2 — DEFER / DO-NOT-CONTEST:**

- Full formula/BQL-style builder, AND/OR/NOT nested criteria, 5,000-field
  breadth, point-in-time history, full global coverage. **Do not chase these.**
  The NL input is our *answer* to the formula builder — it gives composability
  without the breadth war. (A user types intent; the LLM composes the
  predicates. We don't need BQL if NL works.)

### §4.5 Strategic unlocks vs table-stakes — the explicit mapping the user asked for

- **§1 L-5b** (intelligence sync worker) = **THE strategic unlock.** It is the
  single keystone: it converts 6 already-computed intelligence fields from
  "disabled badge" into live screen predicates. Everything differentiating
  (killer screens 1–3, IB-L5) is gated on it. **This is the highest-leverage
  deferred item in the entire PRD.** ~3 eng-days for the whole moat.
- **§2 IB-L5** (frontend) = the moat's UI; trivial once L-5b lands (mostly
  `backendReady` flag flips + 2 columns). **Strategic.**
- **§2 IB-L3 / IB-L4** (returns, analyst/insider/ownership frontend) =
  **table-stakes.** They achieve Bloomberg-parity on classic columns and make
  the product credible to a Bloomberg user, but a competitor matches them
  trivially. Ship them, but understand they don't differentiate.
- **NL screen building** (already shipped backend, under-surfaced) = **strategic
  and nearly free.** This is the most cost-effective single win available: the
  capability exists, it just needs to be made the primary interaction.

### §4.6 Sequencing recommendation (opinionated)

1. **Surface NL screen building prominently** (~0.5–1 d) — cheapest win, ships
   the "type what you want" story immediately.
2. **L-5b sync worker** (~3 d) — the keystone; unblocks the moat.
3. **IB-L5 frontend** (~1 d) — light up intelligence columns/filters.
4. **Explainability "why did this surface"** (~1–2 d) — wire AI brief/chat into
   the row toolbar. Now the demo (§4.3) is fully runnable.
5. Then table-stakes in parallel/after: **IB-L3, IB-L4 (+ L-4b budget),
   server-persist/share, alert-on-screen, peer-percentile columns.**

**Critical path to "the demo Bloomberg can't run" = steps 1–4 ≈ 5.5–7
engineer-days.** That is the entire competitive wedge, and ~4 of those days are
already-deferred, already-scoped work.

---

## §5. Risks to the thesis (be honest)

1. **Intelligence-data quality is the whole bet.** If `news_count_7d` /
   `contradiction_count` are noisy or sparse, the differentiator becomes a
   liability ("why does this say 0 news for a name that's all over the
   headlines?"). The deferred plan's own stale-data semantics question (§1.7)
   and the L-4b 3-ticker universe problem are concrete instances. **The moat is
   only as good as the pipeline feeding it.** Ship with a visible freshness
   indicator (the plan already proposes `intelligence_rollup_synced_at`).
2. **Bloomberg can fast-follow with money.** They have BloombergGPT and are
   shipping AI features monthly. If they decide to expose a news-volume screen
   predicate, our breadth disadvantage reasserts. Our defense is *speed +
   focus + price*, not permanence. The window is real but not infinite.
3. **NL screening over-promises.** If `nl-translate` mis-maps intent, trust
   collapses fast. Keep the explanation chip + show the resolved filters
   (already designed) so the user always sees what it actually screened on.
4. **Table-stakes gaps undermine credibility before the moat lands.** A
   Bloomberg user who sees no returns columns and no save/share may bounce
   before discovering the intelligence layer. Hence IB-L3/L4 are P1, not P2 —
   necessary hygiene, just not the win.

---

## §6. Bottom line for the user's headline question

**"How can we excel and compete against Bloomberg?"** — Not by being a cheaper
Bloomberg (Koyfin already is, and we'd lose the breadth war). We win by being a
**different category**: the screener that filters and ranks the universe by
*narrative, relevance, contradiction, and alert state*, built on the NLP/KG
pipeline we already have, with **natural-language input** instead of a formula
builder and **plain-language explanation** of every result. That product is
~5.5–7 engineer-days away, and most of those days are work that is already
designed and deferred (**L-5b → IB-L5 + promoting `nl-translate`**). Ship the
moat first; backfill the table-stakes (IB-L3/L4, save/share, alert-on-screen,
peer-percentiles) right behind it.

---

## Sources

[1]: https://unibocconi.libguides.com/c.php?g=706997&p=5101015 "Stocks and deals screening — Bloomberg, Università Bocconi LibGuides"
[2]: https://www.bloomberg.com/professional/insights/technology/bloomberg-terminal-essentials-best-equities-functions/ "Bloomberg Terminal Essentials: Best equities functions"
[3]: https://michael-mao.gitbook.io/bloomberg/bql/bloomberg-query-language-bql "Bloomberg Query Language (BQL)"
[4]: https://blog.iqmo.com/blog/bqnt/writing_bql/ "BQL Notes (WIP)"
[5]: https://www.liminfo.com/reference/bloombergref "Bloomberg Terminal Reference — DES, GP, FA, EQS commands"
[6]: https://www.itbrew.com/stories/2025/11/06/inside-the-bloomberg-terminal-ai "Inside the Bloomberg Terminal's AI"
[7]: https://www.bloomberg.com/company/press/bloomberg-launches-gen-ai-summarization-for-news-content "Bloomberg launches gen-AI summarization for news"
[8]: https://www.bloomberg.com/company/press/bloomberggpt-50-billion-parameter-llm-tuned-finance/ "Introducing BloombergGPT"
[9]: https://www.neugroup.com/bloomberg-terminals-how-much-more-youll-pay-next-year/ "Bloomberg Terminals: How Much More You'll Pay Next Year (NeuGroup)"
[10]: https://costbench.com/software/financial-data-terminals/bloomberg-terminal/ "Bloomberg Terminal Pricing 2026"
[11]: https://fastercapital.com/content/Capital-IQ--Capital-IQ-Platform-and-Features-for-Financial-Research-and-Analysis.html "Capital IQ Platform and Features"
[12]: https://www.wallstreetprep.com/knowledge/comparable-company-analysis-comps/ "Comparable Company Analysis (percentile/peer comps)"
[13]: https://www.peerspot.com/products/comparisons/factset_vs_s-p-capital-iq "FactSet vs S&P Capital IQ comparison"
[14]: https://www.koyfin.com/blog/best-stock-screeners/ "8 Best Stock Screeners of 2026 (Koyfin)"
[15]: https://www.tikr.com/blog/tikr-vs-finviz-which-stock-screener-is-better "TIKR vs Finviz"
[16]: https://traderhq.com/koyfin-vs-finviz/ "Koyfin vs Finviz Elite (TraderHQ)"
[17]: https://amsflow.com/compare/best-stock-screeners "Best Stock Screeners — Comparison (amsflow)"
