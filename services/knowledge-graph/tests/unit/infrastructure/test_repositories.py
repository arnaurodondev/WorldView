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


# ---------------------------------------------------------------------------
# get_view_types_for_entity_type  (pure function — no DB)
# ---------------------------------------------------------------------------


class TestGetViewTypesForEntityType:
    def test_financial_instrument_gets_three_views(self) -> None:
        """financial_instrument → (definition, narrative, fundamentals_ohlcv)."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            VIEW_DEFINITION,
            VIEW_FUNDAMENTALS,
            VIEW_NARRATIVE,
            get_view_types_for_entity_type,
        )

        result = get_view_types_for_entity_type("financial_instrument")
        assert set(result) == {VIEW_DEFINITION, VIEW_NARRATIVE, VIEW_FUNDAMENTALS}
        assert len(result) == 3

    def test_non_company_gets_two_views(self) -> None:
        """Non-company entity types → (definition, narrative) only."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            VIEW_DEFINITION,
            VIEW_NARRATIVE,
            get_view_types_for_entity_type,
        )

        for entity_type in ("person", "country", "organization", "regulatory_body", "index"):
            result = get_view_types_for_entity_type(entity_type)
            assert set(result) == {
                VIEW_DEFINITION,
                VIEW_NARRATIVE,
            }, f"Expected 2 views for entity_type={entity_type!r}, got: {result}"
            assert len(result) == 2

    def test_unknown_entity_type_gets_two_views(self) -> None:
        """Unrecognised entity types default to 2 views (safe fallback)."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            get_view_types_for_entity_type,
        )

        result = get_view_types_for_entity_type("unknown_future_type")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# EntityEmbeddingStateRepository.ensure_rows_exist
# ---------------------------------------------------------------------------


class TestEntityEmbeddingStateRepositoryEnsureRowsExist:
    def test_ensure_rows_exist_company_executes_three_inserts(self) -> None:
        """financial_instrument → 3 INSERT statements (one per view type)."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        repo = EntityEmbeddingStateRepository(session)

        asyncio.get_event_loop().run_until_complete(repo.ensure_rows_exist(uuid4(), "financial_instrument"))

        assert (
            session.execute.call_count == 3
        ), f"Expected 3 execute calls for financial_instrument, got {session.execute.call_count}"
        # Verify fundamentals_ohlcv row was requested
        all_view_types_used = [call[0][1]["view_type"] for call in session.execute.call_args_list]
        assert "fundamentals_ohlcv" in all_view_types_used

    def test_ensure_rows_exist_non_company_executes_two_inserts(self) -> None:
        """Non-company entity → 2 INSERT statements (definition + narrative only)."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        repo = EntityEmbeddingStateRepository(session)

        asyncio.get_event_loop().run_until_complete(repo.ensure_rows_exist(uuid4(), "person"))

        assert session.execute.call_count == 2, f"Expected 2 execute calls for person, got {session.execute.call_count}"
        all_view_types_used = [call[0][1]["view_type"] for call in session.execute.call_args_list]
        assert (
            "fundamentals_ohlcv" not in all_view_types_used
        ), "fundamentals_ohlcv must NOT be inserted for non-company entities"

    def test_ensure_rows_exist_all_non_company_types_get_two_inserts(self) -> None:
        """Each non-company entity type gets exactly 2 INSERT calls."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        non_company_types = ["person", "country", "organization", "regulatory_body", "index"]

        for entity_type in non_company_types:
            session = AsyncMock()
            session.execute = AsyncMock(return_value=MagicMock())
            repo = EntityEmbeddingStateRepository(session)

            asyncio.get_event_loop().run_until_complete(repo.ensure_rows_exist(uuid4(), entity_type))

            assert (
                session.execute.call_count == 2
            ), f"Expected 2 execute calls for entity_type={entity_type!r}, got {session.execute.call_count}"

    def test_ensure_rows_exist_uses_on_conflict_do_nothing(self) -> None:
        """INSERT must use ON CONFLICT DO NOTHING for idempotency."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        repo = EntityEmbeddingStateRepository(session)

        asyncio.get_event_loop().run_until_complete(repo.ensure_rows_exist(uuid4(), "financial_instrument"))

        for call in session.execute.call_args_list:
            sql = str(call[0][0])
            assert "ON CONFLICT" in sql.upper(), "INSERT must be idempotent (ON CONFLICT DO NOTHING)"
            assert "DO NOTHING" in sql.upper()


# ---------------------------------------------------------------------------
# CanonicalEntityRepository — get_batch
# ---------------------------------------------------------------------------


class TestCanonicalEntityRepositoryGetBatch:
    def test_get_batch_empty_input_returns_empty_list(self) -> None:
        """get_batch([]) returns [] without hitting the DB."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        session = AsyncMock()
        repo = CanonicalEntityRepository(session)

        result = asyncio.get_event_loop().run_until_complete(repo.get_batch([]))

        assert result == []
        session.execute.assert_not_awaited()

    def test_get_batch_single_entity(self) -> None:
        """get_batch with one ID returns a list with one dict."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        eid = uuid4()
        row = (str(eid), "Apple Inc.", "financial_instrument", "US0378331005", "AAPL", "NASDAQ", None)

        session = _make_session(fetchall_return=[row])
        repo = CanonicalEntityRepository(session)

        result = asyncio.get_event_loop().run_until_complete(repo.get_batch([eid]))

        assert len(result) == 1
        assert result[0]["entity_id"] == eid
        assert result[0]["canonical_name"] == "Apple Inc."
        assert result[0]["ticker"] == "AAPL"

    def test_get_batch_multiple_entities(self) -> None:
        """get_batch with multiple IDs issues ONE query and returns all found rows."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        ids = [uuid4(), uuid4(), uuid4()]
        rows = [
            (str(ids[0]), "Corp A", "financial_instrument", None, "A", "NYSE", None),
            (str(ids[1]), "Corp B", "financial_instrument", None, "B", "NYSE", None),
            (str(ids[2]), "Corp C", "financial_instrument", None, "C", "NYSE", None),
        ]

        session = _make_session(fetchall_return=rows)
        repo = CanonicalEntityRepository(session)

        result = asyncio.get_event_loop().run_until_complete(repo.get_batch(ids))

        # ONE execute call for all IDs (not N)
        session.execute.assert_awaited_once()
        assert len(result) == 3

    def test_get_batch_missing_ids_silently_omitted(self) -> None:
        """Missing entity IDs are not returned — no error raised."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        existing_id = uuid4()
        missing_id = uuid4()

        row = (str(existing_id), "Only One Corp", "financial_instrument", None, "OOC", "NYSE", None)
        session = _make_session(fetchall_return=[row])
        repo = CanonicalEntityRepository(session)

        result = asyncio.get_event_loop().run_until_complete(repo.get_batch([existing_id, missing_id]))

        assert len(result) == 1
        assert result[0]["entity_id"] == existing_id

    def test_get_batch_uses_any_operator(self) -> None:
        """get_batch must use WHERE entity_id = ANY(:ids) — single round-trip."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = CanonicalEntityRepository(session)
        ids = [uuid4(), uuid4()]

        asyncio.get_event_loop().run_until_complete(repo.get_batch(ids))

        call_sql = str(session.execute.call_args[0][0])
        assert "ANY" in call_sql.upper(), "get_batch must use WHERE entity_id = ANY(:ids)"


