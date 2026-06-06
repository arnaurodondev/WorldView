---
id: QA-PLAN-0093-PHASE-5C
title: PLAN-0093 Phase 5c — Live-Execution QA Report
date: 2026-05-24
plan: docs/plans/0093-intelligence-pipeline-remediation-plan.md
predecessor: docs/audits/2026-05-24-qa-plan-0093-validation-report.md
branch: feat/plan-0093-remediation
mode: LIVE (make dev stack up; intelligence_db + nlp_db at alembic head 0048; rag-chat reachable via gateway)
overall_verdict: FAIL — PLAN-0093 does NOT achieve its stated goal on live execution
---

# PLAN-0093 Phase 5c — Live-Execution QA Report

## TL;DR

Phase 5c brought the platform up via `make dev` and executed the four live tests the static Phase 5/5b audits had deferred. **The plan as shipped does NOT achieve its stated goal.** The single most important assertion — that the RAG agent stops fabricating the AMD revenue figure — is FALSE in live execution. Q4-v1 fired today produced HARMFUL output containing the exact "$X > $15B AMD revenue" + "potential volatility" / "one-time event" rationalisation pattern the original 2026-05-23 audit catalogued.

**Aggregate chat-eval verdict: 3/15 PASS** (Q1, Q3, Q8 + the AMD-revenue-and-EPS narrow check pass; everything else FAILs). The plan's ≥6/8 USEFUL gate and zero-HARMFUL gate are both VIOLATED.

In addition, live execution surfaced **6 new findings (F-LIVE-001 through F-LIVE-006)** that all static-mode QA passes (Phase 5 + Phase 5b re-QA) missed by construction.

## Phase 5c Verdict Matrix

