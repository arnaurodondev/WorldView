---
id: QA-PLAN-0093-PHASE-5
title: PLAN-0093 Phase 5 Adversarial QA Validation Report
date: 2026-05-24
plan: docs/plans/0093-intelligence-pipeline-remediation-plan.md
source_audit: docs/audits/2026-05-23-qa-intelligence-pipelines-report.md
branch: feat/plan-0093-remediation
methodology: 6 adversarial agents run in parallel, each independently assuming the implementation is wrong
mode: STATIC (live DBs unreachable; docker daemon stopped)
overall_verdict: FAIL
---

# PLAN-0093 Phase 5 — Adversarial QA Validation Report

## Verdict Summary

| Agent | Verdict | P0 | P1 | P2 | Notes |
|-------|---------|----|----|-----|-------|
| QA-1 Data-Quality | **FAIL** | 3 | 3 | 3 | 3 G-1 SQL queries reference non-existent columns/tables — would error against any real DB |
| QA-2 RAG Hostile-User | PASS_WITH_NOTES (static) | 3 + 4 predicted-HARMFUL | 4 | many | Live rag-chat unreachable; predictions based on prompt + validator review |
| QA-3 Infra Stress | **FAIL** | 1 | 1 | 1 | 11 API/UI containers lack `restart:` policy (defaults to "no") |
| QA-4 Schema/Migration | PASS_WITH_NOTES | 0 | 3 | several | 3 TRUNCATE migrations lack `APP_ENV != production` guard |
| QA-5 Architecture | **PASS** | 0 | 0 | 0 | All R8/R10/R11/R12/R25/R27 clean; 10/10 BP-405 spot-checks resolved |
| QA-6 Documentation | **FAIL** | 9 | 0 | 0 | Entire "Compounding (Mandatory)" section of the plan was skipped |

**Verdict logic** (per orchestrator topology):
- PASS = zero P0 from any agent
- PASS_WITH_WARNINGS = zero P0 from QA-1/2/3/4/5; ≤ 3 P0 from QA-6 (docs only)
- FAIL = any P0 from QA-1 through QA-5, OR > 3 P0 from QA-6

**OVERALL: FAIL** — P0 findings from QA-1 (data tests broken), QA-2 (static-only — needs live confirmation), QA-3 (infra restart gap), AND 9 P0 from QA-6 (well above the ≤ 3 threshold).

---

## QA-1 Data-Quality Auditor — FAIL

**Mode**: STATIC (no DB URLs set, docker stopped). Cannot verify any live SLO; instead audited whether the G-1 test SQL would correctly answer the audit's questions if run.

### P0 findings (3)

1. **`test_age_event_exposures_coverage`** queries table `entity_event_exposure` (singular). Real table per migration 0037 is `entity_event_exposures` (plural). Test will raise `UndefinedTable` against any real DB.
   - File: `tests/validation/test_age_coverage.py:13, 140, 145, 147`
   - Fix: rename to plural

2. **`test_enrichment_attempts_counter_advances`** queries `provisional_entity_queue.updated_at`. Column does not exist (schema has `created_at`, `resolved_at`, `retry_count`, `next_retry_at`, `processing_started_at`). Hard SQL error — **ironically reproduces the F-LOG-MIGRATION-001 pattern the audit warned about**.
   - File: `tests/validation/test_enrichment_quality.py:47`
   - Fix: replace with `SELECT count(*) FROM canonical_entities WHERE enrichment_attempts > 0 AND enriched_at > now() - interval '24 hours'`, OR use the actual queue column (`resolved_at` / `next_retry_at`). Note: original audit's concern was `canonical_entities.enrichment_attempts` being frozen, which is a different table than `provisional_entity_queue`.

3. **`test_summary_coverage`** EXISTS subquery joins `relation_summaries` on `subject_entity_id`/`object_entity_id`/`relation_type` columns that don't exist. Actual schema has FK `relation_id`, and `relations.canonical_type` (not `relation_type`). Hard SQL error.
   - File: `tests/validation/test_relations_quality.py:147-152`
   - Fix: rewrite EXISTS to `WHERE rs.relation_id = r.relation_id AND rs.is_current = true`

### P1 findings (3)

