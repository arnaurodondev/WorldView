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

from unittest.mock import AsyncMock, MagicMock
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
    """Adapter whose list_unenriched yields the given batches in order."""
    adapter = AsyncMock()
    adapter.list_unenriched = AsyncMock(side_effect=batches)
    adapter.increment_attempts = AsyncMock()
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
        ]
    )
    use_case = AsyncMock()
    use_case.enrich = AsyncMock()
    sf = _make_session_factory()
    worker = StructuredEnrichmentWorker(adapter, use_case, sf)

    await worker.run()

    assert use_case.enrich.call_count == 3
    # No errors → no attempt-increment writes.
    adapter.increment_attempts.assert_not_called()


async def test_retryable_error_does_not_increment_attempts() -> None:
    """RetryableEnrichmentError is a transient failure — attempts must NOT be bumped."""
    adapter = _make_adapter([[_entity(_E1)], []])
    use_case = AsyncMock()
    use_case.enrich = AsyncMock(side_effect=RetryableEnrichmentError("429 from EODHD"))
    worker = StructuredEnrichmentWorker(adapter, use_case, _make_session_factory())

    await worker.run()

    adapter.increment_attempts.assert_not_called()


async def test_fatal_error_increments_attempts() -> None:
    """FatalEnrichmentError must trigger _increment_attempts so the entity ages out."""
    adapter = _make_adapter([[_entity(_E1)], []])
    use_case = AsyncMock()
    use_case.enrich = AsyncMock(side_effect=FatalEnrichmentError("LLM short response"))
    worker = StructuredEnrichmentWorker(adapter, use_case, _make_session_factory())

    await worker.run()

    adapter.increment_attempts.assert_awaited_once()
    # The first positional arg should be the entity_id (UUID).
    args, _kwargs = adapter.increment_attempts.call_args
    assert args[0] == _E1


async def test_unexpected_exception_increments_attempts() -> None:
    """Generic Exception (not Retryable) is treated as Fatal — attempts++."""
    adapter = _make_adapter([[_entity(_E1)], []])
    use_case = AsyncMock()
    use_case.enrich = AsyncMock(side_effect=RuntimeError("totally unexpected"))
    worker = StructuredEnrichmentWorker(adapter, use_case, _make_session_factory())

    await worker.run()

    adapter.increment_attempts.assert_awaited_once()


async def test_increment_attempts_failure_logs_but_does_not_crash_loop() -> None:
    """When _increment_attempts itself raises, the loop continues with the next entity.

    This guards against a DB outage during error-handling cascading into a worker crash:
    the operator would lose visibility on every remaining entity in the batch.
    """
    adapter = _make_adapter([[_entity(_E1), _entity(_E2)], []])
    use_case = AsyncMock()
    # Both entities fail fatally — ensures _increment_attempts is invoked twice.
    use_case.enrich = AsyncMock(side_effect=FatalEnrichmentError("LLM short"))
    # The increment itself raises (DB down).
    adapter.increment_attempts = AsyncMock(side_effect=RuntimeError("DB down"))
    worker = StructuredEnrichmentWorker(adapter, use_case, _make_session_factory())

    # Must not propagate — the worker logs and continues.
    await worker.run()

    # Both rows attempted to increment despite the first one raising internally.
    assert adapter.increment_attempts.await_count == 2


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

    with capture_logs() as logs:
        await worker.run()

    summary = [le for le in logs if le.get("event") == "structured_enrichment_worker_complete"]
    assert summary, f"Expected summary log not found: {logs}"
    entry = summary[0]
    assert entry["enriched"] == 1
    assert entry["failed"] == 1
    assert entry["retryable"] == 1
    assert entry["total_processed"] == 3
