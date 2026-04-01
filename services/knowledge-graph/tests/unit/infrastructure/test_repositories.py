"""Unit tests for intelligence_db repositories (mock session)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 27, 12, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(fetchone_return: object = None, fetchall_return: list | None = None) -> AsyncMock:
    """Build a mock AsyncSession whose execute() returns fetchone/fetchall results."""
    session = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = fetchone_return
    result.fetchall.return_value = fetchall_return or []
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# RelationRepository
# ---------------------------------------------------------------------------


class TestRelationRepository:
    def test_upsert_returns_relation_id(self) -> None:
        """upsert() must call advisory lock + INSERT … ON CONFLICT and return a UUID."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
            RelationRepository,
        )

        relation_id = uuid4()
        # Two execute calls: advisory lock (no return) + upsert (returns relation_id)
        session = AsyncMock()
        lock_result = MagicMock()
        lock_result.fetchone.return_value = None
        upsert_result = MagicMock()
        upsert_result.fetchone.return_value = (str(relation_id),)
        session.execute = AsyncMock(side_effect=[lock_result, upsert_result])

        repo = RelationRepository(session)
        result = asyncio.get_event_loop().run_until_complete(
            repo.upsert(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                canonical_type="employs",
                semantic_mode="RELATION_STATE",
                decay_class="DURABLE",
                decay_alpha=0.000950,
                base_confidence=0.70,
            )
        )
        assert isinstance(result, UUID)
        assert session.execute.call_count == 2

    def test_upsert_advisory_lock_first(self) -> None:
        """First execute call must be the advisory lock query."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
            RelationRepository,
        )

        relation_id = uuid4()
        session = AsyncMock()
        lock_result = MagicMock()
        lock_result.fetchone.return_value = None
        upsert_result = MagicMock()
        upsert_result.fetchone.return_value = (str(relation_id),)
        session.execute = AsyncMock(side_effect=[lock_result, upsert_result])

        repo = RelationRepository(session)
        asyncio.get_event_loop().run_until_complete(
            repo.upsert(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                canonical_type="employs",
                semantic_mode="RELATION_STATE",
                decay_class="DURABLE",
                decay_alpha=0.000950,
                base_confidence=0.70,
            )
        )
        first_call_sql = str(session.execute.call_args_list[0][0][0])
        assert "advisory" in first_call_sql.lower()

    def test_upsert_does_not_include_partition_key(self) -> None:
        """partition_key must not appear in the INSERT statement."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import (
            RelationRepository,
        )

        session = AsyncMock()
        lock_result = MagicMock()
        lock_result.fetchone.return_value = None
        upsert_result = MagicMock()
        upsert_result.fetchone.return_value = (str(uuid4()),)
        session.execute = AsyncMock(side_effect=[lock_result, upsert_result])

        repo = RelationRepository(session)
        asyncio.get_event_loop().run_until_complete(
            repo.upsert(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                canonical_type="employs",
                semantic_mode="RELATION_STATE",
                decay_class="DURABLE",
                decay_alpha=0.000950,
                base_confidence=0.70,
            )
        )
        # The INSERT SQL (second call) must not mention partition_key
        insert_sql = str(session.execute.call_args_list[1][0][0])
        assert "partition_key" not in insert_sql


# ---------------------------------------------------------------------------
# RelationEvidenceRepository
# ---------------------------------------------------------------------------


