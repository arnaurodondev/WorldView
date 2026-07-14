"""Unit tests for the shadow-only fitter entrypoint — PLAN-0123 Wave 2, T-A-2-05."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from knowledge_graph.application.analytics.decay_fitting.run_fitter import run_shadow_fit

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 14, tzinfo=UTC)


def _row_result(rows: list[tuple] | tuple | None) -> MagicMock:
    result = MagicMock()
    if isinstance(rows, list):
        result.fetchall.return_value = rows
    else:
        result.fetchone.return_value = rows
    return result


def _make_session_for_type(semantic_mode: str, mention_rows: list[tuple], relation_rows: list[tuple]) -> AsyncMock:
    """A session serving one type's full extraction round-trip.

    Call order inside ``_fit_one_type``: extract_mention_series does
    (scope-guard fetchone, data fetchall); extract_supersession_lifetimes
    does (scope-guard fetchone, data fetchall) — 4 execute() calls per type.
    """
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _row_result((semantic_mode,)),
            _row_result(mention_rows),
            _row_result((semantic_mode,)),
            _row_result(relation_rows),
        ],
    )
    return session


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


class TestRunShadowFit:
    def test_shadow_run_writes_nothing(self) -> None:
        """No commit/execute of any write statement — session.execute is only used for SELECTs."""
        subj, obj, rel_id = uuid4(), uuid4(), uuid4()
        founding = _NOW - timedelta(days=30)
        session = _make_session_for_type(
            "TEMPORAL_CLAIM",
            mention_rows=[(subj, obj, rel_id, founding)],
            relation_rows=[(founding, None, None)],
        )

        fits = _run(run_shadow_fit(session, target_types=("analyst_rating",)))

        assert len(fits) == 2  # one corroboration + one supersession fit
        # No commit() was ever called — this session never writes.
        session.commit.assert_not_called()

    def test_relation_state_type_skipped_not_crashed(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_row_result(("RELATION_STATE",)))

        fits = _run(run_shadow_fit(session, target_types=("employs",)))

        assert fits == []

    def test_type_with_no_data_reported_not_dropped_silently(self, caplog: pytest.LogCaptureFixture) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _row_result(("TEMPORAL_CLAIM",)),
                _row_result([]),
                _row_result(("TEMPORAL_CLAIM",)),
                _row_result([]),
            ],
        )

        fits = _run(run_shadow_fit(session, target_types=("issues_debt",)))

        assert fits == []

    def test_covers_all_target_types_in_one_run(self) -> None:
        """Every target type gets its own extraction round-trip — none silently skipped."""
        subj, obj, rel_id = uuid4(), uuid4(), uuid4()
        founding = _NOW - timedelta(days=10)

        # 2 types, each needing 4 execute() calls (scope-guard + data, x2 definitions).
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _row_result(("TEMPORAL_CLAIM",)),
                _row_result([(subj, obj, rel_id, founding)]),
                _row_result(("TEMPORAL_CLAIM",)),
                _row_result([(founding, None, None)]),
                _row_result(("TEMPORAL_CLAIM",)),
                _row_result([]),
                _row_result(("TEMPORAL_CLAIM",)),
                _row_result([]),
            ],
        )

        fits = _run(run_shadow_fit(session, target_types=("analyst_rating", "price_target")))

        types_seen = {f.canonical_type for f in fits}
        assert "analyst_rating" in types_seen
        # price_target had no data on either definition -> zero fits for it,
        # but the extraction round-trip still ran (no silent skip).
        assert session.execute.await_count == 8
