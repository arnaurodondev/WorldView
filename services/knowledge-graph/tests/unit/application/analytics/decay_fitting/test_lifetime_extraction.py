"""Unit tests for read-only lifetime extraction — PLAN-0123 Wave 2, T-A-2-04.

Mocked AsyncSession (no live DB) — matches this service's established
repository test pattern (see tests/unit/infrastructure/test_ann_repository.py,
tests/unit/infrastructure/repositories/test_relation_type_registry_repository.py).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from knowledge_graph.application.analytics.decay_fitting.lifetime_extraction import (
    RelationStateNotFittableError,
    extract_mention_series,
    extract_supersession_lifetimes,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 14, tzinfo=UTC)


def _make_session(sequence: list[list[tuple] | tuple | None]) -> AsyncMock:
    """A session whose execute() returns a different result each call, in order.

    Each entry in *sequence* is either a list of row-tuples (mapped via
    fetchall) or a single tuple/None (mapped via fetchone) — the extraction
    functions call fetchone() for the scope-guard lookup, then fetchall()
    for the data query, so callers pass [scope_guard_row, data_rows].
    """
    session = AsyncMock()
    results = []
    for entry in sequence:
        result = MagicMock()
        if isinstance(entry, list):
            result.fetchall.return_value = entry
        else:
            result.fetchone.return_value = entry
        results.append(result)
    session.execute = AsyncMock(side_effect=results)
    return session


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


class TestExtractMentionSeriesScopeGuard:
    def test_relation_state_type_rejected(self) -> None:
        session = _make_session([("RELATION_STATE",)])
        with pytest.raises(RelationStateNotFittableError, match="RELATION_STATE"):
            _run(extract_mention_series("employs", session, now=_NOW))

    def test_unknown_type_raises(self) -> None:
        session = _make_session([None])
        with pytest.raises(ValueError, match="not found in relation_type_registry"):
            _run(extract_mention_series("nonexistent_type", session, now=_NOW))


class TestExtractMentionSeriesGrouping:
    def test_groups_by_subject_object_pair_and_computes_ages(self) -> None:
        subj, obj = uuid4(), uuid4()
        rel_id = uuid4()
        founding = _NOW - timedelta(days=60)
        second_mention = _NOW - timedelta(days=50)
        rows = [
            (subj, obj, rel_id, founding),
            (subj, obj, rel_id, second_mention),
        ]
        session = _make_session([("TEMPORAL_CLAIM",), rows])

        series = _run(extract_mention_series("analyst_rating", session, now=_NOW))

        assert len(series) == 1
        s = series[0]
        assert s.relation_id == rel_id
        assert s.observation_window_days == pytest.approx(60.0)
        assert s.mention_ages_days == pytest.approx((10.0,))

    def test_multiple_relation_instances_produce_separate_series(self) -> None:
        subj1, obj1, rel1 = uuid4(), uuid4(), uuid4()
        subj2, obj2, rel2 = uuid4(), uuid4(), uuid4()
        founding = _NOW - timedelta(days=30)
        rows = [
            (subj1, obj1, rel1, founding),
            (subj2, obj2, rel2, founding),
        ]
        session = _make_session([("TEMPORAL_CLAIM",), rows])

        series = _run(extract_mention_series("price_target", session, now=_NOW))

        assert len(series) == 2
        assert {s.relation_id for s in series} == {rel1, rel2}

    def test_zero_mention_relation_has_empty_ages(self) -> None:
        """Only the founding evidence row — no re-mentions."""
        subj, obj, rel_id = uuid4(), uuid4(), uuid4()
        founding = _NOW - timedelta(days=5)
        session = _make_session([("TEMPORAL_CLAIM",), [(subj, obj, rel_id, founding)]])

        series = _run(extract_mention_series("sentiment_signal", session, now=_NOW))

        assert len(series) == 1
        assert series[0].mention_ages_days == ()
        assert series[0].observation_window_days == pytest.approx(5.0)


class TestExtractSupersessionLifetimes:
    def test_relation_state_type_rejected(self) -> None:
        session = _make_session([("RELATION_STATE",)])
        with pytest.raises(RelationStateNotFittableError):
            _run(extract_supersession_lifetimes("employs", session, now=_NOW))

    def test_no_terminal_event_is_censored(self) -> None:
        founding = _NOW - timedelta(days=45)
        session = _make_session([("TEMPORAL_CLAIM",), [(founding, None, None)]])

        lifetimes = _run(extract_supersession_lifetimes("credit_rating", session, now=_NOW))

        assert len(lifetimes) == 1
        assert lifetimes[0].event_observed is False
        assert lifetimes[0].duration_days == pytest.approx(45.0)

    def test_contradiction_terminates_lifetime(self) -> None:
        founding = _NOW - timedelta(days=100)
        contra = _NOW - timedelta(days=70)
        session = _make_session([("TEMPORAL_CLAIM",), [(founding, contra, None)]])

        lifetimes = _run(extract_supersession_lifetimes("earnings_guidance", session, now=_NOW))

        assert lifetimes[0].event_observed is True
        assert lifetimes[0].duration_days == pytest.approx(30.0)

    def test_multiple_relations_produce_multiple_lifetimes(self) -> None:
        founding1 = _NOW - timedelta(days=10)
        founding2 = _NOW - timedelta(days=20)
        rows = [
            (founding1, None, None),
            (founding2, None, None),
        ]
        session = _make_session([("TEMPORAL_CLAIM",), rows])

        lifetimes = _run(extract_supersession_lifetimes("analyst_rating", session, now=_NOW))

        assert len(lifetimes) == 2
        durations = sorted(lt.duration_days for lt in lifetimes)
        assert durations == pytest.approx([10.0, 20.0])