- T-G-1-03 audit-reference comments scrambled (cosmetic, but masks which finding each test guards)
- T-G-1-01 broad `except Exception → pytest.skip` masks "label not created" vs "AGE not deployed" — silent pass-by-skip on the exact bug the audit reported
- T-G-1-05 metric URL silently skips when unreachable — same silent-pass class

### Impact
**The Wave G-1 validation gate "5 test files, 28 sub-tests, all passing" is not satisfiable as-written.** A CI run against a live DB would surface 3 hard failures unrelated to data quality. Until fixed, no SLO claim can be programmatically verified.

---

## QA-2 RAG Hostile-User — PASS_WITH_NOTES (static)

**Mode**: STATIC (`RAG_CHAT_BASE_URL` not set). Verdict counts are predictive based on grader rubric + implementation review.

### Predicted verdict distribution (30 questions)
- USEFUL ~10/30
- MARGINAL ~9/30
- USELESS ~7/30
- **HARMFUL ~4/30 (predicted, unconfirmed)** — A1 (Apple ambiguity), A2 (self-comparison), A6 (BRK.B EPS), A10 (Apple-acquired-MSFT contradictory premise)

### P0 implementation gaps (3)

1. **No premise-contradiction refusal rule** in `libs/prompts/src/prompts/chat/tool_use.py:55-59`. When asked "Why did Apple acquire Microsoft last quarter?", LLM will synthesize plausible reasoning from tool data while accepting the false premise. Numeric validator doesn't check factual/relational claims.

2. **Quarter-label regex too narrow** in `numeric_grounding.py:96` and `grading.py:204`. `_QUARTER_RE` requires 4-digit year + optional FY prefix. LLM can write "Q3 revenue" (no year) and bypass the validator. Forms like "Q1 fiscal 2027" also miss.

3. **Numeric pool not entity-scoped** in `numeric_grounding.py:438-440`. `same_kind = [v for v, k in tool_values if k is kind]` mixes AMD + NVDA values. LLM could write "AMD's Q4 revenue was $68B" and the validator passes it because $68B exists in tool corpus (it's NVDA's actual figure). Q4 grader hardcodes AMD+NVDA ticker ceilings; survey has no equivalent for TSM/BRK.B/AAPL.

### P1 findings (4)

- `_resolve_entity_by_name` returns `candidates[0]` without ambiguity threshold (`intelligence.py:174`)
- Q6 hardcodes `forbid_invented_products` (only MI300); no generic guard for the survey
- Chat-orchestrator reprompt lacks entity-specific context (BRK.B Class B / TSM fiscal year)
- Prompt has no language-discipline clause for non-English queries

### Caveat
**Live execution required to confirm or refute the 4 predicted HARMFUL cases.** Static analysis cannot certify zero HARMFUL on its own.

---

## QA-3 Infrastructure Stress Tester — FAIL

**Mode**: STATIC (docker daemon stopped — fault injection not exercised).

### P0 finding (1)

**11 API/UI containers OMIT `restart:` policy entirely** (Docker Compose defaults to `"no"`):
```
alert, api-gateway, content-ingestion, content-store, gliner-server,
knowledge-graph, market-ingestion, nlp-pipeline, portfolio, rag-chat,
worldview-web
```
After the next 21:40-style daemon bounce, **the data layer auto-recovers but every API + UI surface stays dead** until an operator runs `docker start`. Contradicts "self-heals within 5 min" exit criterion.

The audit's F-LOG-INFRA-001 fix list focused on the 3 dependency gaps (ollama, schema-registry, market-data) + minio. The 11 application-tier containers were never added to the restart-policy contract. The G-2 test (`tests/validation/test_restart_policy.py:_CRITICAL_SERVICES`) only covers 7 infra services — the application tier is architecturally invisible to the regression guard.

### P1 finding (1)
**Soak test (`test_no_restart_loops.py:113-145`) cannot detect crashed-but-not-restarting containers** — it greps for `"restarting"` substring; an Exited container with `restart: "no"` sits in `Exited` state forever and is classified as "fine." Combined with the P0 above, an entire silent-failure class is invisible to the 24h soak.

### Library-level code (LGTM)
- rdkafka base config (`broker.address.ttl=30000`, `family=v4`) — correct
- `_connectivity_probe_loop` — correct (3 misses → `sys.exit(2)`, runs in executor, cancels on shutdown)
- `retry_on_startup` decorator — correct (warns each attempt, CRITICAL on exhaustion, backoff doubles)
- `assert_app_env_or_die` boot guard — wired into 10/10 backend services
- KafkaConsumerStalled Grafana alert — correct PromQL

