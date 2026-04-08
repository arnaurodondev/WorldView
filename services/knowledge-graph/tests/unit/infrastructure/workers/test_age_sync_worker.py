"""Unit tests for AgeSyncWorker (Worker 13F) — PRD-0018 §6 Worker 13F."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_settings(cypher_enabled: bool = True) -> Any:
    settings = MagicMock()
    settings.cypher_enabled = cypher_enabled
    return settings


def _make_valkey(watermark: str | None = None) -> Any:
    """Build a mock ValkeyClient."""
    valkey = AsyncMock()
    valkey.get = AsyncMock(return_value=watermark)
    valkey.set = AsyncMock()
    return valkey


def _make_session(execute_results: list[Any] | None = None) -> Any:
    """Build a mock AsyncSession with configurable execute return values."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()

    if execute_results:
        results = [_make_result(rows) for rows in execute_results]
        session.execute = AsyncMock(side_effect=results)
    else:
        # Default: empty result for all queries
        session.execute = AsyncMock(return_value=_make_result([]))

    return session


def _make_result(rows: list[Any]) -> Any:
    """Build a mock SQLAlchemy result with fetchall()."""
    result = MagicMock()
    result.fetchall = MagicMock(return_value=rows)
    return result


def _make_session_factory(session: Any) -> Any:
    """Build a mock session factory that yields *session*."""
    sf = MagicMock()
    sf.return_value = session
    return sf


def _make_entity_row(
    entity_id: str = "01910000-0000-7000-8000-000000000001",
    canonical_name: str = "Apple Inc.",
    entity_type: str = "financial_instrument",
    ticker: str = "AAPL",
    updated_at: datetime | None = None,
) -> Any:
    row = MagicMock()
    row.entity_id = entity_id
    row.canonical_name = canonical_name
    row.entity_type = entity_type
    row.ticker = ticker
    row.updated_at = updated_at or datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    return row


def _make_relation_row(
    relation_id: str = "01920000-0000-7000-8000-000000000001",
    subject_entity_id: str = "01910000-0000-7000-8000-000000000001",
    object_entity_id: str = "01910000-0000-7000-8000-000000000002",
    canonical_type: str = "competes_with",
    confidence: float = 0.85,
    updated_at: datetime | None = None,
) -> Any:
    row = MagicMock()
    row.relation_id = relation_id
    row.subject_entity_id = subject_entity_id
    row.object_entity_id = object_entity_id
    row.canonical_type = canonical_type
    row.confidence = confidence
    row.updated_at = updated_at or datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    return row


def _run_worker(
    settings: Any | None = None,
    valkey: Any | None = None,
    session: Any | None = None,
    valkey_watermark: str | None = None,
) -> tuple[Any, Any]:
    """Build and run AgeSyncWorker; return (valkey, session)."""
    from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

    if settings is None:
        settings = _make_settings(cypher_enabled=True)
    if valkey is None:
        valkey = _make_valkey(watermark=valkey_watermark)
    if session is None:
        session = _make_session()

    sf = _make_session_factory(session)
    worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
    asyncio.get_event_loop().run_until_complete(worker.run())
    return valkey, session


# ── Test: Feature flag disabled ────────────────────────────────────────────────


class TestAgeSyncWorkerDisabled:
    def test_run_skipped_when_disabled(self) -> None:
        """When cypher_enabled=False, run() returns immediately without DB access."""
        settings = _make_settings(cypher_enabled=False)
        valkey = _make_valkey()
        session = _make_session()
        sf = _make_session_factory(session)

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.get_event_loop().run_until_complete(worker.run())

        # No DB session opened, no Valkey reads/writes
        session.execute.assert_not_called()
        valkey.get.assert_not_awaited()
        valkey.set.assert_not_awaited()

    def test_no_watermark_update_when_disabled(self) -> None:
        """Watermark is NOT updated when the feature flag is off."""
        settings = _make_settings(cypher_enabled=False)
        valkey = _make_valkey()
        sf = _make_session_factory(_make_session())

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.get_event_loop().run_until_complete(worker.run())

        valkey.set.assert_not_awaited()


# ── Test: Watermark handling ───────────────────────────────────────────────────


