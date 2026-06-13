"""Unit tests for AgeSyncWorker (Worker 13F) — PRD-0018 §6 Worker 13F."""

from __future__ import annotations

import asyncio
import json
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
    asyncio.run(worker.run())
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
        asyncio.run(worker.run())

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
        asyncio.run(worker.run())

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

        asyncio.run(worker.run())

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

        asyncio.run(worker.run())

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

        # F-016: _setup_age_session (2 calls) is now invoked 3 times — once
        # before entities, once after the entities commit, once after the
        # relations commit — so the full execute sequence is:
        #  1-2: initial LOAD age + SET search_path
        #  3:   entity SELECT → one row
        #  4:   entity MERGE Cypher
        #  [commit]
        #  5-6: second LOAD age + SET search_path
        #  7:   relation SELECT → empty
        #  [commit]
        #  8-9: third LOAD age + SET search_path
        #  10:  temporal_events SELECT → empty
        #  11:  exposures SELECT → empty
        entity_result = _make_result([entity_row])
        empty = _make_result([])
        session.execute = AsyncMock(
            side_effect=[
                None,
                None,  # initial _setup_age_session
                entity_result,
                None,  # entity SELECT + MERGE
                None,
                None,  # second _setup_age_session (after entities commit)
                empty,  # relation SELECT
                None,
                None,  # third _setup_age_session (after relations commit)
                empty,
                empty,  # temporal_events SELECT + exposures SELECT
                None,
                None,  # FR-13: fourth _setup_age_session (before prune)
                empty,  # FR-13: prune detection SELECT → no phantoms
            ]
        )

        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.run(worker.run())

        # The 4th call should be the Cypher MERGE for the entity
        cypher_call = session.execute.call_args_list[3]
        call_text = str(cypher_call[0][0])
        # BP-SA5-001: label must be lowercase ``entity`` (matches path_discovery.py)
        assert "MERGE" in call_text
        assert "entity" in call_text
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
                None,  # initial _setup_age_session
                _make_result([entity_row]),
                None,  # entity SELECT + MERGE
                None,
                None,  # second _setup_age_session
                _make_result([]),  # relation SELECT
                None,
                None,  # third _setup_age_session
                _make_result([]),
                _make_result([]),  # temporal + exposures
                None,
                None,  # FR-13: fourth _setup_age_session (before prune)
                _make_result([]),  # FR-13: prune detection SELECT → no phantoms
            ]
        )
        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.run(worker.run())

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
        # F-016: _setup_age_session now called 3x. Full sequence:
        #  0-1: initial LOAD+SET, 2: entities empty, commit
        #  3-4: second LOAD+SET, 5: relations SELECT, 6: relation MERGE, commit
        #  7-8: third LOAD+SET, 9: temporal empty, 10: exposures empty, commit
        session.execute = AsyncMock(
            side_effect=[
                None,
                None,  # initial _setup_age_session
                _make_result([]),  # entities SELECT
                None,
                None,  # second _setup_age_session
                _make_result([relation_row]),
                None,  # relations SELECT + MERGE
                None,
                None,  # third _setup_age_session
                _make_result([]),  # temporal events SELECT
                _make_result([]),  # exposures SELECT
                None,
                None,  # FR-13: fourth _setup_age_session (before prune)
                _make_result([]),  # FR-13: prune detection SELECT → no phantoms
            ]
        )

        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.run(worker.run())

        # The Cypher call should contain COMPETES_WITH (index 6 after F-016)
        cypher_call = session.execute.call_args_list[6]
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
                None,  # initial _setup_age_session
                _make_result([]),  # entities SELECT
                None,
                None,  # second _setup_age_session
                _make_result([relation_row]),  # relations SELECT (unknown type → no Cypher)
                None,
                None,  # third _setup_age_session
                _make_result([]),  # temporal events SELECT
                _make_result([]),  # exposures SELECT
                None,
                None,  # FR-13: fourth _setup_age_session (before prune)
                _make_result([]),  # FR-13: prune detection SELECT → no phantoms
            ]
        )

        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.run(worker.run())

        # F-016: 3x _setup_age_session (6) + entities(1) + relations(1) + temporal(1) + exposures(1)
        # + FR-13 prune (4th _setup_age_session = 2, prune detection SELECT = 1) = 13
        assert session.execute.await_count == 13

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
                None,  # initial _setup_age_session
                _make_result([]),  # entities SELECT
                None,
                None,  # second _setup_age_session
                _make_result([relation_row]),
                None,  # relations SELECT + Cypher MERGE
                None,
                None,  # third _setup_age_session
                _make_result([]),  # temporal events SELECT
                _make_result([]),  # exposures SELECT
                None,
                None,  # FR-13: fourth _setup_age_session (before prune)
                _make_result([]),  # FR-13: prune detection SELECT → no phantoms
            ]
        )

        sf = _make_session_factory(session)
        settings = _make_settings()
        valkey = _make_valkey()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.run(worker.run())

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
        asyncio.run(worker.run())

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


# ── Test: _sync_temporal_events pagination ────────────────────────────────────


