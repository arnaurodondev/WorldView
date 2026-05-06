# PLAN-0073 QA Pass-1 Status — Resume Instructions

**Date**: 2026-05-05
**Status**: PARTIAL — pass-1 fixes interrupted by account usage limit
**Resume**: After usage budget reset

---

## What completed

### QA review — DONE
5 specialist agents reviewed PLAN-0073. Full report at:
- `docs/audits/2026-05-05-qa-plan-0073-report.md`
- 83 findings: 9 BLOCKING, 16 CRITICAL, 31 MAJOR, 15 MINOR, 12 NIT

### Pass-1 fixes — 3 of 6 fix-bug agents completed

| Agent | Status | Findings closed |
|-------|--------|-----------------|
| Prompt injection (libs/ml-clients) | DONE | F-S01, F-A05 |
| Migration 0023 + adapter seed | DONE | F-D01, F-D03, F-A06, F-X13, F-D04, F-D05, F-D06, F-S05 |
| Schema/config/Prometheus/S9 proxy | DONE | F-A14, F-A04/F-S08, F-A07, F-S04, F-Q12, F-Q14, F-Q15, F-Q16, F-Q19 |
| **S7 worker wire-up + retry semantics** | **INCOMPLETE** (budget) | F-A01/F-X02, F-A02/F-X06/F-S02, F-A03/F-X03/F-Q07, F-X01, F-X05 — likely partial |
| **S3 market-data R25 + security** | **INCOMPLETE** (budget) | F-D02, F-S03, F-S09, F-S10, F-D10, F-A12 — likely partial |
| **Test coverage gaps** | **INCOMPLETE** (budget) | F-Q01, F-Q02, F-Q03, F-Q05, F-Q06, F-Q13 — likely no tests added |

The 3 incomplete agents may have made partial edits before hitting the budget limit (visible in `git status`). **Verify before continuing**.

---

## BLOCKING findings still requiring fix verification

Re-check these in source after resume:

1. **F-A01 / F-X02** — `direct_producer` wired in `scheduler.py:_add_structured_enrichment_worker` and `structured_enrichment_consumer_main.py`?
2. **F-A02 / F-X06 / F-S02** — RS256 JWT signing replaces `internal_jwt=""` in both bootstrap paths?
3. **F-A03 / F-X03 / F-Q07** — `entity_type not in ("financial_instrument","company")` early-return in `structured_enrichment_consumer.process_message`?
4. **F-X01** — `RetryableEnrichmentError` triggers `consumer.seek()` for redelivery (not silent drop)?
5. **F-D02** — `OnDemandProfileUseCase` refactored to 3-phase session (no DB session held over EODHD HTTP)?
6. **F-Q01** — `tests/unit/infrastructure/workers/test_structured_enrichment_worker.py` exists?
7. **F-Q02** — `tests/unit/infrastructure/consumer/test_structured_enrichment_consumer.py` exists?

---

## Resume Steps

```bash
# 1. Audit current state — what edits the budget-exhausted agents managed to land
cd /Users/arnaurodon/Projects/University/final_thesis/worldview
git diff services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py
git diff services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/structured_enrichment_consumer.py
git diff services/knowledge-graph/src/knowledge_graph/infrastructure/workers/structured_enrichment_worker.py
git diff services/knowledge-graph/src/knowledge_graph/application/use_cases/structured_enrichment.py
git diff services/market-data/src/market_data/application/use_cases/on_demand_profile.py
git diff services/market-data/src/market_data/api/routers/instruments.py

# 2. Run remaining fix-bug agents OR do directly:
#    - Worker wire-up + retry agent (3 BLOCKING + 1 CRITICAL + 6 MAJOR)
#    - S3 market-data R25 + security agent (1 CRITICAL + 1 CRITICAL + 4 MINOR)
#    - Test coverage agent (2 BLOCKING + 4 CRITICAL + 1 MAJOR)

# 3. After all pass-1 fixes done, re-spawn 5 specialist agents for pass-2 QA review

# 4. Fix any new pass-2 findings

# 5. Run full test sweep:
ruff check libs/ services/
ruff format --check libs/ services/
# per-service unit tests
for svc in services/*/; do
  cd "$svc" && python -m pytest tests/ -m unit -v --tb=short
  cd /Users/arnaurodon/Projects/University/final_thesis/worldview
done
# frontend
cd apps/worldview-web && pnpm test && pnpm typecheck

# 6. Update docs/plans/TRACKING.md with QA date 2026-05-05

# 7. Commit fixes
```

