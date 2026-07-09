# Investigation Report: Enhancing the Platform with Prediction-Market (Polymarket) Data

**Date**: 2026-07-09
**Investigator**: Claude (investigate skill)
**Severity**: N/A (strategic / roadmap investigation, not a defect)
**Status**: Complete — current state mapped, gap analysis + integration options produced

## 1. Issue Summary

Investigate (a) what current PRDs/plans exist to enhance the platform with prediction
data, (b) what data we could extract from Polymarket beyond what we capture today, and
(c) how that data could be integrated across the platform. This is a scoping/roadmap
investigation, not a bug hunt.

## 2. Executive Answer

- **Wave 1 is SHIPPED**: PRD-0019 / PLAN-0019 (base Polymarket ingestion) is complete and
  live — snapshot ingestion, TimescaleDB time-series storage, S3/S9 read APIs, a chat
  tool, dashboard widget, and a dedicated `/prediction-markets` page.
- **Wave 2 is WRITTEN BUT DORMANT**: PRD-0033 / PLAN-0056 ("Comprehensive Ingestion")
  is the *existing plan to enhance the platform with prediction data*. It is **DRAFT,
  0/10 waves, never started**, and some of its premises are now stale (it assumes "no
  consumer of `market.prediction.v1`", which is false — S3 consumes it).
- **The real gap is not ingestion, it's activation**: prediction markets are a
  read-only dashboard ornament. They are **NOT** linked to KG entities/tickers, **NOT**
  in alerts/signals, **NOT** in the morning brief, and we capture only the Gamma API
  *metadata snapshot* — not order-book depth, tick history, trades, or open interest.

## 3. Existing PRDs & Plans (status)

| ID | Title | Status | What it is |
|----|-------|--------|-----------|
| **PRD-0019** | Polymarket Prediction Markets Integration | Draft → delivered | Base ingestion + read UI |
| **PLAN-0019** | (impl of 0019) | ✅ **COMPLETE** 2026-04-09 (6/6 waves) | S4 adapter → Kafka → S3 → S9 → frontend + EDGAR market-hours fix |
| **PRD-0033** | Polymarket **Comprehensive** Ingestion (Wave 2) | 📋 **DRAFT** (ready for /plan) | History, events, trades, OI, NER→KG linking, RAG grounding |
| **PLAN-0056** | (impl of 0033) | 📋 **DRAFT — 0/10 waves, never started** | 4 new adapters, 6 partitioned S7 tables, 5 consumers, 7 APIs, S9 proxies |
| **PLAN-0068** | Earnings Calendar + PM Category Fix | ✅ **COMPLETE** 2026-05-05 | Category backfill (102 markets recategorized) + `/prediction-markets` page |

**Bottom line for the user's question:** the plan to enhance the platform with
prediction data already exists — it is **PRD-0033 / PLAN-0056**. It needs a
`/revise-prd` pass (stale premises) before `/plan`/`/implement`, and it should be
re-scoped to prioritize *activation* (KG/alerts/brief) over raw data volume.

## 4. What Data We Capture Today vs. What Polymarket Offers

We currently poll **only the public Gamma API** (`gamma-api.polymarket.com`, no auth) —
a snapshot of market *metadata*. We do **not** touch the two richer Polymarket APIs.

### 4.1 Captured today (Gamma API snapshot → Kafka `market.prediction.v1`)

Fetched fields (`PredictionMarketFetchResult.from_gamma_response`):
`market_id` (conditionId), `question`, `description`, `outcomes[{name, token_id, price}]`,
`volume_24h`, `liquidity`, `close_time` (endDate), `resolution_status` (open/resolved/
cancelled), `resolved_answer`, `market_slug`, `category` (normalized to
politics/crypto/sports/macro/general).

Stored across two tables:
- `prediction_markets` — current state, one row/market (outcomes JSONB **without** prices)
- `prediction_market_snapshots` — TimescaleDB hypertable, one row per `(market_id,
  snapshot_at)`; **prices live here** (`outcomes_prices` dict), plus `volume_24h`,
  `liquidity`. This is a genuine time-series (7-day chunks, compress @30d).

Exposed: `GET /prediction-markets`, `/{id}`, `/{id}/history`, `/categories`.

### 4.2 Available from Polymarket but NOT captured

| Source | Data | Value it unlocks |
|--------|------|------------------|
| **CLOB API** `/prices-history` | True per-outcome price history (1h/1d/1w) with indefinite retention | Probability charts that don't depend on our polling density; backfill of history that predates our ingestion |
| **CLOB API** order book | Bid/ask spread, depth | Signal quality / market confidence; `liquidity` alone is coarse |
| **Data API** `/trades` | Anonymous fills (price, size, time) | Order-flow / momentum signals; "smart money" moves |
| **Data API** `/oi` | Daily open interest per market | Conviction/positioning metric distinct from 24h volume |
| **Gamma** `/events` | Event groupings (e.g. "2028 US Election" → per-candidate children) | Related-market discovery; cleaner UX; `groupItemSlug` is currently parsed then discarded |
| **Gamma** full `tags[]` | Rich multi-tag categorization | Better categorization than the single normalized bucket |
| **Gamma** `createdAt` | Market creation time | Market-age / adoption curves |

Note: **`liquidity` is already stored on the snapshot row but exposed by no API schema**
— a zero-cost win (plumbed-but-unused).

## 5. Integration Map — Where Prediction Data Is (and Isn't) Wired

| Surface | Integrated? | What it does | Gap |
|---------|-------------|--------------|-----|
| S4 ingestion → Kafka → S3 | ✅ Healthy | Snapshot pipeline | Only S3 consumes the topic |
| S9 gateway | ✅ Proxy only | 4 read routes + dashboard snapshot leg | `entity_ids`/`tickers` hardcoded `[]` |
| Frontend | ✅ Read-only | Dashboard widget (top 5), `/prediction-markets` page, category pills, canonical `/event/{slug}` links (wrong-link bug fixed 2026-06-30) | Display only; no history chart on the page |
| Chat / RAG | ✅ Tool exists | `get_prediction_markets` returns odds/URL/volume as a retrieval source | Residual **phantom-citation refusal** (probabilistic; deterministic allowlist fix recommended, see §7). No `grounding_fields` on odds → eval can't substantiate them |
| **Knowledge Graph (S7)** | ❌ **NO** | — | **Biggest gap.** Questions never routed through S6 NER; a market on "Will NVDA exceed $200?" is not linked to the NVDA entity |
| **Alerts / signals** | ❌ **NO** | — | No alerting on probability moves; not a market-impact signal |
| **Morning brief** | ❌ **NO** | — | Portfolio-relevant odds never surfaced in the daily brief |

## 6. Root Cause of "Under-Utilization"

Prediction markets were ingested (Wave 1) as an isolated read-only vertical. Wave 2
(PRD-0033), which contained *all* the activation work (NER→KG linking, RAG grounding,
history, events, trades, OI), was drafted on 2026-04-29 and **never implemented**. The
data is "plumbed but unused" — a recognized anti-pattern in this repo (slug + liquidity
were both captured and stored long before anything consumed them).

## 7. Recommended Integration Path (ranked by leverage ÷ effort)

Ordered to maximize thesis/demo value per unit of work. Items 1–4 are small and mostly
use data we already have; 5–7 are the PRD-0033 substance.

| # | Enhancement | Uses new data? | Effort | Why |
|---|-------------|----------------|--------|-----|
| 1 | Expose stored `liquidity` in S3+S9 schemas | No (already stored) | XS | Free; unblocks depth signal in UI/chat |
| 2 | Deterministic phantom-citation allowlist (`commentary`/`analysis`/… → benign) in `numeric_grounding.py:1021` | No | XS | Kills the residual chat refusal; complements v1.11 prompt |
| 3 | Add `grounding_fields` for odds in `handlers/market.py` | No | S | Lets the value-substantiation eval verify odds %; quality/eval win |
| 4 | Probability history chart on `/prediction-markets` (history API already exists) | No | M | Turns the page from a list into an analytical surface |
| 5 | **KG entity linking** — route questions through S6 NER, populate `entity_ids`/`tickers`, add `prediction_market -[:references]-> entity` | Synthetic docs | L | **Highest strategic value.** Connects markets to portfolio/entities; enables 6 & 7 |
| 6 | Morning-brief inclusion (portfolio-relevant odds) | Needs #5 | M | Directly user-visible; strong demo moment |
| 7 | Alerts/signals on probability deltas | Needs history + #5 | M | Operationalizes the data as a signal, not an ornament |
| 8 | CLOB `/prices-history` + `/trades` + `/oi` ingestion (PRD-0033 Wave A/B) | **Yes** | L | Deeper history/order-flow; do only if #5–7 prove the data earns its keep |

**Sequencing recommendation:** don't start PLAN-0056 as written (it front-loads the
heavy 4-adapter/6-table ingestion). Instead: (i) land the XS/S wins (1–3), (ii) do KG
linking (5) as the keystone, (iii) then brief + alerts (6–7), (iv) only then decide
whether the CLOB/Data-API firehose (8) is worth the storage. This inverts PLAN-0056 to
lead with activation and treat raw-data expansion as demand-driven.

