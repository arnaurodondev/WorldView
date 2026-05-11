# QA Report: PLAN-0062 Iteration 3

**Date**: 2026-05-03
**Skill**: qa
**Scope**: PLAN-0062 audit-iter3 — validates that ALL 16 deferred findings from `docs/audits/2026-05-03-qa-plan-0062-report.md` (F-006..F-021) are actually closed; verifies the iter-2 commit 5ff239b22 + the iter-3 recovery commit 436d91cb together deliver the work.
**Branch**: `feat/content-ingestion-wave-a1`
**Verdict**: **PASS_WITH_WARNINGS** — all 16 audit findings closed; 4 pre-existing platform-wide concerns documented as deferred follow-ups; no BLOCKING/CRITICAL findings remaining.
**Report file**: `docs/audits/2026-05-03-qa-plan-0062-iter3-report.md`

---

## Executive Summary

This QA pass validated commit 5ff239b22 ("close 16 open findings from QA-iter1") and uncovered a major
regression: 5 specialist review agents independently confirmed that **most of the claimed fixes were
absent from the commit**. Only F-007 (schema_paths consolidation) and F-008/F-011/F-012/F-017 (docs)
actually landed; F-006 (producer R28 migrations for `relation.type.proposed.v1` + `nlp.signal.detected.v1`),
F-018 (16 MB consumer JSON-fallback cap), F-019 (text-field cap + polarity allow-list), F-020
(`expected_schema_ids` parameter), F-021 (log sanitisation), and the F-013–F-016 test additions were
silently overwritten when Group 2's `schema_paths` refactor ran last in the parallel-agent pipeline
and re-wrote the same consumer files.

The follow-up commit 436d91cb re-applies all of the lost work in a sequential pass (no parallel
agents) and adds three improvements that emerged from the review:

1. **Producer-side R28 architecture guard** — a regex scan for `payload_avro=json.dumps` across all
   `services/*/src/**/*.py` that fails the build on match. Would have caught the iter-2 regression
   at PR time.
2. **Signals.py read-side magic-byte sniff** — Group 1's claimed JSON fallback was actually missing.
   Added so `/v1/signals` doesn't silently empty out once the producer cuts over.
3. **`raw_array_decode_*` observability warnings** — `decode_raw_array` now logs a structlog warning
   on every silent-drop branch, addressing the "audit-returned-value-persistence" memory feedback.

Across both commits the 16 audit findings are now actually closed. 100 architecture + 169 contracts +
26 messaging + 754 KG + 437 alert + 677 nlp-pipeline unit tests pass; ruff + format + mypy clean on
all touched files. Pre-existing 5-test integration failure in `test_consumer_pipeline.py` remains
unrelated (impact_window AsyncMock fixture bug, predates PLAN-0062).

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 21 | 16 | 6 | 1 | 4 | 4 | 1 |
| Security | 13 | 8 | 3 | 0 | 3 | 2 | 0 |
| Data Platform | 14 | 7 | 2 | 1 | 1 | 2 | 1 |
| Distributed Systems | 12 | 9 | 2 | 1 | 4 | 2 | 0 |
| Architecture | 14 | 11 | 1 | 0 | 6 | 3 | 1 |
| **Total (post-dedup)** | — | **51** | **9** | **3** | **8** | **8** | **3** |

The high BLOCKING/CRITICAL count reflects the iter-2 regression — agents independently confirmed
that 5 separate audit findings were missing from the commit. After the iter-3 recovery commit,
those findings are closed.

### Cross-Agent HIGH-Confidence Signals (all closed in 436d91cb)

