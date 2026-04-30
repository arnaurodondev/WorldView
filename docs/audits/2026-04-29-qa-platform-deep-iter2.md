# Worldview Platform Deep QA — Iteration 2

**Date**: 2026-04-29
**Branch**: `feat/content-ingestion-wave-a1`
**Iter-1 ref**: `docs/audits/2026-04-29-qa-platform-deep-iter1.md`
**Fix commits verified**: `b4d247d9`, `e63bb9e2`, `c4b5903a`, `b2329f67`

---

## Verification table — every iter-1 finding

| Finding | Iter-1 Severity | Status | Evidence |
|---|---|---|---|
| F-DP1-01 KG ON CONFLICT | BLOCKING | **CLOSED** | `kg-service-group-enriched` lag=0 across 12 partitions; no tracebacks in last 200 log lines; `events`=2, `claims`=2 |
| F-DP1-02 (already labelled internal in iter-1) | – | (n/a) | – |
| F-DP1-03 fundamentals snapshot | CRITICAL | **CLOSED** | 31 rows; `eps_ttm` 30/31, `beta` 30/31, `free_cash_flow` 28/31; API returns full payload incl. eps_ttm=7.89, beta=1.109 for AAPL |
| F-DP1-04 sentiment + impact_score | CRITICAL | **PARTIAL** | sentiment 50/3018 ✓, llm_relevance 50/3018 ✓, **impact_score still 0/3018** (all NULL — see F-DP2-01) |
| F-DP1-05 alerts.title backfill | CRITICAL | **CLOSED** | 56/56 alerts have title and signal_label |
| F-DP1-06 prediction_markets.category | MAJOR | **OPEN (regression)** | 521 rows, all category=NULL; consumer dead-lettering 100% of new messages on schema mismatch (see F-DP2-02) |
| F-DP1-07 dead nlp-pipeline-article-consumer | MAJOR | **CLOSED** | only `nlp-pipeline-group` and `nlp-watchlist-group` remain; orphan group deleted |
| F-DP1-08 schema-registry portfolio.events.v1 | MAJOR | **CLOSED** | per-event-type subjects exist (`portfolio.events.v1-holding.changed`, `…-portfolio.created`, etc.); recent POSTs (14:42, 14:49) returned 200; no 409s in last 5 min |
| F-DP1-09 doc fix | DOC | **CLOSED** | annotations applied per commit `c4b5903a` |
| F-DP1-10 quotes.prev_close | MAJOR (deferred) | **DEFERRED** | watchlist insights still returns `change_pct: null` for all movers — explicitly documented |
| F-DP1-11 producer-side polymarket category | MAJOR | **CLOSED** | confirmed in commit `e63bb9e2`; outbox publishing market.prediction.snapshot events at high rate (visible in dispatcher logs) |
| F-DP1-12 article_impact_windows | MAJOR (deferred) | **DEFERRED** | 0 rows; `worldview-nlp-pipeline-price-impact-worker-1` still emitting 401 Unauthorized to `market-data:8003/api/v1/market-data/ohlcv/...` (JWT signing gap, documented) |
| F-DP1-13 orphan kg-instrument-group | MAJOR | **CLOSED** | `kg-instrument-group` no longer present; `kg-service-group-instrument` (the legitimate sibling) lag=0 |
| F-DP1-14 content-store-consumer lag | MAJOR | **CLOSED** | all 12 partitions lag=0 (one transient lag=1 observed) |
| F-DP1-15 doc fix | DOC | **CLOSED** | applied in `c4b5903a` |
| F-DP1-16 frontend min-h-[200px] | MINOR | **PARTIAL** | still present in `apps/worldview-web/components/portfolio/PortfolioAnalyticsSection.tsx:143` and `:171` (centred flex with empty state, so iter-1 acceptance criterion *is* met for those cases — borderline pass). See F-DP2-03. |
| F-DP1-17 /watchlists /news /screen 404 | MINOR | **OPEN** (deploy gap) | source files exist (`apps/worldview-web/app/(app)/{watchlists,news,screen}/page.tsx`) but **frontend container is stale**: started 14:16:30 UTC, fix commit `c4b5903a` at 14:46 UTC. All 3 routes still return 404 in the running platform. See F-DP2-04. |
| F-DP1-18 doc fix | DOC | **CLOSED** | – |
| F-DP1-19 kafka rebalance race | DOC | **CLOSED** | annotation applied |
| F-DP1-20 route doc drift | DOC | **CLOSED** | annotation applied |