## 8. Open Questions for the User

1. **Thesis framing** — is prediction-market data meant to be a *demo surface* (charts,
   chat answers) or a *signal input* to the intelligence/KG layer? That decision picks
   between path §7-{1–4} (surface) and §7-{5–8} (signal).
2. **Do we re-scope PRD-0033** to lead with activation (recommended), or implement it
   as-drafted (ingestion-first)?
3. **CLOB/Data-API appetite** — the deeper APIs add real storage cost (~1M rows backfill
   for history alone). Worth it, or is Gamma-snapshot history sufficient?

## 9. Recommended Next Step

Run **`/revise-prd`** on PRD-0033 / PLAN-0056 to (a) purge stale premises (the
"no consumer" assumption, the already-shipped category/link fixes from PLAN-0068 and
2026-06-30), and (b) re-scope it around the activation-first sequence in §7. Then
`/plan` the revised, trimmed version.

## 10. Compounding Notes

- **Anti-pattern reinforced**: "plumbed but unused" (slug, liquidity, and now the whole
  Wave-2 dataset). Already flagged for BUG_PATTERNS in the 2026-06-28 investigation.
- **Stale-PRD risk**: PRD-0033 has drifted from reality in <3 months — supports the
  existing `/revise-prd` >2-week staleness heuristic.
