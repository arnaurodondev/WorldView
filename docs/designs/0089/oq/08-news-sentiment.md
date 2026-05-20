# Cluster 8 — News + Sentiment + Article Ranking

**Status**: draft — design only, no implementation
**Owner**: agent-news-sentiment
**Date**: 2026-05-19
**Parent index**: `docs/designs/0089/_INDEX.md`
**Scope**: OQ-D9 (sentiment dot source), news ordering, article-enrichment surfaces,
filter taxonomy, cross-page consistency, hover/preview, sentiment time-series.

---

## 1. Cluster summary

The platform currently produces **two independent sentiment signals from two services**
that are conflated in the design language ("the sentiment dot"):

| Signal | Producer | Storage | Granularity | Source signal |
|--------|----------|---------|-------------|---------------|
| **Article sentiment** | S6 NLP pipeline — `ArticleRelevanceScoringWorker` (PLAN-0050 Wave E, F-Q1-07) | `nlp_db.document_source_metadata.sentiment` (enum: positive/negative/neutral/mixed) | Per article | LLM classification on the article body via DeepInfra Meta-Llama-3.1-8B; emitted in the same call that produces `llm_relevance_score`. Set on `RankedArticle.sentiment` returned by `GET /v1/news/{top,entity,relevant}`. |
| **Daily entity sentiment** | EODHD News-Sentiment provider, ingested by S3 market-data | `market_db.daily_sentiments` (`polarity_mean`, `pos_mean`, `neu_mean`, `neg_mean`, `article_count` per instrument per day) | Per instrument per day | Aggregate provided by EODHD — NOT computed by S6, NOT joinable to our articles. Currently **NO endpoint exposes this** to the frontend. |

There is **no** per-article `sentiment_subject_score` in the codebase today; the PRD
inventory references such a field in the abstract — the closest production signal is
the `sentiment` enum above, plus the `polarity` field that lives on `signals` (Block 5
SignalEvent), which is a signal-event polarity (`up | down | unknown`) and is **not**
suitable for article-level UI use.

The article ranker, by contrast, is well-defined. Articles are ranked by
`display_relevance_score = 0.5 * market_impact_score + 0.4 * llm_relevance_score + 0.1 * routing_composite_score`,
computed at query time inside `news_query.py` (see `nlp-pipeline` `application/use_cases/signals.py:223`).
This is the canonical "newsworthiness" metric and powers `/v1/news/top` and
`/v1/news/entity/{id}` since PRD-0026.

The frontend today only surfaces **4 of ~12 enriched fields** the backend emits per
article. The redesign opportunity is large and cheap: backend has the data; UI has to
render it.

The actionable decisions in this cluster:

1. **OQ-D9**: use article-level sentiment as the *primary* surface; use daily_sentiments
   as the *secondary* surface on an entity-overview sentiment sparkline. They are not
   interchangeable — never average them, never let one "override" the other.
2. **Order**: default to `display_relevance_score` on per-entity feeds (Bloomberg NLRT
   default); offer a user-toggle to `published_at` (recency); never expose `impact_score`
   as a top-level sort (it is one of three input weights, not an output).
3. **Filter taxonomy**: time-range stays its own tab strip; sentiment moves into a single
   facet dropdown alongside source (publisher) and topic. Keep total controls ≤ 4 atoms.
4. **DenseArticleRow contract** unifies row rendering across Intelligence / Quote /
   Dashboard / `/news`. One component, one type, one set of props.
5. **Hover preview** renders the first sentence + the top-3 co-mentioned entities; click
   opens the publisher URL (Bloomberg NLRT pattern).
6. **30-day sentiment sparkline** is a *future* surface — requires a backend endpoint
   that does not yet exist (S6 has the raw article-sentiment, but no aggregation worker).
   The daily_sentiments table can carry a *parallel* sparkline today.

---

## 2. Per-OQ deep dive

### 2.1 OQ-D9 — Sentiment dot source: per-article vs daily aggregate

**Recommendation**: per-article `article.sentiment` (S6) for all article-row surfaces;
daily_sentiments (S3) for an entity-overview *sparkline only*, gated behind a new
endpoint we have to add. The two signals **never disagree on the same row** because they
do not describe the same thing.

**Why per-article wins for article rows**

- Granularity matches: a news row IS a single article. Showing a daily-aggregate dot on
  an article row implies "this article is part of a positive day" — a non-statement.
- Source consistency: every article in the feed has S6 article-sentiment as soon as
  `ArticleRelevanceScoringWorker` has scored it. The backend already returns it on the
  same payload (`RankedArticle.sentiment`).