Closed: 14 of 20  •  Partial: 2 of 20 (F-DP1-04, F-DP1-16)  •  Open: 1 of 20 (F-DP1-17, deploy gap)  •  Documented-deferred: 2 of 20 (F-DP1-10, F-DP1-12)  •  Newly-broken: 1 (F-DP1-06)

---

## NEW or PARTIAL findings

### F-DP2-01
- **Severity**: MAJOR
- **Iter-1 ref**: F-DP1-04 (PARTIAL)
- **File/Container**: `worldview-nlp-pipeline-relevance-scoring-1`, `nlp_db.document_source_metadata`
- **Confidence**: HIGH
- **Issue**: The iter-1 fix populated `sentiment` (50/3018) and `llm_relevance_score` (50/3018), but `impact_score` is still 0/3018 across **every** sentiment bucket (positive=7, neutral=33, negative=10 — all `impact_score IS NULL`). The relevance scoring worker is writing sentiment but not impact_score.
- **Evidence**:
  ```
  total | w_sent | w_imp | w_llm
   3018 |     50 |     0 |    50
  ```
  ```
  sentiment | count | min | max | avg     (impact_score)
  negative  |    10 |     |     |
  positive  |     7 |     |     |
  neutral   |    33 |     |     |
  ```
  Worker logs show `articles_scored: 50` per cycle — so the path is running, but the impact_score field of the prompt response is either being ignored, miskeyed, or the LLM isn't returning it.
- **Suggestion**: inspect `ArticleRelevanceScoringWorker._build_prompt` and the response parser; verify the JSON schema sent to Llama-3.1-8B asks for `impact_score` and the parser writes it back. May also be a column name mismatch in the UPDATE statement.

### F-DP2-02
- **Severity**: BLOCKING
- **Iter-1 ref**: F-DP1-06 (regression)
- **File/Container**: `worldview-market-data-prediction-market-consumer-1`, `infra/kafka/schemas/market.prediction.v1.avsc`, `services/content-ingestion/src/content_ingestion/infrastructure/messaging/schemas/market.prediction.v1.avsc`
- **Confidence**: HIGH
- **Issue**: The iter-1 producer-side fix added `category` to the **content-ingestion** local Avro schema (17 fields, no `market_slug`), and registered that as schema-registry version 5 (id=31). But the consumer's local schema at `infra/kafka/schemas/market.prediction.v1.avsc` has 18 fields (it includes a stale `market_slug` field that was never registered with the producer). The consumer ignores the schema_id in the wire-format header and reads the message with its own (different-shape) local schema. Decoding fails at the byte where `market_slug` is expected but `category` was written → 100% dead-letter rate on every new Polymarket message; `prediction_markets.category` will never populate from this consumer path.
- **Evidence**:
  - Wire format of message at offset 36435: `00 00 00 00 1f` (Confluent magic + schema_id 31 = registry v5).
  - Schema-registry v5 (id=31): 17 fields, has `category`, **no** `market_slug`.
  - `infra/kafka/schemas/market.prediction.v1.avsc` (read by consumer): 18 fields, has both `market_slug` and `category`, in that order.
  - `services/content-ingestion/src/content_ingestion/infrastructure/messaging/schemas/market.prediction.v1.avsc` (used by producer to register): 17 fields, no `market_slug`. Matches registry v5.
  - Consumer logs (continuous):
    ```
    deserialization failed: 'utf-8' codec can't decode byte 0x84 in position 98: invalid start byte
    event: kafka_message_dead_lettered
    ```
  - Schema-registry version history:
    - v3 (id=24): 17 fields with market_slug, no category
    - v4 (id=30): 18 fields with both
    - v5 (id=31): 17 fields with category, **no** market_slug ← the iter-1 producer downgraded it