def _make_event_row(
    event_id: str = "01930000-0000-7000-8000-000000000001",
    event_type: str = "MACRO",
    scope: str = "NATIONAL",
    region: str = "US",
    title: str = "CPI m/m",
    confidence: float = 1.0,
    updated_at: datetime | None = None,
) -> Any:
    from datetime import UTC, datetime

    row = MagicMock()
    row.event_id = event_id
    row.event_type = event_type
    row.scope = scope
    row.region = region
    row.title = title
    row.confidence = confidence
    row.updated_at = updated_at or datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    return row


class TestSyncTemporalEventsPagination:
    """_sync_temporal_events: pagination loop terminates correctly."""

    def test_empty_first_page_issues_no_cypher(self) -> None:
        """When temporal_events returns an empty first page, no Cypher MERGE is called."""
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        # F-016: 3x _setup_age_session. Full sequence:
        #  0-1: LOAD+SET, 2: entities empty, commit
        #  3-4: LOAD+SET, 5: relations empty, commit
        #  6-7: LOAD+SET, 8: temporal empty, 9: exposures empty, commit
        session.execute = AsyncMock(
            side_effect=[
                None,
                None,  # initial _setup_age_session
                _make_result([]),  # entities SELECT
                None,
                None,  # second _setup_age_session
                _make_result([]),  # relations SELECT
                None,
                None,  # third _setup_age_session
                _make_result([]),  # temporal_events SELECT
                _make_result([]),  # exposures SELECT
                None,
                None,  # FR-13: fourth _setup_age_session (before prune)
                _make_result([]),  # FR-13: prune detection SELECT → no phantoms
            ]
        )
        sf = _make_session_factory(session)
        valkey = _make_valkey()
        settings = _make_settings()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.run(worker.run())

        # F-016: 3x2 setup calls + 4 data calls + FR-13 prune (2 setup + 1 detect) = 13 total
        assert session.execute.await_count == 13

    def test_partial_page_terminates_loop(self) -> None:
        """A page smaller than event_batch (2000) stops pagination without a second SELECT."""
        event_row = _make_event_row()

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        # F-016: 3x _setup_age_session. Full sequence:
        #  0-1: LOAD+SET, 2: entities empty, commit
        #  3-4: LOAD+SET, 5: relations empty, commit
        #  6-7: LOAD+SET, 8: temporal SELECT (1 row), 9: temporal MERGE, 10: exposures empty, commit
        session.execute = AsyncMock(
            side_effect=[
                None,
                None,  # initial _setup_age_session
                _make_result([]),  # entities SELECT
                None,
                None,  # second _setup_age_session
                _make_result([]),  # relations SELECT
                None,
                None,  # third _setup_age_session
                _make_result([event_row]),
                None,  # temporal SELECT + MERGE
                _make_result([]),  # exposures SELECT
                None,
                None,  # FR-13: fourth _setup_age_session (before prune)
                _make_result([]),  # FR-13: prune detection SELECT → no phantoms
            ]
        )
        sf = _make_session_factory(session)
        valkey = _make_valkey()
        settings = _make_settings()

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)
        asyncio.run(worker.run())

        # Should NOT have issued a second temporal SELECT — only one SELECT + one Cypher
        temporal_selects = [c for c in session.execute.call_args_list if "temporal_events" in str(c[0][0])]
        assert len(temporal_selects) == 1

    def test_temporal_event_cypher_contains_correct_params(self) -> None:
        """Cypher MERGE for a temporal event embeds event_id and title in params JSON."""
        import json

        event_row = _make_event_row(
            event_id="01930000-0000-7000-8000-000000000099",
            title="GDP q/q",
        )

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        # F-016: 3x _setup_age_session. Full sequence:
        #  0-1: LOAD+SET, 2: entities empty, commit
        #  3-4: LOAD+SET, 5: relations empty, commit
        #  6-7: LOAD+SET, 8: temporal SELECT, 9: temporal Cypher, 10: exposures empty, commit
        session.execute = AsyncMock(
            side_effect=[
                None,
                None,  # initial _setup_age_session
                _make_result([]),  # entities SELECT
                None,
                None,  # second _setup_age_session
                _make_result([]),  # relations SELECT
                None,
                None,  # third _setup_age_session
                _make_result([event_row]),
                None,  # temporal SELECT + Cypher
                _make_result([]),  # exposures SELECT
                None,
                None,  # FR-13: fourth _setup_age_session (before prune)
                _make_result([]),  # FR-13: prune detection SELECT → no phantoms
            ]
        )
        sf = _make_session_factory(session)

        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        worker = AgeSyncWorker(session_factory=sf, valkey_client=_make_valkey(), settings=_make_settings())
        asyncio.run(worker.run())

        # F-016: temporal Cypher is at index 9 (was 5 before intermediate commits)
        cypher_call = session.execute.call_args_list[9]
        cypher_sql = str(cypher_call[0][0])
        assert "TemporalEvent" in cypher_sql

        params = json.loads(cypher_call[0][1]["params"])
        assert params["event_id"] == "01930000-0000-7000-8000-000000000099"
        assert params["title"] == "GDP q/q"

    def test_valkey_error_falls_back_to_epoch(self) -> None:
        """When Valkey.get() raises, the epoch watermark is used and the run continues."""

        from knowledge_graph.infrastructure.workers.age_sync_worker import _EPOCH, AgeSyncWorker

        valkey = AsyncMock()
        valkey.get = AsyncMock(side_effect=ConnectionError("valkey down"))
        valkey.set = AsyncMock()

        session = _make_session()
        sf = _make_session_factory(session)
        settings = _make_settings()

        captured_watermarks: list[datetime] = []

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=settings)

        async def _capture(sess: Any, since: datetime) -> int:
            captured_watermarks.append(since)
            return 0

        worker._sync_entities = _capture  # type: ignore[method-assign]
        worker._sync_relations = AsyncMock(return_value=0)  # type: ignore[method-assign]
        worker._sync_temporal_events = AsyncMock()  # type: ignore[method-assign]

        asyncio.run(worker.run())

        assert captured_watermarks == [_EPOCH]

    def test_valkey_write_error_does_not_crash_worker(self) -> None:
        """When Valkey.set() raises after sync, the run completes without raising."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        valkey = AsyncMock()
        valkey.get = AsyncMock(return_value=None)
        valkey.set = AsyncMock(side_effect=ConnectionError("valkey write failed"))

        session = _make_session()
        sf = _make_session_factory(session)

        worker = AgeSyncWorker(session_factory=sf, valkey_client=valkey, settings=_make_settings())
        # Must not raise
        asyncio.run(worker.run())


# ── Test: FR-13 phantom-edge prune pass (_prune_phantom_relations) ──────────────


class TestPrunePhantomRelations:
    """FR-13: the delete-aware subtractive pass that removes AGE edges whose
    relation_id no longer exists in ``public.relations`` (self-healing for the
    additive-only watermark MERGE)."""

    @staticmethod
    def _make_worker(session: Any) -> Any:
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        sf = _make_session_factory(session)
        return AgeSyncWorker(session_factory=sf, valkey_client=_make_valkey(), settings=_make_settings())

    def test_no_phantoms_issues_no_delete(self) -> None:
        """When detection finds no orphans, no Cypher DELETE is issued; returns 0."""
        session = AsyncMock()
        # First execute = detection query → empty result.
        session.execute = AsyncMock(return_value=_make_result([]))
        worker = self._make_worker(session)

        deleted = asyncio.run(worker._prune_phantom_relations(session))

        assert deleted == 0
        # Exactly one call (the detection SELECT); no per-id DELETE round-trips.
        assert session.execute.await_count == 1

    def test_phantom_edges_are_deleted(self) -> None:
        """Each detected phantom relation_id triggers one Cypher DELETE."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import _SQL_PRUNE_DELETE_EDGE

        phantom_rows = [("01920000-0000-7000-8000-000000000001",), ("01920000-0000-7000-8000-000000000002",)]
        results = [_make_result(phantom_rows)] + [_make_result([]) for _ in phantom_rows]
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=results)
        worker = self._make_worker(session)

        deleted = asyncio.run(worker._prune_phantom_relations(session))

        assert deleted == 2
        # 1 detection SELECT + 2 DELETEs = 3 calls.
        assert session.execute.await_count == 3
        # The two follow-up calls must be the phantom-edge DELETE statement,
        # each carrying its relation_id in the :params JSON.
        delete_calls = session.execute.await_args_list[1:]
        seen_ids = set()
        for call in delete_calls:
            sql_arg = str(call.args[0])
            assert "DELETE r" in sql_arg
            params = json.loads(call.args[1]["params"])
            seen_ids.add(params["relation_id"])
        assert seen_ids == {
            "01920000-0000-7000-8000-000000000001",
            "01920000-0000-7000-8000-000000000002",
        }
        # Sanity: the template the worker uses really is the DELETE one.
        assert "DELETE r" in _SQL_PRUNE_DELETE_EDGE

    def test_fail_open_on_error(self) -> None:
        """A detection/delete error is swallowed (returns 0), never aborts sync."""
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError("AGE exploded"))
        worker = self._make_worker(session)

        # Must not raise.
        deleted = asyncio.run(worker._prune_phantom_relations(session))
        assert deleted == 0

    def test_prune_invoked_during_run(self) -> None:
        """run() wires the prune pass into the cycle (delete-aware sync)."""
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        session = _make_session()
        sf = _make_session_factory(session)
        worker = AgeSyncWorker(session_factory=sf, valkey_client=_make_valkey(), settings=_make_settings())

        worker._sync_entities = AsyncMock(return_value=0)  # type: ignore[method-assign]
        worker._sync_relations = AsyncMock(return_value=0)  # type: ignore[method-assign]
        worker._sync_temporal_events = AsyncMock(return_value=0)  # type: ignore[method-assign]
        prune = AsyncMock(return_value=0)
        worker._prune_phantom_relations = prune  # type: ignore[method-assign]

        asyncio.run(worker.run())

        prune.assert_awaited_once()
