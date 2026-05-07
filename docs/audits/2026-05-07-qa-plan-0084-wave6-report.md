# QA Report: PLAN-0084 Wave 6 + Multi-Agent Review

**Date**: 2026-05-07 UTC
**Skill**: qa
**Scope**: PLAN-0084 Wave 6 test coverage + 5-agent multi-agent review
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: PASS_WITH_WARNINGS
**Commits**: Wave 6 (0a3ad290) + auto-fixes (6940d87c)

---

## Executive Summary

Wave 6 implemented test coverage for all 11 PLAN-0084 deferred QA findings (F-001, F-003–F-005, F-008–F-013, DP-009) across 7 test files. A 5-agent multi-agent review then ran across the full PLAN-0084 scope (47 source files, 33 test files). The agents produced 36 deduplicated findings. Three auto-fixes were committed (DP-005: dynamic _dedup_prefix in two KG consumers, ARCH-005: CanonicalEntityPort re-export parity, ARCH-003: stale xfail docstring). The most critical open items are: (1) 7 hand-rolled KG consumers lack Valkey error handling — a Valkey outage causes consumer stalls; (2) canonical tickers MULTI/EXEC has a partial-failure window that could wipe the cache; (3) the refresh loop lacks exponential backoff. All 5 test layers (architecture, lint, mypy, unit tests across all 4 affected services + messaging lib) pass cleanly.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 17 | 15 | 0 (FP) | 3 | 8 | 3 | 1 |
| Security | 11 | 10 | 0 | 1 | 5 | 3 | 1 |
| Data Platform | 10 | 10 | 0 | 2 | 4 | 3 | 1 |
| Distributed Systems | 8 | 11 | 0 | 2 | 7 | 1 | 1 |
| Architecture | 14 | 5 | 0 | 0 | 2 | 3 | 0 |
| **Total (deduped)** | — | **36** | **0** | **6** | **17** | **8** | **3** |

Note: QA-010 (BLOCKING — missing pytest markers) was a **false positive** — both tests at lines 189/230 of test_circuit_breaker.py already have `@pytest.mark.unit`.

### Fixes Applied This Session
| Finding | Fix | Commit |
|---------|-----|--------|
| DP-005 | EnrichedArticleConsumer + EntityCreatedConsumer: `_dedup_prefix` → stable class constant | 6940d87c |
| ARCH-005 | `CanonicalEntityPort` re-exported from `repositories.py` (D-1/D-2 parity) | 6940d87c |
| ARCH-003 | Stale xfail docstring removed from `test_consumer_dedup_mixin_enforcement.py` | 6940d87c |

---

## Test Execution Results

| Layer | Tests | Passed | Failed | Status |
|-------|-------|--------|--------|--------|
| Architecture (101 tests) | 101 | 101 | 0 | ✅ PASS |
| Ruff lint (PLAN-0084 scope) | — | — | 0 | ✅ PASS |
| mypy (PLAN-0084 scope) | — | — | 0 | ✅ PASS |
| libs/messaging unit | 68 | 68 | 0 | ✅ PASS |
| services/rag-chat unit | 676 | 676 | 0 | ✅ PASS |
| services/nlp-pipeline unit | 826 | 826 | 0 | ✅ PASS |
| services/market-data unit | 629 | 629 | 0 | ✅ PASS |
| services/knowledge-graph unit | 1011 | 1011 | 0 | ✅ PASS |
| Integration / E2E | — | — | — | ⏭ SKIP (infra not running) |

---

## Critical Open Issues (Next Wave)

### C-1: 7 Hand-Rolled Consumers Lack Valkey Error Handling
**Severity**: CRITICAL | **Flagged by**: Data Platform + Distributed Systems
**Files**: `services/knowledge-graph/src/.../consumers/`: economic_events_dataset_consumer.py, earnings_calendar_dataset_consumer.py, macro_indicator_dataset_consumer.py, insider_transactions_dataset_consumer.py, structured_enrichment_consumer.py, fundamentals_consumer.py, instrument_consumer.py

All 7 implement `is_duplicate()` and `mark_processed()` manually without try/except. On Valkey connection failure, the exception propagates to BaseKafkaConsumer and triggers offset non-commit → Kafka rebalance storm.