- daily_sentiments only exists for `instrument_id` rows — not for `person`, `topic`,
  `macro_event`, `sector`, etc. Per-entity news feeds for non-instrument entities have
  no daily-sentiments coverage at all.
- daily_sentiments is EODHD-sourced and does NOT include our own ingested articles
  (Bloomberg/FT/CNBC content). Using it for our article rows would be lying about the
  signal.

**Why daily_sentiments is the right source for a sparkline**

- It is already aggregated, indexed by `(instrument_id, date DESC)`, and has the four
  components `pos_mean / neu_mean / neg_mean / article_count` plus `polarity_mean ∈ [-1, 1]`.
- 30D/90D coverage is the EODHD baseline — denser than what S6 can offer until we ship a
  per-entity aggregation worker.
- The sparkline answers a different question than the dot: "is this name trending more
  negative than usual?" rather than "is this specific article positive?"

**Tie-breaking when both exist for the same entity**

Never on the same surface. Article rows always render the per-article dot. The right-rail
sparkline always plots `daily_sentiments.polarity_mean`. If we ever wanted to overlay
"S6 our-corpus sentiment" on the same sparkline, it would be a second series with its own
legend label ("Worldview corpus" vs "EODHD aggregate"). Out of scope for v1.

**Mapping article-sentiment to dot color**

| `RankedArticle.sentiment` | Stripe color (DenseArticleRow) | Rationale |
|---------------------------|-------------------------------|-----------|
| `positive` | `bg-positive` (terminal green `#16a34a` from globals.css tokens) | Single source of truth |
| `negative` | `bg-negative` (terminal red) | — |
| `neutral` | `bg-muted-foreground/40` | Deliberately desaturated — neutral is not "no signal" but "explicitly neutral" |
| `mixed` | `bg-muted-foreground/40` (same as neutral) | UI does not encode "mixed" separately; the LLM emits it but for the UI it is "ambiguous → no directional cue". Surfaces in a hover tooltip ("mixed sentiment") for the curious. |
| `null` | `bg-muted-foreground/20` (almost invisible) | "not yet scored" — distinct from explicit neutral |

We do **not** introduce a 5th color for "mixed" because Bloomberg NLRT, Refinitiv Eikon
and TradingView all use a 3-state encoding (pos / neg / neutral). Adding a 4th hue costs
discoverability for negligible information gain.

### 2.2 News ordering

**Backend reality**

- `/v1/news/top` — sorted by `display_relevance_score DESC` within a rolling
  `hours` window (default 24, max 168). No alternative sort.
- `/v1/news/entity/{id}` — sorts by `display_relevance_score` **or** `published_at`,
  controlled by `order_by` query param. Default is `display_relevance_score`.
- `routing_decisions.composite_score` powers the `routing_score` weight that feeds
  `display_relevance_score` — it is an *input*, never a standalone sort key.

**Recommendation per surface**

| Surface | Default sort | User toggle | Why |
|---------|--------------|-------------|-----|
| Dashboard "Top Today" | `display_relevance_score` (last 24 h) | none | Dashboard is "what matters" — that's exactly what the composite score answers |
| Intelligence tab NewsColumn (per-entity) | `display_relevance_score` | `RECENT` toggle in the filter strip (switches to `published_at`) | Analysts want signal first, then recency for live monitoring |
| Quote tab RelatedHeadlines (top 5) | `display_relevance_score` (last 24 h) | none | 5-item digest, no UI room |
| `/news` global feed | `display_relevance_score` (last 24 h, `min_display_score >= 0.4`) | `LATEST` / `MOST RELEVANT` tab pair | Browse mode supports both intents |
| Portfolio news (PortfolioNews block) | `display_relevance_score` (last 24 h, deduped per ticker top-3) | none | Risk surface — high-signal only |

**Why not user-configurable everywhere**

- Bloomberg NLRT defaults to relevance and is not user-configurable per pane — settings
  are an account-level preference. We honour that pattern: the toggle lives on
  Intelligence and `/news` only (the long-dwell surfaces).
- Letting users toggle on the Dashboard cards turns a 60-pixel widget into a stateful
  control surface, which defeats its purpose.

**Why we never expose `impact_score` as a top-level sort**

It is one of three weights inside the composite. Exposing it directly would force users
to reason about whether they want "price moved" or "LLM thinks it matters" — a question
the composite already answers. The impact score still renders as a per-row number
(rightmost column on DenseArticleRow); users can `j`/`k` scan the rightmost column to
mentally sort. That is enough.

### 2.3 Article enrichment fields — surface map

All fields below are already populated by S6 in the `/v1/news/{top,entity,relevant}` and
`/v1/instruments/{id}/page-bundle.top_news` payloads. The frontend today renders four of
them. The redesign extracts five additional fields into visible surfaces.

