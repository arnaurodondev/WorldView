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

---

# Annex A — Root Causes & Exact Patches (Investigation Phase, 2026-05-24)

After the initial QA pass returned FAIL, four investigation agents (INV-1 through INV-4) read the authoritative schema, prompt, compose, and docs to produce file-level patches. This annex is the **source of truth for fix agents** — every patch below is line-anchored against the head of `feat/plan-0093-remediation` as of commit `9e5958e8`.

## A.1 — QA-1 Root Cause: 3 G-1 SQL Bugs (INV-1)

### Bug 1 — `tests/validation/test_age_coverage.py` (singular table name)
**Root cause**: Test references `entity_event_exposure` (singular); authoritative table is `entity_event_exposures` (plural), defined identically in intelligence-migrations 0004:210, 0007:68, 0037:127. Every site against this table will raise `UndefinedTable`.

**Patch** (4 sites): lines 13, 140, 145, 147 — change `entity_event_exposure` → `entity_event_exposures`. Same for the docstring at line 13.

**Validation hook**: `grep -n "entity_event_exposure\b" tests/validation/test_age_coverage.py` must return zero matches post-patch.

### Bug 2 — `tests/validation/test_enrichment_quality.py:47` (wrong table entirely)
**Root cause**: Query is `provisional_entity_queue.updated_at` — but that column doesn't exist on `provisional_entity_queue` (schema: `created_at, resolved_at, retry_count, next_retry_at, processing_started_at`). **More importantly**, the SLO's actual target is `canonical_entities.enrichment_attempts` being frozen (audit F-DB-ENRICHMENT-001 at line 237: "1,790 of 5,230 canonical_entities (34%) have `enriched_at IS NULL` AND every row has `enrichment_attempts=0`"). The test queries the wrong table.

**Patch**: replace the SLO query with:
```sql
SELECT count(*) FROM canonical_entities WHERE enriched_at >= now() - interval '24 hours'
```
And update docstring + failure-message to cite F-DB-ENRICHMENT-001 + `StructuredEnrichmentWorker` properly. Asserts `> 0` (no enrichment in 24h = worker stalled).

### Bug 3 — `tests/validation/test_relations_quality.py:147-152` (non-existent join columns)
**Root cause**: EXISTS subquery joins `relation_summaries` on `subject_entity_id`, `object_entity_id`, `relation_type` — none exist on `relation_summaries` (per migration 0001:440-453, the columns are `summary_id, relation_id, summary_text, evidence_count, ...`). Also `relations` has `canonical_type` not `relation_type`. Even the right-hand side of the equality would fail.

**Patch**: replace EXISTS clause with `WHERE rs.relation_id = r.relation_id AND rs.is_current = true`. Aligns with the unique partial index `uidx_relation_summaries_current` (migration 0001:456).

---

## A.2 — QA-2 Root Cause: 3 RAG Safety Gaps (INV-2)

### Gap 1 — Premise-contradiction refusal missing
**Root cause**: `libs/prompts/src/prompts/chat/tool_use.py:44-59` has STRICT RULES + FORBIDDEN blocks; no rule obligates the LLM to challenge a contradictory premise in the user's question. `numeric_grounding.py` only checks numbers/quarters, never relational claims.

**Patch**: prepend new STRICT RULE to `tool_use.py` template (before the existing rules):
```
- PREMISE CHECK: Before answering, identify any factual claims embedded in
  the user's question (e.g. 'Why did X acquire Y last quarter?'). For each
  such claim, verify it appears in a tool result before treating it as true.
  If NOT supported, refuse: "I cannot find evidence that <verbatim claim>.
  Tool <name> returned <N> rows and none support this." Do NOT speculate.
```
Plus add to FORBIDDEN: `- Accepting M&A, partnership, spin-off, leadership, or product-launch claims from the user's question without tool confirmation.`

**Regression test**: assert rendered prompt contains literal strings `"PREMISE CHECK"` and `"refuse to answer"`. Add A10 question to `tests/validation/chat_eval/questions.py` with `must_mention_any_of=["cannot find evidence", "no evidence", "I cannot confirm"]`.