# ---------------------------------------------------------------------------
# EntityEmbeddingStateRepository — upsert COALESCE (F-DS-009)
# ---------------------------------------------------------------------------


class TestEntityEmbeddingStateUpsertCoalesce:
    def test_upsert_sql_coalesces_embedding(self) -> None:
        """ON CONFLICT DO UPDATE must use COALESCE for embedding to prevent NULL overwrite."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        session = _make_session()
        repo = EntityEmbeddingStateRepository(session)

        asyncio.get_event_loop().run_until_complete(
            repo.upsert(
                uuid4(),
                "definition",
                embedding=None,
                model_id=None,
                source_text="text",
                source_hash="hash",
                next_refresh_at=_NOW,
            )
        )

        call_sql = str(session.execute.call_args[0][0])
        assert "COALESCE" in call_sql.upper(), "upsert SQL must COALESCE embedding to preserve existing vectors"
        assert "EXCLUDED.embedding" in call_sql

    def test_upsert_sql_coalesces_model_id(self) -> None:
        """model_id must also use COALESCE so it is not overwritten by NULL on hash-unchanged path."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        session = _make_session()
        repo = EntityEmbeddingStateRepository(session)

        asyncio.get_event_loop().run_until_complete(
            repo.upsert(
                uuid4(),
                "definition",
                embedding=None,
                model_id=None,
                source_text="text",
                source_hash="hash",
                next_refresh_at=_NOW,
            )
        )

        call_sql = str(session.execute.call_args[0][0])
        assert "COALESCE" in call_sql.upper()
        # Both embedding and model_id should use COALESCE
        coalesce_count = call_sql.upper().count("COALESCE")
        assert coalesce_count >= 2, f"Expected ≥2 COALESCE uses, found {coalesce_count}"