| Field | Source | Currently rendered? | Recommended surface | Rationale |
|-------|--------|---------------------|---------------------|-----------|
| `title` | S6 | yes | DenseArticleRow center column | unchanged |
| `published_at` | S5 | yes (HH:MM) | DenseArticleRow time column | unchanged |
| `source_name` | S6 (3-char code) | yes | DenseArticleRow source column | unchanged |
| `sentiment` | S6 | yes (dot) | DenseArticleRow left 2 px stripe (replaces dot per Intelligence-tab design §4.2) | denser, peripheral-vision encoding |
| `impact_score` | S6 | yes (0-99 right col) | DenseArticleRow right column | unchanged; tone-color above 70 |
| `display_relevance_score` | S6 (query-time composite) | no | hover tooltip: "Rel 87 · Imp 72 · Rec 12 h" | full triplet on demand |
| `market_impact_score` | S6 (signal pipeline) | no | hover tooltip only | not actionable enough for row |
| `llm_relevance_score` | S6 | no | hover tooltip only | same |
| `routing_tier` | S6 (LIGHT / MEDIUM / DEEP) | no | row trailing 1-char glyph next to impact (•L / •M / •D) — **only on `/news` global feed** | power-user surface; clutters per-entity feed |
| `impact_windows.{day_t0,t1,t2,t5}` | S6 | no | hover tooltip + inline sparkline on `/news` row | 4-point post-publication price reaction |
| `cluster_id` + cluster count | S6 (P2-F) | partial (chip in PLAN-0090) | trailing "+N sim" chip if `cluster_size > 1` | dedup signal |
| `primary_entity_symbol` | S6 | no | DenseArticleRow ticker pill (3-char, mono) — **only when feed is multi-entity** | suppress on entity-tab (redundant) |
| `language` | S5 | no | hover tooltip ("EN", "ES" …) when ≠ "en" | foreign-language signal |
| `word_count` | S5 | no | hover tooltip ("1,247 w") | reading-time signal |
| `url` | S5 | yes (click → publisher) | row click handler | unchanged |
| `source_type` | S5 (bloomberg / reuters / …) | partial | hover tooltip; used for source-filter facet | grouping handle |

**Internal-only fields** (never surfaced visually): `article_id`, `doc_id`,
`routing_score` (the 0.1 weight — opaque), `primary_entity_id` (UUID), embeddings,
`evidence_text` from signals (lives in a separate `/v1/signals` view).

### 2.4 Filter taxonomy

**Current** (PLAN-0090 NewsColumn) — 7 controls in two strips: `ALL · TODAY · 3D · 1W`
on the left and `POS · NEU · NEG` on the right. No source filter, no topic filter, no
"min relevance" knob.

**Recommendation** — 4 controls in a single 22 px strip:

```
[ ALL  TODAY  3D  1W ]   |   [ FILTERS ▾ ]   |   [ RECENT ⇄ RELEVANT ]
   time tabs (≤ 11 chars)      facet dropdown       sort toggle (Intelligence-only)
```

The `FILTERS ▾` dropdown is a single popover with three facet groups:

```
FILTERS                                    [Clear all]
─ Sentiment ──────────────────────────────────────
  ☐ Positive    ☐ Neutral    ☐ Negative
─ Source ─────────────────────────────────────────
  ☐ Bloomberg   ☐ Reuters    ☐ FT
  ☐ WSJ         ☐ CNBC       ☐ +12 more
─ Topic ──────────────────────────────────────────
  ☐ Earnings    ☐ M&A        ☐ Regulation
  ☐ Macro       ☐ Insider    ☐ +8 more
─ Minimum relevance ──────────────────────────────
  ▱▱▱▰▰▰ 60
─ Language ───────────────────────────────────────
  ☐ EN (default)  ☐ ES  ☐ FR  ☐ DE
```

**Why a single dropdown rather than four separate strips**

- Pixel budget: the news column is 403 px wide. Four 22 px strips eat 88 px of vertical
  before the first article — that is 4 articles' worth at 18 px row height.
- Power-user pattern: Refinitiv Eikon "advanced filters" is a dropdown, not a strip.
  Bloomberg NLRT uses the keyboard letter shortcut (`F` opens the filter sheet).
- Discoverability: pinning sentiment to the strip but hiding source in a dropdown sends
  conflicting signals about which axis matters more. They are all secondary axes after
  time and sort.

**Why time stays in the strip**

It is the one axis every user touches every session. Bloomberg, TradingView, and
Yahoo Finance all keep it as a chip strip — copying that pattern keeps the muscle memory.

**Backend impact**