class TestRelationEvidenceRepository:
    def test_insert_raw_does_not_include_partition_key(self) -> None:
        """partition_key is STORED — must never appear in INSERT for relation_evidence_raw."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
            RelationEvidenceRepository,
        )

        session = _make_session(fetchone_return=(str(uuid4()),))
        repo = RelationEvidenceRepository(session)
        asyncio.get_event_loop().run_until_complete(
            repo.insert_raw(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_document_id=uuid4(),
                extraction_confidence=0.85,
                source_trust_weight=0.90,
                evidence_date=_NOW,
            )
        )
        sql = str(session.execute.call_args_list[0][0][0])
        assert "partition_key" not in sql

    def test_insert_raw_returns_uuid(self) -> None:
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
            RelationEvidenceRepository,
        )

        raw_id = uuid4()
        session = _make_session(fetchone_return=(str(raw_id),))
        repo = RelationEvidenceRepository(session)
        result = asyncio.get_event_loop().run_until_complete(
            repo.insert_raw(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_document_id=uuid4(),
                extraction_confidence=0.85,
                source_trust_weight=0.90,
                evidence_date=_NOW,
            )
        )
        assert result == raw_id


# ---------------------------------------------------------------------------
# RelationSummaryRepository
# ---------------------------------------------------------------------------


class TestRelationSummaryRepository:
    def test_insert_new_retires_old_first(self) -> None:
        """insert_new must execute UPDATE is_current=false before INSERT."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
            RelationSummaryRepository,
        )

        session = AsyncMock()
        update_result = MagicMock()
        update_result.fetchone.return_value = None
        insert_result = MagicMock()
        insert_result.fetchone.return_value = (str(uuid4()),)
        session.execute = AsyncMock(side_effect=[update_result, insert_result])

        repo = RelationSummaryRepository(session)
        asyncio.get_event_loop().run_until_complete(
            repo.insert_new(
                relation_id=uuid4(),
                summary_text="test",
                evidence_count=3,
                evidence_hash="abc",
                model_id="llama3",
                prompt_template_id=uuid4(),
                generation_trigger="stale",
            )
        )
        assert session.execute.call_count == 2
        update_sql = str(session.execute.call_args_list[0][0][0])
        assert "is_current" in update_sql
        assert "false" in update_sql.lower()


# ---------------------------------------------------------------------------
# ContradictionRepository
# ---------------------------------------------------------------------------


class TestContradictionRepository:
    def test_find_opposing_neutral_returns_empty(self) -> None:
        """neutral polarity cannot form a contradiction."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction import (
            ContradictionRepository,
        )

        session = _make_session()
        repo = ContradictionRepository(session)
        result = asyncio.get_event_loop().run_until_complete(
            repo.find_opposing_claims(
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="neutral",
            )
        )
        assert result == []
        # Session should NOT have been called (short-circuit)
        session.execute.assert_not_called()

    def test_contradiction_window_is_90_days(self) -> None:
        """The SQL query must use the 90-day window passed as a parameter."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction import (
            ContradictionRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = ContradictionRepository(session)
        asyncio.get_event_loop().run_until_complete(
            repo.find_opposing_claims(
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
            )
        )
        # SQL uses parameterized :window_days (not hardcoded literal)
        sql = str(session.execute.call_args_list[0][0][0])
        assert "window_days" in sql
        # Default window is 90 days — verify in the params dict
        params = session.execute.call_args_list[0][0][1]
        assert params["window_days"] == 90

    def test_positive_polarity_queries_negative(self) -> None:
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction import (
            ContradictionRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = ContradictionRepository(session)
        asyncio.get_event_loop().run_until_complete(
            repo.find_opposing_claims(
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
            )
        )
        params = session.execute.call_args_list[0][0][1]
        assert params["opposite_polarity"] == "negative"


# ---------------------------------------------------------------------------
# OutboxRepository
# ---------------------------------------------------------------------------


class TestOutboxRepository:
    def test_append_returns_uuid(self) -> None:
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import (
            OutboxRepository,
        )

        event_id = uuid4()
        session = _make_session(fetchone_return=(str(event_id),))
        repo = OutboxRepository(session)
        result = asyncio.get_event_loop().run_until_complete(
            repo.append(
                topic="graph.state.changed.v1",
                partition_key="entity-123",
                payload_avro=b"avro-bytes",
            )
        )
        assert result == event_id

    def test_fetch_pending_uses_skip_locked(self) -> None:
        """fetch_pending must use FOR UPDATE SKIP LOCKED to allow concurrent dispatchers."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import (
            OutboxRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = OutboxRepository(session)
        asyncio.get_event_loop().run_until_complete(repo.fetch_pending(batch_size=10))
        sql = str(session.execute.call_args_list[0][0][0])
        assert "SKIP LOCKED" in sql.upper()