### Gap 2 — `_QUARTER_RE` too narrow
**Root cause**: `numeric_grounding.py:96` regex `\bQ([1-4])\s*[/-]?\s*(20\d{2})\b` requires 4-digit year, no FY support. `grading.py:204` allows optional FY but year still mandatory. Bypass forms: "Q3 revenue" (no year), "Q1 FY26" (2-digit), "Q1 fiscal 2027".

**Patch**:
1. Replace `_QUARTER_RE` with verbose pattern matching all canonical forms + 2/4-digit years; add `_normalize_quarter_label` helper that canonicalizes to `Q<n> 20YY`.
2. Add `_BARE_QUARTER_RE` + `_FINANCIAL_KW_RE` + `_extract_bare_quarters()` helper — bare quarters near financial keywords are treated as ungrounded with snippet `"Q3 (no year)"`.
3. Mirror the regex change in `grading.py:204` with 2-digit year normalization.
4. Wire `_extract_bare_quarters` into `NumericGroundingValidator.validate` after line 414.

**Regression tests**: `TestQuarterLabelVariants` class with 4 cases (Q1 FY26 → matches Q1 2026; Q1 fiscal year 2027 mismatch; Q3 revenue → bare-quarter fail; Q4 chip → no fail without financial keyword).

### Gap 3 — Numeric pool not entity-scoped
**Root cause**: `_flatten_tool_values` at `numeric_grounding.py:264-317` returns `list[tuple[float, FieldKind]]` with no entity annotation. Same-kind pool at line 438 mixes AMD + NVDA values — LLM could write "AMD's Q4 revenue was $68B" and validator passes because $68B exists in NVDA's tool corpus.

**Patch**:
1. Replace flat tuple with `@dataclass(frozen=True) class ToolValue(value, field_kind, entity_tag)`.
2. Add `_entity_tag_for(raw)` helper: extracts entity from `raw.entity_id` UUID > `raw.item_id` matched by `_ITEM_ID_TICKER_RE` > `citation_meta.entity_name` > `""`.
3. Validator-side: add `_nearest_entity_tag(response, raw_token)` helper that finds the ticker mentioned within 100 chars BEFORE the number. When entity_tag is identified, restrict pool to matching entities. When not, fall back to per-kind pool with `tol=0` (exact match only).

**Regression tests**: `TestCrossEntityLeakage` — assert AMD+NVDA mixed corpus correctly rejects "$68B AMD revenue".

### Bonus P1 triage from INV-2
- **`_resolve_entity_by_name` ambiguity threshold** (intelligence.py:174): real bug, fix alongside P0s. Log `tool_entity_ambiguous` warning + return None when top-2 similarity diff < 0.10.
- **Q6 hardcoded forbid list**: defer (cost > benefit, partial overlap with new premise-check)
- **Reprompt entity-specific context** (chat_orchestrator.py:944-963): real bug, fix alongside P0s (modest enrichment of rewrite payload with `canonical_name`, `ticker`).
- **Language-discipline clause**: defer (no non-English test cases yet).

---

## A.3 — QA-3 Root Cause: 11 Containers Missing Restart Policy (INV-3)

### Per-service decision
All 11 are long-running (FastAPI APIs / ML inference / Next.js frontend). Unified policy: `restart: unless-stopped`.

| Service | Justification |
|---|---|
| alert | Long-running FastAPI (port 8010); silent alerting outage is security-relevant |
| api-gateway | S9 stateless reverse proxy — sole platform ingress |
| content-ingestion | S3 RSS/EODHD API plane (port 8004) |
| content-store | S5 storage API (port 8005) |
| gliner-server | ML inference (10-min start_period for model download — must auto-recover) |
| knowledge-graph | S7 API (port 8007) |
| market-ingestion | S2 API (port 8002) |
| nlp-pipeline | S6 API (port 8006) |
| portfolio | S1 API (port 8001) |
| rag-chat | S8 chat WebSocket (port 8008) |
| worldview-web | Next.js production frontend (port 3001) |

### Compose patch
Add `restart: unless-stopped` to each of the 11 service blocks (after the healthcheck block, with PLAN-0093 QA-3 comment). 11 single-line additions in `infra/compose/docker-compose.yml`.