`/v1/news/entity/{id}` already supports `start_date`, `end_date`, `order_by` parameters.
It does **not** yet support `sentiment`, `source_type`, `topic`, `min_display_score`,
`language`. `/v1/news/top` supports `min_display_score` and `routing_tier` only. Backend
must add the missing query params on both endpoints (see §7 — Backend additions).

### 2.5 Cross-page news consistency

All four surfaces render the **same `DenseArticleRow` component** with mode-specific
props turning columns on/off. No bespoke article-row variants.

| Surface | Component | Column set | Sort | Default limit |
|---------|-----------|------------|------|---------------|
| Intelligence tab | `<NewsColumn entityId={id} />` → `<DenseArticleRow />` (no ticker col) | stripe · time · source · headline · impact | relevance | infinite scroll, page 20 |
| Quote tab `RelatedHeadlines` | `<NewsColumn entityId={id} variant="compact" />` → `<DenseArticleRow />` (no ticker col) | stripe · time · source · headline · impact | relevance | 5, no scroll |
| Dashboard `PortfolioNews` | `<NewsList portfolio={p} />` → `<DenseArticleRow withTicker />` | stripe · time · TKR · source · headline · impact | relevance | 10, page-up only |
| `/news` global | `<NewsList global />` → `<DenseArticleRow withTicker withRoutingTier withCluster />` | stripe · time · TKR · source · headline · routing · cluster · impact | toggle | infinite scroll, page 50 |

The row component is a single file (`components/news/DenseArticleRow.tsx`). Variants are
prop-controlled, not subclassed:

```ts
interface DenseArticleRowProps {
  article: RankedArticle;
  withTicker?: boolean;       // show primary_entity_symbol column
  withRoutingTier?: boolean;  // show •L/•M/•D glyph
  withCluster?: boolean;      // show "+N sim" chip
  density?: "default" | "compact"; // compact = 16 px (Quote tab digest)
  onArticleClick?: (a: RankedArticle) => void; // for hover-preview wiring
}
```

This delivers the PRD-0089 "one canonical row" rule. Audit hook: ESLint rule
`no-restricted-imports` against `Article*Row` and `*Headlines*` shells that bypass
`DenseArticleRow`.

### 2.6 Article hover preview

**Recommendation**: 280×140 px popover anchored bottom-right of the row, 300 ms open
delay, click-through to publisher in new tab (existing behaviour preserved).

Content:

```
┌──────────────────────────────────────────────────────────┐
│ Apple Q2 Earnings Beat Expectations                     │  ← full title, wraps
│ Bloomberg · 2026-05-19 15:47 UTC · EN · 1,247 w         │  ← meta
│                                                          │
│ "Apple Inc. (AAPL) reported quarterly revenue of $94.8B,│  ← first 220 chars
│  beating consensus by 5.3 %; services revenue grew 18 % │     of body excerpt
│  YoY to a record $26.7B…"                                │     (NOT the title)
│                                                          │
│ Mentions: AAPL · TSMC · Tim Cook · iPhone                │  ← top-N co-mentions
│ Rel 87 · Imp 72 · Rec 12 h                               │  ← scoring triplet
└──────────────────────────────────────────────────────────┘
```

**Data sourcing**

- First-sentence excerpt: NEW backend addition. S5 has `documents.body_text` in S3
  (article body bytes). Either (a) lift the first sentence at ingest into
  `document_source_metadata.summary_excerpt` (preferred — query-time cheap), or (b)
  serve it via a `GET /v1/articles/{id}/preview` endpoint that range-reads the body.
  Recommend (a) — adds one column, populated at ingest by S5's existing parser.
- Top-N co-mentions: aggregate `entity_mentions` for the article, pick top 4 by frequency,
  return canonical labels. NEW backend endpoint or extension to `/v1/news/entity/*`.
- Scoring triplet: already on `RankedArticle`.

**Why hover (not click) preview**

Click-through opens the publisher URL — that is the dominant click outcome on news
surfaces and we don't want to break it for an in-app reader. Hover is non-destructive
and matches Bloomberg NLRT (which uses `Spacebar` for an inline preview overlay).
For touch / no-hover devices: long-press triggers the same popover; small `▸` glyph in
the row trailing area on hover-incapable devices.

**Performance**

Popover content is fetched lazily on hover start, cached for the session
(`qk.news.preview(article_id)`, `staleTime: Infinity`). Excerpt is short (≤ 256 chars)
so payload is tiny.

### 2.7 Sentiment time-series visualisation

