# PLAN-0102 — Morning Brief Redesign: From News Aggregator to 5-Minute Investor Summary

**Date**: 2026-05-28
**Author**: investigation agent (Claude Opus 4.7)
**Status**: P0 — highest-priority finding from user conversation
**Owner**: TBD (proposed: rag-chat squad + market-data squad for Wave C)

---

## 1. Pain Point — Why the Current Brief Fails the 5-Minute Test

The user's literal feedback was:

> "The morning brief was not as useful as it could be. It doesn't give general market info, no relation or impact to my portfolio. The daily brief should be the summary an investor would have to read if they only had 5 minutes that day."

The current brief output (pasted by the user) is:

```
Generated 2026-05-29 03:59 UTC
MORNING BRIEFING
5 new
Lead: Anthropic raised $65B in Series H funding at a $965B post-money valuation,
      signaling strong institutional confidence in AI infrastructure plays.
AI & TECH DEVELOPMENTS
- Anthropic secured $65B in Series H led by Altimeter Capital and Sequoia, with
  $15B from hyperscalers including Amazon
- Snowflake surged 37% on announcement of a $6B partnership with Amazon
- Groq is targeting a $650M fundraise following a licensing deal with Nvidia
CORPORATE STRATEGY
- Elon Musk considers merging SpaceX and Tesla, potentially creating a $3.4T
  combined entity
- Apollo and Blackstone are working on a $36B debt deal to support Anthropic
- LiveOne (LVO) expands partnership with Tesla
Additional Finnhub headlines listed below...
```

This reads like a Bloomberg headline crawl, not a portfolio brief. Specifically:

| Failure mode | Evidence |
|---|---|
| No tape direction | No futures, no S&P/NDX/RTY level, no VIX, no sector heatmap |
| No portfolio context | No mention of which holdings moved overnight, P&L impact, or sector exposure |
| No macro calendar | No Fed event / CPI / earnings list for today + tomorrow |
| No actionable framing | Every bullet is a fact, never an implication ("so what does this mean for me?") |
| No personalisation | The brief reads identically for every user — purely curated public news |
| Lead is generic | "Anthropic raised $65B" is news, not a *trading-day-relevant signal for this user* |

The root cause is structural, not prompt-level: the brief is implemented as a **news summariser over a pre-filtered article feed**. The prompt at `libs/prompts/src/prompts/briefing/morning.py:30-85` literally says *"You are a financial intelligence analyst writing a morning market briefing. Synthesize the following data into a clear, actionable structured brief."* — it never tells the LLM to *connect* that news to the user's holdings, to surface tape direction, or to lead with implication.

---

## 2. Target Structure — The 6-Section, 5-Minute Brief

A portfolio manager scanning before market open reads in this order:

| Section | Read time | What it answers | What it contains |
|---|---|---|---|
| **1. Tape direction** | 20 s | "What did markets do overnight?" | S&P fut / NDX fut / RTY fut % + VIX level + 1-line sector heatmap; ONE summary sentence |
| **2. Your portfolio today** | 60 s | "How am I positioned into today?" | Top-3 holdings with pre-mkt %; top winners + losers since close; any holdings with news in the brief window |
| **3. Macro calendar** | 20 s | "What scheduled events could move me?" | Today + tomorrow's Fed / CPI / jobless / earnings prints relevant to held names |
| **4. News that matters to you** | 120 s | "What changed overnight that affects my book?" | 3–5 items ranked by `display_relevance_score × portfolio_overlap_score`. Each item leads with the *implication* |
| **5. Risks + opportunities** | 60 s | "Where am I exposed today?" | 2–3 model-generated lines tying macro + tape + portfolio: e.g. *"10y above 4.5% — your duration-sensitive holdings (TLT 12%, REIT 8%) lose ~1% per 25bp"* |
| **6. Bonus context** | 30 s | "What else should I know?" | 1–2 generic high-impact items the model thinks every investor should know |

Above this, a **2-sentence lead** synthesises Sections 1+2+5:

> *"Overnight: ES +0.4%, VIX 14.2. Your most material exposure today is AAPL (12% wt) into 10:00 EST guidance commentary — see Section 4 N1."*

---

## 3. Data Inventory — What We Already Have but Aren't Surfacing

Mapping every upstream call the brief currently makes, against every field it ignores. The file is `services/rag-chat/src/rag_chat/application/use_cases/briefing_context.py`.

### 3.1 S1 — Portfolio (`briefing_context.py:113`)

