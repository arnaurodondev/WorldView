"""Unit tests for TemporalEventRepository and EntityEventExposureRepository.

All tests use mocked AsyncSessions — no DB required.

Covers:
- upsert_by_natural_key: happy path, conflict update path (ON CONFLICT fires)
- list_active: no filters, scope filter, event_type filter, region filter,
               entity_id EXISTS filter, active_only filter, empty result
- EntityEventExposureRepository.upsert: happy path, idempotent second call
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
_YESTERDAY = _NOW - timedelta(days=1)


# ---------------------------------------------------------------------------
# Session mock helpers
# ---------------------------------------------------------------------------


def _make_session(
    fetchone_return: object = None,
    fetchall_return: list | None = None,
) -> AsyncMock:
    """Mock AsyncSession whose execute() returns configurable fetchone/fetchall."""
    session = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = fetchone_return
    result.fetchall.return_value = fetchall_return or []
    session.execute = AsyncMock(return_value=result)
    return session


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# TemporalEventRepository
# ---------------------------------------------------------------------------


class TestTemporalEventRepositoryUpsert:
    def test_upsert_returns_event_id(self) -> None:
        """upsert_by_natural_key returns the event_id from RETURNING clause."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        event_id = uuid4()
        session = _make_session(fetchone_return=(str(event_id),))
        repo = TemporalEventRepository(session)

        result = _run(
            repo.upsert_by_natural_key(
                event_id=event_id,
                event_type="geopolitical",
                scope="NATIONAL",
                region="US",
                title="US-China Tech Restrictions",
                active_from=_YESTERDAY,
                confidence=0.92,
            )
        )

        assert result == event_id
        assert isinstance(result, UUID)
        session.execute.assert_awaited_once()

    def test_upsert_passes_all_required_params(self) -> None:
        """All required SQL parameters are present in the execute call."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        event_id = uuid4()
        session = _make_session(fetchone_return=(str(event_id),))
        repo = TemporalEventRepository(session)

        _run(
            repo.upsert_by_natural_key(
                event_id=event_id,
                event_type="macro",
                scope="GLOBAL",
                region="EU",
                title="ECB Rate Decision Surprise",
                active_from=_YESTERDAY,
                confidence=1.0,
                description="ECB raised rates by 50bp vs 25bp expected",
                source_url="https://eodhd.com/api/economic-events",
                residual_impact_days=30,
            )
        )

        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["event_id"] == str(event_id)
        assert params["event_type"] == "macro"
        assert params["scope"] == "GLOBAL"
        assert params["region"] == "EU"
        assert params["title"] == "ECB Rate Decision Surprise"
        assert params["confidence"] == 1.0
        assert params["residual_impact_days"] == 30

    def test_upsert_region_none_for_local_events(self) -> None:
        """region=None is passed as-is; DB NULL allows any region for LOCAL events."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        event_id = uuid4()
        session = _make_session(fetchone_return=(str(event_id),))
        repo = TemporalEventRepository(session)

        _run(
            repo.upsert_by_natural_key(
                event_id=event_id,
                event_type="regulatory",
                scope="LOCAL",
                region=None,
                title="Company-Level SEC Investigation",
                active_from=_YESTERDAY,
                confidence=0.75,
            )
        )

        params = session.execute.call_args[0][1]
        assert params["region"] is None

    def test_upsert_source_article_ids_empty_by_default(self) -> None:
        """source_article_ids defaults to empty list when not provided."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        event_id = uuid4()
        session = _make_session(fetchone_return=(str(event_id),))
        repo = TemporalEventRepository(session)

        _run(
            repo.upsert_by_natural_key(
                event_id=event_id,
                event_type="macro",
                scope="NATIONAL",
                region="US",
                title="FOMC Rate Decision",
                active_from=_YESTERDAY,
                confidence=1.0,
            )
        )

        params = session.execute.call_args[0][1]
        assert params["source_article_ids"] == []

    def test_upsert_source_article_ids_converted_to_strings(self) -> None:
        """source_article_ids list is converted to list[str] for asyncpg binding."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        event_id = uuid4()
        article_id_1 = uuid4()
        article_id_2 = uuid4()
        session = _make_session(fetchone_return=(str(event_id),))
        repo = TemporalEventRepository(session)

        _run(
            repo.upsert_by_natural_key(
                event_id=event_id,
                event_type="geopolitical",
                scope="REGIONAL",
                region="APAC",
                title="Taiwan Strait Tensions",
                active_from=_YESTERDAY,
                confidence=0.88,
                source_article_ids=[str(article_id_1), str(article_id_2)],
            )
        )

        params = session.execute.call_args[0][1]
        assert params["source_article_ids"] == [str(article_id_1), str(article_id_2)]

    def test_upsert_sql_contains_on_conflict(self) -> None:
        """SQL must include ON CONFLICT clause for idempotency."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        event_id = uuid4()
        session = _make_session(fetchone_return=(str(event_id),))
        repo = TemporalEventRepository(session)

        _run(
            repo.upsert_by_natural_key(
                event_id=event_id,
                event_type="macro",
                scope="NATIONAL",
                region="US",
                title="NFP Release",
                active_from=_YESTERDAY,
                confidence=1.0,
            )
        )

        sql_text = str(session.execute.call_args[0][0])
        assert "ON CONFLICT" in sql_text
        assert "DO UPDATE" in sql_text
        assert "RETURNING event_id" in sql_text


class TestTemporalEventRepositoryListActive:
    def test_list_active_empty_returns_zero_total(self) -> None:
        """Empty result set returns ([], 0)."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = TemporalEventRepository(session)

        events, total = _run(repo.list_active())

        assert events == []
        assert total == 0

    def _make_db_row(
        self,
        event_id: UUID | None = None,
        event_type: str = "geopolitical",
        scope: str = "NATIONAL",
        region: str | None = "US",
        title: str = "US Tariffs on China",
        description: str | None = None,
        source_article_ids: list | None = None,
        source_url: str | None = None,
        active_from: datetime | None = None,
        active_until: datetime | None = None,
        residual_impact_days: int = 90,
        confidence: float = 0.85,
        created_at: datetime | None = None,
        exposed_entity_count: int = 3,
        total_count: int = 1,
    ) -> tuple:
        return (
            str(event_id or uuid4()),
            event_type,
            scope,
            region,
            title,
            description,
            source_article_ids or [],
            source_url,
            active_from or _YESTERDAY,
            active_until,
            residual_impact_days,
            confidence,
            created_at or _NOW,
            exposed_entity_count,
            total_count,
        )

    def test_list_active_returns_parsed_events(self) -> None:
        """Rows are parsed into dicts with all expected keys."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        event_id = uuid4()
        row = self._make_db_row(event_id=event_id, exposed_entity_count=5, total_count=1)
        session = _make_session(fetchall_return=[row])
        repo = TemporalEventRepository(session)

        events, total = _run(repo.list_active())

        assert total == 1
        assert len(events) == 1
        ev = events[0]
        assert ev["event_id"] == event_id
        assert ev["event_type"] == "geopolitical"
        assert ev["scope"] == "NATIONAL"
        assert ev["region"] == "US"
        assert ev["exposed_entity_count"] == 5
        assert ev["confidence"] == pytest.approx(0.85)

    def test_list_active_no_filters_sends_minimal_conditions(self) -> None:
        """No filters → only 1=1 condition; no extra params."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = TemporalEventRepository(session)

        _run(repo.list_active(active_only=False))

        params = session.execute.call_args[0][1]
        # Only limit + offset when no filters (active_only=False)
        assert set(params.keys()) == {"limit", "offset"}

    def test_list_active_scope_filter_adds_param(self) -> None:
        """scope filter adds te.scope = :scope condition."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = TemporalEventRepository(session)

        _run(repo.list_active(scope="GLOBAL", active_only=False))

        params = session.execute.call_args[0][1]
        assert params["scope"] == "GLOBAL"
        sql = str(session.execute.call_args[0][0])
        assert "te.scope = :scope" in sql

    def test_list_active_event_type_filter(self) -> None:
        """event_type filter is applied when set."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = TemporalEventRepository(session)

        _run(repo.list_active(event_type="macro", active_only=False))

        params = session.execute.call_args[0][1]
        assert params["event_type"] == "macro"

    def test_list_active_region_filter(self) -> None:
        """region filter is applied when set."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = TemporalEventRepository(session)

        _run(repo.list_active(region="EU", active_only=False))

        params = session.execute.call_args[0][1]
        assert params["region"] == "EU"

    def test_list_active_from_date_and_to_date_filters(self) -> None:
        """from_date and to_date are both applied when set."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = TemporalEventRepository(session)
        from_dt = date(2026, 1, 1)
        to_dt = date(2026, 4, 8)

        _run(repo.list_active(from_date=from_dt, to_date=to_dt, active_only=False))

        params = session.execute.call_args[0][1]
        assert params["from_date"] == from_dt
        assert params["to_date"] == to_dt
        sql = str(session.execute.call_args[0][0])
        assert "te.active_from >= :from_date" in sql
        assert "te.active_from <= :to_date" in sql

    def test_list_active_entity_id_filter_adds_exists_subquery(self) -> None:
        """entity_id adds an EXISTS subquery on entity_event_exposures."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = TemporalEventRepository(session)
        eid = uuid4()

        _run(repo.list_active(entity_id=eid, active_only=False))

        params = session.execute.call_args[0][1]
        assert params["entity_id"] == str(eid)
        sql = str(session.execute.call_args[0][0])
        assert "EXISTS" in sql
        assert "entity_event_exposures" in sql

    def test_list_active_only_true_adds_residual_window_condition(self) -> None:
        """active_only=True adds the residual window NOT-EXPIRED condition."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = TemporalEventRepository(session)

        _run(repo.list_active(active_only=True))

        sql = str(session.execute.call_args[0][0])
        # Check the active_only filter: excludes EXPIRED via residual window
        assert "active_until IS NULL" in sql
        assert "residual_impact_days" in sql

    def test_list_active_total_count_from_window_function(self) -> None:
        """total_count is extracted from the COUNT(*) OVER() column (col index 14)."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        rows = [
            self._make_db_row(total_count=42),
            self._make_db_row(total_count=42),
        ]
        session = _make_session(fetchall_return=rows)
        repo = TemporalEventRepository(session)

        events, total = _run(repo.list_active(active_only=False))

        assert total == 42
        assert len(events) == 2

    def test_list_active_sql_contains_count_over(self) -> None:
        """SQL includes COUNT(*) OVER() window function for total count."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = TemporalEventRepository(session)

        _run(repo.list_active())

        sql = str(session.execute.call_args[0][0])
        assert "COUNT(*) OVER()" in sql
        assert "exposed_entity_count" in sql

    def test_list_active_pagination_params(self) -> None:
        """limit and offset are always passed as params."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            TemporalEventRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = TemporalEventRepository(session)

        _run(repo.list_active(limit=25, offset=50, active_only=False))

        params = session.execute.call_args[0][1]
        assert params["limit"] == 25
        assert params["offset"] == 50


# ---------------------------------------------------------------------------
# EntityEventExposureRepository
# ---------------------------------------------------------------------------


class TestEntityEventExposureRepository:
    def test_upsert_returns_exposure_id(self) -> None:
        """upsert returns the provided exposure_id."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        session = _make_session()
        repo = EntityEventExposureRepository(session)
        exposure_id = uuid4()

        result = _run(
            repo.upsert(
                exposure_id=exposure_id,
                event_id=uuid4(),
                entity_id=uuid4(),
                exposure_type="directly_affected",
                confidence=0.90,
            )
        )

        assert result == exposure_id
        assert isinstance(result, UUID)
        session.execute.assert_awaited_once()

    def test_upsert_on_conflict_do_nothing_in_sql(self) -> None:
        """SQL must contain ON CONFLICT DO NOTHING for idempotent insert."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        session = _make_session()
        repo = EntityEventExposureRepository(session)

        _run(
            repo.upsert(
                exposure_id=uuid4(),
                event_id=uuid4(),
                entity_id=uuid4(),
                exposure_type="sector_exposure",
                confidence=0.75,
            )
        )

        sql = str(session.execute.call_args[0][0])
        assert "ON CONFLICT" in sql
        assert "DO NOTHING" in sql

    def test_upsert_passes_all_params(self) -> None:
        """All params are bound and passed to the DB execute call."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        session = _make_session()
        repo = EntityEventExposureRepository(session)
        exposure_id = uuid4()
        event_id = uuid4()
        entity_id = uuid4()

        _run(
            repo.upsert(
                exposure_id=exposure_id,
                event_id=event_id,
                entity_id=entity_id,
                exposure_type="revenue_geography",
                confidence=0.65,
                evidence_text="Revenue 40% from US markets",
            )
        )

        params = session.execute.call_args[0][1]
        assert params["exposure_id"] == str(exposure_id)
        assert params["event_id"] == str(event_id)
        assert params["entity_id"] == str(entity_id)
        assert params["exposure_type"] == "revenue_geography"
        assert params["confidence"] == 0.65
        assert params["evidence_text"] == "Revenue 40% from US markets"

    def test_upsert_evidence_text_none_by_default(self) -> None:
        """evidence_text defaults to None when not supplied."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        session = _make_session()
        repo = EntityEventExposureRepository(session)

        _run(
            repo.upsert(
                exposure_id=uuid4(),
                event_id=uuid4(),
                entity_id=uuid4(),
                exposure_type="supply_chain",
                confidence=0.80,
            )
        )

        params = session.execute.call_args[0][1]
        assert params["evidence_text"] is None

    def test_upsert_idempotent_second_call(self) -> None:
        """Second call with same (event_id, entity_id, exposure_type) is a no-op.

        The SQL ON CONFLICT DO NOTHING ensures no error is raised.
        Both calls succeed and return the provided exposure_id.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        session = _make_session()
        repo = EntityEventExposureRepository(session)
        exposure_id = uuid4()
        event_id = uuid4()
        entity_id = uuid4()

        result_1 = _run(
            repo.upsert(
                exposure_id=exposure_id,
                event_id=event_id,
                entity_id=entity_id,
                exposure_type="directly_affected",
                confidence=0.90,
            )
        )
        # Second call with same triple — ON CONFLICT DO NOTHING fires
        result_2 = _run(
            repo.upsert(
                exposure_id=uuid4(),  # different ID — caller owns the ID
                event_id=event_id,
                entity_id=entity_id,
                exposure_type="directly_affected",
                confidence=0.91,
            )
        )

        assert isinstance(result_1, UUID)
        assert isinstance(result_2, UUID)
        assert session.execute.await_count == 2

    def test_upsert_conflict_target_in_sql(self) -> None:
        """SQL conflict target matches the DB unique constraint columns."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
        )

        session = _make_session()
        repo = EntityEventExposureRepository(session)

        _run(
            repo.upsert(
                exposure_id=uuid4(),
                event_id=uuid4(),
                entity_id=uuid4(),
                exposure_type="operationally_impacted",
                confidence=0.70,
            )
        )

        sql = str(session.execute.call_args[0][0])
        # Unique constraint: (event_id, entity_id, exposure_type)
        assert "event_id" in sql
        assert "entity_id" in sql
        assert "exposure_type" in sql
