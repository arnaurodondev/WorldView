"""Unit tests for StructuredEnrichmentWorker (Worker 13J — PRD-0073 §9.5).

Covers F-Q01 of the PLAN-0073 QA report.

The worker drains the unenriched canonical-entity queue in batches of 50.
Tests verify:
    * the batch loop terminates on the first empty page (no infinite loop)
    * RetryableEnrichmentError does NOT increment enrichment_attempts
    * FatalEnrichmentError DOES increment enrichment_attempts
    * Generic Exception falls into the same bucket as Fatal (catch-all)
    * Increment-attempts I/O failure is caught and logged but does not crash
      the surrounding loop (next entity still processed)
    * Final summary log emitted with correct counts
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from knowledge_graph.domain.errors import FatalEnrichmentError, RetryableEnrichmentError
from knowledge_graph.domain.models import CanonicalEntity
from knowledge_graph.infrastructure.workers.structured_enrichment_worker import (
    StructuredEnrichmentWorker,
)
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_E1 = UUID("01900000-0000-7000-8000-000000000001")
_E2 = UUID("01900000-0000-7000-8000-000000000002")
_E3 = UUID("01900000-0000-7000-8000-000000000003")


def _entity(eid: UUID, etype: str = "financial_instrument") -> CanonicalEntity:
    return CanonicalEntity(
        entity_id=eid,
        canonical_name="Test Co.",
        entity_type=etype,
        ticker="TST",
        enrichment_attempts=0,
    )


def _make_session_factory() -> MagicMock:
    """Mock async_sessionmaker that returns a no-op async context manager."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    sf = MagicMock()
    sf.return_value.__aenter__ = AsyncMock(return_value=session)
    sf.return_value.__aexit__ = AsyncMock(return_value=False)
    return sf


def _make_adapter(batches: list[list[CanonicalEntity]]) -> AsyncMock:
    """Adapter whose claim_for_enrichment yields the given batches in order.

    PLAN-0093 T-C-4-01: the worker no longer calls ``list_unenriched`` —
    it now calls ``claim_for_enrichment`` which atomically returns + bumps
    enrichment_attempts in a single SQL round-trip. Tests are updated to
    mock the new method; ``list_unenriched`` is still wired here as a
    no-op so any forgotten reference fails loudly rather than silently.
    """
    adapter = AsyncMock()
    adapter.claim_for_enrichment = AsyncMock(side_effect=batches)
    adapter.list_unenriched = AsyncMock(side_effect=AssertionError("worker must use claim_for_enrichment"))
    adapter.increment_attempts = AsyncMock()
    adapter.decrement_attempts = AsyncMock()
    return adapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_drains_batches_until_empty() -> None:
    """Worker keeps fetching until list_unenriched returns an empty list.

    First call returns [e1, e2], second call returns [e3], third returns [].
    use_case.enrich must be called for all 3 entities.
    """
    adapter = _make_adapter(
        [
            [_entity(_E1), _entity(_E2)],
            [_entity(_E3)],
            [],
        ],
    )
    use_case = AsyncMock()
    use_case.enrich = AsyncMock()
    sf = _make_session_factory()
    worker = StructuredEnrichmentWorker(adapter, use_case, sf)

    await worker.run()

    assert use_case.enrich.call_count == 3
    # No errors → no attempt-increment writes.
    adapter.increment_attempts.assert_not_called()


async def test_retryable_error_decrements_attempts() -> None:
    """PLAN-0093 T-C-4-01: claim already incremented attempts; retryable error must
    DECREMENT so transient failures don't burn an attempt (preserves the existing
    semantic that 429s/network blips don't count against the 3-attempt budget).
    """
    adapter = _make_adapter([[_entity(_E1)], []])
    use_case = AsyncMock()
    use_case.enrich = AsyncMock(side_effect=RetryableEnrichmentError("429 from EODHD"))
    worker = StructuredEnrichmentWorker(adapter, use_case, _make_session_factory())

    # Patch asyncio.sleep so the exponential-backoff sleep doesn't slow the test.
    with patch(
        "knowledge_graph.infrastructure.workers.structured_enrichment_worker.asyncio.sleep",
        new=AsyncMock(),
    ):
        await worker.run()

    # The rollback (decrement) is what the worker calls now.
    adapter.decrement_attempts.assert_awaited_once()
    # Old +1 path must NOT fire on retryable — that would double-charge.
    adapter.increment_attempts.assert_not_called()