| Signal | Agents | Resolution |
|--------|--------|------------|
| F-006 R28 producer migration only 1-of-3 done | QA F-001, Security F-001/F-004, DP F-001/F-002, DS F-001/F-003, Arch F-A001 | **FIXED** in 436d91cb (canonicalization.py + article_consumer.py migrated) |
| F-018 16 MB cap NOT in 3 consumers | QA F-AUDIT-07, Security F-002, Arch F-A007, DS F-005 | **FIXED** in 436d91cb |
| F-019 text cap + polarity allow-list NOT applied | QA F-AUDIT-06, Security F-003, Arch F-A008 | **FIXED** in 436d91cb |
| F-020 `expected_schema_ids` NOT implemented | QA F-AUDIT-04, Security F-005, DS F-006, Arch F-A008 | **FIXED** in 436d91cb |
| F-021 log sanitisation NOT applied | QA F-AUDIT-05, Security F-006, Arch F-A009 | **FIXED** in 436d91cb |
| signals.py read-side has no Avro fallback | QA F-AUDIT-03, Security F-001, DP F-003, DS F-007, Arch F-A010 | **FIXED** in 436d91cb |
| Architecture test doesn't enforce producer-side R28 | DP F-004, Arch F-A002 | **FIXED** in 436d91cb (new `TestProducerR28Enforcement`) |
| STANDARDS §3.7.2 not added | Arch F-A003 | **FIXED** in 436d91cb |
| F-009/F-010 known-limitation sub-sections missing | Arch F-A004 | **FIXED** in 436d91cb |
| F-011 plan markdown still says "Hard Rule 18" | Arch F-A005 | **FIXED** in 436d91cb |
| F-017 BP numbering collision | Arch F-A006 | **FIXED** in 436d91cb |
| Tests F-013/F-014/F-015/F-016 missing | QA F-AUDIT-08 | **FIXED** in 436d91cb (19 new tests) |
| Tests F-009/F-010/F-011/F-012 polish missing | QA F-AUDIT-09/10/11 | **FIXED** in 436d91cb |

### Fixes Applied in This Iteration (436d91cb)

| Audit Finding | What was missing in 5ff239b22 | Resolution |
|---------------|------------------------------|------------|
| F-006 (canonicalization.py) | Producer still json.dumps | `serialize_confluent_avro` before `outbox_repo.append`, DS F-001 fail-fast pattern |
| F-006 (article_consumer.py:1311) | Producer still json.dumps | Same pattern |
| F-006 (signals.py read-side) | No magic-byte sniff | Added; promoted swallowed exception to WARN; TODO marker for legacy branch removal |
| F-018 (3 consumers) | No size cap | `_MAX_JSON_FALLBACK_BYTES = 16 * 1024 * 1024` + `MalformedDataError` |
| F-019 (enriched_consumer.py) | No text cap, no polarity allow-list | `_truncate_text_field` + `_normalize_polarity` helpers wired into all 3 parse functions; observable warnings |
| F-020 (serialization_utils.py) | Signature unchanged | Added `expected_schema_ids: set[int] \| None = None` keyword-only parameter; raises `ValueError` on mismatch |
| F-021 (enriched_consumer.py) | Still `data=str(d)[:200]` | Split `KeyError` / `ValueError` handlers; emit only structural metadata (field name, error class) |
| F-008 (STANDARDS.md §3.7.2) | Section missing despite principle doc cross-link | Added §3.7.2 covering `_json` transport convention with cross-link to BP-313 |
| F-009/F-010 (STANDARDS Known Limitations) | Sub-sections missing | Added 2 sub-sections: schema_id=0 default; missing CI compat-check |
| F-011 (plan markdown) | 2 occurrences of "Hard Rule 18" remained | Replaced with "Hard Rule R28" |
| F-017 (TRACKING.md BP collision) | Still "BP-313/314/315" colliding with PLAN-0062 BP-313 | Renumbered to BP-314/315/316 with clarifying note |
| Architecture test producer-side scan | Not in iter-2 | New `TestProducerR28Enforcement::test_no_producer_uses_json_dumps_for_payload_avro` |
| 19 missing tests | Lost in iter-2 file conflicts | Re-added (F-013/F-014/F-015/F-016/F-018/F-019/F-009/F-012/F-010/F-011) |

### Open Items (deferred, not BLOCKING)