---

## QA-4 Schema/Migration Validator — PASS_WITH_NOTES

**Mode**: STATIC (test DB URLs unset). Cannot run live upgrade/downgrade cycle.

### P1 findings (3)

1. **Migrations 0045, 0047 (intel) and 0020 (nlp) TRUNCATE without `APP_ENV != production` guard.** Each docstring claims pre-prod safety, but the assertion that `assert_app_env_or_die` provides is at *application startup* — not at migration runtime. If anyone ever runs `alembic upgrade head` against a populated DB (staging restored from prod dump, or accidental prod connection string), 4 KG tables + 1 NLP table are silently wiped with no rollback possible. **Plan T-A-1-03 promised this guard would be in every TRUNCATE migration** — it isn't.

2. **0045 CHECK constraint hard-codes 5 sentinel UUIDs** instead of consulting `is_system`. If a future sentinel is added via 0044's pattern (or one of the 5 IDs changes), the CHECK silently rejects valid sentinel self-loops. No test ties the CHECK constraint to the actual sentinel roster.

3. **0048 docstring claims partition forward-compat but has no post-upgrade verification** that all 8 partitions (`relations_p0..p7`) inherited the new columns.

### Other observations
- 0044's `is_system` column has zero application-code consumers (column created, indexed, seeded, but no repository filters by it). Adds INDEX maintenance cost for no current benefit. Likely a B-2 follow-up gap.
- 0046's deviation (kept `confidence_stale` column) is correctly documented and necessary (ConfidenceWorker still depends on it).
- 0047's app-level FK on `claim_id` (since `claims` is partitioned) is correctly handled in `relation_evidence.py:70-73`.

### Live cycle NOT RUN
`alembic downgrade -10 && alembic upgrade head` + the F-1 PREPARE pass require a reachable test DB. Recommend a CI gate.

---

## QA-5 Architecture Auditor — PASS

### Scope audited
- 35 NEW files under `services/` + `libs/`
- 58 MODIFIED files (excluding tests/alembic)
- 10 plan-promised symbol spot-checks (BP-405)

### Results
- **R10 (UUIDv7)**: PASS — no new `uuid.uuid4()` call sites
- **R11 (UTC-only)**: PASS — no new naive `datetime.utcnow()` or `datetime.now()` calls
- **R12 (structlog only)**: PASS — no stdlib `import logging` in any new non-test file
- **R8 (outbox for DB+Kafka)**: PASS — no new dual-write paths introduced
- **R25 (no infra in use cases)**: PASS — `chat_orchestrator.py`, `intent_inference.py`, `numeric_grounding.py`, `_entity_summary.py` all stay in correct layer
- **R27 (read-only uses ReadOnlyUoW)**: PASS — new application services are pure functions/stateless
- **BP-405 (no phantom names)**: PASS — all 10 spot-checked symbols (`assert_app_env_or_die`, `retry_on_startup`, `_connectivity_probe_loop`, `_bootstrap_age_labels`, `claim_for_enrichment`, `NumericGroundingValidator`, `_scrub_orphan_citations`, `_update_backlog_gauge`, `path_insight_explanation_pending_total`, `entity_summary_from_row`) found in source

### Verdict
Clean — 0 P0, 0 P1, 0 P2.

---

## QA-6 Documentation + Compounding Auditor — FAIL

### Promises kept (4 of 13)
- ✅ `docs/services/knowledge-graph.md` AGE bootstrap section (B-1 commit d3e9cac1)
- ✅ `docs/services/nlp-pipeline.md` routing v2 (C-1 commit 9c232b3e)
- ✅ `docs/services/market-data.md` symbol resolution (C-3 commit bdaa4cd2)
- ✅ `docs/specs/0026-news-intelligence-ranked-feed.md` routing v2 amendment
- ✅ `services/nlp-pipeline/.claude-context.md` (partial — covers C waves)

### P0 broken promises (9)