**Recommendation**: 30-day daily sentiment sparkline on the Intelligence tab right rail,
inside the `EntityOverviewBlock`. Source: `daily_sentiments` (S3) — gated behind a NEW
S9 endpoint `GET /v1/instruments/{id}/sentiment-history?days=30`. **Skip when the entity
is not a financial_instrument** (the table has no rows for person/topic/macro).

Visual:

```
SENTIMENT (30D)   ▁▂▂▃▃▄▅▅▅▆▇▆▆▅▄▄▃▂▂▃▃▄▄▅▆▆▇▇▆▅      +0.32
                  L18  ←─────  M16  ─────→  H4         ← article counts
```

Specs:

- 60 × 16 px sparkline, `recharts <Sparkline>` reused from PLAN-0090.
- Y axis: `polarity_mean` ∈ [-1, 1], no gridlines, no axis label (terminal density).
- Trailing label: current polarity rounded to 2 decimals (right-aligned, tabular-nums,
  10 px mono).
- Below the sparkline: 3-segment article-count breakdown — L/M/H bucket of positive,
  neutral, negative day counts.
- Hover-anywhere on the sparkline: tooltip with `date · polarity · article_count`.
- Empty state: "Coverage too thin for sentiment trend" when fewer than 7 days have
  `article_count >= 3`.

**Why not S6 article-sentiment**

Three blockers:

1. No aggregation worker exists to roll per-article `sentiment` into a daily series.
   Building one is medium-effort (new worker + retention).
2. Coverage is opportunistic — S6 only scores articles that pass routing thresholds.
   Charting that produces survivorship bias.
3. daily_sentiments is already there, indexed, and 250-3000 articles deep per day per
   ticker — the curve is smooth and stable.

**Future iteration (v1.1)**

When S6 ships a per-entity-per-day aggregation worker (proposed Worker 13D-X), overlay
the two series on the sparkline ("our corpus" vs "EODHD aggregate") with a one-line
legend. Useful divergence signal but out of scope here.

---

## 3. Cross-page row contract — `DenseArticleRow` spec

### 3.1 File and location

`apps/worldview-web/components/news/DenseArticleRow.tsx`
(moved from `components/instrument/intelligence/news/` — it is no longer
instrument-scoped).

### 3.2 Props

```ts
// Mirror the backend RankedArticle exactly; this is the canonical article shape.
import type { RankedArticle } from "@/types/api";

export interface DenseArticleRowProps {
  /** Backend payload — RankedArticle from /v1/news/* */
  article: RankedArticle;

  /** Show 3-char ticker pill between source and headline. Default false. */
  withTicker?: boolean;

  /** Show single-char routing-tier glyph (L/M/D) before impact. Default false. */
  withRoutingTier?: boolean;

  /** Show "+N sim" chip when cluster_size > 1. Default false. */
  withCluster?: boolean;

  /** "default" = 18 px; "compact" = 16 px (Quote-tab digest only). */
  density?: "default" | "compact";

  /** Override default behaviour (window.open publisher URL).
   *  Wave-9 wires this to in-app preview when feature flag is on. */
  onArticleClick?: (article: RankedArticle) => void;

  /** Highlighted via keyboard j/k navigation. */
  isActive?: boolean;
}
```

### 3.3 Visual layout (default density, 18 px)

```
│▌HH:MM  BBG  [TKR]  Apple beats Q2 by 5.3 %                  •L  +3sim  87│
└┬┘└─┬─┘  └┬┘  └┬─┘  └─────────────┬──────────────┘            └┬┘  └─┬──┘ └┬┘
 │   │     │    │                  │                            │     │    │
 │  time  src ticker            headline                       tier cluster impact
 │   30px 40px 36px              flex-1 truncate                12px  44px  28px
 │
 sentiment stripe (2 px, full row height, left edge)
```

| Atom | Size | Font | Behaviour |
|------|------|------|-----------|
| Sentiment stripe | 2 px wide × row height | n/a | bg color from §2.1 mapping. Replaces the previous round dot. |
| Time | 30 px | `text-[10px] font-mono` | HH:MM 24h, viewer local TZ |
| Source | 40 px | `text-[10px]` muted | 3-char alpha code, truncate |
| Ticker (optional) | 36 px | `text-[10px] font-mono` | omitted when `withTicker=false` |
| Headline | flex-1 | `text-[11px]` | `truncate`; title-attr = full headline |
| Routing tier (optional) | 12 px | `text-[10px] font-mono` | `•L` / `•M` / `•D`; muted; omitted when `withRoutingTier=false` |
| Cluster chip (optional) | up to 44 px | `text-[9px]` muted, border 1 px | `+{n}sim`; click → ClusterArticlesModal; omitted when `withCluster=false` or `cluster_size <= 1` |
| Impact | 28 px right-align | `text-[10px] font-mono tabular-nums` | 0-99, tone color: ≥70 positive · 40-69 warning · <40 muted |