---

## Remaining Findings to Address

### BLOCKING (incomplete)
- F-A01 / F-X02 — direct_producer wire-up
- F-A02 / F-X06 / F-S02 — RS256 JWT
- F-A03 / F-X03 / F-Q07 — entity_type filter
- F-X01 — Kafka redelivery on retryable
- F-Q01 — worker tests
- F-Q02 — consumer tests

### CRITICAL (incomplete)
- F-D02 — R25 session refactor (likely partial)
- F-S03 — SSRF route guards (likely partial)
- F-X04 — sweep backoff
- F-X05 — empty event_id fail-closed
- F-X07 — partial-commit ordering documentation
- F-Q03 — adapter integration tests
- F-Q04 — 7 missing T-C-2-02 tests
- F-Q05 — frontend panel tests
- F-Q06 — MarketDataClient tests
- F-Q08 — fallback model decision
- F-Q13 — verify `get_by_id` exists (per completed agent F-Q13 was confirmed real and present)

### MAJOR (mostly incomplete)
- F-X08, F-X09, F-X10, F-X11, F-X12, F-X14, F-X15, F-X16, F-X17 — DS findings
- F-A11 — worker fatal classification
- F-A08, F-A09, F-A10 — port pattern hygiene (deferred per QA report)
- F-A13 — docs updates (4 files)
- F-S07 — EODHD api_token in URL (pre-existing)
- F-Q09, F-Q10, F-Q11, F-Q17, F-Q18 — additional tests

### MINOR / NIT
- F-X18, F-X19, F-X20, F-X21, F-X22, F-X23
- F-A12 — orphan use cases (likely partial)
- F-A15, F-A16
- F-D07, F-D08, F-D09, F-D10
- F-S09, F-S10, F-S11, F-S12-S14 (mostly positive confirmations — no action)
- F-Q15-Q20

---

## Files modified (pass-1 partial)

Significant churn across:
- `libs/ml-clients/src/ml_clients/adapters/deepinfra_description.py` + new test file
- `services/intelligence-migrations/alembic/versions/0023_*.py` + test
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/adapters/entity_enrichment_adapter.py`
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py`
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py`
- `services/api-gateway/src/api_gateway/routes/proxy.py` + test
- Plus partial edits in `scheduler.py`, `structured_enrichment_consumer.py`, `structured_enrichment_worker.py`, `structured_enrichment.py`, `on_demand_profile.py`, `instruments.py` router, `security_repo.py`, `eodhd/client.py` from incomplete agents

`git status` shows additional files modified that were NOT in any agent's scope (e.g., `jwt_utils.py`, `internal_jwt.py`, `entity_consumer.py`, `outbox/dispatcher.py`). These may be pre-existing uncommitted work from PLAN-0072 QA pass-2 — verify before deciding what to commit.

---

## Compounding Updates Identified (for BUG_PATTERNS.md after fixes complete)

- BP-NEW: "Kafka consumer `RetryableException` silently dropped when `_handle_failure` is log-only" (F-X01)
- BP-NEW: "Migration UPDATE seed using uppercase canonical_type when registry uses lowercase — silent no-op" (F-D01) — addressed by completed agent
- BP-NEW: "DirectProducerProtocol parameter defaulted to None and never wired in bootstrap" (F-A01/F-X02)
- HR-NEW: "Empty internal_jwt='' constructor — relies on skip_verification" (F-A02/F-X06/F-S02)