| # | Promise | Status |
|---|---------|--------|
| 1 | `docs/BUG_PATTERNS.md` — BP-545..BP-549 (5 entries from audit compounding section) | **NOT ADDED**; latest BP is 543 |
| 2 | `RULES.md` — R35 (depends_on: service_healthy mandate) | **NOT ADDED**; latest rule is R34 |
| 3 | `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` — HR-051/052/053 | **NOT ADDED**; IDs already used by PLAN-0084 for different patterns; the 3 PLAN-0093 patterns (silent-failure-as-restart-loop, prompt-supplements-pretraining, watermark-advances-on-partial-sync) never added under any ID |
| 4 | `.claude/review/checklists/REVIEW_CHECKLIST.md` — 3 new checks | **NOT ADDED** |
| 5 | `services/knowledge-graph/.claude-context.md` — new pitfalls | **UNCHANGED** since 49db67df |
| 6 | `services/rag-chat/.claude-context.md` — new pitfalls (E-1..E-5) | **UNCHANGED** since 49db67df |
| 7 | `docs/services/rag-chat.md` — intent inference + numeric grounding | **UNCHANGED** since 49db67df |
| 8 | `docs/MASTER_PLAN.md` — status update | **UNCHANGED** since 49db67df |
| 9 | `docs/plans/TRACKING.md` row 32 status `in-progress` → `complete`, QA date filled | **PARTIAL** (24/24 shown, but status not flipped + QA date column says "Phase 5 QA pending") |

### Memory check
- `PrunedDescriptionAdapter` not referenced anywhere in current memory files — already pruned. No action.

---

## Consolidated P0 Action List

### Code/test fixes (must fix before re-running QA)
| ID | Owner | Fix |
|----|-------|-----|
| QA-1.P0-1 | tests/validation | `entity_event_exposure` → `entity_event_exposures` |
| QA-1.P0-2 | tests/validation | `provisional_entity_queue.updated_at` does not exist — replace query |
| QA-1.P0-3 | tests/validation | `relation_summaries` join uses wrong column names |
| QA-2.P0-1 | libs/prompts + services/rag-chat | Add premise-contradiction refusal rule to `tool_use.py` |
| QA-2.P0-2 | services/rag-chat | Broaden `_QUARTER_RE` in `numeric_grounding.py` |
| QA-2.P0-3 | services/rag-chat | Entity-scope the numeric pool in `_matches_any` |
| QA-3.P0-1 | infra | Add `restart: unless-stopped` to 11 API/UI containers + extend G-2 test `_CRITICAL_SERVICES` |

### Live verifications still owed
- QA-1: re-run all 28 G-1 tests against a live `INTELLIGENCE_DB_URL_TEST` + `NLP_DB_URL_TEST` AFTER fixing the 3 P0 SQL bugs
- QA-2: fire the 30 adversarial questions through `tests/validation/chat_eval/harness.py` against a running rag-chat — must produce 0 HARMFUL
- QA-3: execute the host-event survival runbook + multi-dep-kill fault injection AFTER the 11 restart policies are in
- QA-4: run `alembic downgrade -10 && alembic upgrade head` + F-1 PREPARE pass against live DBs

### Docs/compounding fixes
- QA-6.P0-1..9: 9 individual fixes (BUG_PATTERNS, RULES, HIGH_RISK_PATTERNS, REVIEW_CHECKLIST, 3 service docs, MASTER_PLAN, TRACKING)

---

## Recommendation

Per the orchestrator stop conditions:
> "Any QA P0 finding from QA-1 or QA-2 → escalate to user before remediation"

Both have confirmed P0s. QA-3 also has a confirmed P0. **Escalating to user for remediation scope decision before spawning fix agents.**

The QA-5 PASS is meaningful — the architecture of what was built is sound. The failures cluster around:
1. **Test queries that wouldn't have been caught without a live DB** (QA-1's 3 SQL bugs) — exactly the F-LOG-MIGRATION-001 pattern the audit warned about
2. **A scope gap in the audit's restart-policy fix** (QA-3) — focused on infra deps but didn't enumerate application-tier services
3. **Implementation gaps in the RAG safety contract** (QA-2) that the static analysis predicts will manifest as HARMFUL responses on edge cases the original 8-question audit didn't probe
4. **The entire compounding (BP/HR/R) section of the plan was skipped** (QA-6)

None of these are deep architecture flaws — all are addressable with focused fix agents. The remaining question is whether to remediate-then-revalidate now, or land what's there and address fixes in a follow-up plan.
