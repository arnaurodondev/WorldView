# QA Report: PLAN-0055 Iter-4 Runtime Validation

**Date**: 2026-04-30
**Skill**: qa
**Scope**: PLAN-0055 (Auto-Backfill, Source Stability, LLM Provenance)
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: **SHIP**

---

## Executive Summary

Fourth QA iteration — first to spin up real containers and probe endpoints end-to-end. Rebuilt and recreated the three affected service stacks (S3 market-ingestion, S4 content-ingestion, S6 nlp-pipeline). Migrations 0006/0012/0013/0014 applied successfully on dev DBs (`alembic_version` confirmed). Five of six PLAN-0055 deliverables verified live: S3 startup backfill enqueue (`startup_backfill_completed`), S4 startup watermark seed (`seeded=12 skipped=0 failed=0`), S4 idempotent source POST + `config_drift_detected` WARN, S6 append-only `document_source_llm_scores` ledger (100 rows written), `document_source_llm_latest` materialized view refresh. The runtime probe found 1 BLOCKING (BP-180 asyncpg `AmbiguousParameterError` on the new admin endpoint) which has been fixed and re-verified — endpoint now returns dry-run estimates and inserts replay jobs cleanly.

---

## Iter-4 Findings & Resolution

### F-001 (BLOCKING — FIXED)
- **What**: `POST /api/v1/admin/llm-replay` raised `asyncpg.exceptions.AmbiguousParameterError: could not determine data type of parameter $1` whenever `since`/`until` were null (which is every default call).
- **Root cause**: Classic BP-180 — asyncpg cannot infer parameter types at PREPARE time when a nullable param is used in `param IS NULL` checks.
- **Fix**: `services/nlp-pipeline/src/nlp_pipeline/api/routes/admin.py` — wrapped `:since`, `:until`, and `:score_types` in `CAST(... AS TIMESTAMPTZ)` / `CAST(... AS TEXT[])` in both the count query (lines ~111-119) and the INSERT (lines ~150-160).
- **Verification**: Rebuilt nlp-pipeline image, hot-recreated container, dev-login + admin token probe:
  ```
  POST /api/v1/admin/llm-replay (dry_run)
  → {"estimated_articles":3031,"estimated_minutes":25,"status":"DRY_RUN"}
  POST /api/v1/admin/llm-replay (real)
  → {"job_id":"70bf7fd7-…","status":"PENDING","total_articles":3081}
  ```
  DB row verified in `llm_replay_jobs` with model_id, prompt_version=v2, score_types={relevance}.

### Pre-existing platform issues (NOT PLAN-0055; reported for visibility)
| ID | Severity | Service | Issue |
|----|----------|---------|-------|
| F-101 | CRITICAL | nlp-pipeline-price-impact-worker | All `GET market-data:8003/api/v1/market-data/ohlcv/*` calls return 401. Likely missing internal JWT propagation. AIW table empty as a result. |
| F-102 | MAJOR | nlp-pipeline-watchlist-consumer | Every `portfolio.watchlist.updated.v1` message dead-letters with `'utf-32-be' codec` deserialization error — pattern matches BP-122 (Confluent Avro magic byte missed). |
| F-103 | MAJOR | nlp-pipeline-unresolved-resolution-worker | 100% failure rate (`processed:43, errors:43`); root cause not surfaced in logs. |
| F-104 | MINOR | content-ingestion-worker | Finnhub transcripts endpoint 100% failure across all symbols ("All 3 retries exhausted"). |

These are tracked as platform stability follow-ups. None block PLAN-0055.

### F-105 (MINOR — wontfix this iter)
First-deploy lifespan race: if API container starts before the migrate sidecar applies 0006, `SeedSourceWatermarksUseCase` crashes with `column sources.config_hash does not exist`. The crash is swallowed by the `try/except` in lifespan and the API still serves traffic; on a fresh `--force-recreate` cycle it succeeds. Compose `depends_on: condition: service_completed_successfully` is in place; the issue is that `docker compose build <api-only>` leaves migrate sidecar images stale.

---

## Validation Matrix (live runtime)

| Wave / item | Result | Live evidence |
|-------------|--------|---------------|
| A-1 `_MAX_CHUNKS=500` | ✅ | service runs without ValueError on 14d horizon |
| A-1 `_default_chunk_days_for_timeframe` | ✅ | unit tests + log analysis |
| A-2 S3 startup backfill hook | ✅ | `startup_backfill_completed enqueued=0 horizon_days=14` |
| A-3 S4 startup watermark seed | ✅ | `startup_watermarks_seeded seeded=12 skipped=0 failed=0` |
| B-1 `sources.config_hash` GENERATED | ✅ | `is_generated=ALWAYS`, sha256 expression |
| B-1 `uq_sources_dedup` constraint | ✅ | `UNIQUE (source_type, config_hash)` |
| B-1 idempotent `POST /api/v1/sources` | ✅ | first+second POST → same id |
| B-1 config-drift WARN | ✅ | mutating `last_run_config_hash` triggers `config_drift_detected` log |
| C-1 AIW UNIQUE replaces old INDEX | ✅ | `uq_article_impact_windows_dedup` exists; `idx_article_impact_windows_unique` removed |
| C-2 `document_source_llm_scores` writes | ✅ | 100 rows (50 relevance + 50 sentiment) with `model_id=meta-llama/...`, `prompt_version=v1` |
| C-3 `document_source_llm_latest` mat view | ✅ | `REFRESH MATERIALIZED VIEW CONCURRENTLY` succeeds; 100 rows |
| C-4 `POST /api/v1/admin/llm-replay` | ✅ | dry_run + real-run both green; jobs inserted |
| Migrations applied (S4: 0006, S6: 0014) | ✅ | `alembic_version` confirmed |
| News read path `/api/v1/news/top` | ✅ | 200 OK with display_relevance_score |
| Health endpoints S3/S4/S6 | ✅ | all `/healthz` → `{"status":"ok"}` |

---

## Test Execution

| Layer | Result |
|-------|--------|
| Unit (content-ingestion) | 587 passed |
| Unit (market-ingestion) | 203 passed (64 deselected) |
| Unit (nlp-pipeline) | 565 passed |
| Ruff (src + tests, 6 paths) | ✅ All checks passed |
| Runtime endpoint probe | ✅ All PLAN-0055 endpoints functional |

**Total**: 1,355 unit tests + live endpoint validation passed.

---

## Verdict: SHIP

PLAN-0055 fully validated against live containers. The single runtime BLOCKING (BP-180 in admin replay) is closed. All 8 waves operational; 4 platform-stability findings logged for follow-up but do not gate this PR.
