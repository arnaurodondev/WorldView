"""Tests verifying production call sites actually move S5 Prometheus metrics.

These tests guard against the "metrics defined but never incremented" pattern
(BP-174): exercising real helpers (not the Prometheus client directly) so a
regression that drops the metric call would fail here.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from content_store.infrastructure.metrics.gauge_updater import update_gauges_once
from content_store.infrastructure.metrics.prometheus import (
    record_processing_outcome,
    s5_articles_received_total,
    s5_canonical_written_total,
    s5_dlq_total,
    s5_documents_ingested_total,
    s5_duplicates_suppressed_total,
    s5_outbox_pending_total,
)

pytestmark = pytest.mark.unit


def _counter_value(counter: Any, **labels: str) -> float:
    """Helper to read the current value of a (possibly labelled) counter."""
    if labels:
        return counter.labels(**labels)._value.get()  # type: ignore[no-any-return]
    return counter._value.get()  # type: ignore[no-any-return]


# ─────────────────────────────────────────────────────────────────────────────
# (a) New-document path: articles_received + documents_ingested{unique}
# ─────────────────────────────────────────────────────────────────────────────


def test_new_document_path_increments_received_and_ingested():
    """A successful non-suppressed ingest must fire both ingest counters."""
    before_received = _counter_value(s5_articles_received_total)
    before_unique = _counter_value(s5_documents_ingested_total, dedup_result="unique")
    before_canonical = _counter_value(s5_canonical_written_total)

    record_processing_outcome(suppressed=False, dedup_result="unique", duration=0.12)

    assert _counter_value(s5_articles_received_total) == before_received + 1
    assert _counter_value(s5_documents_ingested_total, dedup_result="unique") == before_unique + 1
    # New documents also count as a canonical write.
    assert _counter_value(s5_canonical_written_total) == before_canonical + 1


# ─────────────────────────────────────────────────────────────────────────────
# (b) Dedup-suppress path: duplicates_suppressed{tier} + NO canonical_written
# ─────────────────────────────────────────────────────────────────────────────


def test_suppressed_path_increments_suppressed_not_canonical():
    """A suppressed article must fire the tier-labelled suppressed counter
    but must NOT bump the canonical_written counter."""
    tier = "stage_a"  # corresponds to dedup_result="duplicate_exact"
    before_suppressed = _counter_value(s5_duplicates_suppressed_total, tier=tier)
    before_canonical = _counter_value(s5_canonical_written_total)

    record_processing_outcome(suppressed=True, dedup_result="duplicate_exact", duration=0.03)

    assert _counter_value(s5_duplicates_suppressed_total, tier=tier) == before_suppressed + 1
    # Canonical writes must NOT increase on the suppressed path.
    assert _counter_value(s5_canonical_written_total) == before_canonical


# ─────────────────────────────────────────────────────────────────────────────
# (c) Gauge updater: reads counts from the session and sets gauges
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gauge_updater_sets_outbox_and_dlq_from_session():
    """update_gauges_once should read counts from the session and apply them
    to the two gauges. We patch session.execute to return scalar() values for
    both queries in order (outbox first, then DLQ)."""
    # Build two fake result objects whose .scalar() returns our integers.
    outbox_result = MagicMock()
    outbox_result.scalar.return_value = 17
    dlq_result = MagicMock()
    dlq_result.scalar.return_value = 4

    # Mock async session: execute() returns outbox_result then dlq_result.
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[outbox_result, dlq_result])
    # Async context manager protocol — session_factory() -> session.
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    # session_factory() must return the async-context-managed session.
    session_factory = MagicMock(return_value=session)

    await update_gauges_once(session_factory)

    # _value.get() is the canonical read for prom_client Gauge.
    assert s5_outbox_pending_total._value.get() == 17.0
    assert s5_dlq_total._value.get() == 4.0
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_gauge_updater_swallows_query_errors():
    """If either query raises, the updater must not propagate — the gauge
    simply retains its previous value."""
    # Seed a known-distinct value so we can assert "no change".
    s5_outbox_pending_total.set(99)
    s5_dlq_total.set(99)

    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db is down"))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=session)

    # Must not raise.
    await update_gauges_once(session_factory)

    # Values unchanged.
    assert s5_outbox_pending_total._value.get() == 99.0
    assert s5_dlq_total._value.get() == 99.0


# Suppress unused-import warning for SimpleNamespace which is left available
# in case future tests need a richer fake.
_ = SimpleNamespace
