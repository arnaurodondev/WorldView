# QA — Data Integrity & API Returns (Live)

**Date:** 2026-06-30 (probed 2026-07-01 UTC)
**Scope:** Read-only live QA. Verify DB data integrity and that key API endpoints return correct, non-empty data. No code/container/git changes made.
**Platform:** compose project `worldview`, all core services healthy (one exception noted §9).

> **Topology note:** `nlp_db`, `intelligence_db`, `kg_db` live on **`worldview-postgres-intelligence-1`**. `content_store_db`, `market_data_db`, etc. live on **`worldview-postgres-1`**. The `*_orphan_20260622` DBs on `postgres-1` are stale copies — ignore them.

---

## Verdict

- **Data at rest is healthy and fresh.** News ingestion, prediction markets, and temporal events are all current (contradicts the 06-25 EODHD dead-key halt — **resolved**).
- **Two real API-layer defects found in the FTS search path** (both HIGH): the endpoint (a) times out end-to-end on the `news` scope, and (b) returns citations with **null title/url/date/entity facets** despite the data existing in the DB, due to a silently-swallowed 401 on internal enrichment calls.
- Two MEDIUM data-completeness gaps (empty `source_name` everywhere; SEC/newsapi have no structured title).

---

## 1. FTS source_type fix — VERIFIED at DB level

`nlp_db.document_source_metadata` (dsm), 54,565 rows. Real literals dominate:

| source_type | count | | source_type | count |
|---|--:|---|---|--:|
| eodhd_ticker_news | 18,629 | | eodhd_news (legacy) | 276 |
| eodhd | 16,016 | | finnhub_news (legacy) | 126 |
| finnhub | 14,577 | | sec_10k / 10q / 8k | 14 / 5 / 12 |
| sec_edgar | 4,503 | | earnings_transcript | 21 |
| newsapi | 327 | | tenant_upload | 6 |

- **`sec_edgar` FTS works:** direct S6 `GET /api/v1/search/documents?q=filing&source_type=sec_edgar` → **200, total=1659**. The fix (mapping `sec_edgar` scope to the real literal) returns thousands of matchable rows.
- **`sec_edgar` URLs are clean:** 4503/4503 have real `https://www.sec.gov/Archives/edgar/...` URLs, **0 empty**.
- The `news` scope maps to a large OR of eodhd/finnhub/newsapi literals (~50k rows) — matchable at DB level, but see §2 for the endpoint timeout.

---

## 2. HIGH — FTS `/v1/search` is too slow; `news` scope 503s end-to-end

`GET /v1/search` (gateway → S6 `/api/v1/search/documents`) latencies:

| query | result | latency |
|---|---|--:|
| `q=Apple` (no filter) | 200, total=2481 | **18.7 s** |
| `q=filing&source_type=sec_edgar` | 200, total=1659 | **16.2 s** |
| `q=earnings&source_type=news` | **503 "Search backend unavailable"** | 30.5 s (gateway httpx timeout) |

- The chunk-FTS query over `nlp_db` is inherently slow (16–19 s even for narrow queries). The `news` scope pushes it past the **gateway proxy's ~30 s httpx timeout**, surfacing to the user as `503`. No S6 upstream completion line appears in gateway logs for the `news` request → the proxy client timed out, not an S6 error.
- **Impact:** the `news` document-search scope is broken end-to-end via the gateway even though the data is present. Even the working scopes are far too slow for interactive use.
- **Severity: HIGH** (user-facing 503 + unusable latency).

---

## 3. HIGH — FTS results have null title / url / published_at / entity facets (silent 401)

Search results return `title=null, source_url=null, published_at=null, entity_hits=[]` for docs that **do** have those fields in dsm. Verified 4 result doc_ids (finnhub/eodhd_ticker_news/sec_edgar) — all have `url` + `published_at` (and title, except sec_edgar) populated in dsm, yet the endpoint returned them null.

**Root cause (traced):**
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/document_search.py:212-215` deliberately sets `title=None, source_url=None, published_at=None` in the repo, deferring to an enrichment step — **even though the same query already `LEFT JOIN`s dsm** and could select `dsm.url / dsm.title / dsm.published_at` directly.
- The use case (`application/use_cases/search_documents.py`) enriches via **S5 `POST /api/v1/documents/batch`** (titles/urls) and **S7 `POST /api/v1/entities/batch`** (entity names), each with a 2 s timeout and graceful fallback.
- **Both calls return 401** in the live path. S6 logs (repeated):
  - `s5_batch_non_200 status_code=401 url=http://content-store:8005/api/v1/documents/batch`
  - `s7_batch_non_200 status_code=401 url=http://knowledge-graph:8007/api/v1/entities/batch`
  - Cause: `Missing X-Internal-JWT header` — the internal batch clients aren't presenting a valid internal JWT. The 401 is swallowed (warning only) → fields fall back to null.

**Impact:** every FTS-derived citation lacks title, URL, publish date, and entity facets — i.e. search citations are unusable for grounding/linking. This is the classic **silent-failure / audit-return-not-persisted** pattern (non-200 downgraded to a warning, endpoint still returns 200).
**Severity: HIGH.** (Contrast: `/v1/news/top` and entity-news read title/url straight from dsm and are citation-complete — see §6.)

---

## 4. MEDIUM — `source_name` is empty for 100% of the dominant sources

In dsm, `source_name` is NULL/empty for **all** high-volume types:

| source_type | rows | empty source_name |
|---|--:|--:|
| eodhd_ticker_news | 18,629 | 18,629 (100%) |
| eodhd | 16,016 | 16,016 (100%) |
| finnhub | 14,577 | 14,577 (100%) |
| sec_edgar | 4,503 | 4,503 (100%) |
| newsapi | 327 | 327 (100%) |