Row container: `h-[18px] flex items-center gap-2 px-3 border-b border-border/20`
+ `hover:bg-muted/15` (no transition).

`density="compact"` reduces height to 16 px and shrinks all atoms 1 px; used only on
Quote-tab `RelatedHeadlines` where the section budget is 80 px (5 × 16 = 80).

### 3.4 Hover / preview wiring

```ts
const [previewArticle, setPreviewArticle] = useState<RankedArticle | null>(null);

<Popover open={previewArticle?.article_id === article.article_id}>
  <PopoverTrigger asChild>
    <div
      onMouseEnter={() => previewTimeoutRef.current = setTimeout(() => setPreviewArticle(article), 300)}
      onMouseLeave={() => { clearTimeout(previewTimeoutRef.current); setPreviewArticle(null); }}
      onClick={() => onArticleClick?.(article) ?? window.open(article.url, "_blank", "noopener,noreferrer")}
    >
      {/* row atoms */}
    </div>
  </PopoverTrigger>
  <PopoverContent side="bottom" align="end" className="w-[280px] p-2 text-[11px]">
    <ArticlePreview articleId={article.article_id} />
  </PopoverContent>
</Popover>
```

`ArticlePreview` is its own component that fires `useQuery(qk.news.preview(id))` — keeps
DenseArticleRow stateless about preview data.

### 3.5 Accessibility

- `role="link"` when `article.url` exists; `tabIndex={0}`.
- `aria-label` = `${time} · ${source} · ${title} · ${sentiment} sentiment · impact ${impact_score}`.
- Stripe is decorative (`aria-hidden`); sentiment also surfaces in `aria-label`.
- Keyboard: `Enter` opens article; `Space` opens preview popover (matches Bloomberg).

### 3.6 Migration plan

`CompactArticleRow.tsx` (PLAN-0090) becomes a 5-line thin wrapper around `DenseArticleRow`
with `density="compact"` for backward compatibility, then is removed in Wave G after the
four call sites migrate. Old `Article*Row` shells in
`components/news/Article*` are replaced wholesale.

---

## 4. Sentiment surfacing rubric

| Surface | Source | Visual | Endpoint |
|---------|--------|--------|----------|
| DenseArticleRow stripe | `RankedArticle.sentiment` (S6 per-article) | 2 px left edge stripe — pos/neg/neutral/null mapping | already on every news payload |
| Hover-preview "Sentiment" label | same as above | text label inside popover | same |
| Right-rail sparkline (EntityOverviewBlock) | `daily_sentiments.polarity_mean` (S3, EODHD) | 60×16 sparkline + L/M/H breakdown | NEW: `GET /v1/instruments/{id}/sentiment-history?days=N` |
| Right-rail "Sentiment summary" line (future v1.1) | composite of both series | 11 px line: "Last 7 d: +0.21 (S6) · +0.15 (EODHD)" | requires S6 per-entity aggregation worker |
| Top-relations row tone (future v1.1) | aggregate of per-article sentiment for edges connecting to target entity | row text color tinted (5 % opacity) | requires edge-sentiment aggregation in S7 |
| Dashboard "Sentiment shift" widget (future v1.1) | day-over-day delta of polarity_mean | tile widget showing tickers with ≥0.3 swing | uses sentiment-history endpoint |

**Rules**:

1. Per-article sentiment is the *only* source on row surfaces. No averaging, no
   overriding from daily aggregates.
2. Daily aggregate sentiment is the *only* source on entity-level trend surfaces. We
   never roll per-article sentiment into a chart until we ship the aggregation worker.
3. Sparkline polarity is the ONLY metric we render numerically (one decimal place).
4. All sentiment surfaces share the same 3-color palette: positive / negative / neutral.
   No hue creep.

---

## 5. Filter taxonomy specification

### 5.1 Strip layout

22 px tall, `flex items-center px-3 gap-3 border-b border-border`:

```
[ALL] [TODAY] [3D] [1W]   │   [⊟ FILTERS]   │   [RELEVANT] / [RECENT]
```

- Time tabs (4): 10 px uppercase tracking-wide, underline on active. State machine:
  `"all" | "day" | "3d" | "1w"`. Selecting `all` clears `start_date`/`end_date`.
- Filter button: 10 px, opens popover. Badge with count of active facet selections
  (e.g. `⊟ FILTERS · 3`).
- Sort toggle: present on Intelligence tab and `/news`; not on Dashboard widgets.
  State: `"relevance" | "recency"`. Maps to backend `order_by` param.

### 5.2 Filter popover schema