`BriefingContextGatherer._s1.get_portfolio_context()` calls `services/portfolio/src/portfolio/api/internal.py:99` `GET /internal/v1/users/{user_id}/portfolio/context`.

**What it returns** (`portfolio/api/internal.py:149-171`):
- `holdings[]`: `ticker`, `entity_id`, `canonical_name`, `quantity`, `current_weight`
- `watchlist[]`: `ticker`, `entity_id`, `canonical_name`
- `total_positions`

**What it does NOT return — gaps**:
- No `cost_basis` (the field exists at `portfolio/api/schemas.py:474`, just not on this endpoint)
- No `day_change_pct` / `unrealised_pnl` per holding
- No sector breakdown / sector concentration
- No `last_price` / `mark_price`

**What the brief currently surfaces** (`brief_context_formatter.py:172-189`): only `name`, `quantity`, `weight` as `"Apple Inc.: 100 units, weight 12.0%"`. Every other field is dropped.

### 3.2 S3 — Quotes (`briefing_context.py:155`)

`self._s3.get_batch_quotes(instrument_ids)` returns per-instrument `QuoteSummary { last, bid, ask, volume, timestamp }` (`briefing_context.py:155`).

**Critical bug**: the resulting `quotes` dict is **passed into `BriefingContext.for_morning()` (`briefing_context.py:233`) but never rendered into the prompt**. `brief_context_formatter.format_market_overview()` (`brief_context_formatter.py:240-250`) only renders `ctx.market_overview.sector_performance` — and `market_overview` is **never populated** (no field is set on `BriefingContext.for_morning()`; default is `None`). So we fetch live quotes for every holding and silently throw them away.

This is a textbook "audit returned value never persisted" footgun — see memory entry `feedback_audit_returned_value_persistence.md`.

### 3.3 S5 — Alerts (`briefing_context.py:148`)

`get_pending_alerts(min_severity="medium")`. Already rendered (`brief_context_formatter.py:221-238`). No gap.

### 3.4 S6 — News (`briefing_context.py:137`)

`GET /api/v1/news/top?hours=24&limit=30&min_display_score=0.15` (`briefing_context.py:427-431`).

**Strength**: already scored by `display_relevance_score = 0.5*market + 0.4*llm + 0.1*routing` (per PRD-0026).

**Gap**: not ranked by **portfolio overlap**. The top-news endpoint returns the same articles to every user. The brief never joins `article.primary_entity_id` (present at `NewsArticleSummary.primary_entity_id`, `briefing_context.py:601`) against `portfolio.holdings[*].entity_id`. We already have both halves; we just don't intersect them.

### 3.5 S7 — Events (`briefing_context.py:157, 450-473`)

`search_events(entity_ids=[holdings.entity_id], date_from=now-7d)` — only fetches events linked to portfolio entities. The S7 service **already ingests macro events** (`services/knowledge-graph/src/knowledge_graph/app.py:17-18`): `economic_events_dataset_consumer` and `macro_indicator_dataset_consumer`.

**Gap**: macro events (Fed FOMC, CPI prints, jobless claims) typically have NO `subject_entity_id` because they apply economy-wide. PRD-0018 added a `region` field so they could be filtered at query time, but the brief's call only filters by entity. So Fed Wednesday is invisible to the brief even though the data is in `temporal_events`.

### 3.6 Summary table