| Sub-phase | Verdict | Detail |
|---|---|---|
| 5c-1 Stack up via `make dev` | PASS (after F-LIVE-001 + F-LIVE-002 + F-LIVE-003 fixes) | 10/10 backend services healthy. Initial state: 7/10 in crashloop, 5 migrations un-applied. |
| 5c-2 G-1 SLO tests vs live DBs | PARTIAL (14 pass / 9 backlog / 5 skip out of 29) | 2 new test bugs (F-LIVE-004, F-LIVE-005). Real worker-output gaps surface as expected on fresh DB. |
| 5c-3 Alembic + F-1 PREPARE | PARTIAL | Alembic head 0042→0048 OK after F-LIVE-002+003. F-1 PREPARE pass is noise-heavy (F-LIVE-007: doesn't understand SQLAlchemy `:name` placeholders); 2 real bugs surface. |
| 5c-4 Host-event survival | **PASS** | All 11 app-tier services survived `docker kill postgres+kafka+valkey` and were healthy 90s after dep restart. FIX-3 restart policies + connection-resilience confirmed working. |
| 5c-5 Chat-eval against live rag-chat | **FAIL** | 3/15 pass. Q4-v1 returned HARMFUL with the exact $34.6B-AMD pattern from the original audit. FIX-2 RAG safety contract is INSUFFICIENT in live execution. |
| 5c-6 Extended adversarial QA | DEFERRED | Skipped due to context budget after FAIL on 5c-5. |

## OVERALL VERDICT: **FAIL**

The plan ships infrastructure improvements (PASS), test scaffolding (PASS), and well-intentioned RAG safety code (FAIL — the safety code prevents Q4 in static analysis but the LIVE agent still fabricates the same number).

---

## New Findings (Phase 5c only)

### F-LIVE-001 — APP_ENV not propagated to compose env (BLOCKING; FIXED)

**Discovered**: 2 minutes into `make dev`.

**Root cause**: PLAN-0093 A-1 (commit `24fb922c`) added `assert_app_env_or_die` to all 9 backend lifespans but did not actually add `APP_ENV=local` to any service env block — the commit body claimed it but the diff didn't. Static QA-3 verified the helper exists + is called; it could not verify the env var is actually set at runtime.

**Symptom**: 7 of 9 backend services crashlooped on fresh `make dev` with `RuntimeError: BLOCKING SECURITY: APP_ENV unset`. The security guard worked as designed — APP_ENV being unset + `internal_jwt_skip_verification=True` is the exact condition the helper refuses.

**Fix**: Added `APP_ENV=development` to all 9 `services/<svc>/configs/docker.env.example` templates (commit `95ac9769`). Future check-outs that copy template → docker.env will have the var. Existing developers must `grep -q APP_ENV docker.env || echo APP_ENV=development >> docker.env`.

**Compounding candidate (BP-NEW)**: "Lifespan assertion added without matching env wiring → fresh-clone production-grade outage." Detection rule: every `assert_*_or_die` helper paired with a grep test for the env var in every `docker.env.example`.

---

### F-LIVE-002 — Migration 0044 uses non-existent entity_type (BLOCKING; FIXED)

**Discovered**: 10 minutes into `make dev`.

**Root cause**: Migration 0044's sentinel seed used `entity_type='organization'` for "Unknown Organization", but the `ck_canonical_entities_entity_type` CHECK constraint allows only 11 values: `financial_instrument, person, event, sector, industry, macro_indicator, place, product, index, currency, unknown` — `organization` is NOT in the enum. INSERT failed at the 3rd sentinel; whole 0044 transaction rolled back; 0045-0048 never applied.

**Symptom on live DB**: alembic head stayed at 0042 (pre-PLAN-0093) across the entire branch. None of B-2/B-3/D-3 schema changes were actually present. Every "now there are no NULL confidence rows" claim in the original audit Annex C was FALSE in live data.

**Fix**: Remapped to `entity_type='unknown'` (commit `fc0466fb`). Migration now applies cleanly.

**Why static QA missed it**: QA-4 only verified the file structure (downgrade present, TRUNCATE guard added) + a sentinel-sync regression test. It did not run `alembic upgrade head` against a real Postgres. Any live execution would have caught this in <30 seconds.

---

### F-LIVE-003 — Migration 0046 uses `SET DEFAULT base_confidence` which Postgres rejects (BLOCKING; FIXED)

**Discovered**: 12 minutes in (after F-LIVE-002 fixed 0044).

**Root cause**: Migration 0046 used `server_default=sa.text("base_confidence")` to let bare INSERTs adopt the row's own `base_confidence` value. PostgreSQL rejects this outright — `cannot use column reference in DEFAULT expression`. SQL DEFAULTs must be constants or constant-function calls (`NOW()`, `gen_random_uuid()`), never another column.

**Fix**: Dropped the server_default (commit `fc0466fb`). Migration 0045 TRUNCATEs the table beforehand, and application INSERT paths always supply confidence explicitly. If a future code path needs auto-fallback, a BEFORE INSERT trigger is the only SQL-supported way.

---

### F-LIVE-004 — G-1 tests use `:name` placeholder but psycopg needs `%(name)s` (CRITICAL; FIXED)

**Discovered**: G-1 live-DB test run.

**Root cause**: Two G-1 tests use SQLAlchemy `:param` placeholder syntax (`WHERE entity_id = :eid`), but the `scalar()` helper in `tests/validation/conftest.py` passes raw SQL to psycopg's `cursor.execute()` which requires `%(name)s` style. Both sites raised `syntax error at or near ":"` against live DB.

**Fix**: Renamed to `%(eid)s` and `%(floor)s` (commit `930a823d`).

**Why static QA missed it**: QA-1 verified the SQL referenced real columns/tables (which it did) but placeholder syntax compatibility is only knowable at runtime.

---

### F-LIVE-005 — G-1 test queries `entity_mentions.score`; real column is `confidence` (CRITICAL; FIXED)

**Discovered**: G-1 live-DB test run.

**Root cause**: `test_zero_sub_floor_entity_mentions` queries `entity_mentions.score` but migration 0001 created the column as `confidence DOUBLE PRECISION NOT NULL`. The original audit uses "GLiNER score" colloquially; the test inherited that wording.

**Fix**: Renamed column reference (commit `930a823d`).

---

### F-LIVE-006 — `PathExplanationBatchWorker` (D-1) exists in code but is NOT in compose (BLOCKING; OPEN)

**Discovered**: G-1 live-DB test run + KG `/metrics` endpoint inspection.

**Root cause**: PLAN-0093 D-1 added two artefacts:
1. `services/knowledge-graph/src/.../workers/path_explanation_batch_worker.py` — the worker class
2. `path_insight_explanation_pending_total` gauge in `prometheus.py` — incremented by the worker

But there is NO `docker-compose.yml` entry that runs this worker. The existing `knowledge-graph-path-insight-worker` is a DIFFERENT worker (`path_insight_worker_main`, runs `path_discovery_complete` jobs only).

**Symptom on live**: 285 `path_insights` rows have `NULL llm_explanation` AND `computed_at > 1h ago`. The gauge is missing from KG `/metrics` output entirely (Prometheus only exposes gauges after their first `.set()` call).

**Fix required** (deferred): add `knowledge-graph-path-explanation-worker` service block to compose mirroring the existing path-insight-worker pattern but invoking `path_explanation_batch_worker.py` as a long-running process.

**Why static QA missed it**: QA-5 (architecture) spot-checked names existed — they did, in source. QA-6 (docs) verified the gauge was added to the doc — it was. Neither agent checked that the worker is actually invoked by an entry point in compose.

---

### F-LIVE-007 — F-1 PREPARE pass has a fundamental tooling bug (MAJOR; OPEN)

**Discovered**: F-1 PREPARE pass live execution.

**Root cause**: `tests/architecture/repository_sql_extractor.py` pulls raw SQL literals from source files and PREPAREs them against live Postgres. But application code uses SQLAlchemy `text(":name")` which SQLAlchemy converts to PostgreSQL `$1` style at runtime; the extractor passes the raw `:name` literal which Postgres rejects as `syntax error at or near ":"`.

**Symptom**: 60+ false-positive failures. Two genuine schema-drift findings drown in the noise:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/document_search.py:141` → `relation "filtered" does not exist` (CTE/scope issue)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/news_query.py:31` → `column "article_impact_windows.article_id" must appear in the GROUP BY clause` (real SQL bug)

**Fix required** (deferred): convert `:name` → `$1, $2, ...` (with dummy bindings) before PREPAREing, OR skip statements that contain `:name` placeholders entirely.

---

### F-LIVE-008 — Q4 RAG agent STILL fabricates AMD revenue > $15B (BLOCKING; OPEN — the core PLAN-0093 failure)

**Discovered**: Live chat-eval execution.

**Root cause** (hypothesised; pending deeper investigation): the FIX-2 patches (premise-check rule, quarter-regex broadening, entity-scoped numeric pool) work in isolation per their unit tests, BUT in the live execution path:
1. The agent calls `get_fundamentals_history` for both NVDA and AMD
2. The validator's entity-scoping requires the response to mention "AMD" within 100 chars of each AMD number — which is true for proper attribution
3. But the agent also synthesises rationalisations ("potential volatility may explain the figure") that wrap fabricated numbers in plausible-sounding prose; the validator only catches the NUMBER not the prose
4. The agent appears to NOT actually call `get_fundamentals_history` reliably (test reports `missing required tool from ['get_fundamentals_history']; got []`)

**Symptom on live**:
- Q4 v1 ("Compare revenue trajectories of NVIDIA and AMD over last 4 quarters") → HARMFUL with:
  - `AMD revenue > $15.0B mentioned` (the exact fabrication signature)
  - `orphan rationalisation phrases: ['potential volatility', 'one-time event', 'may reflect']`
  - `missing required tool ['get_fundamentals_history']; got []`
- Q4 v4/v5/v6 → USELESS (`response reads as a refusal`) — premise-check rule is over-refusing legitimate comparison questions
- Q4 v2 → response doesn't mention the correct NVDA Q4FY26 revenue 68.127B
- Q4 cross-cutting test `test_q4_zero_amd_figures_above_15b` confirms the fabrication

**Other RAG failures**:
- Q2 (MSTR news) → USELESS, `'all_tools_failed'` event, only 1 tool called (no fallback)
- Q5 (Tesla macro) → HTTP 503, "Service temporarily unavailable"
- Q6 (AI chip screener) → 0 ticker mentions, screener tool returned empty
- Q7 (Tesla contradictions) → HTTP 503

**Pass rate against the plan's gates**:
| Gate | Required | Actual | Result |
|---|---|---|---|
| ≥ 6/8 USEFUL on audit questions | ≥ 6 | 3 (Q1, Q3, Q8) | **FAIL** |
| 0 HARMFUL across all questions | 0 | ≥ 1 (Q4-v1) | **FAIL** |
| Q5/Q7 not 503 (multi-tool fallback works) | 200 | 503 | **FAIL** |
| Q6 mentions ≥ 3 tickers | ≥ 3 | 0 | **FAIL** |

**Fix required** (deferred — significant scope): a follow-up PRD/plan to:
1. Make the agent reliably call `get_fundamentals_history` for revenue/EPS questions (current calls are coming back empty — likely a tool routing or budget issue)
2. Implement actual claim-kind validation beyond numbers (the rationalisation prose passes today because it has no numbers in it)
3. Tighten/loosen the premise-check rule so v4/v5/v6 don't over-refuse legitimate comparison questions
4. Implement multi-tool fallback for Q5 (currently a single-tool failure → 503)
5. Wire `screen_universe` properly so Q6 returns actual ticker lists

---

## Data-Quality SLO Status (G-1 vs live DB)

After F-LIVE-002+003+004+005 fixes, the SLO breakdown:

| Test | Result | Notes |
|---|---|---|
| AGE coverage (5 tests) | 4 pass / 1 skip-on-empty | 0 relations / events in live DB; no work to assert against |
| Relations quality (8 tests) | 6 pass / 1 fail / 1 skip | Macro sentinel exists, no NULL confidence, no orphan FKs, no self-loops. PASS_WITH_NOTES: `test_macro_sentinel_entity_exists` now passes |
| NLP quality (7 tests) | 2 pass / 5 fail | Fail mode: worker backlogs (`impact_score=0%`, `article_impact_windows=0`, `llm_relevance_score 70% NULL`) — fresh DB has no operational time |
| Enrichment (5 tests) | 1 pass / 4 fail | Definition embedding 10.5% NULL (>5% threshold), fundamentals_ohlcv 0%, description 59% NULL — worker backlogs |
| Path insight (3 tests) | 1 pass / 2 fail | F-LIVE-006: PathExplanationBatchWorker not deployed → 285 stale rows + gauge missing |

**Summary**: 14/29 G-1 PASS, 9/29 FAIL (5 are worker-backlog, 1 is F-LIVE-006, 3 are real-but-acceptable on fresh DB), 5/29 SKIP-on-empty, 1 (`test_retry_workers_gate_on_healthy_deps`) FAIL from pre-existing drift `c0303d5f` (not Phase 5c regression).

## Infra Resilience Status (G-2 vs live)

| Test | Result |
|---|---|
| Restart policy contract | PASS (18 services, FIX-3 patches confirmed) |
| Host-event survival (kill 3 deps + recover) | PASS — 11/11 app-tier survived |
| 7 app-tier containers stayed `Up` through the kill (long-lived connections auto-reconnect on dep return) | PASS |

The QA-3 P0 — "11 services would stay dead after host events" — is now CLOSED in live execution. The restart policies + connection-resilience patterns work.

## Phase 5c Commits

| SHA | Scope |
|---|---|
| `95ac9769` | F-LIVE-001 — APP_ENV=development in 9 docker.env.example templates |
| `fc0466fb` | F-LIVE-002 + F-LIVE-003 — migration 0044 entity_type fix + 0046 server_default fix |
| `930a823d` | F-LIVE-004 + F-LIVE-005 — G-1 placeholder syntax + column name |

## Outstanding Work (BLOCKING)

To upgrade Phase 5c verdict from FAIL to PASS, the following are required and beyond the scope of `/qa` (each needs a focused fix or follow-up plan):

1. **F-LIVE-006**: deploy `PathExplanationBatchWorker` in compose (add new service block + healthcheck + restart policy + dependencies). Should ride alongside existing `knowledge-graph-path-insight-worker`. ~1 hour of work.

2. **F-LIVE-007**: fix the F-1 PREPARE pass to convert `:name` → `$1`. Without this, the prepare audit is unusable. ~2 hours.

3. **F-LIVE-008 (CORE)**: the RAG agent's Q4 behavior is the entire reason PLAN-0093 was written. Live execution proves the patches are insufficient. Needs a NEW plan (PLAN-0094 or similar) that:
   - Makes the agent reliably call `get_fundamentals_history` for revenue/EPS questions
   - Adds claim-kind validation beyond numerics
   - Calibrates the premise-check rule to not over-refuse
   - Implements multi-tool fallback for Q5/Q7
   - Fixes Q6 screener empty-results

4. **Worker-backlog issues**: 5 G-1 NLP/enrichment SLOs need real operational time to validate (expected — fresh DB has no 24h+ data). Recommend re-running G-1 after the platform has been ingesting for 24h.

## Recommendation for the Project Owner

The plan's infrastructure work (Sub-Plans A, B, D, F) is sound — confirmed by the host-event survival + the fact that all 10 backend services are stable. The plan's RAG safety work (Sub-Plan E + the FIX-2 follow-up) does NOT achieve its goal in live execution. The original 2026-05-23 audit finding (AMD revenue fabrication) is NOT actually closed. Marking PLAN-0093 as complete + flipping TRACKING.md to "complete" is incorrect — the bell-weather Q4 still fabricates.

Either:
- (A) Revert TRACKING.md to `in-progress`, document Phase 5c findings, open a follow-up plan to address F-LIVE-008
- (B) Accept the infrastructure wins, mark this plan complete, file F-LIVE-008 as the seed of the next plan

Most teams in this situation would pick (B) — ship what's done, fix what isn't in the next sprint. That's defensible. But the original audit's title was "Intelligence Pipeline Remediation — KG-RAG + Infrastructure" and the KG-RAG half is still broken.

## Compounding Candidates

- **BP-NEW** "Lifespan assertion shipped without env wiring" (F-LIVE-001) — every `assert_*_or_die` paired with a grep test for the env var in every `docker.env.example`
- **BP-NEW** "Migration not run live before being merged" (F-LIVE-002, F-LIVE-003) — every migration PR must execute against an ephemeral DB in CI; if alembic head doesn't advance, fail the build
- **BP-NEW** "SQL DEFAULT cannot reference another column" (F-LIVE-003) — grep rule + REVIEW_CHECKLIST entry
- **BP-NEW** "Worker class added without compose deployment" (F-LIVE-006) — every new worker file must be paired with a `docker-compose.yml` service entry; CI check
- **BP-NEW** "F-1 PREPARE tool can't handle SQLAlchemy `:name`" (F-LIVE-007) — known limitation of the tool, document until fixed
- **HR-NEW** "Static QA cannot certify runtime correctness" — the meta-lesson from Phase 5c: 5 of the 6 P0s were missed by static analysis because they only manifest at runtime. Every claim of "this fix works" must be paired with a live execution before being marked as such.
