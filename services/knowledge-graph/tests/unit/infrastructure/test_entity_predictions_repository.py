"""Unit tests for EntityEventExposureRepository.list_prediction_exposures_for_entity.

PLAN-0056 Wave C4 — read side of the KG prediction linkage.
All tests use mocked AsyncSessions — no DB required (mirrors
test_temporal_event_repository.py).

Covers:
- returns parsed rows (condition_id / question / polarity / etc.)
- empty result → ([], 0)
- SQL joins temporal_events and filters event_type='prediction' (exclusion of
  corporate/earnings exposures is enforced by this WHERE clause)
- limit/offset are forwarded as bound params
- polarity/polarity_confidence NULL passthrough
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
_CLOSE = datetime(2026, 12, 31, 0, 0, 0, tzinfo=UTC)


def _make_session(fetchall_return: list | None = None):  # type: ignore[no-untyped-def]
    from unittest.mock import AsyncMock, MagicMock

    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = fetchall_return or []
    session.execute = AsyncMock(return_value=result)
    return session


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _make_row(
    *,
    event_id: object = None,
    condition_id: str = "0xcondition",
    question: str = "Will X happen?",
    close_time: datetime | None = _CLOSE,
    polarity: str | None = "bullish",
    polarity_confidence: float | None = 0.8,
    exposure_type: str = "directly_affected",
    confidence: float = 0.9,
    total_count: int = 1,
) -> tuple:
    # Column order must match the SELECT in list_prediction_exposures_for_entity:
    # event_id, condition_id, question, close_time, polarity, polarity_confidence,
    # exposure_type, confidence, total_count
    return (
        str(event_id or uuid4()),
        condition_id,
        question,
        close_time,
        polarity,
        polarity_confidence,
        exposure_type,
        confidence,
        total_count,
    )


class TestListPredictionExposuresForEntity:
    def test_empty_returns_zero_total(self) -> None:
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = EntityEventExposureRepository(session)

        items, total = _run(repo.list_prediction_exposures_for_entity(entity_id=uuid4()))

        assert items == []
        assert total == 0

    def test_returns_parsed_rows(self) -> None:
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        event_id = uuid4()
        row = _make_row(
            event_id=event_id,
            condition_id="0xabc",
            question="Will the Fed cut rates?",
            polarity="bearish",
            polarity_confidence=0.72,
            confidence=0.95,
            total_count=1,
        )
        session = _make_session(fetchall_return=[row])
        repo = EntityEventExposureRepository(session)

        items, total = _run(repo.list_prediction_exposures_for_entity(entity_id=uuid4()))

        assert total == 1
        assert len(items) == 1
        item = items[0]
        assert item["event_id"] == event_id
        assert item["condition_id"] == "0xabc"
        assert item["question"] == "Will the Fed cut rates?"
        assert item["polarity"] == "bearish"
        assert item["polarity_confidence"] == 0.72
        assert item["exposure_type"] == "directly_affected"
        assert item["confidence"] == 0.95

    def test_null_polarity_passthrough(self) -> None:
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        row = _make_row(polarity=None, polarity_confidence=None, close_time=None)
        session = _make_session(fetchall_return=[row])
        repo = EntityEventExposureRepository(session)

        items, _ = _run(repo.list_prediction_exposures_for_entity(entity_id=uuid4()))

        assert items[0]["polarity"] is None
        assert items[0]["polarity_confidence"] is None
        assert items[0]["close_time"] is None

    def test_sql_filters_prediction_event_type(self) -> None:
        """The query JOINs temporal_events and restricts to event_type='prediction'.

        This WHERE clause is what excludes corporate/earnings/macro exposures.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = EntityEventExposureRepository(session)

        _run(repo.list_prediction_exposures_for_entity(entity_id=uuid4()))

        sql = str(session.execute.call_args.args[0])
        assert "temporal_events" in sql
        assert "entity_event_exposures" in sql
        assert "te.event_type = 'prediction'" in sql

    def test_limit_offset_forwarded_as_params(self) -> None:
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = EntityEventExposureRepository(session)
        entity_id = uuid4()

        _run(repo.list_prediction_exposures_for_entity(entity_id=entity_id, limit=25, offset=10))

        params = session.execute.call_args.args[1]
        assert params["limit"] == 25
        assert params["offset"] == 10
        assert params["entity_id"] == str(entity_id)

    def test_total_reflects_full_count(self) -> None:
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        rows = [_make_row(total_count=47) for _ in range(5)]
        session = _make_session(fetchall_return=rows)
        repo = EntityEventExposureRepository(session)

        items, total = _run(repo.list_prediction_exposures_for_entity(entity_id=uuid4(), limit=5))

        assert total == 47
        assert len(items) == 5
