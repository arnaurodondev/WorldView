---
id: PLAN-0109
title: Platform Remediation — Stack Restoration, Silent-Failure Anti-Pattern, Ingestion + Relevance + Alpaca Pipeline Fixes
prd: none (remediation against existing PRD-0017/0026/0089/0099)
status: draft
created: 2026-06-09
updated: 2026-06-09
---

# PLAN-0109 — Platform Remediation

## Overview

This plan consolidates **all issues uncovered during the 2026-06-09 platform stability audit** and the subsequent deep-dive investigations into a single dependency-ordered remediation track.

Driving incident: at **2026-06-09 04:58:39 UTC** a single external SIGTERM event (likely `docker compose down` from a parallel session) killed 13 containers — `market-ingestion` + 3 sidecars, `content-ingestion` + 3 sidecars, and 9 nlp-pipeline workers. The `restart: on-failure` policy on those sidecars meant Docker did not revive them. Symptoms cascaded into the screener, news feed, and chat answers for ~22 hours before the audit caught it.

The investigation also surfaced multiple **pre-existing** issues that the kill merely amplified — these need fixing regardless of the kill, and several are structural rather than incidental.

PRDs the plan touches (without changing their scope):
- PRD-0017 — screener default-load behavior (S3/market-data).
- PRD-0026 — `display_relevance_score = 0.5·market + 0.4·llm + 0.1·routing` formula. Worker that produces `llm_relevance_score` is broken — fix without changing formula.
- PRD-0089 — IB-L5 intelligence rollup that depends on PRD-0026 outputs.
- PRD-0099 — S3 LATERAL JOIN screener query (already patched in commit `afde005a9`).

## Services affected
worldview-web · api-gateway · market-data · market-ingestion · content-ingestion · content-store · nlp-pipeline · portfolio · alert · rag-chat · libs/messaging · libs/observability · infra/compose · infra/prometheus · infra/grafana.

## Sub-Plans

| Plan | Title | Estimated effort | Critical-path? |
|------|-------|---|---|
| **A** | Stack restoration + OHLCV consumer revival | 0.5 d | YES — unblocks ingestion observation everywhere else |
| **B** | Relevance-scoring worker — Qwen3 enable_thinking + parse hardening | 1 d | (parallel to A) |
| **C** | News ingestion per-source remediation + structured logging | 2.5 d | depends on A |
| **D** | Alpaca 1-minute pipeline deep-dive + multi-timeframe rebuild | 3 d | depends on A |
| **E** | Article-consumer orphan-rate + stub-content quality investigation | 1 d | depends on A |
| **F** | Silent-failure refactor — compose policy, outbox error_detail, Kafka producer hardening, alerts, worker healthcheck | 5 d | independent (highest leverage; should land early) |
| **G** | `portfolio.holding.changed` deprecation gating | 0.25 d | independent |
| **H** | Investigations still requiring user discussion before implementation | — | gated on user decisions |

**Total**: ~13 dev-days assuming serial work, ~7 wall-clock days assuming parallel agents.

## Plan dependency graph

```
                  ┌─────────────┐
                  │   F (ops)   │  ← can run anytime, highest leverage
                  └──────┬──────┘
                         ↓
            ┌────────────┴────────────┐
            ↓                         ↓
┌──────────────────┐         ┌──────────────────┐
│  A (stack up)    │────→    │ B (relevance)    │
└────┬─────┬──┬────┘         └──────────────────┘
     ↓     ↓  ↓
     C     D  E
     │     │  │
     ↓     ↓  ↓
     (observability + dashboards from F-3 ride on top)
```

## Sub-Plan Index (waves are in companion files)