class TestAgeSyncWorkerWatermark:
    def test_watermark_updated_after_run(self) -> None:
        """After a successful run, Valkey watermark is set to a new ISO-8601 value."""
        valkey, _ = _run_worker()

        valkey.set.assert_awaited_once()
        call_args = valkey.set.call_args
        assert call_args[0][0] == "s7:age:sync:watermark"
        # Value should be an ISO-8601 string
        new_wm = call_args[0][1]
        dt = datetime.fromisoformat(new_wm)
        assert dt.tzinfo is not None

    def test_epoch_watermark_used_when_key_missing(self) -> None:
        """When Valkey key is absent (None), the epoch (1970-01-01) is used."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import _EPOCH, AgeSyncWorker

        valkey = _make_valkey(watermark=None)
        session = _make_session()
        sf = _make_session_factory(session)
        settings = _make_settings()

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)

        # Capture the watermark passed to _sync_entities
        captured: list[datetime] = []

        async def _capture_sync(sess: Any, since: datetime) -> int:
            captured.append(since)
            return 0

        worker._sync_entities = _capture_sync  # type: ignore[method-assign]
        worker._sync_relations = AsyncMock(return_value=0)  # type: ignore[method-assign]
        worker._sync_temporal_events = AsyncMock()  # type: ignore[method-assign]

        asyncio.get_event_loop().run_until_complete(worker.run())

        assert captured == [_EPOCH]

    def test_stored_watermark_is_used_on_second_run(self) -> None:
        """When Valkey has an existing watermark, it is used as the since boundary."""
        stored_wm = "2026-04-01T00:00:00+00:00"
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        valkey = _make_valkey(watermark=stored_wm)
        session = _make_session()
        sf = _make_session_factory(session)
        settings = _make_settings()

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)

        captured: list[datetime] = []

        async def _capture_sync(sess: Any, since: datetime) -> int:
            captured.append(since)
            return 0

        worker._sync_entities = _capture_sync  # type: ignore[method-assign]
        worker._sync_relations = AsyncMock(return_value=0)  # type: ignore[method-assign]
        worker._sync_temporal_events = AsyncMock()  # type: ignore[method-assign]

        asyncio.get_event_loop().run_until_complete(worker.run())

        assert len(captured) == 1
        assert captured[0] == datetime.fromisoformat(stored_wm)


# ── Test: Entities synced ──────────────────────────────────────────────────────


class TestAgeSyncWorkerEntities:
    def test_entity_merge_cypher_called(self) -> None:
        """For each entity row, AGE Cypher MERGE is executed with entity_id param."""
        entity_row = _make_entity_row()

        # execute side effects: LOAD age, SET search_path, entity query (1 batch), relation q (empty),
        # temporal events q (empty), exposures q (empty)
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()

        # First two calls: LOAD 'age' and SET search_path (return values ignored)
        # Third call: entity SELECT returns one row
        # Fourth call: entity MERGE Cypher
        # Fifth call: relation SELECT → empty
        # Sixth call: temporal_events SELECT → empty
        # Seventh call: exposures SELECT → empty
        entity_result = _make_result([entity_row])
        empty = _make_result([])
        session.execute = AsyncMock(side_effect=[None, None, entity_result, None, empty, empty, empty])

        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.get_event_loop().run_until_complete(worker.run())

        # The 4th call should be the Cypher MERGE for the entity
        cypher_call = session.execute.call_args_list[3]
        call_text = str(cypher_call[0][0])
        assert "MERGE" in call_text
        assert "Entity" in call_text
        # Params JSON should contain entity_id
        params_arg = cypher_call[0][1]
        import json

        params = json.loads(params_arg["params"])
        assert params["entity_id"] == str(entity_row.entity_id)
        assert params["name"] == entity_row.canonical_name

    def test_prometheus_entity_counter_incremented(self) -> None:
        """s7_age_sync_entities_total is incremented by the number of entities synced."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_age_sync_entities_total

        before = s7_age_sync_entities_total._value.get()

        entity_row = _make_entity_row()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                None,
                None,
                _make_result([entity_row]),  # entities SELECT
                None,  # entity Cypher MERGE
                _make_result([]),  # relations
                _make_result([]),  # temporal events
                _make_result([]),  # exposures
            ]
        )
        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.get_event_loop().run_until_complete(worker.run())

        after = s7_age_sync_entities_total._value.get()
        assert after - before == 1.0


# ── Test: Edge label derivation ────────────────────────────────────────────────