- **Suggestion**: Two options:
  1. Make `infra/kafka/schemas/market.prediction.v1.avsc` field-for-field identical to `services/content-ingestion/.../schemas/market.prediction.v1.avsc` (drop the orphan `market_slug` field). This is the canonical fix and makes the local schema match what was actually registered.
  2. Better: have the consumer fetch the schema-by-id from the schema-registry at deserialize time (using the wire-format header's id) instead of trusting a local copy. This eliminates this entire class of bug platform-wide.

  Note: this regression also broke any pre-existing consumer behaviour that may have been reading older messages successfully — pre-iter-1 the consumer was never producing rows with `category` filled in, but it *was* writing rows with `category=NULL`; now it dead-letters everything, so even the NULL-category path is dead.

### F-DP2-03
- **Severity**: NIT
- **Iter-1 ref**: F-DP1-16 (PARTIAL)
- **File/Container**: `apps/worldview-web/components/portfolio/PortfolioAnalyticsSection.tsx`
- **Confidence**: HIGH
- **Issue**: Two `min-h-[200px]` panels remain, but each is wrapped in `flex items-center justify-center` and hosts an empty-state child. This technically meets the iter-1 acceptance criterion ("flex centering with empty state") so this can be considered closed — flagging as NIT for clarity.
- **Evidence**: `PortfolioAnalyticsSection.tsx:143` and `:171` — both use `min-h-[200px] bg-card border border-border rounded-[2px] p-2 flex items-center justify-center`.
- **Suggestion**: leave as-is or replace with `min-h-fit` once empty states render their own content. No action required to ship.

### F-DP2-04
- **Severity**: MAJOR
- **Iter-1 ref**: F-DP1-17 (OPEN — deploy gap)
- **File/Container**: `worldview-worldview-web-1`
- **Confidence**: HIGH
- **Issue**: The redirect stub pages added in commit `c4b5903a` (`/watchlists`, `/news`, `/screen` → workspace/alerts/screener) exist in the source tree but the running frontend container is older than the commit — its image was built before the stubs were added. All three routes still return 404 in the live platform.
- **Evidence**:
  - `git show c4b5903a:apps/worldview-web/app/(app)/watchlists/page.tsx` exists and is correct.
  - `docker inspect worldview-worldview-web-1 --format '{{.State.StartedAt}}'` → 2026-04-29T14:16:30Z.
  - `git log -1 --format='%ai' c4b5903a` → 2026-04-29 14:46Z (CEST 16:46) → image is ~30 minutes older than the fix commit.
  - `curl -sI http://localhost:3001/watchlists` → `HTTP/1.1 404 Not Found` (and same for `/news`, `/screen`).
- **Suggestion**: rebuild and recreate the `worldview-web` container: `docker compose build worldview-web && docker compose up -d worldview-web`. After restart, all three routes should 307-redirect to canonical surfaces.

### F-DP2-05
- **Severity**: MAJOR
- **Iter-1 ref**: NEW
- **File/Container**: `worldview-content-store-consumer-1`
- **Confidence**: HIGH
- **Issue**: One traceback observed: `ObjectNotFoundError: Object not found: bucket='worldview-bronze', key='content-ingestion/finnhub/3995d2.../raw/v1.json'`. The consumer is being asked to process a `content.article.raw.v1` event whose MinIO bronze object was never written (or was deleted). The consumer's behaviour on missing-object — retry, dead-letter, or log+skip — needs verification; one error in 200 lines is low-volume but should not be a hard exception/traceback.
- **Evidence**: `worldview-content-store-consumer-1` logs at 14:51:12.939 contain a full traceback through `process_article.py:139 → minio_bronze.py:26 → s3_adapter.py:129`.
- **Suggestion**: in `ProcessArticleUseCase.execute`, catch `ObjectNotFoundError` explicitly: log a warning with article_id+bronze_key and either dead-letter the event or skip. This is unrelated to iter-1 but surfaced during the rescan.

---

## Track 2 — Container scan

Scan of `--tail 200` logs across 59 worldview containers found errors only in:
1. `worldview-content-store-consumer-1` — 1 NoSuchKey traceback (F-DP2-05).
2. `worldview-postgres-1` — 1 FATAL: `database "market_data" does not exist` from a query that hit the wrong DB name (likely my own first verification call, not platform-internal). No follow-up errors.
3. `worldview-market-data-prediction-market-consumer-1` — continuous dead-letter (F-DP2-02).

Otherwise the 56 remaining containers are clean.

## Track 3 — Endpoint health

| Endpoint | Result |
|---|---|
| `GET /v1/news/top` | ✓ 200, sentiment populated for first 50 articles, impact_score still null (F-DP2-01) |
| `GET /v1/fundamentals/{id}/snapshot` | ✓ 200, AAPL returned eps_ttm=7.89, beta=1.109, fcf=51.5B |
| `GET /v1/alerts/history` | ✓ 200 (empty for dev tenant — alerts in DB belong to `tenant_id IS NULL`; not a bug, expected dev-login isolation) |
| `GET /v1/signals/prediction-markets?category=politics` | ✓ 200, returns 0 (DB has no category populated — see F-DP2-02) |
| `GET /v1/feedback/submissions?mine=true` | ✓ 200, returns 1 redacted record |

## Track 4 — Kafka health

All 30+ consumer groups have lag=0 across all partitions (verified with `--all-groups` filter). One ephemeral lag=1 on `content-store-consumer` partition 3 (transient). No groups with LAG>100. Consumer group inventory matches expected (24 active, no orphans).

## Track 5 — Regression hunt

1. **schema-registry portfolio dispatcher**: NOT BROKEN. Recent POSTs (14:42, 14:49) returned 200; per-event-type subjects working. F-DP1-08 fix is sound.
2. **polymarket category change**: BROKE THE CONSUMER (F-DP2-02 above). The iter-1 fix to register a 17-field schema (no market_slug) created a wire-shape mismatch with the consumer's 18-field local schema.
3. **alerts.title backfill duplicates**: NOT INTRODUCED. 56 alerts, 56 distinct dedup_keys, no duplicates from the backfill.
4. **KG ON CONFLICT change**: clean — no test-suite or runtime regressions observed; consumer is healthy.

---

## Verdict

**NEEDS-FIXES**

Specific items required before SHIP:

1. **F-DP2-02 (BLOCKING)**: reconcile `infra/kafka/schemas/market.prediction.v1.avsc` with `services/content-ingestion/.../schemas/market.prediction.v1.avsc` — either drop the orphan `market_slug` field from the consumer's schema or migrate the consumer to schema-by-id lookup. Without this, `prediction_markets.category` will never populate and 100% of Polymarket messages dead-letter.
2. **F-DP2-04 (MAJOR)**: rebuild `worldview-web` container so the F-DP1-17 redirect stubs go live (`/watchlists`, `/news`, `/screen` currently still 404).
3. **F-DP2-01 (MAJOR)**: investigate why `ArticleRelevanceScoringWorker` writes `sentiment` + `llm_relevance_score` but **not** `impact_score`. The iter-1 fix only restored 2 of 3 columns.
4. **F-DP2-05 (MAJOR)**: handle `ObjectNotFoundError` gracefully in `ProcessArticleUseCase` so missing-bronze events don't surface a traceback.

Documented-deferred items (acceptable):
- F-DP1-10 (`quotes.prev_close` → null `change_pct` in watchlist insights)
- F-DP1-12 (`article_impact_windows` empty due to worker→market-data 401 JWT signing gap)