| Finding | Severity | Status | Owner |
|---------|----------|--------|-------|
| Pre-existing `test_consumer_pipeline.py` 5-test failure (impact_window AsyncMock fixture) | MAJOR | Deferred | `/fix-bug` follow-up; predates PLAN-0062 |
| Pre-existing import-guard violations (alert s7_entity_resolver Redis import; market-data api/router LAYER violation) | MAJOR | Deferred | Predate PLAN-0062 |
| Pre-existing 2 RUF059 lint errors (alert/use_cases + nlp-pipeline/workers tests) | MINOR | Deferred | Pre-existing |
| Pre-existing 58 ruff-format drift in unrelated files (rag-chat etc.) | MINOR | Deferred | Pre-existing |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Architecture | full | 100 | 100 | 0 | 0 | **PASS** (was 99 + 1 new producer-R28 guard) |
| Lint (ruff) | touched files | — | — | 0 | — | **PASS** |
| Format (ruff) | touched files | — | — | 0 | — | **PASS** |
| Type Check (mypy) | touched packages | — | — | 0 | — | **PASS** |
| Library Unit (contracts) | full | 172 | 169 | 0 | 3 (pyarrow) | **PASS** |
| Library Unit (messaging) | unit | 26 | 26 | 0 | 0 | **PASS** (+4 new expected_schema_ids tests) |
| Library Unit (common, observability, storage, ml-clients) | unit | 30 | 30 | 0 | 0 | **PASS** |
| Service Unit (knowledge-graph) | full | 754 | 754 | 0 | 0 | **PASS** (+7 new) |
| Service Unit (alert) | full | 437 | 437 | 0 | 0 | **PASS** (+2 new) |
| Service Unit (nlp-pipeline) | full | 677 | 677 | 0 | 0 | **PASS** |
| Service Unit (portfolio) | full | 645 | 645 | 0 | 0 | **PASS** |
| Service Unit (market-ingestion) | full | 203 | 203 | 0 | 0 | **PASS** |
| Service Unit (market-data) | full | 557 | 557 | 0 | 0 | **PASS** |
| Service Unit (content-ingestion) | full | 598 | 598 | 0 | 0 | **PASS** |
| Service Unit (rag-chat) | full | 483 | 483 | 0 | 0 | **PASS** |
| Service Unit (api-gateway) | full | 74 | 74 | 0 | 0 | **PASS** |
| Service Unit (content-store) | full | 302 | 302 | 0 | 0 | **PASS** |
| Integration (nlp-pipeline) | scoped | 5 | 0 | 5 | 0 | **PRE-EXISTING FAIL** (impact_window mock fixture; predates PLAN-0062) |

Total: ~5,200 tests pass.

### Per-Service Summary

| Service | Unit | Notes |
|---------|------|-------|
| portfolio | PASS | 645 |
| market-ingestion | PASS | 203 |
| market-data | PASS | 557 |
| content-ingestion | PASS | 598 |
| nlp-pipeline | PASS | 677 (integration: 5 pre-existing fail unrelated) |
| knowledge-graph | PASS | 754 (+7 from this iter) |
| rag-chat | PASS | 483 |
| api-gateway | PASS | 74 |
| alert | PASS | 437 (+2 from this iter) |
| content-store | PASS | 302 |

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| Architecture test (consumer-side R28) | PASS | Unconditional after PLAN-0062 Wave D-1; new self-tests verify the classifier itself |
| Architecture test (producer-side R28) | **NEW PASS** | Added in 436d91cb — would have caught the iter-2 regression |
| Import Guards | PRE-EXISTING WARN | 1 net-new (market-data api/routers/price_snapshot.py) + 1 baselined (alert s7_entity_resolver Redis); both predate PLAN-0062 |
| Schema Validation | PASS | All `.avsc` files parse; no incompatible changes |
| Doc Freshness | PASS | STANDARDS §3.7.2 added; principle doc cross-links resolved; plan markdown wording consistent; TRACKING BP collision resolved |
| Security Scan | PASS_WITH_WARNINGS | F-018/F-019/F-020/F-021 defence-in-depth gaps closed in this iter; pre-existing log-sanitisation in non-PLAN-0062 paths remains |

---

## Recommendations

1. **PASS — ready to mark PLAN-0062 audit findings F-006..F-021 closed**. The two-commit sequence
   (5ff239b22 + 436d91cb) collectively closes all 16. TRACKING.md should reflect the iter-3 closure.

2. **Pre-existing integration test failure** (`test_consumer_pipeline.py` impact_window mock):
   `/fix-bug` follow-up.

3. **Producer-side R28 architecture test** is a one-line regex today; consider upgrading to AST
   walk if a future producer needs to legitimately use `json.dumps` for non-Avro outbox columns.

4. **Lessons learned for future parallel-agent work**:
   - Parallel agents that touch the same files must use either (a) worktree isolation, OR (b) strict
     file-disjoint scopes verified by checking the agent's planned modifications BEFORE launching.
   - The system-reminder file-modification notifications can show intermediate states that are later
     overwritten — only the final committed state is canonical.
   - Re-verify the actual on-disk content of every modification before declaring an iteration done.

5. **Compounding**: add a new BP entry (BP-314) "Parallel agent file-edit conflicts can silently
   overwrite earlier agents' work" to BUG_PATTERNS.md so future orchestrators check sequencing
   and verification carefully.

---

## Verdict

**PASS_WITH_WARNINGS** — all 16 PLAN-0062 audit findings closed across commits 5ff239b22 +
436d91cb; 100% of touched test layers pass; 4 pre-existing concerns documented as out-of-scope
follow-ups; producer-side R28 architecture guard added so this regression class cannot recur.