Only the small legacy types (`eodhd_news`, `finnhub_news`, `financial`) carry `source_name` — and those instead have **empty `url`**. `/v1/news/top` likewise returns `source_name: null`. Citations therefore have no human-readable publisher/source label; the frontend must derive one from `source_type`.
**Severity: MEDIUM** (data completeness; degrades citation display, not correctness).

---

## 5. MEDIUM — SEC EDGAR & newsapi have no structured title; form_type absent

- `sec_edgar`: **title empty for all 4503** dsm rows (and 6438/6438 in `content_store_db.documents`). newsapi: 602/602 empty title in content_store. So SEC/newsapi citations render with an empty title.
- **`form_type` (10-K/10-Q/8-K) is genuinely absent as structured data.** Only ~31 docs carry a `sec_10k/sec_10q/sec_8k` source_type; the 4503 bulk are generic `sec_edgar` with the form recoverable only by parsing the EDGAR URL/accession. Confirms the known follow-up — form classification is not queryable.
**Severity: MEDIUM.**

---

## 6. Prediction markets — HEALTHY

`market_data_db.prediction_markets`: **526 rows, 0 empty `market_slug`, 526 distinct slugs**, all high-quality (e.g. `will-ro-khanna-win-the-2028-democratic-presidential-nomination`). Fresh (`updated_at` max 2026-07-01 04:45). Snapshots: **1,425,072 rows**, newest `2026-07-01 04:44`.

Categories (open markets): sports 277, politics 182, **null 60**, crypto 7.

- **MINOR:** `prediction_markets.last_snapshot_at` is **NULL for all 526 rows** despite 1.4M snapshots existing — the denormalized column is never backfilled (use the snapshots table for freshness, not this column).
- **MINOR:** 60 markets have `category = null`.
- All 526 are `resolution_status='open'` (0 resolved) — plausible, not flagged.

**API:** `/v1/signals/prediction-markets?limit=5` → 200, 5 items with slugs; `/v1/signals/prediction-markets/categories` → 200, 4 categories. Good — slugs are present for the chat tool URLs.

---

## 7. temporal_events / earnings — HEALTHY & FRESH

`intelligence_db.temporal_events`:

| event_type | count | newest active_from | created last 7d |
|---|--:|---|--:|
| corporate (earnings) | 15,946 | 2026-07-15 | 568 |
| macro | 2,696 | 2026-07-06 | 334 |
| regulatory | 435 | 2026-06-29 | 40 |

- **Earnings are NOT stale** — 568 corporate events created in the last 7 days, forward-dated to 2026-07-15. The EODHD-quota staleness concern does not currently apply.
- **NOTE:** only 3 of the 7 allowed `event_type`s are populated — **no `geopolitical`, `sanctions`, `natural_disaster`, or `other`** events exist. Worth confirming those extractors are wired (not a data-corruption issue).

---

## 8. News ingestion freshness — HEALTHY (EODHD halt resolved)

`content_store_db.documents` newest ingest per source:

| source_type | newest ingest | ingested last 3d |
|---|---|--:|
| eodhd | 2026-07-01 04:50 | 2,954 |
| finnhub | 2026-07-01 04:42 | 2,190 |
| eodhd_ticker_news | 2026-07-01 04:31 | 4,240 |
| newsapi | 2026-07-01 04:29 | 94 |
| sec_edgar | 2026-06-30 23:27 | 623 |

All sources ingested within the last hour. The 2026-06-25 EODHD dead-key halt (per prior investigation notes) is **resolved** — ingestion is flowing across all providers.

---

## 9. API endpoint probe summary

Probed via gateway `worldview-api-gateway-1:8000` with a dev JWT (`POST /v1/auth/dev-login`), python-urllib inside the container.

| Endpoint | Status | Data |
|---|---|---|
| `GET /v1/news/top` | 200 | 5 articles; title/url/published_at set; **source_name null** |
| `GET /v1/signals/prediction-markets` | 200 | 5 items; slugs present |
| `GET /v1/signals/prediction-markets/categories` | 200 | 4 categories |
| `GET /v1/dashboard/snapshot` | 200 | all 6 legs present (news/heatmap/prediction_markets/earnings_calendar/alerts/morning_brief) |
| `GET /v1/search?...&source_type=sec_edgar` | 200 (16 s) | total=1659, but **null title/url** (§3) |
| `GET /v1/search?...&source_type=news` | **503** | timeout (§2) |
| S6 direct `GET /api/v1/search/documents?q=Apple` | 200 (18.7 s) | total=2481, **null title/url** (§3) |

**Infra note (out of scope):** `worldview-alert-intelligence-consumer-1` is reporting **unhealthy** — not investigated here.

---

## Findings by severity

| # | Severity | Finding |
|---|---|---|
| §2 | **HIGH** | `/v1/search` `news` scope 503s (gateway 30 s timeout); all FTS queries 16–19 s — unusable latency |
| §3 | **HIGH** | FTS results have null title/url/published_at/entity_hits; S5+S7 batch enrichment returns 401, silently swallowed. Data exists in dsm and could be selected directly |
| §4 | MEDIUM | `source_name` 100% empty for all dominant source types (dsm + news/top API) |
| §5 | MEDIUM | SEC EDGAR + newsapi have no structured title; `form_type` (10-K/Q/8-K) not queryable |
| §6 | MINOR | `prediction_markets.last_snapshot_at` NULL for all rows; 60 markets null category |
| §7 | MINOR | Only 3 of 7 `temporal_events` types populated (no geopolitical/sanctions/disaster/other) |

**No data corruption found.** The DB layer is sound and fresh; the actionable defects are in the FTS API path (§2, §3).