### Test patch — unified critical list
Grow `tests/validation/test_restart_policy.py:_CRITICAL_SERVICES` from 7 to 18 entries (add the 11 above). Keep `tests/infra/test_compose_restart_policy.py` unchanged (6-entry historical anchor — Sub-Plan A baseline pin) with cross-reference comment to the superset.

### Soak detector patch (P1)
`tests/validation/soak/test_no_restart_loops.py` currently greps for `"restarting"` substring only — misses `Exited` containers. Replace with dual-streak detector:
1. `_snapshot_container_states()` returns `{name: classification}` where classification ∈ {up, restarting, down, unknown}
2. Take `expected_up` baseline at soak start (every `worldview-*` container currently Up)
3. Track two streaks per container: `restart_streak` AND `down_streak`
4. Fail if either crosses `_FAILURE_THRESHOLD` (3 samples × 5min = 15min)

One-shot `*-init` / `*-migrate` containers are correctly EXCLUDED from `expected_up` (already Exited at baseline).

---

## A.4 — QA-4 Migration Patches (INV-4)

### A.4.1 — APP_ENV guard on 3 TRUNCATE migrations
Add shared helper (or inline, but prefer module):
```python
def _assert_truncate_allowed(table: str) -> None:
    """Refuse to TRUNCATE in production unless explicitly overridden.

    The platform-wide assert_app_env_or_die runs at APP startup — Alembic
    migrations run independently (CI, ad-hoc CLI, restored staging dumps)
    and bypass that gate.
    """
    if os.environ.get("APP_ENV", "").lower() == "production":
        if os.environ.get("ALLOW_DESTRUCTIVE_MIGRATION") != "1":
            raise RuntimeError(
                f"Refusing to TRUNCATE {table!r} in APP_ENV=production. "
                "Set ALLOW_DESTRUCTIVE_MIGRATION=1 to override."
            )
```
Apply to:
- `services/intelligence-migrations/alembic/versions/0045_add_relations_fk_constraints.py:60` — `_assert_truncate_allowed("relations + dependents")`
- `services/intelligence-migrations/alembic/versions/0047_evidence_raw_not_null_fks.py:51` — `_assert_truncate_allowed("relation_evidence_raw")`
- `services/nlp-pipeline/alembic/versions/0020_entity_mentions_tenant_not_null.py:44` — `_assert_truncate_allowed("entity_mentions")`

### A.4.2 — 0045 sentinel CHECK constraint
Add a comment block before the CHECK definition pointing to `0044._SENTINELS`. Add new regression test `services/intelligence-migrations/tests/migrations/test_sentinel_check_constraint_sync.py` that dynamically imports `_SENTINELS` from 0044 (via importlib) and regex-extracts the UUIDs in 0045's CHECK source. Asserts set equality. Pure text test, no DB needed.

### A.4.3 — 0048 partition verification
Append a `DO $$ ... RAISE EXCEPTION ...` block to `upgrade()` that queries `pg_inherits` + `information_schema.columns` and raises if any `relations_p*` partition is missing `summary_attempt_count`. Cheap, single-pass, surfaces partition-DDL desync at migration time.

---

## A.5 — QA-6 Documentation Patches (INV-4)

### Numbering corrections (important)
- **BP**: plan called for BP-545..549; current max is BP-543 → **renumber to BP-544..548 (5 patterns)**. The audit only enumerated 5 patterns.
- **HR**: plan called for HR-051/052/053; those IDs are taken by PLAN-0084 → **renumber to HR-063/064/065**.

### B.1 — BUG_PATTERNS.md (append 5 rows after BP-543)
- **BP-544**: AGE vlabel/elabel missing → silent ProgrammingError → watermark advance (B-1 fix, source F-KG-PERSIST-001)
- **BP-545**: rdkafka DNS cache holds stale broker IPs; consumers silently stop (A-2 fix, source F-LOG-003)
- **BP-546**: Repository SELECT with stale column name fails at execution time, not parse time (F-1 production guard; QA-1 P0s are repro of this pattern in TEST CODE)
- **BP-547**: LLM agent extrapolates from N=1 tool row; numeric hallucination wrapped in prose (E-2 partial fix; QA-2 P0-1 premise refusal still OPEN)
- **BP-548**: `enrichment_attempts` counter that never UPDATEs makes a partial-index sweep look correct (D-1 fix, source F-DB-ENRICHMENT-001)

