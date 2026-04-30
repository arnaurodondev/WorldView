# QA Report: PLAN-0057 Waves A-5 + B-1 + B-2 + B-3 — Iteration 1

**Date**: 2026-04-30
**Skill**: `/qa` (iterative)
**Scope**: PLAN-0057 partial (Waves A-5 + B-1 + B-2 + B-3 shipped this session; plan now 7/24 done overall)
**Branch**: `feat/content-ingestion-wave-a1` (HEAD `87059f4e` — merge of A-5 worktree)
**Verdict**: **PASS_WITH_WARNINGS** — 0 BLOCKING; 1 actionable fix applied; 13 deferred enrichments.

---

## Executive Summary

Five specialist QA agents reviewed the four Sub-Plan A finishing wave (A-5 usage_logger threading) plus all three of Sub-Plan B (B-1 transit-loss fix, B-2 SQL schema fix, B-3 prompt rewrite). Consolidated triage:

- **Security**: APPROVE — no SQL injection, no format-string injection, no hardcoded secrets, tenant isolation preserved, no PII/prompt content in logs. 1 minor (`exc_info=True` stack-trace risk in fire-and-forget logger — acceptable per the agent's own assessment).
- **Distributed Systems**: 7 findings — 1 actionable HIGH (provisional savepoint failure leaves mention in zombie state). 6 informational/observability/concurrency notes that are documented behaviour or low-probability edge cases.
- **Data Platform**: PASS on all 10 mandate points — schema correctness, D-004 ordering, idempotency, DLQ, Avro envelopes, indexes all confirmed correct.
- **Architecture**: 11 findings — 1 false positive (#11 claimed B-3 not in HEAD; verified present at `entity_mention.py:21,145,206` and worker prompt with all 4 worked examples), 1 documentation gap (deferred), the rest PASS.
- **QA / Test Engineer**: 18 findings — over-graded severity. Most are test-coverage enrichments, not behavioural defects. 5 are quick-win additions; 13 are observability/metrics nice-to-haves.

**Net actionable from this iteration**: 1 fix (DS Finding-4 — `_insert_provisional` failure-path mention downgrade). Applied in this commit.

---

## Multi-Agent Review Summary

| Agent | Findings | BLOCKING | CRITICAL (raw) | After triage | Auto-PASS |
|---|---|---|---|---|---|
| QA / Test Engineer | 18 | 0 | 5 (over-graded) | 5 quick test wins (deferred) + 13 nice-to-have | — |
| Security Engineer | 8 | 0 | 0 | 1 minor (acceptable) | 7 PASS |
| Data Platform Engineer | 10 | 0 | 0 | 0 (all PASS) | 10 PASS |
| Distributed Systems Reviewer | 7 | 0 | 1 over-graded | 1 actionable HIGH (Finding-4) | — |
| Architecture Decision Lead | 11 | 0 | 1 false positive | 1 deferred docs gap | 9 PASS |
| **Total** | **54** | **0** | **0 after triage** | **1 applied + 5 deferred test enrichments + 1 deferred docs sweep** | **26 PASS** |

### Cross-agent signals (HIGH confidence — flagged by 2+ agents independently)
- None. Each finding is single-agent-sourced.

---

## Test Execution Results

| Layer | Scope | Tests | Status |
|---|---|---|---|
| Lint (ruff check) | libs + services | — | PASS_WITH_PRE_EXISTING (2 RUF059 in untouched files) |
| Format (ruff format --check) | libs + services | — | PASS_WITH_PRE_EXISTING (47 untouched files; 0 in scope) |
| Type check (mypy) | libs + services | 1,051 source files | PASS |
| Unit (nlp-pipeline) | tests/unit -m unit | 589 | PASS |
| Unit (knowledge-graph) | tests/unit -m unit | 650 | PASS |
| Integration (nlp-pipeline) | test_consumer_pipeline.py | 5 fail | NOT_REGRESSED — predates this work (verified via git stash round-trip) |
| Migration round-trip | intelligence-migrations | requires Postgres | DEFERRED |

---

## Findings — Triaged

### F-DS-04 (HIGH → APPLIED): provisional savepoint failure leaves mention in zombie state

**File**: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py:475-491` (Block 9 PROVISIONAL outcome handler)

#### Summary
When `_insert_provisional()` fails inside the SAVEPOINT (DB outage, unique constraint race, etc.), the prior code logged a warning but left the mention with `resolution_outcome=PROVISIONAL` and `provisional_queue_id=None`. Downstream `_build_raw_*` helpers (Wave B-1) then treat the mention as truly-unresolved (no queue_id → not in `entity_id_by_ref` → silent drop). The `UnresolvedResolutionWorker` filters on `resolution_outcome='unresolved'` so it does NOT re-attempt the mention either. Net: mention is stuck in permanent zombie state, drops every relation/event/claim referring to it forever.

#### Severity / Confidence
**Severity**: HIGH (in the rare savepoint-failure case; ZERO impact on the happy path)
**Confidence**: HIGH
**Flagged by**: Distributed Systems Reviewer

#### Fix
Downgraded the mention to `resolution_outcome=UNRESOLVED` in the except branch, with explicit `provisional_queue_id=None` and a richer warn-log including `downgraded_to="unresolved"`. The next `UnresolvedResolutionWorker` cycle will then pick it up. Restoration of correct invariant: no queue row → `resolution_outcome='unresolved'` → re-attempt.

```python
except Exception:
    mention.resolution_outcome = ResolutionOutcome.UNRESOLVED
    mention.provisional_queue_id = None  # explicit (already None)
    logger.warning(
        "entity_resolution.provisional_insert_failed",
        mention_id=str(mention.mention_id),
        downgraded_to="unresolved",
    )
```

**Effort**: 5 lines
**Risk**: Low (only triggers on the rare failure path; happy path unchanged)

---

### F-ARCH-11 (CRITICAL → DISMISSED FALSE POSITIVE): "B-3 code not in HEAD"

The Architecture agent claimed `get_unresolved_batch_with_context`, `UnresolvedMentionWithContext`, `_CLASSIFICATION_PROMPT_TEMPLATE` rewrite, and `context_sentence` plumbing were not present in HEAD. Direct verification:

- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/entity_mention.py:21` — `class UnresolvedMentionWithContext`
- `entity_mention.py:145` — `async def get_unresolved_batch_with_context(...)`
- `entity_mention.py:244-246` — wraps results with `context_sentence`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py:104-112` — all 4 worked examples (iShares Core S&P 500 ETF, MAS, "the company", Q3) inline in the prompt template
- `unresolved_resolution_worker.py:206` — fallback path also produces `UnresolvedMentionWithContext`

**Verdict**: agent failed to grep deeply enough or queried wrong commit. Code is fully present. No action.

---

### F-DS-03 (HIGH → DOCUMENTED): cross-session atomicity edge case

The DS agent flagged that if `nlp_session.commit()` succeeds but `intel_session.commit()` fails on the next line, the routing_decision row persists in nlp_db while the provisional_entity_queue rows for the same article get rolled back. The idempotency guard at `article_consumer.py:225` then skips re-processing on Kafka re-delivery (it only checks `routing_decision`). Net: provisional queue rows for that article are permanently absent.

**Triage**: this is a documented eventual-consistency property of D-004 (the canonical worldview UoW pattern across nlp_db + intelligence_db). The window is small (between two consecutive `commit()` calls inside the same context-manager exit) and only triggers on a DB outage in that microsecond. Architectural rewrite to close it would require either (a) adding a sentinel table `article_processing_complete` checked at idempotency time, or (b) outbox-pattern claim-check on intel_session writes — both substantial refactors.

**Verdict**: not a regression introduced by these waves; documented as known eventual-consistency property. Recommend monitoring `provisional_entity_queue` cardinality vs. expected per-article; alert on persistent gap.

---

### F-A5-* (Test coverage enrichments → DEFERRED to docs sweep / final QA gate)

5 quick-win tests recommended by the QA agent that are nice-to-have but not blocking the merge:

1. Parametrise `test_log_opens_session_and_calls_repository` to cover both `provider="ollama"` and `provider="deepinfra"` (current test hardcodes one).
2. Edge-case test: `mention_names` dedup at `deep_extraction.py:158` — surface_a appears twice → only once in mention_names list passed to prompt.
3. Edge-case test: all mentions unresolved → empty `entity_id_by_ref` → empty `raw_relations/events/claims` arrays in the enriched event.
4. Asymmetric resolution test: subject_ref resolved + object_ref provisional (covered indirectly by existing `test_subject_provisional_emits_flag_and_queue_id` and `test_object_provisional_emits_flag_and_queue_id`; explicit asymmetric-pair test would harden).
5. NULL section_title test: `get_unresolved_batch_with_context` returns rows where the chunk has no enclosing section (LEFT JOIN produces NULL) — verify `context_sentence` is just doc_title.

**Triage**: ~30 minutes total for 5 tests. Deferred because (a) all are nice-to-have edge cases, (b) the existing 9 unit tests on `_build_raw_*` plus 7 on the worker prompt cover the main behaviour, (c) the final QA gate at end of all 24 waves will use real-container integration tests that exercise these paths.

---

### F-ARCH-10 (Documentation gaps → DEFERRED to end-of-Sub-Plan-A docs sweep)

- `docs/services/nlp-pipeline.md`: no mention of `usage_logger` plumbing, `llm_usage_log` table as Block-10 destination, `LlmUsageLogProtocol` or `SessionScopedNlpUsageLogger`.
- `services/nlp-pipeline/.claude-context.md`: no mention of `provisional_queue_id` on EntityMention (B-2), no mention of `llm_usage_log` table.
- `docs/services/knowledge-graph.md`: no mention of KG-side `usage_logger` threading or `SessionScopedKgUsageLogger`.

**Triage**: defer to a single docs-sweep commit at the end of Sub-Plan A (after A-5 = last A-wave). Cleaner than scattering tiny doc updates across the per-wave commits.

---

### F-A5-001..005, F-B1-001/002, F-B2-001/002, F-B3-001..004, F-EDGE-001, F-ASYNC-001, F-SCHEMA-001, F-METRICS-001 — DEFERRED / DISMISSED

Test coverage / observability / metrics enrichments from the test agent. None are behavioural defects. Most either:
- Already covered by existing tests (the agent missed the test file)
- Concern the rare-edge-case branches that the final container-level QA will exercise
- Request observability features (Prometheus counters per provider, DLQ for failed cost logs) that are correctly out-of-scope for these foundation-tier waves and belong to a future observability PRD

---

### Security findings — APPROVED

All 8 security checkpoints PASS or acceptable-with-note. No SQL injection, format-string injection, hardcoded secrets, tenant-isolation breach, PII leakage, or unsafe DDL. The 1 minor note about `exc_info=True` exposing DB connection strings in stack traces is acceptable; the recommendation is to verify the observability platform's secret-masking config — out-of-scope for this wave.

---

## Recommendations

### Pre-merge (this commit)
- ✅ **F-DS-04 fix applied**: provisional savepoint failure now downgrades to UNRESOLVED.

### Deferred to end-of-Sub-Plan-A docs sweep
- F-ARCH-10 (3 service docs + 1 .claude-context.md update).

### Deferred to final container-level QA at end of all 24 waves
- 5 quick-win test additions (F-A5-002, F-B1-001, F-B1-002, F-B3-001, B-3 deepinfra-side usage log).

### Out of scope (not these waves)
- DLQ for failed cost-log writes (would belong to a Tier-3 observability PRD).
- Prometheus counter `nlp_llm_usage_log_total` per provider/capability (same).
- Cross-session atomicity sentinel-table refactor (F-DS-03 is a documented D-004 eventual-consistency property, not a regression).

### Compounding additions to BUG_PATTERNS.md (recommended)
- **BP-zombie-resolution-state**: when a savepoint-protected DB write inside a multi-stage resolution cascade fails, the mention's outcome MUST be downgraded to UNRESOLVED — leaving it as PROVISIONAL with no queue row creates an unrecoverable zombie state because both the relations builder AND the resolution-worker filter on outcome.

---

## TRACKING.md Update
Per `/qa` skill mandate: PLAN-0057 row's QA column is updated to `2026-04-30 (waves A-1..A-5, B-1..B-3 iter-1)`.

---

## Verdict
**PASS_WITH_WARNINGS** — Sub-Plan A (foundation) + Sub-Plan B (resolution unblocking) are merge-ready after applying F-DS-04. No BLOCKING issues. The structural fixes for the audit's headline findings (F-CRIT-02, -03, -05, -06, -07, -10, -12, F-MAJOR-10) are in place; pipeline observability (audit trail, cost log, processing path), 224-row canonical seeds, alias UNIQUE invariant, transit-loss fix, and improved unresolved-resolution prompt are all live. Ready to proceed to Sub-Plan C (alias enrichment) in a fresh session.