| Datum | Already collected? | Currently surfaced in prompt? |
|---|---|---|
| Holdings list | yes | yes (name/qty/weight only) |
| Holdings cost basis / P&L | no (S1 endpoint doesn't return it) | no |
| Holdings sector | no | no |
| Holdings overnight % change | yes (via S3 batch quotes) | **NO — silently dropped** |
| Watchlist | yes | yes |
| Top news (general) | yes | yes |
| Portfolio-overlapping news | partial (entity_ids are in payload) | **NO — never joined** |
| Per-entity events | yes | yes |
| Macro events (Fed/CPI) | partial (S7 ingests them) | **NO — query doesn't pull them** |
| Active alerts | yes | yes |
| Sector heatmap | no | no |
| Index levels (SPY/QQQ/VIX) | yes (S3 supports any ticker via `find_instrument_by_ticker`) | no |
| Futures (ES, NQ) | unknown — need to check market-ingestion EODHD coverage | no |

---

## 4. Gaps and Required New Tools

### CAN_BUILD_NOW (data exists, just unsurfaced)

1. **Render the quotes we already fetch** — surface `last_price` and `prev_close_pct` per holding in the portfolio section. Pure formatter change.
2. **Portfolio-news entity overlap scoring** — re-rank `ctx.news_articles` by `display_relevance_score × (2.0 if primary_entity_id ∈ holding_entity_ids else 1.0)`. Pure formatter change.
3. **Pull macro events** — add a second S7 call: `search_events(entity_ids=[], event_types=["fed_meeting","cpi_print","jobless_claims","earnings"], date_from=today, date_to=today+2d)`. Requires the S7 `search_events` port to accept entity-less queries (verify in `s7_client.py:222`).
4. **Add indices to the quote batch** — append `SPY`, `QQQ`, `VIX`, `IWM`, `TLT` to `tickers` in `_resolve_tickers()` (`briefing_context.py:393`).
5. **Compute pre-market move per holding** — `(quote.last - holding.prev_close) / holding.prev_close`. We have `quote.last`; we need `prev_close` (a new S3 field, or compute via daily-bars endpoint).

### NEEDS_NEW_TOOL (1-2 day additions)

6. **Sector concentration** — extend `PortfolioContextResponse` (S1) to include `sector` per holding. S1 already has the entity_id; the sector field lives in `entities.sector` in intelligence_db. Either S1 calls S7 to join, or S6/S7 expose a `GET /internal/v1/entities/sectors?entity_ids=...` batch endpoint (cleaner: keeps the cross-DB join in the right service).
7. **Portfolio P&L** — `GET /internal/v1/users/{user_id}/portfolio/pnl?lookback=1d` returning `holdings[].day_change_pct`, `holdings[].day_change_usd`, plus aggregate. Logic already exists for the dashboard's KPI strip; just needs an internal endpoint.

### NEEDS_NEW_DATA (Wave C or later)

8. **Overnight futures** — EODHD covers cash indices (SPY) but **not futures**. Either (a) pull futures from a new feed, (b) approximate using overnight cash-index level changes (Yahoo / Finnhub provide pre-market quotes), or (c) cite the night close + this morning's pre-market and let the LLM phrase it as "ES proxy via SPY pre-mkt +0.4%". Recommend option (c) for Wave A; revisit for Wave C if user demands real futures.
9. **Earnings calendar by held ticker** — already ingested by S5 alert service for earnings alerts, but no API to read the calendar separately. Small lift to expose.

---

## 5. Proposed Prompt Redesign

Current prompt at `libs/prompts/src/prompts/briefing/morning.py:30-85` should be replaced with something like:

> *"You are writing the 5-minute morning brief for an investor. They will scan it once before market open and act on it. Your goal is to tell them what changed overnight that affects their book today.*
>
> *You receive:*
> - *Their portfolio: holdings (ticker / weight / sector / overnight %); cash + total value; sector concentration.*
> - *Overnight tape: index levels (SPY/QQQ/VIX/TLT), 1-line sector heatmap.*
> - *Macro calendar: scheduled events today + tomorrow (Fed / CPI / jobless / earnings on held names).*
> - *News (already ranked by relevance × portfolio overlap): items with [cN] markers.*
>
> *Output in this order and never re-order:*
> 1. *LEAD (2 sentences): synthesise tape + your most material exposure today.*
> 2. *TAPE: one bullet, one number per index, end with VIX.*
> 3. *YOUR PORTFOLIO TODAY: top 3 holdings with overnight %, then winners/losers, then holdings-with-news.*
> 4. *MACRO TODAY: one bullet per scheduled event with time and held-name impact if any.*
> 5. *NEWS THAT MATTERS: 3–5 items. **Each bullet must lead with the implication for the investor, then the fact. ** Format: "AAPL supply-chain risk — your 12% AAPL weight could see 1–2% downside if reported [cN]".*
> 6. *RISKS + OPPORTUNITIES: 2–3 cross-section lines tying tape + macro + portfolio.*
>
> *NEVER include news that doesn't connect to the user's holdings, sector exposure, or a macro event affecting their universe. Reject generic 'tech industry update' items unless the user holds AI/cloud names.*
>
> *NEVER use phrases 'consider', 'you should', 'it may be worth' — state the implication directly. Always cite [cN].*"

This swap alone (no new data) will roughly double the brief's usefulness because the LLM is finally told *what* to do with the data we hand it.

---

## 6. Proposed Implementation — 3 Waves

### Wave A — Repackage (1 day, no new endpoints)

**Goal**: rewrite formatter + prompt to render existing data in the new 6-section structure. No new tools, no new data.

- Rewrite `libs/prompts/src/prompts/briefing/morning.py` to the v4.0 prompt above.
- Update `BriefContextFormatter.format_portfolio_morning()` (`brief_context_formatter.py:172`) to include per-holding `quote.last` + computed overnight %.
- Add `format_indices()` method that renders `quotes[SPY/QQQ/VIX]` as a tape bullet.
- Modify `_resolve_tickers()` (`briefing_context.py:393`) to always append `["SPY","QQQ","VIX","IWM","TLT"]`.
- Re-rank `ctx.news_articles` in `format_news()` (`brief_context_formatter.py:193`) by `score * (2.0 if entity_id in held_entity_ids else 1.0)` before truncation.
- Pull macro events via a second `_fetch_events()` call with `entity_ids=[]` and a `event_types=["fed_meeting","cpi_print","earnings"]` filter (requires verifying S7 port accepts empty entity list — see `s7_client.py:222`).
- Tests: `test_brief_context_formatter.py` gains cases for portfolio-quote rendering, news re-ranking, macro section.

**Definition of done**: a logged-in user with AAPL+MSFT sees a brief whose first line mentions both names and tape.

### Wave B — Personalisation (3 days, 2 new endpoints)

- New `GET /internal/v1/users/{user_id}/portfolio/pnl?lookback=1d` on S1 returning `day_change_pct` + `day_change_usd` per holding and total.
- New `GET /internal/v1/entities/sectors?entity_ids=...` on S6 (or S7) returning sector per entity for the held set.
- `BriefingContextGatherer` adds a `_fetch_pnl()` + `_fetch_sectors()` call to the parallel `asyncio.gather`.
- `PortfolioSnapshot` gains optional fields `day_change_pct`, `sector`, `cost_basis`.
- Prompt section "YOUR PORTFOLIO TODAY" now shows winners/losers with real P&L numbers.

**Definition of done**: brief surfaces "Top winners: AAPL +1.2%, MSFT +0.8%. Top losers: TLT -0.4%" with real numbers, and "Risks" section can reason about sector concentration.

### Wave C — Tape + Calendar (3-5 days)

- Investigate market-ingestion (S4) for futures support; if absent, plumb pre-market quotes via EODHD's `intraday` endpoint or Finnhub for SPY/QQQ/IWM 04:00–09:30 EST window.
- New S5 endpoint `GET /internal/v1/calendar/today?held_entity_ids=...` exposing the earnings calendar already used by alerts.
- Promote macro events to first-class brief section with time-of-day formatting ("FOMC minutes 14:00 EST — Fed Chair speaks; relevant to your TLT 12% weight").
- A/B compare Wave A brief vs Wave C brief with the user.

**Definition of done**: the brief opens with a real overnight-futures sentence and lists every scheduled event in the user's universe for today + tomorrow.

---

## 7. Open Product Questions

These need user / founder input before implementation; do not assume an answer:

1. **Trade recommendations** — should the brief *suggest* actions ("trim AAPL above $X") or stay descriptive ("AAPL +1.2% pre-mkt; earnings tomorrow")? The latter is safer for compliance and matches the current prompt rule "Do not use phrases like 'consider', 'you should'." A senior PM may want stronger language.
2. **Sentiment / conviction scores** — surface `display_relevance_score` numerically per bullet, or hide it?
3. **Delta-from-yesterday segment** — do repeat readers want a "What's new vs yesterday's brief?" diff? We persist briefs already (`UserBriefRecord` in `brief_archive.py`); diff against yesterday is a Wave B add.
4. **Brief length** — current cap is ≤4 sections × ≤4 bullets × ≤140 chars (≈700 chars body). Wave A adds 2 sections; should we lift the cap to ≤6 × ≤4 × ≤180 chars, or stay tight?
5. **Quiet days** — when nothing in the user's universe moved overnight, what does a "quiet" brief look like? Single sentence + macro calendar only?
6. **Cross-asset exposure** — does the user hold non-equity instruments (FX, crypto, futures, bonds)? Wave C's tape design assumes equity-only.
7. **Refresh cadence** — current brief is generated on demand and cached. Should it auto-regenerate at 06:00 local time and push? (Affects S10 scheduler scope.)

---

## 8. Risk-Register Summary (3 sentences for PLAN-0102)

The morning brief is structurally a news aggregator, not a portfolio brief: it silently discards the per-holding quotes it already fetches, never joins news entities against held entities, and never queries macro events because the S7 call filters by `entity_id` only. A Wave A "repackage" — rewriting the prompt to the 6-section 5-minute structure and surfacing existing data we already pay to fetch — closes the most critical gap in under a day with no new endpoints. Waves B and C add personalised P&L + sector context and real overnight tape, but the user's pain is overwhelmingly fixable by changing what we render, not what we fetch.