class TestEdgeLabelDerivation:
    def test_lowercase_underscore_type(self) -> None:
        """competes_with → COMPETES_WITH."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("competes_with") == "COMPETES_WITH"

    def test_mixed_case_type(self) -> None:
        """HAS_EXECUTIVE (already uppercase) → HAS_EXECUTIVE."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("has_executive") == "HAS_EXECUTIVE"

    def test_space_in_type_converted(self) -> None:
        """Spaces are replaced with underscores before uppercasing."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("competes with") == "COMPETES_WITH"

    def test_unknown_type_returns_none(self) -> None:
        """An unrecognised canonical_type returns None (security: not embedded)."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("unknown_injected_type") is None

    def test_all_27_labels_valid(self) -> None:
        """Every label in _VALID_EDGE_LABELS survives a round-trip through _derive_edge_label."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import (
            _VALID_EDGE_LABELS,
            _derive_edge_label,
        )

        for label in _VALID_EDGE_LABELS:
            assert _derive_edge_label(label) == label


# ── Test: Relation edge label in Cypher ───────────────────────────────────────


class TestAgeSyncWorkerRelations:
    def test_relation_edge_label_embedded_in_cypher(self) -> None:
        """Relation MERGE Cypher contains the derived edge label (not a generic placeholder)."""
        relation_row = _make_relation_row(canonical_type="competes_with")

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        # LOAD, SET, entities→empty, relation SELECT, relation Cypher, temporal→empty, exposures→empty
        session.execute = AsyncMock(
            side_effect=[
                None,
                None,
                _make_result([]),  # entities
                _make_result([relation_row]),  # relations SELECT
                None,  # relation Cypher MERGE
                _make_result([]),  # temporal events
                _make_result([]),  # exposures
            ]
        )

        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.get_event_loop().run_until_complete(worker.run())

        # The Cypher call should contain COMPETES_WITH
        cypher_call = session.execute.call_args_list[4]
        call_text = str(cypher_call[0][0])
        assert "COMPETES_WITH" in call_text

    def test_unknown_relation_type_skipped(self) -> None:
        """Relations with unknown canonical_type are skipped (no Cypher call)."""
        relation_row = _make_relation_row(canonical_type="injected_type")

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                None,
                None,
                _make_result([]),  # entities
                _make_result([relation_row]),  # relations SELECT
                _make_result([]),  # temporal events
                _make_result([]),  # exposures
            ]
        )

        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.get_event_loop().run_until_complete(worker.run())

        # Total execute calls: LOAD, SET, entities Q, relations SELECT (no Cypher), temporal Q, exposures Q = 6
        assert session.execute.await_count == 6

    def test_prometheus_relation_counter_incremented(self) -> None:
        """s7_age_sync_relations_total is incremented by the number of relations synced."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_age_sync_relations_total

        before = s7_age_sync_relations_total._value.get()

        relation_row = _make_relation_row(canonical_type="competes_with")

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                None,
                None,
                _make_result([]),  # entities
                _make_result([relation_row]),  # relations SELECT
                None,  # Cypher MERGE
                _make_result([]),  # temporal events
                _make_result([]),  # exposures
            ]
        )

        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.get_event_loop().run_until_complete(worker.run())

        after = s7_age_sync_relations_total._value.get()
        assert after - before == 1.0


# ── Test: AGE session setup ────────────────────────────────────────────────────


class TestAgeSessionSetup:
    def test_load_age_called_before_cypher(self) -> None:
        """LOAD 'age' and SET search_path are executed before any Cypher queries."""
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        session.execute = AsyncMock(return_value=_make_result([]))

        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.get_event_loop().run_until_complete(worker.run())

        # First call should be LOAD 'age'
        first_call_text = str(session.execute.call_args_list[0][0][0])
        assert "LOAD" in first_call_text and "age" in first_call_text.lower()

        # Second call should be SET search_path
        second_call_text = str(session.execute.call_args_list[1][0][0])
        assert "search_path" in second_call_text


# ── Test: _derive_edge_label helper ───────────────────────────────────────────


class TestDeriveEdgeLabelHelper:
    def test_event_exposes_is_valid(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("EVENT_EXPOSES") == "EVENT_EXPOSES"

    def test_empty_string_returns_none(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("") is None

    def test_whitespace_only_returns_none(self) -> None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import _derive_edge_label

        assert _derive_edge_label("   ") is None