**Fix pattern** (matching ValkeyDedupMixin):
```python
async def is_duplicate(self, event_id: str) -> bool:
    if self._dedup_client is None:
        return False
    key = f"{self._dedup_prefix}:{event_id}"
    try:
        return bool(await self._dedup_client.exists(key))
    except Exception:
        logger.warning("dedup.valkey_check_failed", event_id=event_id)
        return False  # fail-open: at-least-once

async def mark_processed(self, event_id: str) -> None:
    if self._dedup_client is None:
        return
    key = f"{self._dedup_prefix}:{event_id}"
    try:
        await self._dedup_client.set(key, "1", ex=self._dedup_ttl)
    except Exception:
        logger.warning("dedup.valkey_mark_failed", event_id=event_id)
```

### C-2: Canonical Tickers MULTI/EXEC Partial Failure
**Severity**: CRITICAL | **Flagged by**: Distributed Systems ×2
**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/cache/canonical_tickers_cache.py:264-271`

DEL + SADD are queued via Redis MULTI/EXEC pipeline. If a network error occurs after the commands are buffered client-side but before `pipe.execute()` completes, DEL may have been applied (cache wiped) while SADD never ran. The exception handler returns 0 silently.

**Fix**: Replace MULTI/EXEC pipeline with a Lua script (`execute_lua_script`) that performs DEL+SADD atomically server-side.

### C-3: Canonical Tickers Refresh Loop — No Exponential Backoff
**Severity**: CRITICAL | **Flagged by**: Distributed Systems
**File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/cache/canonical_tickers_cache.py:182-199`

On persistent Valkey outage, the loop retries every 60 seconds indefinitely — 120 WARNING lines per 2 hours of downtime, no escalation.

**Fix**: Implement exponential backoff (60s → 120s → ... → 3600s cap) with CRITICAL log after 5 consecutive failures.

---

## Major Open Issues

| ID | Description | File |
|----|-------------|------|
| DS-001 | SETNX probe starvation: failed probe keeps losers blocked for full probe_ttl | `circuit_breaker.py` |
| DS-003 | Citation cron first-run failure logged at WARNING only (no Prometheus counter) | `citation_accuracy_cron.py` |
| DS-004 | Cron graceful shutdown: cancel() during use_case.execute() leaves transaction mid-flight | `app.py` |
| DS-011 | Failures ZSET not reset on record_success() → single failure bounces back to OPEN | `circuit_breaker.py` |
| QA-003 | Disabled-cron test trivially passes (mock_start.assert_not_called always passes) | `test_app_lifespan_citation_cron.py` |
| QA-007 | ON CONFLICT DO NOTHING test checks `_post_values_clause is not None` not SQL text | `test_outbox_repo.py`, `test_entity_mention_repo.py` |
| QA-008 | Prometheus REGISTRY is global — concurrent test execution risks gauge cross-contamination | `test_circuit_breaker.py` |
| SEC-004 | APP_ENV="" bypasses skip_verification production guard (decision needed) | `config.py` |
| SEC-005 | JWT DecodeError in skip_verification mode → tenant_id="" without 401 | `internal_jwt.py` |

---

## Minor / NIT Findings

| ID | File | Issue |
|----|------|-------|
| QA-001 | `test_circuit_breaker.py` | Per-function `@pytest.mark.unit` vs module-level `pytestmark` |
| QA-009 | `citation_accuracy_cron.py` | `_next_sunday_03_utc()` has no dedicated unit tests |
| QA-013 | `test_internal_jwt_middleware.py` | Skip paths (health, metrics, readyz) not fully parametrized |
| DP-003 | `quotes_consumer.py` | `_dedup_prefix`/`_dedup_ttl_seconds` present but no-op (confusing) |
| DP-007 | `valkey/client.py` | `set()` dual TTL kwarg (`ttl` vs `ex`) priority not in docstring |
| ARCH-001 | `nlp-pipeline/.claude-context.md` | New ports (ChunkSearchPort, CanonicalEntityPort) not documented |
| ARCH-002 | `rag-chat/.claude-context.md` | LLMJudgePort not cross-referenced in citation cron section |

---

## Recommendations

1. **PLAN-0085 Wave 1** (CRITICAL): Add try/except to 7 hand-rolled KG consumers OR migrate to ValkeyDedupMixin.
2. **PLAN-0085 Wave 2** (CRITICAL): Replace canonical tickers MULTI/EXEC with Lua script + add exponential backoff.
3. **Fix QA-003** (broken disabled-cron test) and **QA-007** (strengthen ON CONFLICT assertions).
4. **Decide SEC-004**: Require `APP_ENV=development` for skip_verification=True in local dev.
5. **Document DS-002** TOCTOU at-least-once contract explicitly in ValkeyDedupMixin docstring.