async def test_fatal_error_does_not_double_increment() -> None:
    """PLAN-0093 T-C-4-01: claim_for_enrichment already incremented at claim time,
    so the worker MUST NOT call increment_attempts again on fatal errors —
    double-charging would exhaust the 3-attempt budget after just 2 real failures.
    """
    adapter = _make_adapter([[_entity(_E1)], []])
    use_case = AsyncMock()
    use_case.enrich = AsyncMock(side_effect=FatalEnrichmentError("LLM short response"))
    worker = StructuredEnrichmentWorker(adapter, use_case, _make_session_factory())

    await worker.run()

    # Counter already advanced at claim time — no second bump.
    adapter.increment_attempts.assert_not_called()
    adapter.decrement_attempts.assert_not_called()


async def test_unexpected_exception_does_not_double_increment() -> None:
    """PLAN-0093 T-C-4-01: same no-double-increment rule for unexpected RuntimeErrors."""
    adapter = _make_adapter([[_entity(_E1)], []])
    use_case = AsyncMock()
    use_case.enrich = AsyncMock(side_effect=RuntimeError("totally unexpected"))
    worker = StructuredEnrichmentWorker(adapter, use_case, _make_session_factory())

    await worker.run()

    adapter.increment_attempts.assert_not_called()


async def test_decrement_failure_logs_but_does_not_crash_loop() -> None:
    """When _decrement_attempts itself raises (e.g. DB down during retryable rollback),
    the loop continues with the next entity so the operator doesn't lose visibility
    on the remaining batch.
    """
    adapter = _make_adapter([[_entity(_E1), _entity(_E2)], []])
    use_case = AsyncMock()
    # Both entities are retryable — exercises the decrement path twice.
    use_case.enrich = AsyncMock(side_effect=RetryableEnrichmentError("429"))
    adapter.decrement_attempts = AsyncMock(side_effect=RuntimeError("DB down"))
    worker = StructuredEnrichmentWorker(adapter, use_case, _make_session_factory())

    # Patch sleep so the exponential-backoff between retryable attempts doesn't slow the test.
    with patch(
        "knowledge_graph.infrastructure.workers.structured_enrichment_worker.asyncio.sleep",
        new=AsyncMock(),
    ):
        # Must not propagate — the worker logs and continues.
        await worker.run()

    # Both retryable rows attempted to roll back despite the first one raising.
    assert adapter.decrement_attempts.await_count == 2


async def test_logs_summary_counts() -> None:
    """Final structured log line carries enriched/failed/retryable/total counts."""
    # 1 ok, 1 retryable, 1 fatal — the structured log should reflect that.
    e_ok = _entity(_E1)
    e_retry = _entity(_E2)
    e_fatal = _entity(_E3)
    adapter = _make_adapter([[e_ok, e_retry, e_fatal], []])

    use_case = AsyncMock()

    async def _enrich(entity: CanonicalEntity) -> None:
        if entity.entity_id == _E2:
            raise RetryableEnrichmentError("transient")
        if entity.entity_id == _E3:
            raise FatalEnrichmentError("bad")
        # _E1 succeeds — no return value needed.

    use_case.enrich = AsyncMock(side_effect=_enrich)
    worker = StructuredEnrichmentWorker(adapter, use_case, _make_session_factory())

    with (
        capture_logs() as logs,
        patch(
            "knowledge_graph.infrastructure.workers.structured_enrichment_worker.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        await worker.run()

    summary = [le for le in logs if le.get("event") == "structured_enrichment_worker_complete"]
    assert summary, f"Expected summary log not found: {logs}"
    entry = summary[0]
    assert entry["enriched"] == 1
    assert entry["failed"] == 1
    assert entry["retryable"] == 1
    assert entry["total_processed"] == 3
