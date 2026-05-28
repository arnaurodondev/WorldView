---
id: PLAN-0095
title: ITER-9 Pipeline Quality — Fundamentals Integrity, Chat Latency, Tool Hygiene, Worker Tuning
prd: inline (see §0)
status: draft
created: 2026-05-26
updated: 2026-05-26
source_audit: docs/audits/2026-05-26-iter-9-multi-issue-investigation-report.md
---

# PLAN-0095 — ITER-9 Pipeline Quality Remediation

## §0 — Inline PRD

> No separate PRD doc — this plan executes the six findings of the ITER-9 audit
> (`docs/audits/2026-05-26-iter-9-multi-issue-investigation-report.md`). All
> root-cause analysis, file:line citations, and minimal-fix sketches live in
> that report; this plan turns them into ship-able waves.

### Problem statement

The ITER-8 chat-eval emitted verdict **7 USEFUL / 0 USELESS / 0 HARMFUL** but
**failed the p99 < 60 s latency gate (observed 91.9 s)**. The follow-up ITER-9
multi-issue investigation found six distinct issues spanning data correctness,
query performance, agent latency, tool ergonomics, eval hygiene, and worker
throughput. They cluster naturally into 4 waves.

### Goals

1. **Kill the only HARMFUL-shaped failure mode left in the platform**: stop
   `get_fundamentals_history` from returning ANNUAL revenue/EPS in quarterly
   slots (§1) — AMD/NVDA Q1 numbers are currently 4-5× too large.
2. **Turn the dominant fundamentals tool-call cost from 22 s to <300 ms** via
   a composite `(instrument_id, period_end_date)` index on all 14 fundamentals
   section tables (§2).
3. **Get the chat-eval p99 latency gate green** (< 60 s) by collapsing
   fan-out tool calls into a batch endpoint, and by checking the completion
   cache *before* the input classifier (§3).
4. **Remove false-positive noise from the chat-eval grader** with tighter
   tool descriptions, an intent-classifier map update, a per-call fresh
   `thread_id` in the harness, and a cache-bypass env flag for eval runs
   (§4 + §5).
5. **Drain the path-insight backlog (4,710 → 0 rows)** and unblock the six
   starving workers identified in INV-GG (§6).

### Non-goals

- Refactor `intent_inference` to a learned classifier — env-driven map update
  only.
- Long-term split of the cluster-2 LLM workers into per-container processes
  (deferred to a future plan; short-term tuning is sufficient).
- Migrate the path-insight worker off APScheduler.

### Open questions

- **EODHD deep-dive findings**: a parallel investigation is producing
  `docs/audits/2026-05-26-eodhd-fundamentals-deep-dive.md`. When it lands its
  recommendations fold into **W1** (data integrity wave). Until then, W1 ships
  with the two confirmed §1 + §2 fixes; a placeholder task **T-W1-99** holds
  the EODHD slot. Update this plan in-place when the report arrives.

---

## §1 — Overview

**PRD**: inline (above)
**Services affected**: market-data (S2), rag-chat (S8), knowledge-graph (S7),
nlp-pipeline (S6), chat-eval harness
**Total waves**: 4
**Total estimated effort**: ~6–8 hours engineering + 1 docker rebuild cycle
**Critical path**: W1 → W2 (W2 batch endpoint depends on the W1 query
correctness fix being live). W3 + W4 can run in parallel after W1.

### ⛔ COMMIT BLOCKER — READ FIRST (prerequisite to landing Wave 1)

> **You cannot `git commit` any W1 change on `feat/plan-0093-remediation`
> until PLAN-0094 W2 is resolved.** Pre-commit will run mypy over every
> touched service; the PLAN-0094 W2 WIP currently fails mypy in `rag-chat`
> and `knowledge-graph`. This will block W1 even though W1 only edits
> `market-data`, because pre-commit's scope follows the staging area, not
> the touched-by-this-commit set.

The PLAN-0094 W2 work-in-progress is currently dirty in the working tree:

```
M apps/worldview-web/components/dashboard/PortfolioNewsWidget.tsx
M services/knowledge-graph/tests/unit/application/test_structured_enrichment.py
M services/rag-chat/src/rag_chat/application/pipeline/handlers/news.py
M services/rag-chat/src/rag_chat/application/security/llm_injection_classifier.py
M services/rag-chat/tests/unit/security/test_llm_injection_classifier.py
```

`pre-commit` runs `mypy` over the touched services on `git commit`, and the
PLAN-0094 W2 WIP currently fails mypy. **Wave 1 cannot land** (i.e. cannot
produce a green pre-commit) until either:

  (a) PLAN-0094 W2 lands its own fix-up commit (**preferred** — finish what
      was started; verify nothing PLAN-0094 W2 touches collides with
      PLAN-0095 — confirmed clean on 2026-05-26: W2 touches
      `apps/worldview-web/components/dashboard/PortfolioNewsWidget.tsx`,
      `services/knowledge-graph/tests/unit/application/test_structured_enrichment.py`,
      `services/rag-chat/src/rag_chat/application/pipeline/handlers/news.py`,
      `services/rag-chat/src/rag_chat/application/security/llm_injection_classifier.py`,
      `services/rag-chat/tests/unit/security/test_llm_injection_classifier.py`
      — none of these are touched by PLAN-0095 W1/W2/W3/W4), or
  (b) Wave 1 is started on a clean branch off `main`, or
  (c) the W2 WIP is stashed before `git commit` (riskier — work-in-progress
      is then easy to forget).

**Resolve-PLAN-0094-W2-first gate**: do NOT start PLAN-0095 W1 implementation
on the current branch unless option (a), (b), or (c) is taken first. The
W1 pre-flight checklist below tracks this.

## §2 — Dependency Graph

```
                      ┌─────────────────────────────────────┐
                      │ Commit blocker: PLAN-0094 W2 WIP    │
                      │ mypy failures must clear first      │
                      └────────────────┬────────────────────┘
                                       │
                                       ▼
W1 (market-data fundamentals integrity + index migration + EODHD T-W1-04..07
    — snapshot period_type tracking, freshness column, observability)
        │
        ├──────────────────────────────────────────────┐
        ▼                                              ▼
W2 (rag-chat latency: batch tool + market-data         W3 (tool docs + eval
    batch endpoint + classifier reorder)                  hygiene; no deploy)
        │                                              │
        └──────────────────────────────┬───────────────┘
                                       ▼
                          W4 (worker tuning — path-insight env
                              + DefinitionRefresh fallback +
                              MarketDataClient backoff +
                              NLP relevance API key)
```

W3 has no deploy footprint (eval-harness + tool descriptions + intent map) so
it can ship in parallel with W2. W4 is independent of W2/W3.

## §3 — Codebase State Verification

