# Investigation Report: News Momentum, News Relevance, and Prediction Markets

**Date**: 2026-06-28
**Investigator**: Claude (investigate skill)
**Scope**: Three independent dashboard/data-quality concerns
**Status**: All three root-caused

---

## Track 1 — Dashboard "News Momentum" panel is empty

**Severity**: HIGH (user-visible feature dead; symptom of a platform-wide ingestion outage)
**Status**: Root cause identified

### Issue Summary
The dashboard NEWS MOMENTUM widget renders "No news momentum yet" on its default 24H window.

### Root Cause
**The EODHD API key is revoked (HTTP 401), so news ingestion has been fully halted since 2026-06-25.** The panel logic is correct — it simply has no recent articles to rank.

- Key: `CONTENT_INGESTION_EODHD_API_KEY=<REDACTED>` at
  `services/content-ingestion/configs/docker.env:69`.
- Live probe (host): `GET https://eodhd.com/api/news?api_token=667bca...` → **`HTTP 401 Unauthenticated`**.
- `content-ingestion-worker` logs: every `eodhd:fetch:*` task fails 401, retries 3×, exhausts.

### Evidence
| Evidence | Source | Finding |
|----------|--------|---------|
| `created_max` in `document_source_metadata` | nlp_db | `2026-06-25 05:26` — no article ingested in ~3 days |
| Window counts | nlp_db | `dsm_24h=0`, `dsm_72h=0`, `dsm_168h=4678` |
| 1W aggregation | nlp_db | 3,821 resolved entities (top: 584 articles) → panel **would** populate on 1W |
| Worker logs | content-ingestion-worker | `HTTP 401 Unauthorized` on every EODHD fetch |
| Live key probe | host curl | `HTTP 401 Unauthenticated` |

### Execution Path (verified)
`AiSignalsWidget.tsx` (default 24H) → S9 `GET /v1/signals/ai?hours=24`
(`api-gateway/.../routes/signals.py:143`) → S6 `GET /api/v1/news/trending-entities`
(`nlp-pipeline/.../api/routes/trending_entities.py:122`) → SQL counts distinct articles
*published within window* (`.../repositories/trending_entities_query.py`). With 0 articles in
24H, the use case returns `[]` → frontend `EmptyState` "No news momentum yet"
(`lib/copy/empty-states.ts:249`).

### Secondary (latent) issue — scheduler self-wedge
`has_active_task` (`content-ingestion/.../repositories/task.py:195`) treats *recent* PENDING
tasks as blocking, and the watchdog re-arms orphaned PENDING rows (refreshing `updated_at`).
Result: 643 recent PENDING tasks (one per source) perpetually block re-enqueue
(`scheduler_skip_active_task` for all 643 sources, `tasks_enqueued=0`). Currently masked by
the dead key, but after rotating the key the stuck PENDING tasks should be cleared/expired or
re-enqueue may not resume cleanly.

### Recommended Fix
1. Rotate the EODHD key via the gitops `env/dev` source-of-truth (same procedure as the
   prior DeepInfra rotation) and redeploy content-ingestion.
2. Clear/expire the stuck `pending` content-ingestion tasks so the scheduler re-enqueues.
3. **Add monitoring**: alert when `max(document_source_metadata.created_at) < now() - N hours`
   (ingestion-freshness SLO) and on sustained adapter 401/403 rates. A dead third-party key
   should page, not silently empty a dashboard.

---

## Track 2 — News relevance computation is inaccurate

**Severity**: MEDIUM (correctness/quality; not an outage)
**Status**: Root cause identified (design weaknesses)

### Findings (ranked)
1. **Three divergent formulas; only one runs.** PRD §6.5 weights (0.5/0.4/0.1), the
   "single source of truth" Python fn (`application/services/relevance_score.py`), and the
   production SQL (`infrastructure/nlp_db/repositories/news_query.py:49-61`) all disagree.
   The config knobs `s6_display_weight_*` (`config.py:452`) and the Python function are **dead
   code** — only hard-coded SQL constants affect what users see. Re-tuning weights does nothing.
2. **"LLM relevance" scores *market impact* from the headline only** (title + source name; no
   body, entities, or query). Prompt: `libs/prompts/.../classification/article_relevance.py`.
   Model: `Llama-3.1-8B` (DeepInfra). Vague titles default to 0.3 → mass of identical scores.
3. **"Routing" component is ingestion triage, not relevance** (entity density, source trust,
   recency; `application/blocks/routing.py:46`). When market+llm are NULL, relevance ≈
   `0.40 × routing`.
4. **Market component structurally NULL for the freshest news** (price windows need up to
   T+5d). Breaking news is scored without the market signal. The `market>0` guard conflates
   "zero impact" with "no data".
5. **No semantic/embedding relevance** anywhere, despite `bge-large` embeddings already used
   for chunks.
6. **Coverage gap**: only MEDIUM/DEEP-tier articles get LLM-scored (30-min/batch-50 worker);
   worker has an unnecessary Ollama startup dependency on the DeepInfra path.