- [Sub-Plan A — Stack restoration](#sub-plan-a)
- [Sub-Plan B — Relevance worker fix](#sub-plan-b)
- [Sub-Plan C — News ingestion per-source](#sub-plan-c)
- [Sub-Plan D — Alpaca + OHLCV pipeline](#sub-plan-d)
- [Sub-Plan E — Article-consumer + content quality](#sub-plan-e)
- [Sub-Plan F — Silent-failure refactor](#sub-plan-f)
- [Sub-Plan G — holding.changed gating](#sub-plan-g)
- [Sub-Plan H — Items requiring user decision](#sub-plan-h)

## Reserved IDs (Phase -1 collision check, 2026-06-09)

- **PLAN-0109** — this plan (verified next free).
- **BP-655 .. BP-664** — reserved for new bug patterns documented by this work.
- **Migrations next-free per service** (filesystem-authoritative as of 2026-06-09):
  - portfolio: `0022_*` (HEAD `0021_add_transaction_trade_side.py`)
  - market-data: `036_*` (HEAD `035_add_l5b_intelligence_columns.py`)
  - market-ingestion: `0018_*` (HEAD `0017_top100_insider_market_cap.py`)
  - content-ingestion: `0010_*` (HEAD `0009_remove_finnhub_global_news.py`)
  - content-store: `0007_*` (HEAD `0006_rename_duplicate_clusters_constraint.py`)
  - nlp-pipeline: `0021_*` (HEAD `0020_entity_mentions_tenant_not_null.py`)
  - alert: `0010_*` (HEAD `0009_add_user_rule_alert_type.py`)
- No new RULES.md entries planned (the patterns enforce existing R8/R25/R27 hard rules).

---

# Sub-Plan A — Stack Restoration {#sub-plan-a}

**Goal**: bring the platform back to a 100%-running steady state, find and fix the `market-data` OHLCV consumer that was identified during live observation as having zero active consumer-group members.

**Why critical-path**: Sub-Plans C/D/E all need a running ingestion pipeline to validate their fixes. F can run in parallel since it touches compose + libs only.

## Wave A-1 — OHLCV consumer revival

**Tasks**:

### T-A-1-01: Locate the missing OHLCV consumer sidecar
- **Type**: investigation
- **Target files**: read-only (`infra/compose/docker-compose.yml`, `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py`, `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer_main.py`).
- **What to determine**:
  1. Is there a dedicated `market-data-ohlcv-consumer-1` sidecar in compose? If yes, what is its current state (`docker ps -a`)?
  2. If absent, was the consumer expected to run inside the main `market-data-1` container as a background task? If yes, why is its consumer-group empty?
- **Acceptance**: file:line citation for the consumer's entry point + an explicit verdict on whether the sidecar exists, is exited, or is missing from compose entirely.

### T-A-1-02: Bring the consumer up
- **Type**: config / ops
- **Depends on**: T-A-1-01
- **Tasks**:
  - If sidecar exists but `Created`/`Exited`: `docker compose up -d --force-recreate market-data-ohlcv-consumer market-data-fundamentals-consumer market-data-quotes-consumer market-data-prediction-market-consumer market-data-intraday-resampling-consumer` and verify all 5 reach `healthy`.
  - Verify Kafka consumer group is non-empty: `docker exec worldview-kafka-1 kafka-consumer-groups --bootstrap-server localhost:9092 --describe --group market-data-ohlcv`.
- **Acceptance**: `kafka-consumer-groups --describe` returns at least one ACTIVE MEMBER for `market-data-ohlcv` group AND lag begins decreasing in <2 min observation.

### T-A-1-03: Validate end-to-end bar landing
- **Type**: integration test (manual + scripted)
- **Depends on**: T-A-1-02
- **What to do**:
  - Trigger one Alpaca 1m batch via existing scheduler (just wait 60s).
  - Watch `ohlcv_bars` table grow: `SELECT MAX(bar_date), COUNT(*) FROM ohlcv_bars WHERE timeframe='1m';` before/after 2-min window.
  - For 5 representative crypto tickers, verify newest bar timestamp < 90s old.
- **Acceptance**: `MAX(bar_date)` advances by ≥1 minute during a 2-min observation window for ≥10 distinct instruments.

### T-A-1-04: Apply Sub-Plan F's PR-A locally to prevent recurrence (depends on F-1 landing first if F is sequenced before A; otherwise patch ad-hoc here)
- **Type**: config
- **Target**: `infra/compose/docker-compose.yml` only for the 5 market-data consumer sidecars.
- **Change**: `restart: on-failure` → `restart: unless-stopped`; `depends_on: condition: service_healthy` (on `market-data`) → `condition: service_started`.

**Validation gate**:
- [ ] All 11 market-data sidecars `Up (healthy)`
- [ ] OHLCV consumer-group lag < 10 messages after 5-min observation
- [ ] `ohlcv_bars` table received ≥30 new rows during a 5-min observation
- [ ] No `Traceback`/`ERROR` in market-data logs since restart

**Break impact**: none (config-only).
**Regression guardrails**: BP-258 (consumer registered but never started), BP-235 (httpx timeout interaction).

---

# Sub-Plan B — Relevance-Scoring Worker Fix {#sub-plan-b}

**Goal**: restore `llm_relevance_score` writes by fixing Qwen3 reasoning-mode leak, hardening the JSON parser, and emitting an alertable empty-response metric. Backfill the ~6,000 article gap.

**Why now**: zero articles scored in 7 days; PRD-0026 display formula degraded; PRD-0089 L-5b `llm_relevance_7d_max` rollup all-NULL; news tab ranking degraded.

## Wave B-1 — Worker hardening

### T-B-1-01: Layer A — disable Qwen3 thinking mode
- **Type**: impl
- **Target**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py` line ~338 in `_call_external_api`.
- **Change**: in the `json={...}` body POSTed to DeepInfra, add `"chat_template_kwargs": {"enable_thinking": False}` and bump `"max_tokens": 96` → `"max_tokens": 512`.
- **Acceptance**: unit test asserts the outgoing payload contains the new kwarg.

### T-B-1-02: Layer B — tolerate degraded responses
- **Type**: impl
- **Depends on**: T-B-1-01 (same file)
- **Change**: replace direct `json.loads(content)` with a 3-step extraction:
  1. Reject empty/None content with a `ValueError("empty_content")`.
  2. Strip `<think>...</think>` blocks with `re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL)`.
  3. Strip ```json ... ``` fences (regex `r"```(?:json)?\s*(\{.*?\})\s*```"`); fall back to greedy `r"\{.*\}"`.
- **Tests (inline with T-B-1-01/02)**:
  - `test_external_api_empty_content_returns_none_and_increments_metric`
  - `test_external_api_markdown_fenced_response_parses`
  - `test_external_api_qwen_think_prefix_stripped`

### T-B-1-03: Layer C — detect + alert
- **Type**: impl
- **Depends on**: T-B-1-02
- **Change**:
  - Add Prometheus counter `nlp_pipeline_relevance_scoring_empty_response_total{model_id, reason}` with `reason ∈ {empty_content, json_decode, missing_score}`.
  - Track `_consecutive_empty_responses` in the worker loop; if `>= batch_size // 2`, raise `RuntimeError("relevance_scoring_provider_degraded")` from `scoring_cycle` so the existing `run_forever` warning + Prometheus rule fires.
- **Tests**:
  - `test_consecutive_empty_responses_aborts_cycle`

### T-B-1-04: Prometheus rule
- **Type**: config
- **Target**: `infra/prometheus/rules/alert-rules.yml`
- **Add**: `RelevanceScoringDegraded` — `expr: increase(nlp_pipeline_relevance_scoring_empty_response_total[15m]) > 20`, `for: 5m`, severity `critical`.

## Wave B-2 — Backfill + validation

### T-B-2-01: Compute backlog size + cost estimate
- **Type**: script
- **Target**: `scripts/ops/backfill_relevance_scores.py` (NEW)
- **Behavior**: query for unscored MEDIUM/DEEP articles in last 14 days, log the count, abort if `> 20000` without `--force`.

### T-B-2-02: Run backfill against the now-healthy worker
- **Type**: ops
- **Depends on**: Wave B-1 deployed + smoke-passed.
- **Action**: the existing worker's `SELECT … WHERE llm_relevance_score IS NULL` will auto-process the backlog on its 30-min cadence; just monitor. Expected cost ~$0.05, wall-clock ~30 min for 6k articles.

### T-B-2-03: Refresh downstream
- **Type**: ops
- **Trigger**: once backlog `COUNT(*) < 100`, refresh dependent materialized views and re-run L-5b rollup for the in-window subset of instruments.

**Validation gate**:
- [ ] At least 50 articles successfully scored in the first hour after deploy
- [ ] `llm_scored_at` MAX advances within the last 30 min on every poll
- [ ] `nlp_pipeline_relevance_scoring_empty_response_total` stays flat (no further empty responses)
- [ ] L-5b `llm_relevance_7d_max` populated for ≥30 instruments after one rollup cycle

**Break impact**: none (additive behavior). Existing tests for the worker still pass.
**Regression guardrails**: feedback_audit_returned_value_persistence (worker returning diagnostics without persisting them); feedback_prompt_input_mismatch (silent drop on parse failure).

---

# Sub-Plan C — News Ingestion Per-Source Remediation {#sub-plan-c}

**Goal**: address every per-source ingestion bug surfaced by the audit AND ship structured per-source logging so silent-quota-exhaustion-style failures surface immediately.

## Wave C-1 — Critical fixes (NewsAPI + watermark + ticker-news transaction hygiene)

### T-C-1-01: NewsAPI silent-error detection + structured logging (NOT only quota)
- **Type**: impl
- **Target**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/newsapi/client.py:143`
- **Change**:
  - After `data = response.json()`, if `data.get("status") == "error"`, raise a typed `NewsAPIServerError(code=data.get("code"), message=data.get("message"))`.
  - User priority: this is NOT primarily about avoiding free-tier exhaustion (which is acceptable). It IS about making any silent-failure mode (rateLimited, parameterInvalid, apiKeyMissing, …) emit a structured `newsapi_upstream_error` log line with `code` and `message` so it appears on dashboards instead of becoming a 0-doc SUCCEEDED.
- **Tests**:
  - `test_client_raises_on_status_error_rate_limited`
  - `test_client_raises_on_status_error_parameter_invalid`
  - `test_client_succeeds_on_status_ok_empty_articles` (a real "no news today" response must NOT raise).

### T-C-1-02: Watermark always advances on successful poll
- **Type**: impl
- **Target**: `services/content-ingestion/src/content_ingestion/application/use_cases/execute_task.py:217`
- **Change**: write `last_run_at = utc_now()` **unconditionally** on a non-exception outcome (separate from `last_watermark`, which retains the `fetched > 0` gate by semantic intent).
- **Tests**:
  - `test_last_run_at_set_when_fetched_zero`
  - `test_last_watermark_unchanged_when_fetched_zero`

### T-C-1-04: Per-source API call budget audit + optimization
- **Type**: investigation + report (not impl)
- **Goal**: quantify how fast each source is burning its API quota under steady-state operation. Surface optimization opportunities (pagination depth, dedup before request, batching).
- **Method**:
  - For each of the 5 sources (newsapi, finnhub, eodhd-general, eodhd-ticker-news, sec_edgar), compute over the last 14 days: HTTP calls/day, pages-per-call, articles-per-page, articles-saved-after-dedup, articles-saved-after-routing-LIGHT-suppression.
  - Cross-reference with the documented free/paid tier quota for each source.
  - Quantify "wasted" calls: requests that returned 0 new articles after dedup; requests that drove only LIGHT-suppressed docs.
  - Identify optimization opportunities: (a) increase cursor watermark precision so we don't re-fetch known articles, (b) widen poll cadence on consistently-quiet sources (e.g. sec_edgar evening hours), (c) pre-filter by symbol watchlist before fetching where the API supports it.
- **Deliverable**: `docs/audits/2026-06-10-news-ingestion-api-budget.md` with the table + 3-5 concrete optimization recommendations sized S/M/L.
- **Acceptance**: report committed; follow-up tasks filed in TRACKING.md if any optimization is recommended at L size.

### T-C-1-03: EODHD-ticker-news transaction hygiene (R27 compliance)
- **Type**: impl
- **Target**: `services/content-ingestion/src/content_ingestion/application/use_cases/execute_task.py:159-164` and `:274-282`.
- **Change** — two options, ship both:
  1. Immediate: wrap both short-lived sessions in `try/finally: await sess.rollback()` so a pooled connection never goes back to the pool with `idle in transaction (aborted)` state.
  2. Structural: migrate the read-only `_fetch_from_source` dedup session to `ReadOnlyUnitOfWork` per R27 (currently violated; CLAUDE.md hard-rule 17).
  - Also confirm `pool_pre_ping=True` on the AsyncEngine.
- **Tests**:
  - `test_fetch_session_rollback_called_on_exit`
  - integration test: two concurrent `_execute_task` calls; second should NOT inherit aborted Tx.

## Wave C-2 — Validation deep-dives (read-only investigations, may result in follow-up tasks)

### T-C-2-01: Finnhub outage root-cause investigation
- **Type**: investigation
- **Goal**: determine whether the 2026-06-04/05 gap on all 8 Finnhub ticker sources was a Finnhub-side outage OR a code/scheduler bug we missed.
- **Method**: correlate ingestion_tasks log + scheduler logs around the 06-04 window; check Finnhub status page archives (https://status.finnhub.io/) if reachable; if external, document and add freshness alert. If internal, file a follow-up task.

### T-C-2-02: EODHD general source post-bootstrap validation
- **Type**: integration test (live)
- **Goal**: with the source created 2026-06-06, confirm it now ingests on cadence. Watch logs for 3 consecutive polls, verify docs land.

### T-C-2-03: SEC EDGAR post-bootstrap validation
- **Type**: integration test (live)
- **Goal**: identical pattern to C-2-02 for `sec-edgar-filings` source. Add the explicit "empty result window" info log T-C-3-02 suggests.

### T-C-2-04: EODHD-ticker-news live concurrency test
- **Type**: integration test (live)
- **Goal**: after Wave C-1 ships, run 50 consecutive ticker_news cycles at concurrency=2 and assert zero "Can't reconnect" errors in worker logs.

## Wave C-3 — Per-source structured logging upgrade

### T-C-3-01: Per-source "ingest cycle complete" structured event
- **Type**: impl
- **Target**: `services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py`
- **Add**: emit `content_ingestion_cycle_complete` with structured fields: `source_type`, `fetched_count`, `inserted_count`, `dedup_count`, `latency_ms`, `upstream_status_code` (when applicable). Mirrors the Alpaca pattern in market-ingestion.
- **Acceptance**: log line is queryable in Loki by `source_type` and aggregate-able to per-source ingestion rate.

### T-C-3-02: SEC EDGAR "empty window" info log
- **Type**: impl
- **Target**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/client.py`
- **Add**: when EFTS returns 0 filings in a window, emit `sec_edgar_efts_empty_response` with the window bounds. Otherwise SEC gaps look identical to bugs.

### T-C-3-03: Per-source staleness alert
- **Type**: config
- **Target**: `infra/prometheus/rules/alert-rules.yml`
- **Add**: `ContentSourceStale` — `expr: time() - max by (source_type) (content_ingestion_last_doc_timestamp_seconds) > 86400` (24h), `severity: warning`. Distinguishes "upstream outage" from "we broke it" via duration.

**Validation gate (whole sub-plan)**:
- [ ] NewsAPI client raises `NewsAPIServerError` on every error-mode response in mocked tests
- [ ] `last_run_at` advances on empty-fetch cycles
- [ ] 50 concurrent ticker_news cycles complete without "Can't reconnect"
- [ ] One full poll cycle observed for each of 5 sources with successful docs landing
- [ ] `ContentSourceStale` alert fires within 5min in a simulated outage test

**Break impact**: API-shape change for `NewsAPIServerError` (was silently swallowed). Update content-ingestion integration tests.

---

# Sub-Plan D — Alpaca + OHLCV Pipeline {#sub-plan-d}

**Goal**: validate and harden the OHLCV producer/consumer flow end-to-end. Implement the user's intended design: batch 1000 instruments via Alpaca's bulk-bars endpoint, ingest into 1-minute table, then **recompute** higher-timeframe bars (5m, 15m, 1h, 4h, 1d, 1w, 1M) from the 1m source rather than fetching them separately.

## Wave D-1 — Worker priority + fair-share scheduling

**User clarification needed (Sub-Plan H, item H-1):** the audit observed "worker priority starvation" — after 46 Alpaca 1m tasks completed in the first tick, the single worker pivoted to EODHD daily/weekly/monthly batches and the remaining ~600 Alpaca 1m policies never ran that tick. All 649 policies share `priority=20`. The user's stated design intent is that Alpaca 1m runs continuously; lower-cadence EODHD timeframes should NOT preempt it. Decide one of:

- (a) Reserve a dedicated worker slot for `provider='alpaca' AND timeframe='1m'`.
- (b) Round-robin / fair-share at the scheduler level.
- (c) Raise Alpaca-1m priority above all other ingest types.

Pending user decision before tasks below are written in detail.

### T-D-1-01: Decide scheduling strategy (gated on H-1)
### T-D-1-02: Implement chosen strategy
### T-D-1-03: Test 5-minute window — assert all enabled 1m policies ran ≥1 cycle

## Wave D-2 — Bulk Alpaca batching

### T-D-2-01: Audit current batch sizing
- **Type**: investigation
- **Target**: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/alpaca.py`
- **What to determine**: does the adapter use Alpaca's bulk endpoint `/v2/stocks/bars?symbols=AAPL,MSFT,...` with up to 1000 symbols per call? Or does it currently iterate per-symbol?

### T-D-2-02: Implement bulk batching (if absent)
- **Type**: impl
- **Target**: same adapter file
- **Change**: batch up to 1000 symbols per HTTP request to Alpaca's bars endpoint; split universe into ⌈N/1000⌉ batches per tick.

## Wave D-3 — Multi-timeframe recomputation

### T-D-3-01: Design intraday-resampling consumer behavior
- **Type**: impl (likely already exists — needs audit first)
- **Target**: `services/market-data/src/market_data/infrastructure/messaging/consumers/intraday_resampling_consumer.py` (already in compose at line 978).
- **Change**:
  - On every new 1m bar (or batch of 1m bars), recompute the affected `5m`, `15m`, `1h`, `4h`, `1d`, `1w`, `1M` bars for that instrument by re-aggregating from `ohlcv_bars` where `timeframe='1m'`.
  - Use Timescale `time_bucket('5 minutes', bar_date)` etc.
  - Idempotency: `ON CONFLICT (instrument_id, timeframe, bar_date) DO UPDATE`.

### T-D-3-02: Disable redundant EODHD daily/weekly/monthly fetches
- **Type**: config
- **Target**: `polling_policies` seed migration.
- **Change**: for instruments covered by Alpaca, disable EODHD daily/weekly/monthly pulls (we recompute from 1m). Leave EODHD enabled only for the universe Alpaca doesn't cover (e.g. some ETFs, FX, crypto-on-non-Alpaca-venues).
- **Decision required from H-1**: which instruments stay on EODHD vs Alpaca-derived.

### T-D-3-03: Backfill recomputed 5m/15m/1h/… for the past 30 days
- **Type**: script
- **Target**: `scripts/ops/backfill_resampled_bars.py` (NEW)

## Wave D-4 — Observability

### T-D-4-01: Per-symbol freshness metric
- **Type**: impl
- **Add**: `market_data_ohlcv_latest_bar_timestamp_seconds{symbol, timeframe}` gauge exported from a 30s job that does `SELECT MAX(bar_date) GROUP BY instrument_id, timeframe`.

### T-D-4-02: Grafana panels (per agent report, 5 panels)
- Consumer-group lag heatmap
- Per-symbol bars/minute for 1m timeframe
- Scheduler tick interval gauge
- Task success rate by (provider, dataset_type, timeframe)
- DB insert lag vs Alpaca bar timestamp

**Validation gate**:
- [ ] Over a 10-min weekend observation, all ~15 enabled crypto symbols receive a 1m bar every minute
- [ ] Higher timeframes (5m, 15m, 1h) auto-recompute within 60s of their boundary
- [ ] Consumer-group lag <50 messages sustained
- [ ] All 5 Grafana panels render with non-empty data

**Break impact**: redundant EODHD policies become disabled — confirm no UI breaks on the assumption "EODHD daily must exist for non-Alpaca symbols".

---

# Sub-Plan E — Article-Consumer Orphan-Rate + Content Quality {#sub-plan-e}

**Goal**: (i) fix the observability bug where stub-filtered articles never get a `routing_decisions` row, and (ii) **investigate whether the ~46% of articles with `word_count < 50` are genuinely stubs or whether we're dropping content during processing** (user-flagged).

## Wave E-1 — Content-quality investigation (DO THIS FIRST)

User concern (correct): seeing 46% of ingested news under 50 words is suspicious. Headlines/teasers from Finnhub and SEC EDGAR genuinely run short, but if NLP processing is silently dropping body text, we'd see the same symptom. **Investigate before applying the routing-decision-write fix** so the fix doesn't paper over a real content-loss bug.

### T-E-1-01: Sample 50 orphan articles end-to-end
- **Type**: investigation
- **Method**:
  - Get 50 random orphan `document_id`s.
  - For each, fetch from `content_store_db.documents` the **raw upstream payload** and the `cleaned_body_text`.
  - Compare: did the upstream payload genuinely contain only a title? Or did it contain a body that our extractor dropped?
- **Quantify**: of 50, how many are genuine title-only stubs vs. cases where we lost body content.
- **Acceptance**: a verdict — "stub-filter is correct, observability fix only" OR "extractor is dropping bodies, fix at file:line".

### T-E-1-02: If content was lost — root-cause the extractor
- **Type**: impl (conditional on E-1-01)
- **Target**: the extraction pipeline path that produces `cleaned_body_text` from upstream payloads.
- **Fix scope**: depends on findings.

## Wave E-2 — Observability fix (regardless of E-1 verdict)

### T-E-2-01: Write SUPPRESS routing_decisions row on stub-filter
- **Type**: impl
- **Target**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` lines 582-590.
- **Change**: before the early `return` on `word_count < min_word_count`, write a `routing_decisions` row with `routing_tier=LIGHT`, `final_routing_tier=SUPPRESS`, `processing_path=HALT`, `feature_scores_json={"stub_filtered": True, "word_count": word_count}`. Use `uuid5_from_parts(doc_id, "stub_filter")` for deterministic idempotency.
- **Acceptance**:
  - Invariant test: `count(document_source_metadata 7d) == count(routing_decisions 7d)`.
  - Redelivery test: process same stub twice → only one routing_decisions row, no exceptions.

### T-E-2-02: Backfill 491 historical orphans
- **Type**: script
- **Target**: `scripts/ops/backfill_stub_filter_decisions.py` (NEW)
- **Behavior**: INSERT routing_decisions rows for the existing 491 orphans with `feature_scores_json={"stub_filtered_backfill": true}`.

**Validation gate**:
- [ ] Sample-50 investigation completed with documented verdict
- [ ] Either: extractor fix shipped (E-1-02) OR documented absence of content-loss bug
- [ ] Invariant `count(dsm) == count(rd)` holds for all docs after fix
- [ ] 491 backfill rows present with deterministic UUIDs

**Break impact**: query patterns that COUNT orphans as a bug indicator will now show 0 — update any QA scripts.

---

# Sub-Plan F — Silent-Failure Refactor {#sub-plan-f}

**Goal**: eliminate the four structural enablers of silent failure across the stack: container restart policy, dependency-stranding, kafka producer host-sleep recovery, and outbox error-detail drop. Ship platform-wide alerts and a per-worker healthcheck CLI.

Sequential 4-PR plan (already scoped in detail by audit agent):

## Wave F-1 — PR-A: Compose hardening + Kafka producer keepalive (0.5 d, LOW risk)

### T-F-1-01: Flip 33 sidecars `restart: on-failure` → `unless-stopped`
- **Target**: `infra/compose/docker-compose.yml` lines 285-2007 (33 distinct sidecars enumerated in audit).

### T-F-1-02: Demote `depends_on: service_healthy` → `service_started` for sidecar→parent-API edges
- **Target**: same file. Keep `service_healthy` only for true data deps (postgres, kafka, schema-registry).
- **Why**: prevents permanent stranding when parent API briefly dies.

### T-F-1-03: Kafka producer rdkafka config additions
- **Target**: `libs/messaging/src/messaging/kafka_config.py:37-42`
- **Add**: `socket.keepalive.enable=true`, `socket.timeout.ms=30000`, `socket.connection.setup.timeout.ms=30000`, `reconnect.backoff.ms=500`, `reconnect.backoff.max.ms=10000`, `metadata.max.age.ms=180000`, `metadata.request.timeout.ms=30000`.
- **Why**: survive macOS host-sleep TCP stale-connection (root cause of 2026-05-20 14h dispatcher stall).

### T-F-1-04: Integration test — broker pause/resume reconnect
- **Target**: `libs/messaging/tests/integration/test_producer_reconnect.py` (NEW)
- **Method**: testcontainers-kafka; pause broker 30s; verify produce succeeds after unpause within `delivery.timeout.ms`.

## Wave F-2 — PR-B: Outbox error_detail refactor (2 d, MEDIUM risk, 3 sub-PRs)

### T-F-2-01: Schema migration (Alembic head per service)
- **Add** `last_error TEXT`, `last_error_at TIMESTAMPTZ`, `last_error_class VARCHAR(128)` to:
  - portfolio: `0022_outbox_last_error.py`
  - market-ingestion: `0018_outbox_last_error.py`
  - market-data: `036_outbox_last_error.py`
  - content-ingestion: `0010_outbox_last_error.py`
  - content-store: `0007_outbox_last_error.py` (extend `dead_letter_queue` too — already has `error_detail`, add the other two)
  - nlp-pipeline: `0021_outbox_last_error.py`
  - alert: `0010_outbox_last_error.py`
  - intelligence-migrations (KG): next free
- **Acceptance**: each migration is idempotent and adds the three columns with NULL defaults.

### T-F-2-02: Repo signature unify
- **Target**: 9 repo files. Bump `move_to_dead_letter(record_id, error_class, error_msg)` everywhere. Add same kwargs to `increment_attempts`.
- **Adjust**: market-ingestion's `move_to_dead_letter_simple` → renamed to canonical name.

### T-F-2-03: Dispatcher passes error_detail
- **Target**: `libs/messaging/src/messaging/kafka/dispatcher/base.py:482`.
- **Change**: pass `error_class=delivery_error.__class__.__name__`, `error_msg=str(delivery_error)[:1000]` to both `move_to_dead_letter` and `increment_attempts`. Update `OutboxRepositoryProtocol` at line 139.

### T-F-2-04: Status-string unification (separate sub-PR for revert-ability)
- **Migrate**: `published` and `dispatched` → `delivered` (matches majority and S3 history). Add CHECK constraint to prevent regression.
- **Touch**: portfolio, market-ingestion (was `published`); nlp-pipeline, knowledge-graph, alert (was `dispatched`).

### T-F-2-05: Backfill the 926 historical DLQ rows with placeholder error
- **Change**: `UPDATE content_store.dead_letter_queue SET error_detail='<unknown: pre-PR-B>' WHERE error_detail = '' OR error_detail IS NULL`. Same for any other backfilled tables.

## Wave F-3 — PR-C: Alert rules + Grafana panels (0.5 d, LOW risk)

### T-F-3-01: 5 new Prometheus rules
- **Target**: `infra/prometheus/rules/alert-rules.yml`
- **Add**:
  - `OutboxIdleWithBacklog` — rate dispatched == 0 AND pending > 0 for 10m
  - `WorkerCycleStalled` — `time() - last_cycle_ts > 2 * cycle_interval` for 5m (requires F-4 metric)
  - `PipelineDataFreshnessStale` — per-pipeline latest record > 600s for 10m
  - `DLQGrowthSpike` — `increase(dlq_total[10m]) > 50`
  - `ContainerNotRunning` — `container_last_seen{name=~"worldview-.*"}` unless running (requires cAdvisor or docker-state-exporter)

### T-F-3-02: 2 Grafana panels
- **Add**:
  - Sidecar uptime heat-strip across all 33 worker containers
  - DLQ growth per service per minute

## Wave F-4 — PR-D: Worker `--healthcheck` CLI + cycle-timestamp metric (2 d, MEDIUM risk)

### T-F-4-01: Shared healthcheck lib
- **Target**: `libs/observability/src/observability/healthcheck.py` (NEW)
- **API**:
  - `mark_cycle_complete(worker_name: str, interval_s: int) -> None` — sets a process-local atomic UNIX timestamp + a Prometheus gauge `worldview_worker_last_cycle_timestamp_seconds{worker}` and gauge `worldview_worker_cycle_interval_seconds{worker}`.
  - `check_health() -> int` — returns 0 if the timestamp is within `2 * interval_s` of `now()`, else 1.

### T-F-4-02: Wire `--healthcheck` into every service's `__main__.py`
- **Target**: 8 service `__main__.py` files. Argparse on `--healthcheck` calls `check_health()` and exits with its return code.

### T-F-4-03: Call `mark_cycle_complete` from every worker loop
- **Target**: all 33 worker/consumer loop files. Add one call per loop iteration.

### T-F-4-04: Update HEALTHCHECK stanzas in compose
- **Target**: `docker-compose.yml` — replace all 46 boilerplate `["CMD", "python", "-c", "import os; os.kill(1, 0)"]` with `["CMD", "python", "-m", "<service>", "--healthcheck"]`.

**Validation gate (whole sub-plan)**:
- [ ] `make dev` brings all 40 containers `healthy` from cold
- [ ] Manually kill a worker process; healthcheck flips to `unhealthy` within `2 * cycle_interval`
- [ ] Pause/resume broker → producers reconnect within `delivery.timeout.ms`
- [ ] DLQ rows have populated `last_error` after a forced-failure smoke test
- [ ] All 5 new alert rules pass `promtool check rules`

**Break impact**: 4 alembic-migration adoption per service; tests asserting `move_to_dead_letter()` arity change. Status-string unification requires UI/dashboards re-querying.

**Regression guardrails**:
- BP-147 (missing serializer for new event type) — F-2 startup self-check covers it
- BP-590 (parallel session stash conflict) — N/A
- feedback_pre_commit_stash_conflict — ensure all PRs commit on first try
- BP-258 (consumer registered but never started) — F-1 + F-4 together prevent

---

# Sub-Plan G — `holding.changed` Gating {#sub-plan-g}

**Goal**: per user decision — keep the event but gate emission behind a default-`false` settings flag until a real consumer ships.

### T-G-1-01: Add settings flag
- **Target**: `services/portfolio/src/portfolio/config.py`
- **Add**: `emit_holding_changed_events: bool = False` (env var `PORTFOLIO_EMIT_HOLDING_CHANGED`).

### T-G-1-02: Gate emission at the producer
- **Target**: `services/portfolio/src/portfolio/application/use_cases/upsert_holdings_from_snapshot.py:159-167`.
- **Change**: wrap the `HoldingChanged` event emission in `if settings.emit_holding_changed_events:`.

### T-G-1-03: Doc + ADR
- **Update**: `docs/services/portfolio.md`; add a one-paragraph ADR note in `docs/architecture/decisions/` saying "deprecated emission gated; re-enable when alert position-closure rule lands".

### T-G-1-04: Replay or drop the 14 dead-letter rows
- **Option chosen**: drop (per audit — holdings table is canonical source of truth; no consumer; replay would be pointless work).

**Validation gate**: portfolio outbox `holding.changed` count stays at 0 in 24-hour observation.

---

# Sub-Plan H — Items Requiring User Decision {#sub-plan-h}

These items have multiple viable approaches; user must decide before tasks above are written in implementation detail.

## H-1: Alpaca scheduling — fair-share strategy ✓ RESOLVED 2026-06-10

**Decision**: raise Alpaca-1m priority above all other ingest types AND wire EODHD as a per-symbol fallback when Alpaca fails or returns 0 bars.

**Verified mechanically**: `AlpacaProviderAdapter._BATCH_SIZE = 1000` (services/market-ingestion/.../adapters/providers/alpaca.py:85) + `fetch_ohlcv_batch()` already implements multi-symbol CSV batching. `worker.py:274+` already takes the batch path when `supports_batch=True`. So Alpaca-1m ingestion of 649 symbols **costs ~1-2 HTTP calls per minute**, not 649.

Sub-Plan D-1 will:
- Raise Alpaca-1m policy `priority` to e.g. `100` (was `20`), other providers stay at `20`.
- Disable redundant EODHD daily/weekly/monthly for Alpaca-covered instruments (see H-3).
- On Alpaca HTTP failure or `row_count=0` for a specific symbol, fall back that symbol to EODHD daily within the same tick (cheap, resilient).

## H-2: Relevance worker — architecture (pending deep-dive, agent running 2026-06-10)

Awaiting agent's quantitative cost + quality comparison (token counts, $/article, coverage matrix, sliding-window aggregation analysis). Decision will be updated here once the report lands; default remains Path 1 (3-layer fix in Sub-Plan B).

## H-3: EODHD coverage decision ✓ RESOLVED 2026-06-10

**Decision**: EODHD daily/weekly/monthly enabled ONLY for instruments NOT queryable from Alpaca (Alpaca is significantly cheaper). For Alpaca-covered instruments, all higher timeframes are recomputed from 1m bars via `intraday_resampling_consumer`.

Universe split to be implemented in Sub-Plan D-3:
- **Alpaca-covered** (default): US equities, US ETFs, crypto on Alpaca-supported venues (BTC-USD, ETH-USD, …). 1m bars only; higher TF computed.
- **EODHD-only** (fallback): non-US instruments (UK ADRs, .L tickers, .HK, …), US ETFs Alpaca doesn't quote, crypto on venues Alpaca doesn't cover. EODHD daily/weekly/monthly + on-demand intraday.
- Detection: try Alpaca first per-instrument in a one-shot probe (e.g. fetch last 1 bar); on `not found` flip the policy to EODHD-only.

## H-4: get_price_history fallback window ✓ RESOLVED 2026-06-10

**Decision**: try last 24h first, fall back to 7-day window only if 24h is empty. Cheaper for the common case (crypto + Friday-after-close), still resilient on long weekends.

Implementation: amend `services/rag-chat/src/rag_chat/application/pipeline/handlers/market.py` to attempt two fallbacks in order. ~10 LOC change. Will land as part of Sub-Plan B (small enough to ride along) or as its own micro-commit.

(Context: `get_price_history` is the rag-chat LLM agent's tool. The orchestrator's planner picks it when a chat user asks about price/history/trend/range. The fallback handles after-hours queries like "what is AAPL trading at?".)

---

# Cross-Cutting Concerns

## Contract changes
- F-2 changes `OutboxRepository.move_to_dead_letter` signature across 9 implementations + 1 protocol.
- C-1 introduces `NewsAPIServerError` exception type (currently silently swallowed).
- E-2 adds an additional `routing_decisions` write — `RoutingDecision.feature_scores_json` schema gains optional `stub_filtered` field.

## Migration order
1. F-2 outbox migrations (one per service, parallel-able)
2. No others in this plan.

## Event flow changes
- No new Kafka topics.
- `portfolio.holding.changed.v1` emission becomes flag-gated (G).

## Config changes
- `PORTFOLIO_EMIT_HOLDING_CHANGED` (default `false`).
- New Prometheus rules + 2 Grafana dashboards.
- Compose: 33 sidecar restart-policy flips + 33 `depends_on` demotions + 46 healthcheck CMD rewrites.

## Documentation updates
- `docs/services/portfolio.md` (G)
- `docs/services/nlp-pipeline.md` (B)
- `docs/services/content-ingestion.md` (C)
- `docs/services/market-data.md` and `docs/services/market-ingestion.md` (D)
- `docs/libs/messaging.md` (F-2)
- `docs/libs/observability.md` (F-4)
- New ADR for compose restart-policy and Kafka keepalive (F-1)

---

# Risk Assessment

## Critical path
A → (C, D, E run in parallel after A) → backfills in B-2.

## Highest risk
F-4 (worker `--healthcheck` CLI) — touches every worker loop. Mitigation: ship F-1 first (compose-only) to immediately remove the silent-stop class; F-4 is the long-term reinforcement.

## Rollback strategy per sub-plan
- A: revert compose changes, restart impacted containers.
- B: revert worker code; backlog auto-drains.
- C: revert per file (independent fixes).
- D: keep current behavior; redundant EODHD polls return to enabled.
- E: revert routing_decisions write; orphans return.
- F: revert per PR (A, B, C, D are independent).
- G: flip env var to `true`.

## Testing gaps
- D-3 multi-timeframe recomputation is hard to test deterministically — need a fixture with a known 30min window of 1m bars and assertions on the resulting 5m/15m/1h aggregates.
- F-4 worker healthcheck — integration tests requiring actually-running workers are heavier than unit tests.

---

# Compounding step

Memory entries / docs to update on completion:
- BP-655 — "Sidecar restart policy `on-failure` silently strands containers on clean SIGTERM" (F-1).
- BP-656 — "Outbox dispatcher drops error_detail; DLQ post-mortem impossible without log archaeology" (F-2).
- BP-657 — "Qwen3 reasoning mode + max_tokens=96 + json_object response_format returns empty content" (B).
- BP-658 — "NewsAPI returns HTTP 200 with `{status:'error'}` on free-tier quota; client checking only status_code silently advances watermark" (C-1).
- BP-659 — "SQLAlchemy session closed without rollback leaves connection `idle in transaction (aborted)` in pool — surfaces as 'Can't reconnect' on next acquirer" (C-1).
- BP-660 — "Stub-filtered articles skip routing_decisions write — looks like consumer-drop bug for years" (E-2).
- BP-661 — "Kafka producer needs explicit `socket.keepalive.enable=true` to survive host sleep on macOS dev box" (F-1).