State held by parent (NewsColumn / NewsList):

```ts
interface NewsFilterState {
  timeRange: "all" | "day" | "3d" | "1w";
  sentiment: Array<"positive" | "neutral" | "negative">; // multi-select; empty = all
  sources: string[];          // source_type values; empty = all
  topics: string[];           // topic tag IDs; empty = all
  minRelevance: number;       // 0-100 in UI; divided by 100 for backend param
  languages: string[];        // ISO 639-1; default ["en"]
  sortBy: "relevance" | "recency";
}
```

Backend query mapping:

| UI field | Backend param | Endpoint support |
|----------|---------------|------------------|
| `timeRange` | `start_date`, `end_date` (computed) | `/news/entity` ✓ ; `/news/top` uses `hours` instead — adapter computes |
| `sentiment` | `sentiment` (csv) | NEW — both endpoints |
| `sources` | `source_type` (csv) | NEW — both endpoints |
| `topics` | `topic` (csv) | NEW (requires topic-tag table — see §7) |
| `minRelevance` | `min_display_score` (0.0-1.0) | `/news/top` ✓ ; `/news/entity` NEW |
| `languages` | `language` (csv) | NEW — both endpoints |
| `sortBy` | `order_by` (`display_relevance_score` / `published_at`) | `/news/entity` ✓ ; `/news/top` NEW |

### 5.3 URL persistence

Filters serialise into the URL query string so links are shareable:
`/instruments/AAPL/intelligence?t=3d&sent=positive,neutral&src=bloomberg,ft&min=60`

Parsed client-side via `useSearchParams()`; written back via `router.replace()` (no nav
event). Persists across page refreshes.

### 5.4 Why not faceted search à la Refinitiv

Refinitiv's per-facet sidebar is 320 px wide and dominates the page. Our news column is
the entire content of one of three columns — it cannot afford a sidebar. The dropdown is
the right compromise: discoverable for new users, fast for power users (`F` hotkey opens).

---

## 6. Recommended decisions table

| Decision | Recommendation | Backend impact | UI impact |
|----------|----------------|----------------|-----------|
| Sentiment dot source | per-article (S6 `RankedArticle.sentiment`) on rows; daily_sentiments on sparkline | NEW `/v1/instruments/{id}/sentiment-history` endpoint | replace dot with 2 px left stripe; add sparkline to EntityOverviewBlock |
| News default sort (per-entity) | `display_relevance_score` | none (default already this) | wire `sortBy` toggle in filter strip |
| News default sort (global / dashboard) | `display_relevance_score` last 24 h | none | — |
| Article enrichment in row | sentiment + impact + ticker (when multi-entity) + cluster chip + tier glyph | none | DenseArticleRow with prop variants |
| Article enrichment in hover | excerpt + co-mentions + scoring triplet + meta (lang, word_count) | NEW `summary_excerpt` column on `document_source_metadata` + NEW `/v1/articles/{id}/preview` endpoint | new `ArticlePreview` popover |
| Filter taxonomy | 4 time tabs + filter dropdown + sort toggle | NEW query params: `sentiment`, `source_type`, `topic`, `language`, `min_display_score` (entity), `order_by` (top) | NewsFilters rewrite |
| Cross-page consistency | one component, `DenseArticleRow`, prop-controlled | none | move file to `components/news/`; refactor four call sites |
| Hover preview | 280 px popover, 300 ms delay, lazy fetch | NEW preview endpoint + summary_excerpt column | `ArticlePreview` component |
| Sentiment time-series | 30 d sparkline in EntityOverviewBlock from `daily_sentiments` | NEW `/v1/instruments/{id}/sentiment-history` (S3 → S9) | new `SentimentSparkline` component |
| Mixed sentiment encoding | render same as neutral (desaturated stripe); expose label in hover only | none | mapping table in DenseArticleRow |
| "+N sim" cluster chip | inline on row only on `/news` (`withCluster`) | none | existing ClusterArticlesModal |
| Routing-tier glyph | inline only on `/news` (`withRoutingTier`) | none | DenseArticleRow prop |

---

## 7. Backend additions required

Ordered by dependency / blast radius:

1. **`document_source_metadata.summary_excerpt`** (text, nullable) — populated by S5 at
   ingest from the first 256 chars of `body_text` (sentence-bounded). One-line Alembic
   migration; backfill worker for existing rows. **Blocking for hover preview.**

2. **`GET /v1/articles/{article_id}/preview`** (S6 → S9 proxy) — returns
   `{title, source_name, source_type, published_at, language, word_count, summary_excerpt,
   co_mentions: [{entity_id, name, ticker?, mention_count}], display_relevance_score,
   market_impact_score, llm_relevance_score, sentiment, impact_score}`. **Blocking for
   hover preview.**