| Reference | Type | Service | Actual current state | Plan target | Delta |
|-----------|------|---------|----------------------|-------------|-------|
| `GetFundamentalsHistoryUseCase.execute` | use case | market-data | `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:77-92` issues 3 sequential `find_by_section` calls; income query passes **no** `period_type` | add `period_type=PeriodType.QUARTERLY` to income call | code change |
| `query_fundamentals` | repo fn | market-data | `services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_query.py:107-154` accepts `(session, security_id, section)`; no period filter | extend signature with `period_type: PeriodType \| None = None` + `WHERE` clause | code change |
| `find_by_section` | port | market-data | `services/market-data/src/market_data/application/ports/fundamentals_read.py` (path inferred) | extend signature mirror | code change |
| `fundamentals_consumer.py` | consumer | market-data | `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:451-478` writes both QUARTERLY and ANNUAL income rows under same section enum, distinct `period_type` | no change (data is correct on write; bug is read-side) | none |
| 14 fundamentals section tables | schema | market-data | `services/market-data/alembic/versions/001_initial_schema.py:43-62` + `_base.py:26-31` create single-column `ix_<table>_instrument_id` indexes | new composite `(instrument_id, period_end_date ASC)` index per table via new Alembic migration | NEW migration |
| `POST /v1/fundamentals/batch` | route | market-data | does not exist | NEW route — accepts `{tickers: list[str], periods: int}`, returns `{results: {ticker: {status, periods?, reason?}}}` | new artifact |
| `get_fundamentals_history_batch` | rag-chat tool | rag-chat | does not exist; tool registry only has single-ticker `get_fundamentals_history` | NEW tool in `services/rag-chat/src/rag_chat/application/pipeline/tool_registry_builder.py` | new artifact |
| `chat_pipeline.py` order | logic | rag-chat | orchestrator at `services/rag-chat/src/rag_chat/application/pipeline/chat_pipeline.py:154-155` runs `pipeline.validate_input()` (defined at L203) BEFORE `pipeline.check_cache()` (defined at L251). (Audit report's `:457` ref is stale; verified 2026-05-26 in PLAN-0095 revision pass.) | swap order at the orchestrator call site (L154-155): cache check first; classifier runs only on cache miss | code change |
| `tool_registry_builder.py` descriptions | strings | rag-chat | `services/rag-chat/src/rag_chat/application/pipeline/tool_registry_builder.py:205-216, 250-287, 503-533, 565-590, 618-639` | rewrite per §4 of audit — explicit "DO NOT use for…" clauses | code change |
| `intent_inference.py` map | dict | rag-chat | `services/rag-chat/src/rag_chat/application/services/intent_inference.py:45-54` missing `get_entity_intelligence`, `search_entity_relations`, `get_entity_narrative` | add 3 mappings | code change |
| `harness.py` thread_id | test | chat-eval | `tests/validation/chat_eval/harness.py:216` sends `{"message": q, "entity_ids": ...}` — no `thread_id` | generate `thread_id=str(uuid4())` per `ask()` call | test-only change |
| `test_q8_openai_msft_paths.py` grader | test | chat-eval | strict tool-list requirement fails on cache-hit answers | accept cache-hit as valid OR set `RAG_COMPLETION_CACHE_DISABLED=true` env for eval session | test-only change |
| `RAG_COMPLETION_CACHE_DISABLED` | env | rag-chat | **NEW — does not exist in codebase yet** (verified 2026-05-26 — `git grep RAG_COMPLETION_CACHE_DISABLED` returns no hits; audit §5 ref is aspirational, not factual). T-W3-04 must (a) implement the env-var bypass in `chat_pipeline.check_cache()` (return `None` early when env is `"true"`) AND (b) set the env in the eval fixture. | NEW env + code change in `chat_pipeline.py:251` |
| `KNOWLEDGE_GRAPH_PATH_EXPLANATION_*` env | env | knowledge-graph | **Verified 2026-05-26**: in-code defaults at `config.py:276-278` are ALREADY `batch=300 / concurrency=7 / cycle_minutes=20` (the audit's "current: 200/5/20" was stale or read from a prior commit). `docker.env.example:48-50` ALREADY exports 300/7/20. Only remaining tuning: cycle 20→12 min. | `cycle_minutes=12` (others already match); also confirm the deployed `docker.env` (not just `.example`) has these values | env change (small) |
| `DefinitionRefreshWorker` LLM provider | code | knowledge-graph | `KNOWLEDGE_GRAPH_GEMINI_API_KEY` missing; no DeepInfra fallback | add DeepInfra fallback chain (mirror EmbeddingRefreshWorker) | code change |
| `MarketDataClient` JWT-mint race | code | nlp-pipeline (`PriceImpactLabellingWorker`) | mints JWT once at startup; race against api-gateway readiness | 3-retry exponential backoff OR deferred client creation on first `run_once()` | code change |
| `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` | env | nlp-pipeline | empty → falls back to Ollama → Ollama down → starvation | wire same DeepInfra key used by other workers | env change + docker-compose |

## §4 — Sub-Plans

---

### Wave W1 — Market-data fundamentals data integrity

**Goal**: (a) Stop annual income-statement rows from leaking into quarterly
`get_fundamentals_history` responses; (b) replace single-column indexes with
composite `(instrument_id, period_end_date ASC)` on all 14 section tables;
(c) fold in EODHD deep-dive findings if/when the parallel audit lands.

**Justification for single wave**: §1 and §2 both touch
`fundamentals_query.py`, the same 14 section tables, and the same use case
test surface. Shipping them together avoids a needless second deploy and
keeps the regression test seeding logic in one place.

**Depends on**: commit-blocker resolved (PLAN-0094 W2 mypy)
**Estimated effort**: ~3 h (90 min for §1+§2 + ~90 min for the four EODHD tasks T-W1-04..07)
**Architecture layer**: application + infrastructure + Alembic
**Branch**: `feat/plan-0095-w1`
**Migration**: YES — **3 new Alembic revisions** in `services/market-data/alembic/versions/`:
  - revision N: composite `(instrument_id, period_end_date)` indexes (T-W1-03)
  - revision N+1: snapshot `period_type_*` columns (T-W1-04)
  - revision N+2: `instruments.last_fundamentals_ingest_at` column (T-W1-07)
  All three are additive; sequence them in this order so T-W1-04/07 land on
  top of T-W1-03's head. Current Alembic head is `018_add_fiscal_year_end_month.py`
  (verified 2026-05-26); new revisions are `019_*` → `020_*` → `021_*`.
**Docker rebuild**: YES — `market-data` image + `market-data-migrate` re-run

#### Pre-flight

- [ ] Verify working tree clean (or branch off `main`) so pre-commit mypy
      passes — see §1 commit blocker.
- [ ] Confirm Alembic head before adding new revision; new file uses next
      sequence number (`002_*.py` if `001_initial_schema.py` is the only
      revision; otherwise next-in-sequence).

#### Tasks

##### T-W1-01: Add `period_type` parameter to `query_fundamentals`

**Type**: impl
**depends_on**: none
**blocks**: T-W1-02
**Target files**:
- `services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_query.py:107-154`
- `services/market-data/src/market_data/application/ports/fundamentals_read.py` (port signature mirror)

**Audit reference**: §1, minimal-fix sketch lines 30-38.

**What to build**:
Extend `query_fundamentals` (function at `fundamentals_query.py:107`) with a
new optional parameter `period_type: PeriodType | None = None`. When set, add
`stmt = stmt.where(model_class.period_type == str(period_type))`. The port
ABC must mirror the new kwarg (default `None`) so existing call sites in
other use cases keep working unchanged.

**Acceptance check**:
- Unit test `test_query_fundamentals_filters_by_period_type` in
  `services/market-data/tests/unit/infrastructure/db/test_fundamentals_query.py`
  asserts that seeding a QUARTERLY + ANNUAL row at the same `period_end_date`
  and querying with `period_type=PeriodType.QUARTERLY` returns only the
  quarterly row.

##### T-W1-02: Pass `period_type=QUARTERLY` from use case

**Type**: impl
**depends_on**: [T-W1-01]
**blocks**: T-W1-03
**Target files**:
- `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:83-86`

**Audit reference**: §1, lines 22-28.

**What to build**:
In the `find_by_section(iid_str, FundamentalsSection.INCOME_STATEMENT, ...)`
call at lines 83-86, add `period_type=PeriodType.QUARTERLY` kwarg. Keep the
earnings call (line 78, already quarterly-only on the consumer side per
audit line 14) and the highlights call (line 90) unchanged.

**Acceptance check**:
- Unit test `test_get_fundamentals_history_returns_only_quarterly_income`
  in `services/market-data/tests/unit/application/use_cases/test_get_fundamentals_history.py`
  seeds QUARTERLY ($50B) + ANNUAL ($200B) income rows at the same
  `period_end_date`; asserts returned revenue == $50B and EPS matches the
  quarterly earnings row.
- Manual: `curl localhost:8000/v1/instruments/AMD/fundamentals/history` —
  AMD Q1 FY2026 revenue is in the $7-8B range, NOT $34.6B.

##### T-W1-03: Alembic migration — composite indexes on 14 section tables

**Type**: migration
**depends_on**: none
**blocks**: deploy
**Target files**:
- new `services/market-data/alembic/versions/NNN_composite_fundamentals_indexes.py`

**Audit reference**: §2, lines 50-59.

**What to build**:
Migration creates 14 composite indexes (one per section table):

```
ix_earnings_history_instrument_period
ix_income_statements_instrument_period
ix_balance_sheets_instrument_period
ix_cash_flow_statements_instrument_period
ix_highlights_instrument_period
ix_valuation_instrument_period
ix_technicals_instrument_period
ix_splits_dividends_instrument_period
ix_esg_scores_instrument_period
ix_analyst_ratings_instrument_period
ix_insider_transactions_instrument_period
ix_institutional_holders_instrument_period
ix_earnings_estimates_instrument_period
ix_earnings_trend_instrument_period
```

Each: `CREATE INDEX ix_<table>_instrument_period ON <table>(instrument_id,
period_end_date ASC);`. **Use `CREATE INDEX` (not `CONCURRENTLY`) per BP-393
since this is single-tenant dev/staging and our migration runner does not
run outside a transaction.** Downgrade drops all 14 indexes.

Leave the existing single-column `ix_<table>_instrument_id` indexes in place
(harmless; can be dropped in a later cleanup migration after observing query
plans in prod).

**Acceptance check**:
- `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` is
  green locally.
- `EXPLAIN ANALYZE` on the use case query shows index scan on
  `ix_earnings_history_instrument_period` (no sort node).
- Wall-clock for `GET /v1/instruments/AMD/fundamentals/history` drops from
  ~15-22 s to <300 ms (audit-claimed 30-100× speedup).

##### T-W1-04: BP-542 — Snapshot derivation periodicity tracking (P0)

**Type**: impl + migration
**depends_on**: [T-W1-01]
**blocks**: W1 sign-off
**Target files**:
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:618-620` (snapshot input selection — `_most_recent_financial_row` prefers `yearly`)
- `services/market-data/src/market_data/infrastructure/db/fundamentals_snapshot_writer.py:133-216` (UPSERT row builder; columns at L216-)
- new Alembic revision (additive columns on `instrument_fundamentals_snapshot`)

**Audit reference**: EODHD deep-dive §5 (lines 140-169), BP-542.

**What to build**:
The snapshot mixes QUARTERLY and ANNUAL source rows without labelling. Two
alternatives — pick (a) for v1, document (b) for a follow-on:

  (a) **Minimum-viable (chosen)**: add three nullable VARCHAR columns
      `period_type_income`, `period_type_cash_flow`, `period_type_balance`
      to `instrument_fundamentals_snapshot`; populate from
      `_most_recent_financial_row`'s chosen source. Frontend / observability
      gain `period_type_*` so stale-vs-fresh can be detected.
  (b) Future: split snapshot into two rows (quarterly + annual TTM); deferred
      to PLAN-0096.

**Acceptance check**:
- Alembic up→down→up clean.
- Unit test `test_snapshot_writer_records_source_period_type` — feed a row
  derived from `{"yearly": ..., "quarterly": ...}` payload; assert
  `period_type_income == "ANNUAL"` (the preferred path).
- Manual: `SELECT period_type_income, period_type_cash_flow,
  period_type_balance FROM instrument_fundamentals_snapshot LIMIT 5` returns
  non-NULL values for fresh rows after consumer redeploy.

##### T-W1-05: BP-543 — Document mixed-periodicity risk on balance_sheet / cash_flow

**Type**: docs + guardrail (no code change)
**depends_on**: [T-W1-01]
**blocks**: none
**Target files**:
- `services/market-data/.claude-context.md` (Pitfalls section)
- `docs/services/market-data.md` (Fundamentals section)

**Audit reference**: EODHD deep-dive §4 (lines 100-137), BP-543.

**What to build**:
`balance_sheet` and `cash_flow` tables ALSO store both QUARTERLY and ANNUAL
rows at the same `period_end_date`. No current query joins them, but any
future caller must pass `period_type=` (now available from T-W1-01). Add a
loud Pitfalls note. No production query path is broken today; this is a
forward-looking guardrail.

**Acceptance check**:
- `services/market-data/.claude-context.md` Pitfalls section contains
  string "balance_sheet and cash_flow ALSO mix QUARTERLY+ANNUAL".
- Docs cross-link BP-543.

##### T-W1-06: BP-544 — Observability for unknown EODHD fields

**Type**: impl (observability only)
**depends_on**: none
**blocks**: none
**Target files**:
- `services/market-data/src/market_data/infrastructure/messaging/consumers/metric_extractor.py:80-380` (the static `_METRIC_CATALOG` dict)
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:442-541` (section dispatch — skipped sections silently dropped today)

**Audit reference**: EODHD deep-dive §7 (lines 195-228), BP-544.

**What to build**:
Emit two structured-log signals so silent drops are no longer invisible:
1. `eodhd_unknown_section` — when consumer encounters a top-level section
   not in `_SECTION_HANDLERS`; log `section_key`, `symbol`.
2. `eodhd_unknown_field` — when a section dict has keys that neither match
   any alias in `_METRIC_CATALOG` nor a known JSONB-passthrough field.
   Sample only (e.g. log first occurrence per `(section, field)` pair per
   container lifetime) to avoid log spam.

This is observability only — no behavioural change.

**Acceptance check**:
- Unit test `test_consumer_logs_unknown_section` — feed payload with
  `"esg_scores_v2"` key; assert `eodhd_unknown_section` log emitted.
- Unit test `test_metric_extractor_samples_unknown_fields` — feed section
  dict with unknown key; assert one log emission, second call to same key
  emits no further log.

##### T-W1-07: BP-545 — Per-instrument fundamentals freshness column

**Type**: migration + impl
**depends_on**: none
**blocks**: none
**Target files**:
- new Alembic revision (additive `last_fundamentals_ingest_at` column on
  `instruments` table)
- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:575` (success log site — also set the column)

**Audit reference**: EODHD deep-dive §8 (lines 230-254), BP-545.

**What to build**:
Add nullable `last_fundamentals_ingest_at TIMESTAMPTZ` to `instruments`.
Update it inside the same UoW that writes the section rows (no dual-write —
already in the consumer's transaction). Enables operator queries like
`SELECT ticker FROM instruments WHERE last_fundamentals_ingest_at <
NOW() - INTERVAL '7 days'`.

**Acceptance check**:
- Alembic up→down→up clean.
- Unit test `test_consumer_sets_last_fundamentals_ingest_at` — process a
  payload; assert column updated to `utc_now()`-ish value.

**Deferred to PLAN-0096** (out of scope here; documented for traceability):
- EODHD §3 zero-vs-null FCF margin semantics tightening (P1 but cosmetic;
  no live failure).
- EODHD §6 backfill `fiscal_year_end_month` for non-US tickers
  (data-coverage gap; not a correctness bug today).
- BP-542 alternative (b): split snapshot table into quarterly + annual TTM
  rows.

#### Validation gate

- [ ] ruff + mypy clean on `market-data`
- [ ] All existing market-data unit tests pass
- [ ] New unit tests pass (T-W1-01, T-W1-02, T-W1-04, T-W1-06, T-W1-07)
- [ ] Alembic up→down→up cycle clean for all 3 new revisions (in sequence)
- [ ] EXPLAIN on production-shaped data shows index scan, no sort
- [ ] Live curl against AMD/NVDA returns quarterly numbers in the
      $5-15B range (NOT $30B+)
- [ ] `instrument_fundamentals_snapshot.period_type_income` is non-NULL for
      fresh rows after redeploy
- [ ] `instruments.last_fundamentals_ingest_at` updates after consumer run
- [ ] At least one `eodhd_unknown_section` or `eodhd_unknown_field` log
      observable in dev, or zero (acceptable) — confirming the new probes
      are wired
- [ ] Docker compose rebuild of `market-data` + `market-data-migrate` clean

#### Architecture compliance

- [ ] **R24** — only `market-data` owns its DDL; intelligence_db untouched
- [ ] **R32** — Alembic revision number is next-in-sequence
- [ ] **R25** — port signature updated alongside concrete adapter
- [ ] **BP-393** — migration uses plain `CREATE INDEX`, not CONCURRENTLY

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| Any use case that calls `find_by_section` for INCOME_STATEMENT | Now defaults to all period types if caller doesn't pass `period_type` — but new behaviour is identical to old (optional kwarg, default None) | None needed; default preserves backward compat |
| `tests/unit/application/use_cases/test_get_fundamentals_history.py` | New assertions on QUARTERLY-only return | Add the new test; existing tests should still pass |

#### Regression guardrails

- **BP-393** — Alembic CONCURRENTLY incompatible with our transactional
  migration runner.
- **BP-130** — smoke-test hardcoded migration head string; if smoke test
  asserts on `head == "001"`, update to the new head.
- **BP-126** — Alembic NOT NULL column missing server_default; N/A here
  (no NOT NULL changes).

#### Compounding updates

- `docs/services/market-data.md` — add §"Fundamentals query: QUARTERLY-only
  income" subsection; note new composite indexes; document new
  `period_type_*` snapshot columns (T-W1-04) and
  `instruments.last_fundamentals_ingest_at` (T-W1-07); document
  `eodhd_unknown_section`/`eodhd_unknown_field` log signals (T-W1-06).
- `services/market-data/.claude-context.md` Pitfalls — add THREE entries:
  (1) "income rows are stored under one section enum with distinct
  period_type; always filter on the read path (PLAN-0095 W1)";
  (2) "balance_sheet and cash_flow ALSO mix QUARTERLY+ANNUAL — pass
  `period_type=` on any new query (PLAN-0095 T-W1-05, BP-543)";
  (3) "snapshot rows now carry `period_type_*` columns — prefer them over
  inferring periodicity (PLAN-0095 T-W1-04, BP-542)".
- `docs/BUG_PATTERNS.md` — new entries:
  - **BP-559** "Mixed-periodicity dict overwrite in fundamentals join" (§1 of audit)
  - **BP-542** already named in EODHD deep-dive — file under PLAN-0095 T-W1-04
  - **BP-543** EODHD deep-dive — file under T-W1-05
  - **BP-544** EODHD deep-dive — file under T-W1-06
  - **BP-545** EODHD deep-dive — file under T-W1-07
- `docs/plans/TRACKING.md` — flip PLAN-0095 row to W1 in-progress, then
  done. Update wave/task summary to include T-W1-04..07.
- `RULES.md` — no new rule.

#### Files touched (sequencing audit — single-wave order)

The following file is touched by **multiple W1 tasks**; sequence carefully
inside the W1 commit(s):

- `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py`
  - T-W1-04 edits L618-620 (snapshot input)
  - T-W1-06 edits L442-541 (section dispatch — add unknown-section log)
  - T-W1-07 edits L575 (success log — also set `last_fundamentals_ingest_at`)
  All three edits are non-overlapping line ranges and can ship in a single
  commit. No cross-wave overlap with W2/W3/W4.

---

### Wave W2 — rag-chat latency: batch tool, batch endpoint, classifier reorder

**Goal**: Collapse the screener → fundamentals 3-LLM-turn cascade into a
single turn by introducing `get_fundamentals_history_batch`. Backed by a new
`POST /v1/fundamentals/batch` route in market-data. Independently, swap
`validate_input` and `check_cache` in `chat_pipeline.py` so the 15% cache-hit
traffic skips the 5-8 s classifier.

**Acceptance gate (wave-level)**: ITER-9 chat-eval p99 **< 60 s** as
reported by `tests/validation/chat_eval/run_eval.py` summary output (the
JSON artifact at `runs/<ts>/summary.json` field `latency.p99_seconds`).

**Depends on**: W1 (HARD dependency — both correctness AND latency):
  - correctness: the new `/v1/fundamentals/batch` endpoint reuses
    `GetFundamentalsHistoryUseCase`; without T-W1-01/02 it would return the
    same mixed-periodicity bug.
  - latency: the batch endpoint amortises N tickers' worth of
    `query_fundamentals` calls; without the T-W1-03 composite index each
    inner call costs 15-22 s and the batch is no faster than the fan-out
    it replaces. T-W1-03 is therefore a **prerequisite for the W2
    acceptance gate** as well as for correctness.
**Estimated effort**: ~3 hours
**Architecture layer**: application (rag-chat tool + chat_pipeline reorder)
                       + API (market-data route) + use case
**Branch**: `feat/plan-0095-w2`
**Migration**: NO
**Docker rebuild**: YES — `rag-chat` + `market-data` images

#### Tasks

##### T-W2-01: Add `POST /v1/fundamentals/batch` to market-data

**Type**: impl
**depends_on**: [T-W1-02]
**blocks**: T-W2-02
**Target files**:
- `services/market-data/src/market_data/api/routers/fundamentals.py` (new
  route, after the existing single-ticker GET at lines 69-116)
- request/response Pydantic schemas in the same router file or
  `services/market-data/src/market_data/api/schemas/fundamentals.py`

**Audit reference**: §3, lines 77-81.

**What to build**:
Request body: `{tickers: list[str], periods: int}` (cap `len(tickers) ≤ 25`
to bound worst-case fan-out latency; reject with 422 if exceeded).
Implementation:

```python
results = await asyncio.gather(
    *[uc.execute(ticker, periods=periods) for ticker in tickers],
    return_exceptions=True,
)
response = {"results": {}}
for ticker, result in zip(tickers, results):
    if isinstance(result, Exception):
        response["results"][ticker] = {"status": "error", "reason": str(result)}
    else:
        response["results"][ticker] = {"status": "ok", "periods": result}
return response
```

Per-ticker failures must NOT fail the whole batch (`return_exceptions=True`).
Use the same use case instance for all tickers (reuse the DI-injected one).

**Acceptance check**:
- Unit test `test_fundamentals_batch_returns_per_ticker_status` —
  `[AAPL, BADTICKER, NVDA]` → `AAPL.status=="ok"`, `BADTICKER.status=="error"`,
  `NVDA.status=="ok"`.
- Unit test `test_fundamentals_batch_rejects_oversized_list` — 26 tickers
  returns 422.
- Curl: `curl -X POST localhost:8000/v1/fundamentals/batch -d '{"tickers":["AAPL","NVDA","AMD"],"periods":4}'`
  returns 200 with three `ok` results in <500 ms (gated by W1 index).

##### T-W2-02: Add `get_fundamentals_history_batch` tool in rag-chat

**Type**: impl
**depends_on**: [T-W2-01]
**blocks**: T-W2-03
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/tool_registry_builder.py`
  (new tool registration alongside existing `get_fundamentals_history`)
- corresponding port in `services/rag-chat/src/rag_chat/application/ports/`
  + adapter in `services/rag-chat/src/rag_chat/infrastructure/clients/market_data_client.py`

**Audit reference**: §3, lines 77-81.

**What to build**:
Tool description (mirror audit §3 sketch ~30 lines):

> Fetch quarterly fundamentals (revenue, EPS, margins) for **multiple
> tickers in one call**. Use this when comparing or screening 2+ companies.
> Returns `{ticker: {status, periods?, reason?}}`; partial failures don't
> fail the call. Prefer over multiple `get_fundamentals_history` calls.

Calls `POST {s9_base}/v1/fundamentals/batch` (S9 proxy or direct per
existing pattern — read `market_data_client.py` to confirm; rag-chat goes
through S9 per R14).

**Acceptance check**:
- Unit test `test_get_fundamentals_history_batch_tool_calls_batch_endpoint`
  — mocks S9, asserts POST to `/v1/fundamentals/batch` with the expected
  body and returns the per-ticker dict.
- Chat-eval `agg_q6` (screener → 5 tickers fundamentals) drops from 10 tool
  calls to ≤4 (1 screener + 1 batch + ≤2 retries).

##### T-W2-03: Swap classifier ↔ cache check order

**Type**: impl
**depends_on**: none
**blocks**: T-W2-04
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/chat_pipeline.py:154-155` (the orchestrator call site; `validate_input` definition is at L203, `check_cache` definition is at L251)

**Audit reference**: §3, line 83. (Audit's `:457` line number is stale — confirmed in PLAN-0095 revision pass; correct call-site lines are 154-155.)

**What to build**:
Currently `validate_input()` runs before `check_cache()` at L154-155. Swap so
`check_cache()` runs first; on cache hit, return the cached completion and
**skip** the classifier entirely. On cache miss, fall through to the
existing classifier-then-LLM path.

Security argument (audit §3, line 83): a poisoned cache entry was classified
on its *first write*; re-classifying on every read is defensive duplication,
not a gate.

**Acceptance check**:
- Unit test `test_chat_pipeline_cache_hit_skips_classifier` — mock
  `check_cache()` to return a hit; assert `validate_input` is NOT called.
- Unit test `test_chat_pipeline_cache_miss_still_runs_classifier` — mock
  cache miss; assert `validate_input` IS called.
- p99 latency on cache-hit subset of chat-eval drops by 5-8 s.

##### T-W2-04: Wave acceptance — chat-eval p99 < 60 s

**Type**: validation
**depends_on**: [T-W2-02, T-W2-03]
**blocks**: W2 sign-off

**What to build**: re-run `tests/validation/chat_eval/run_eval.py` against
a docker stack rebuilt with W1+W2 in place. The aggregate p99 must drop
from 91.9 s (ITER-8 baseline) to **< 60 s**. Audit-claimed projection:
~45 s (51% improvement). Capture the new run artifact path in the W2
commit message.

**Acceptance check**:
- `tests/validation/chat_eval/runs/<new-timestamp>/summary.json` field
  `latency.p99_seconds < 60.0` (the chat-eval harness writes this field
  to the summary artifact; verify the field name exists today before W2
  starts — if the harness emits the value under a different key, update
  this gate to match the actual key name in the W2 commit message).

#### Validation gate

- [ ] ruff + mypy clean on rag-chat + market-data
- [ ] All existing unit tests still pass
- [ ] New unit tests (T-W2-01, T-W2-02, T-W2-03) pass
- [ ] Docker rebuild of rag-chat + market-data clean
- [ ] Chat-eval p99 < 60 s (T-W2-04)

#### Architecture compliance

- [ ] **R14** — rag-chat → S9 only, never direct to market-data
- [ ] **R25** — new tool follows port/adapter pattern
- [ ] **R27** — read-only path, no UoW writes

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| `tests/unit/test_chat_pipeline.py` | Cache-check ordering changed | Update test fixtures to expect new order |
| Tool manifest snapshot test (if exists) | New tool added | Re-snapshot |

#### Regression guardrails

- **BP-235** — httpx timeout shadowing: new batch endpoint client must set
  `httpx.Timeout(N)` explicitly, especially when wrapped in
  `asyncio.wait_for`.
- **BP-407** — Kafka backpressure: N/A.
- **BP-319** — model_dump_json for cache writes: confirm the cache write
  path is untouched.

#### Compounding updates

- `docs/services/rag-chat.md` — document new tool + new ordering of
  cache vs classifier.
- `docs/services/market-data.md` — document `POST /v1/fundamentals/batch`.
- `services/rag-chat/.claude-context.md` Pitfalls — "cache hit short-
  circuits classifier (PLAN-0095 W2 T-W2-03)".
- `docs/BUG_PATTERNS.md` — new entry **BP-560** "Classifier latency
  shadowed cache-hit fast path".
- `docs/plans/TRACKING.md` — update PLAN-0095 row.
- `RULES.md` — no new rule.
- `CLAUDE.md` — no change.

---

### Wave W3 — Tool ergonomics & eval hygiene

**Goal**: Tighten 5 tool descriptions so the model stops misrouting peer /
biographical questions; extend the intent-classifier map; make the chat-eval
harness use a fresh `thread_id` per call; allow grader cache-hit acceptance;
add `RAG_COMPLETION_CACHE_DISABLED=true` to the eval session.

**Deploy needed**: tool descriptions are loaded at rag-chat startup so a
rag-chat redeploy is required. T-W3-04 also adds a small `check_cache()`
env-var bypass (newly created — see §3 verification table), bundled into
the same rebuild. The harness + grader changes are test-side only.

**Depends on**: none (can run in parallel with W2)
**Estimated effort**: ~90 min
**Architecture layer**: rag-chat application (descriptions + intent map);
                       chat-eval harness
**Branch**: `feat/plan-0095-w3`
**Migration**: NO
**Docker rebuild**: YES (rag-chat — for tool descriptions only)

#### Tasks

##### T-W3-01: Rewrite 5 tool descriptions

**Type**: impl
**depends_on**: none
**blocks**: T-W3-04
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/tool_registry_builder.py:205-216, 250-287, 503-533, 565-590, 618-639`

**Audit reference**: §4, lines 91-106.

**What to build**:
Rewrite descriptions for: `get_entity_graph`, `traverse_graph`,
`get_entity_paths`, `get_entity_intelligence`, `compare_entities`. Key
additions per audit:
- Explicit "DO NOT use for…" clauses on `get_entity_graph` and
  `traverse_graph` (peer/category vs two-entity-relation distinction).
- "(2) biographical/timeline questions about people/executives" added to
  `get_entity_intelligence`.
- `compare_entities` — note "financial only, NOT a relationship tool".

Verbatim before/after wording lives in the audit agent's report; use that as
authoritative source.

**Acceptance check**:
- Unit test `test_tool_descriptions_contain_anti_patterns` — asserts that
  `get_entity_graph` description contains "DO NOT use for"; similar for
  `traverse_graph`.
- Chat-eval Q1 (Apple competitors) and Q3 (Tim Cook before Apple) re-run
  pick `get_entity_intelligence` (not `get_entity_graph + search_documents`).

##### T-W3-02: Extend intent_inference map

**Type**: impl
**depends_on**: none
**blocks**: T-W3-04
**Target files**:
- `services/rag-chat/src/rag_chat/application/services/intent_inference.py:45-54`

**Audit reference**: §4, lines 108-110.

**What to build**:
Add three new mappings to the tool-name → intent dict:
- `get_entity_intelligence` → `RELATIONSHIP` (or whichever specialised
  intent exists for relationship-aware second-turn prompts; read the file
  to confirm valid intent enum values).
- `search_entity_relations` → `RELATIONSHIP`.
- `get_entity_narrative` → `RELATIONSHIP`.

Currently all three map to `GENERAL`, losing the chance to switch to the
relationship-specialised second-turn prompt.

**Acceptance check**:
- Unit test `test_intent_inference_relationship_tools_mapped` — asserts
  each of the 3 tools resolves to the relationship intent.

##### T-W3-03: Harness fresh `thread_id` per call

**Type**: impl
**depends_on**: none
**blocks**: T-W3-04
**Target files**:
- `tests/validation/chat_eval/harness.py:216`

**Audit reference**: §5, lines 126-131.

**What to build**:
Change the payload from `{"message": q, "entity_ids": ...}` to:

```python
{"message": q, "entity_ids": ..., "thread_id": str(uuid4())}
```

Generate a fresh UUID **per `ask()` call**, not per test, not per
module-scoped fixture. The conftest at lines 19-23 already warns about this;
this task promotes the advisory invariant to enforced.

**Acceptance check**:
- Unit test `test_harness_ask_generates_fresh_thread_id` — call `ask()`
  twice with the same question; assert the two payloads have different
  `thread_id` values.
- The "iter3_top5 Unity Software" artifact bug (audit §5) does not recur.

##### T-W3-04: Grader cache-hit allowance + `RAG_COMPLETION_CACHE_DISABLED=true`

**Type**: test
**depends_on**: [T-W3-01, T-W3-02, T-W3-03]
**blocks**: W3 sign-off
**Target files**:
- `tests/validation/chat_eval/test_q8_openai_msft_paths.py` (and any
  similarly strict per-question test files; grep for tests that assert on a
  required tool list)
- `tests/validation/chat_eval/conftest.py` — add fixture that exports
  `RAG_COMPLETION_CACHE_DISABLED=true` for the eval session
- chat-eval Makefile target / pytest invocation

**Audit reference**: §4 line 111; §5 fix #3 line 133.

**What to build**:
1. **Implement the env-var bypass in `chat_pipeline.check_cache()`**
   (`services/rag-chat/src/rag_chat/application/pipeline/chat_pipeline.py:251`).
   This env does NOT exist in the codebase today (verified
   2026-05-26 — `git grep RAG_COMPLETION_CACHE_DISABLED` empty). Add:
   ```python
   if os.environ.get("RAG_COMPLETION_CACHE_DISABLED", "").lower() == "true":
       return None
   ```
   at the top of `check_cache()`. Read once at startup (via pydantic-settings)
   or per call — per-call is fine because os.environ lookup is cheap and
   eval-only.
2. In `test_q8_openai_msft_paths.py` (and siblings if applicable), accept a
   `cache_hit` event as satisfying the tool-call requirement: if the
   response stream contains `{"event": "cache_hit"}`, treat the per-question
   "required tools" assertion as satisfied.
3. In `tests/validation/chat_eval/conftest.py`, add a session-scoped fixture
   that sets `os.environ["RAG_COMPLETION_CACHE_DISABLED"] = "true"` for the
   chat-eval session and restores it on teardown.

The two fixes are belt-and-suspenders: (1) handles legitimate cache hits
that happen to satisfy semantics, (2) ensures most eval runs measure cold-
path behaviour.

**Acceptance check**:
- `pytest tests/validation/chat_eval/test_q8_openai_msft_paths.py` passes
  when cache is hit AND when cache is disabled.
- A grep for `RAG_COMPLETION_CACHE_DISABLED` in conftest returns the new
  fixture.

#### Validation gate

- [ ] ruff + mypy clean on rag-chat
- [ ] All existing rag-chat unit tests still pass
- [ ] 4 new unit tests pass (T-W3-01..03 + the grader fixture)
- [ ] Chat-eval Q1 + Q3 re-route to `get_entity_intelligence`
- [ ] Q8 grader passes whether cache is hit or disabled

#### Architecture compliance

- [ ] **R25** — no new ports needed (description-only changes)
- [ ] **R15** — docs updated for new tool wording

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| Tool-manifest snapshot test | Descriptions changed | Re-snapshot |
| `test_intent_inference.py` | Map expanded | Add new assertions |
| Existing per-question chat-eval tests that asserted strict tool list | Cache-hit acceptance new | Apply same fix pattern as T-W3-04 |

#### Regression guardrails

- **BP-549** — orphan helpers: if intent_inference had a default-only branch
  unused after the map extension, delete it.
- **Audit §5 culprit** — the `thread_id=None` collision pattern must not
  recur. Belt-and-suspenders: harness fix + env-var disable.

#### Compounding updates

- `docs/services/rag-chat.md` — tool catalogue section updated with the 5
  rewritten descriptions; intent map extended.
- `tests/validation/chat_eval/README.md` (if exists) — document the
  `RAG_COMPLETION_CACHE_DISABLED=true` fixture and the per-call
  `thread_id` invariant.
- `docs/BUG_PATTERNS.md` — new entry **BP-561** "Test harness shared
  `thread_id` causes completion cache cross-contamination".
- `docs/plans/TRACKING.md` — update PLAN-0095 row.
- `RULES.md` — no new rule.
- `CLAUDE.md` — no change.

---

### Wave W4 — Worker tuning (path-insight + FIX-LIVE-GG remaining items)

**Goal**: Drain the 4,710-row path-insight backlog via env-tuned batch /
concurrency / cycle; finish the FIX-LIVE-GG worker remediation by adding
MarketDataClient JWT-mint backoff, DefinitionRefresh DeepInfra fallback, and
NLP relevance scoring API key wiring.

**Depends on**: none (independent of W1/W2/W3)
**Estimated effort**: ~2 hours (mostly env + DI wiring; one code change for
the JWT-mint backoff)
**Architecture layer**: env + worker code + docker-compose
**Branch**: `feat/plan-0095-w4`
**Migration**: NO
**Docker rebuild**: YES — knowledge-graph + nlp-pipeline

#### Tasks

##### T-W4-01: Path-insight worker env tuning

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/configs/docker.env` (and `.example`)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_explanation_batch_worker.py` (verify env-driven reads exist; add if not)

**Audit reference**: §6 path-insight, lines 141-151.

**What to build**:
**Stale-assumption note (PLAN-0095 revision 2026-05-26)**: the in-code
`Settings` defaults at `services/knowledge-graph/src/knowledge_graph/config.py:276-278`
and `configs/docker.env.example:48-50` ALREADY equal `300/7/20`. The
remaining gap is (a) the deployed `docker.env` (without `.example`) — must
audit whether it still carries `200/5` overrides — and (b) the cycle
adjustment to 12 min for the backlog burst.

Set in `services/knowledge-graph/configs/docker.env` (only override the
cycle if the defaults already cover batch/concurrency):

```
KNOWLEDGE_GRAPH_PATH_EXPLANATION_CYCLE_MINUTES=12
# (batch=300, concurrency=7 already match the in-code defaults; only export
# them explicitly if the deployed env needs to pin against future drift)
```

Projected throughput 400 → 1,260 rows/h IF the deployed env was actually
running 200/5; if it was already running 300/7 (i.e. the audit's
"observed" baseline was misread), the realised gain is only the cycle
adjustment (~50% rather than 3×). Either way the change is safe and
strictly improving.

**Acceptance check**:
- After docker-compose restart of `knowledge-graph`, `valkey-cli` or worker
  startup log emits `path_explanation_batch_size=300 concurrency=7 cycle_minutes=12`.
- 1 hour of live observation shows `path_explanation_rows_processed` near
  1,260/h.

##### T-W4-02: MarketDataClient — JWT-mint exponential backoff

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/clients/market_data_client.py` (path inferred — locate via grep)
- Used by `PriceImpactLabellingWorker`

**Audit reference**: §6 cluster-1, lines 156-157.

**What to build**:
On startup, the worker mints an internal JWT against api-gateway. If
api-gateway is not yet ready, the call fails and the worker dies. Add a
3-retry exponential backoff (e.g. 1 s → 2 s → 4 s) around the mint call.
Alternative (preferred per audit): defer client creation to the first
`run_once()` call so the cycle naturally retries on its next tick.

Pick whichever pattern matches existing client code in the same service
(`grep "exponential" services/nlp-pipeline/src`).

**Acceptance check**:
- Unit test `test_market_data_client_retries_jwt_mint_on_startup_failure` —
  mock first 2 attempts to fail, third to succeed; assert no exception
  bubbles.
- Compose restart with api-gateway delayed by 5 s — `PriceImpactLabellingWorker`
  no longer dies, recovers on retry.

##### T-W4-03: DefinitionRefreshWorker DeepInfra fallback

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/workers/definition_refresh_worker.py` (path inferred)

**Audit reference**: §6 cluster-2 item 5, lines 162.

**What to build**:
Today the worker calls Gemini via `KNOWLEDGE_GRAPH_GEMINI_API_KEY`. That key
is missing in our env; no DeepInfra fallback exists. Result: 59.5% NULL
company descriptions.

Add the same DeepInfra fallback chain used by `EmbeddingRefreshWorker` (also
in knowledge-graph). Order: Gemini (if key set) → DeepInfra (always
available) → log error and tombstone if both fail.

**Acceptance check**:
- Unit test `test_definition_refresh_falls_back_to_deepinfra_when_gemini_unset`
  — set `KNOWLEDGE_GRAPH_GEMINI_API_KEY=""`; assert DeepInfra call made.
- After 1 worker cycle in dev, `SELECT count(*) FROM entities WHERE
  description IS NULL` drops measurably.

##### T-W4-04: NLP relevance scoring API key

**Type**: config
**depends_on**: none
**blocks**: none
**Target files**:
- `services/nlp-pipeline/configs/docker.env` (and `.example`)
- `infra/compose/docker-compose.yml` — `nlp-pipeline` env block

**Audit reference**: §6 cluster-1 item 2, lines 157.

**What to build**:
Set `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY=${DEEPINFRA_API_KEY}` (or
whatever the canonical name is in `worldview-config` / `make fetch-secrets`
output). Currently empty → falls back to Ollama → Ollama down → worker
starves.

**Acceptance check**:
- `docker compose exec nlp-pipeline env | grep RELEVANCE_SCORING` shows a
  non-empty value.
- 30 minutes of live observation: `ArticleRelevanceScoringWorker` processes
  articles (not stuck at zero).

#### Validation gate

- [ ] ruff + mypy clean on knowledge-graph + nlp-pipeline
- [ ] 2 new unit tests pass (T-W4-02, T-W4-03)
- [ ] Docker rebuild of both services clean
- [ ] Path-insight backlog drains visibly (gauge `path_explanation_backlog`
      trending down)
- [ ] No more `PriceImpactLabellingWorker` death loops in logs
- [ ] No more `ArticleRelevanceScoringWorker` Ollama-down errors

#### Architecture compliance

- [ ] **R25** — fallback chain follows existing port pattern
- [ ] **R12** — structlog for retry / fallback log events
- [ ] **R30** — API keys via pydantic-settings env vars, never in code

#### Break impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| Worker startup tests | Backoff added | Update mocks to expect retry behaviour |
| Compose env smoke tests | New env vars expected | Add to baseline |

#### Regression guardrails

- **BP-235** — httpx timeout: new DeepInfra fallback calls must set
  explicit `httpx.Timeout(N)`.
- **BP-407** — retry storm: ensure max-retry cap so a permanent api-gateway
  outage doesn't cause exponential thrash.
- **BP-200** — Valkey API: N/A.

#### Compounding updates

- `docs/services/knowledge-graph.md` — document path-insight new defaults
  and `DefinitionRefreshWorker` fallback chain.
- `docs/services/nlp-pipeline.md` — document `MarketDataClient` mint-retry
  behaviour and relevance scoring key requirement.
- `services/knowledge-graph/.claude-context.md` Pitfalls — "definition
  refresh requires DEEPINFRA_API_KEY as fallback; PLAN-0095 W4".
- `services/nlp-pipeline/.claude-context.md` Pitfalls — "relevance
  scoring worker silently falls back to Ollama if API key empty;
  PLAN-0095 W4 T-W4-04".
- `docs/BUG_PATTERNS.md` — new entries **BP-562** "JWT-mint race on
  cold-start without backoff", **BP-563** "Silent Ollama fallback when
  required API key empty".
- `docs/plans/TRACKING.md` — flip PLAN-0095 row to done after W4 ships.
- `RULES.md` — no new rule.
- `CLAUDE.md` — no change.

---

## §5 — Cross-cutting concerns

- **Contract changes**:
  - `query_fundamentals` + `find_by_section` port gain `period_type` kwarg
    (additive; default `None` preserves backward compat).
  - New `POST /v1/fundamentals/batch` route (additive).
  - `instrument_fundamentals_snapshot` gains 3 nullable columns (additive).
  - `instruments` gains 1 nullable column (additive).
  - `PublicBriefingResponse` untouched (this plan).
- **Migration needs**: **3 new Alembic revisions in market-data**, all
  additive, sequenced 019 → 020 → 021 (current head verified
  `018_add_fiscal_year_end_month.py` on 2026-05-26):
  - 019: composite `(instrument_id, period_end_date)` indexes (T-W1-03)
  - 020: snapshot `period_type_*` columns (T-W1-04)
  - 021: `instruments.last_fundamentals_ingest_at` (T-W1-07)
- **Event flow changes**: none.
- **Configuration changes**:
  - market-data: none (defaults preserved).
  - rag-chat: `RAG_COMPLETION_CACHE_DISABLED` becomes test-fixture-set; no
    prod env change required.
  - knowledge-graph: 3 path-insight vars + (optional) DEEPINFRA key
    reference for fallback chain.
  - nlp-pipeline: `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` must be
    populated in compose env (`make fetch-secrets` already pulls
    `DEEPINFRA_API_KEY`).
- **Documentation updates**: see per-wave "Compounding updates" sections.

## §6 — Risk assessment

- **Critical path**: W1 → W2. W3 and W4 parallelisable after W1.
- **Highest risk task**: T-W1-03 (Alembic migration on 14 tables). Mitigate
  by running up→down→up cycle locally; the migration is additive (new
  indexes only, no DDL on existing columns).
- **Second highest**: T-W2-03 (classifier reorder). Mitigate by keeping the
  classifier on the cache-miss path; cache-hit becomes the only fast path.
  Audit explicitly argues this is safe (poisoned entries were classified on
  first write).
- **Rollback strategy**:
  - W1: `alembic downgrade -1` drops new indexes; revert two code lines for
    the `period_type` filter. Old (buggy) behaviour returns but rows still
    correct on consumer side.
  - W2: revert tool registration + classifier swap; market-data batch route
    can stay (harmless if unused).
  - W3: revert description / harness / fixture changes; eval becomes noisier
    but functional.
  - W4: zero out the 3 path-insight env vars; defaults restore; revert
    fallback chain commit.
- **Testing gaps**: no full end-to-end test that exercises chat-eval p99
  gate inside CI (run is operator-driven). Acceptable for now.

## §7 — Compounding step

- **New bug patterns** to add to `docs/BUG_PATTERNS.md`:
  - **BP-559** (mixed-periodicity dict overwrite in fundamentals join, §1)
  - **BP-560** (classifier shadows cache fast-path, §3)
  - **BP-561** (test harness shared thread_id cache cross-contamination, §5)
  - **BP-562** (JWT-mint race on cold-start, §6)
  - **BP-563** (silent Ollama fallback when required API key empty, §6)
  - **BP-542** (snapshot derivation mixes quarterly/annual without labels, EODHD §5)
  - **BP-543** (balance_sheet & cash_flow also mix periodicities, EODHD §4)
  - **BP-544** (static metric catalog → silent EODHD field drops, EODHD §7)
  - **BP-545** (no per-instrument freshness tracking, EODHD §8)
  Total: 9 new BP entries.
- **No new rule** required — all changes leverage existing R12 / R14 /
  R15 / R24 / R25 / R27 / R30 / R32.
- **No CLAUDE.md change** — workflow unchanged.
- **TRACKING.md**: flip status across the wave lifecycle (added below).
- **REVIEW_CHECKLIST.md**: no change (orphan-prune item from PLAN-0093
  already covers W1's `_FINANCIAL_MUTATION_LIMIT`-style helper deletions
  if any surface).

---

## Owner

**Owner**: TBD (assign at implementation start). Suggested: same engineer
who shipped FIX-LIVE-II (commit `f6b76ff9`) for W2 + W3 (rag-chat depth);
data-platform engineer for W1; platform engineer for W4.