### Recommended Fixes (ranked)
1. Unify the formula; make SQL read the config weights (kill the dead code). *(S)*
2. Feed the LLM real context — body/lead + resolved entities; separate "relevance" from
   "market impact". *(M)*
3. Add an embedding-similarity relevance signal (relevance-to-entity / -portfolio / -query). *(M)*
4. Fix NULL/degeneracy semantics (distinguish "no data" from "labelled zero"; recency prior
   for too-fresh articles). *(S)*
5. Stop using `routing.composite_score` as user-facing relevance. *(M)*
6. **Security**: the DeepInfra API key is committed plaintext in `docker.env` — Rule #8
   violation; move to a secret.

---

## Track 3 — Prediction market ingestion: wrong links + under-utilization

**Severity**: MEDIUM (UX bug + missed integration)
**Status**: Root cause identified

### TL;DR
Ingestion is **healthy** end-to-end (S4 content-ingestion adapter → Kafka `market.prediction.v1`
→ S3 market-data consumer → S9 → frontend). `market_slug` and `category` are captured, stored,
and exposed all the way to the wire. BP-147 (serializer) and BP-148 (`occurred_at` default) are
both fixed. The problems are downstream of ingestion.

### Root Cause of "the links are wrong"
Every prediction-market row links to a Polymarket **text-search** page
(`https://polymarket.com/markets?_q={title}`) instead of the canonical market — the trader
lands on a search list, not that market.

- `apps/worldview-web/lib/api/prediction-markets.ts:93` hardcodes `url: ""` (deliberately
  blanks it; comment justifies the search fallback).
- `components/dashboard/PredictionMarketsWidget.tsx:507-508` and
  `app/(app)/prediction-markets/page.tsx:192-195` fall back to the title-search URL because
  `url` is empty, and **never read `market_slug`** (which is present in the payload).
- Historical origin: PLAN-0043 (2026-04-28) abandoned `/event/{slug}` after 404s
  (Polymarket splits `/event/{slug}` grouped vs `/market/{slug}` single) and fell back to
  search globally. Slug plumbing was completed afterward but the frontend was never updated to
  use it — so the slug is dead weight today.

**Slug data is usable**: 521/525 stored slugs are clean Polymarket slugs (e.g.
`will-harvey-weinstein-be-sentenced-to-more-than-30-years-in-prison`); only **4/525** carry a
malformed numeric tail (e.g. `...-143-229-513-574-212-254`, likely grouped/multi-outcome).
(Direct HTTP verification is blocked by Polymarket's Cloudflare bot protection, not by bad data.)

### "Not fully using them" — gap analysis
Prediction markets are a read-only dashboard ornament, architecturally isolated:
1. **No KG entity linking** — market questions never routed through S6 NER; `entity_ids`/
   `tickers` hardcoded `[]` in the gateway transform. (Biggest missing integration.)
2. **No signals/alerts** on probability moves.
3. **No RAG grounding** — chat can't cite market-implied probabilities (a headline PRD-0019
   use case).
4. **Not in the morning brief.**
5. **PLAN-0056 / PRD-0033** ("Comprehensive Ingestion Wave 2": history, event groupings,
   trade flow, OI, resolution, KG linking, RAG) is **0/10 waves, never started**; its premise
   ("no consumer of `market.prediction.v1`") is now stale.
6. **`liquidity`** is stored on the snapshot row but exposed by no API schema.

### Recommended Fixes (ranked)
| # | Fix | Effort |
|---|-----|--------|
| 1 | **Fix links** — in `lib/api/prediction-markets.ts:93` set `url` from slug (`https://polymarket.com/event/{market_slug}`), keep title-search as null-slug fallback; strip/skip the 4 malformed-tail slugs. | XS |
| 2 | Verify/backfill `category` coverage (confirm migration 015 ran live). | S |
| 3 | Expose `liquidity` in S3 + S9 schemas (already stored). | S |
| 4 | KG entity linking (route questions through S6 NER → link entities; populate `entity_ids`/`tickers`). | L |
| 5 | RAG grounding (make prediction markets a retrieval source). | M |
| 6 | Probability chart view on `/prediction-markets` (history API exists). | M |
| 7 | Re-scope or formally close stale PRD-0033/PLAN-0056. | XS (doc) |

---

## Compounding / Prevention

- **New monitoring gap (both Track 1 & 2)**: third-party API key death (EODHD 401, prior
  DeepInfra revocation) silently degrades user-facing features. Add an ingestion-freshness SLO
  alert and adapter auth-failure alerting.
- **Anti-pattern (Track 2)**: a "single source of truth" config/function that no live code
  path reads — silent tuning failure. Worth a BUG_PATTERNS entry.
- **Anti-pattern (Track 3)**: data captured + stored + exposed but never consumed downstream
  (slug, liquidity) — "plumbed but unused". Worth a BUG_PATTERNS entry.