3. **Extend `/v1/news/entity/{id}` and `/v1/news/top` query params**:
   - `sentiment` (csv: positive,negative,neutral)
   - `source_type` (csv)
   - `topic` (csv) — depends on topic-tag table (see §7.6)
   - `language` (csv)
   - `min_display_score` (entity endpoint; top already has it)
   - `order_by` (top endpoint; entity already has it)

   All optional, all backward-compatible.

4. **`GET /v1/instruments/{instrument_id}/sentiment-history`** (S3 → S9 proxy) —
   returns `{points: [{date, polarity_mean, pos_mean, neu_mean, neg_mean, article_count}],
   coverage: {total_days, days_with_coverage}}`. Pull straight from `daily_sentiments`.
   Sentinel response when `instrument_id` has no rows: `{points: [], coverage: …}`.

5. **Topic-tag persistence** — currently S6 emits `topic` labels in `entity_mentions` /
   `routing_decisions.features` but there is no canonical topic taxonomy persisted per
   article. Need:
   - `nlp_db.document_topics` table `(doc_id, topic_label, score)` indexed by `doc_id`.
   - S6 worker (extension of existing routing block) writes topics at ingest.
   - `/v1/news/topics` enumeration endpoint for the filter dropdown.
   - Optional for v1; defer to v1.1 if scope-tight.

6. **`/v1/articles/{article_id}/preview` → `co_mentions`** requires aggregating
   `entity_mentions` for the article and JOINing to canonical labels. Trivial extension
   of existing news_query repo.

7. **(future, v1.1)** Per-entity-per-day sentiment aggregation worker — rolls
   `document_source_metadata.sentiment` into a `nlp_db.entity_sentiment_daily` table
   keyed by `(entity_id, date)`. Enables sentiment trend for non-instrument entities.

---

## 8. Follow-up OQs

1. **Topic taxonomy ownership** — who curates the topic enum (Earnings / M&A /
   Regulation / Macro / Insider / …)? S6 routing block emits free-text labels today.
   Need either a curated taxonomy (12-20 tags) or an LLM-classification step. Recommend
   curated. Owner: NLP-pipeline maintainer.

2. **Co-mention payload size** — top-4 entities per article preview is fine for blue-chip
   names but a Bloomberg long-form article may mention 20+ entities. Cap at 4 by
   `mention_count` desc; expose the full list inside the cluster modal.

3. **Sparkline empty state coverage threshold** — "≥ 7 days with ≥ 3 articles" is a
   judgement call. Validate against actual `daily_sentiments` density for the
   bottom-quartile ticker we cover before shipping.

4. **Mixed sentiment surface in hover** — should we render the literal "mixed" word in
   the popover, or stick with "neutral / mixed"? Recommend "mixed (ambiguous)" to make
   the LLM honesty visible.

5. **Sort-by-recency in `/news` global** — recency on a global feed is a firehose. Need
   a `min_display_score` floor of 0.3 even in recency mode to suppress noise. Confirm
   with content-platform owner.

6. **Sentiment overlay on impact-window sparkline** — `RankedArticle.impact_windows.day_t0..t5`
   is a 4-point post-publication price series. Could overlay sentiment as background
   tint. Defer to v1.1; would compete with too many channels in a 60 px sparkline.

7. **DenseArticleRow on portfolio holdings table** — should the holdings table inline a
   1-row mini-feed per ticker? Probably not (it duplicates PortfolioNews block). Out of
   scope here, flagged for `04-portfolio-detail.md` agent.

8. **Hover preview a11y** — `Spacebar`-to-open matches Bloomberg but conflicts with
   default browser scroll on focused links. Confirm key binding with global shell
   (`01-global-shell.md`) before implementation.

9. **Filter persistence across entities** — when the user navigates AAPL → MSFT, do we
   keep their `sentiment=positive` filter? Recommend: yes, by default (URL-driven), with
   a "Clear filters" affordance in the dropdown when the active count > 0.

10. **Cluster modal coordination with `/news` route** — `withCluster=true` on `/news`
    rows triggers ClusterArticlesModal. The modal currently lives under
    `components/news/cluster/`. Confirm the route renders modals via the
    `@modal` parallel slot so deep links can land on `/news/cluster/{id}` directly.

---

**End of cluster 8 design.** Cross-references: see `07-instrument-intelligence.md` for
NewsColumn layout; `02-dashboard.md` for PortfolioNews block; `05-instrument-quote.md` for
RelatedHeadlines digest; `00-backend-data-inventory.md` §1.3 / §2.2 / §3.3 for endpoint
shapes.