### B.2 — RULES.md R35 (insert after line 345, before `---`)
Verbatim text + Summary Table row. Wording: "Every long-running service that calls postgres/valkey/kafka/an LLM endpoint MUST declare `depends_on: { <dep>: { condition: service_healthy } }` in docker-compose. Optional deps wrap startup probes in `@retry_on_startup`. `condition: service_started` is insufficient — must be `service_healthy`."

### B.3 — HIGH_RISK_PATTERNS.md (append after line 1018)
- **HR-063**: Silent-Failure-as-Restart-Loop (Watermark Advance in Generic Exception Handler) — BP-544/548 are real instances
- **HR-064**: Prompt-Supplements-Pretraining for Numerical or Factual Claims — BP-547 + QA-2 P0-1 are real instances
- **HR-065**: Watermark Advances on Partial Sync (or Empty Result Counted as Success) — BP-544/548/533 are flow-related

### B.4 — REVIEW_CHECKLIST.md (3 new bullets)
- Under `## 7b. Docker Compose Completeness`: depends_on healthcheck check (R35 reference)
- Under `## 6b. Schema & Data Pipeline Integrity`: repository SELECT columns exist check (BP-546 reference)
- Under `## 10i. LLM Agent Loop` (line 181, NOT the Frontend Mutations 10i): no-pretraining clause check (HR-064 reference)

### B.5 — Service docs
- **`docs/services/rag-chat.md`**: new H2 `## PLAN-0093 E-Wave Hardening (2026-05-24)` with 6 bullets (intent inference, numeric grounding, name resolution, multi-tool fallback, citation validation, plus pointer to audit)
- **`services/knowledge-graph/.claude-context.md`**: 7 new pitfall bullets (B-1..B-4 + D-1..D-3)
- **`services/rag-chat/.claude-context.md`**: 5 new pitfall bullets (E-1..E-5)
- **`docs/MASTER_PLAN.md`**: per INV-4's analysis, MASTER_PLAN has no plan-completion log table. Recommend Option 1: inline PLAN-0093 reference in §3 Service Catalog rows for S6/S7/S8 (rather than creating a new pattern). Defer to user decision.

### B.6 — TRACKING.md row 32
After all QA-4 + QA-6 fixes land AND Phase 5 re-QA passes:
- Status: `in-progress` → `complete`
- Blocking On: `Phase 5 QA pending` → `none`
- Append to title block: outcome note ("Phase 5 QA initial FAIL → patches applied → re-QA PASS_WITH_NOTES")

**Open question from INV-4**: TRACKING.md `## Conventions` line 282 references moving completed rows but no Completed Plans table exists. Either (a) add new `## Completed Plans` section, or (b) leave in Active with status `complete` (current convention drift). Defer to user.

---

# Annex B — Fix Orchestration Plan

After this annex is committed, spawn the following fix agents (most can run in parallel):

| Fix Agent | Scope | Source patches |
|---|---|---|
| FIX-1 | QA-1 G-1 SQL bugs (3 test files) | A.1 |
| FIX-2 | QA-2 RAG safety contract (5 source files, 2 test files) | A.2 |
| FIX-3 | QA-3 compose + tests (3 files) | A.3 |
| FIX-4 | QA-4 migration guards + tests (4 files) | A.4 |
| FIX-5 | QA-6 BUG_PATTERNS + RULES + HIGH_RISK_PATTERNS + REVIEW_CHECKLIST (4 files) | A.5 / B.1-B.4 |
| FIX-6 | QA-6 service docs (3 files) | A.5 / B.5 |

FIX-1..FIX-6 are independent (no file overlap). Run in parallel via 6 worktree agents.

After all 6 commit + merge, spawn Phase 5b — a fresh adversarial QA team (QA-1', QA-2', QA-3', QA-4', QA-6') re-running the focused checks against the fixed code.
