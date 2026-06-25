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
        result = asyncio.run(
            repo.upsert(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                canonical_type="employs",
                semantic_mode="RELATION_STATE",
                decay_class="DURABLE",
                decay_alpha=0.000950,
                base_confidence=0.70,
            ),
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
        asyncio.run(
            repo.upsert(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                canonical_type="employs",
                semantic_mode="RELATION_STATE",
                decay_class="DURABLE",
                decay_alpha=0.000950,
                base_confidence=0.70,
            ),
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
        asyncio.run(
            repo.upsert(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                canonical_type="employs",
                semantic_mode="RELATION_STATE",
                decay_class="DURABLE",
                decay_alpha=0.000950,
                base_confidence=0.70,
            ),
        )
        # The INSERT SQL (second call) must not mention partition_key
        insert_sql = str(session.execute.call_args_list[1][0][0])
        assert "partition_key" not in insert_sql

    def test_upsert_includes_explicit_confidence_value(self) -> None:
        """PLAN-0093 B-2 T-B-2-04: confidence is an explicit INSERT column.

        Migration 0046 adds a server_default = base_confidence so omitting
        confidence still produces a NOT-NULL value, but the application
        writer is required to set it EXPLICITLY so the invariant is visible
        in the SQL and reviewers immediately see what value is being stored.
        """
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
        asyncio.run(
            repo.upsert(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                canonical_type="employs",
                semantic_mode="RELATION_STATE",
                decay_class="DURABLE",
                decay_alpha=0.000950,
                base_confidence=0.70,
            ),
        )
        insert_sql = str(session.execute.call_args_list[1][0][0])
        # The column list must include ``confidence`` (not just confidence_stale).
        # We search for the token between commas/parens to avoid false-positives
        # from "confidence_stale" matches.
        assert ", confidence," in insert_sql or "confidence, " in insert_sql, (
            "expected ``confidence`` column in INSERT — got:\n" + insert_sql
        )
        # And the VALUES side must reference :base_confidence twice (one for
        # the base_confidence column, one for the confidence column).
        assert (
            insert_sql.count(":base_confidence") >= 2
        ), "expected :base_confidence to be bound for both base_confidence and confidence columns"


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
        asyncio.run(
            repo.insert_raw(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_document_id=uuid4(),
                extraction_confidence=0.85,
                source_trust_weight=0.90,
                evidence_date=_NOW,
                # PLAN-0093 B-3 T-B-3-02: claim_id + chunk_id are NOT NULL
                # (migration 0047).  Writer raises ValueError when omitted.
                claim_id=uuid4(),
                chunk_id=uuid4(),
            ),
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
        result = asyncio.run(
            repo.insert_raw(
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_document_id=uuid4(),
                extraction_confidence=0.85,
                source_trust_weight=0.90,
                evidence_date=_NOW,
                claim_id=uuid4(),
                chunk_id=uuid4(),
            ),
        )
        assert result == raw_id

    def test_insert_raw_rejects_missing_claim_id(self) -> None:
        """PLAN-0093 B-3 T-B-3-02 + P0 2026-06-11: omitting claim_id raises a
        FatalError subclass so the consumer dead-letters instead of retrying
        forever (a bare ValueError was classified as retryable and looped)."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
            RelationEvidenceRepository,
        )

        from messaging.kafka.consumer.errors import FatalError, MissingRequiredFieldError

        assert issubclass(MissingRequiredFieldError, FatalError)
        session = _make_session(fetchone_return=(str(uuid4()),))
        repo = RelationEvidenceRepository(session)
        with pytest.raises(MissingRequiredFieldError, match="claim_id is NOT NULL"):
            asyncio.run(
                repo.insert_raw(
                    subject_entity_id=uuid4(),
                    object_entity_id=uuid4(),
                    source_document_id=uuid4(),
                    extraction_confidence=0.85,
                    source_trust_weight=0.90,
                    evidence_date=_NOW,
                    # claim_id omitted
                    chunk_id=uuid4(),
                ),
            )

    def test_insert_raw_rejects_missing_chunk_id(self) -> None:
        """PLAN-0093 B-3 T-B-3-02 + P0 2026-06-11: omitting chunk_id raises a
        FatalError subclass (dead-letter, not silent retry loop)."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
            RelationEvidenceRepository,
        )

        from messaging.kafka.consumer.errors import MissingRequiredFieldError

        session = _make_session(fetchone_return=(str(uuid4()),))
        repo = RelationEvidenceRepository(session)
        with pytest.raises(MissingRequiredFieldError, match="chunk_id is NOT NULL"):
            asyncio.run(
                repo.insert_raw(
                    subject_entity_id=uuid4(),
                    object_entity_id=uuid4(),
                    source_document_id=uuid4(),
                    extraction_confidence=0.85,
                    source_trust_weight=0.90,
                    evidence_date=_NOW,
                    claim_id=uuid4(),
                    # chunk_id omitted
                ),
            )


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
        asyncio.run(
            repo.insert_new(
                relation_id=uuid4(),
                summary_text="test",
                evidence_count=3,
                evidence_hash="abc",
                model_id="llama3",
                prompt_template_id=uuid4(),
                generation_trigger="stale",
            ),
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
        result = asyncio.run(
            repo.find_opposing_claims(
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="neutral",
            ),
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
        asyncio.run(
            repo.find_opposing_claims(
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
            ),
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
        asyncio.run(
            repo.find_opposing_claims(
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
            ),
        )
        params = session.execute.call_args_list[0][0][1]
        assert params["opposite_polarity"] == "negative"

    def test_fetch_active_for_subject_joins_claims_not_relation_evidence_raw(self) -> None:
        """Regression (2026-06-16 data-pipeline-gaps Gap 1).

        ``relation_contradiction_links.relation_evidence_id`` holds a
        ``claims.claim_id``, so the confidence-formula lookup must resolve the
        subject via ``claims`` (``c.claim_id = rcl.relation_evidence_id``), not
        via ``relation_evidence_raw.raw_id`` (which matched 0/7180 rows). Pin
        the correct join so it can't silently revert.
        """
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.contradiction import (
            ContradictionRepository,
        )

        session = _make_session(fetchall_return=[])
        repo = ContradictionRepository(session)
        asyncio.run(repo.fetch_active_for_subject(subject_entity_id=uuid4()))

        sql = str(session.execute.call_args_list[0][0][0]).lower()
        assert "join claims c on c.claim_id = rcl.relation_evidence_id" in sql
        assert "c.subject_entity_id = :subject_entity_id" in sql
        assert "relation_evidence_raw" not in sql
        assert "rer.raw_id = rcl.relation_evidence_id" not in sql


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
        result = asyncio.run(
            repo.append(
                topic="graph.state.changed.v1",
                partition_key="entity-123",
                payload_avro=b"avro-bytes",
                event_id=event_id,
            ),
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
        asyncio.run(repo.fetch_pending(batch_size=10))
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

        asyncio.run(repo.ensure_rows_exist(uuid4(), "financial_instrument"))

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

        asyncio.run(repo.ensure_rows_exist(uuid4(), "person"))

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

            asyncio.run(repo.ensure_rows_exist(uuid4(), entity_type))

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

        asyncio.run(repo.ensure_rows_exist(uuid4(), "financial_instrument"))

        for call in session.execute.call_args_list:
            sql = str(call[0][0])
            assert "ON CONFLICT" in sql.upper(), "INSERT must be idempotent (ON CONFLICT DO NOTHING)"
            assert "DO NOTHING" in sql.upper()


# ---------------------------------------------------------------------------
# CanonicalEntityRepository — create() co-inserts EXACT self-alias (PLAN-0057 C-5)
# ---------------------------------------------------------------------------


class TestCanonicalEntityRepositoryCreateSelfAlias:
    """Regression coverage for PLAN-0057 Wave C-5 / T-C-5-01.

    `CanonicalEntityRepository.create()` must insert an EXACT self-alias row in
    the same SQL transaction as the canonical row. Without this, callers that
    bypass the dedicated `instrument_consumer` / `provisional_enrichment` paths
    leave the canonical without a Stage-1 alias-exact match for its own name.
    """

    def _make_session_two_calls(self, entity_id: UUID) -> AsyncMock:
        """Build a session whose first execute() returns the entity_id (canonical
        INSERT … RETURNING) and whose second execute() is the alias INSERT
        (no return value needed — DO NOTHING path).

        PLAN-0057 QA-iter1 F-DS-05: the alias INSERT is now wrapped in
        ``session.begin_nested()`` (SAVEPOINT) so a cross-entity EXACT
        collision against the legacy ``uidx_entity_aliases_normalized``
        index does not poison the outer transaction. We mock
        ``begin_nested`` as an async context manager that does nothing.
        """
        session = AsyncMock()
        canonical_result = MagicMock()
        canonical_result.fetchone.return_value = (str(entity_id),)
        alias_result = MagicMock()
        alias_result.fetchone.return_value = None
        session.execute = AsyncMock(side_effect=[canonical_result, alias_result])

        nested_cm = AsyncMock()
        nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
        nested_cm.__aexit__ = AsyncMock(return_value=None)
        session.begin_nested = MagicMock(return_value=nested_cm)
        return session

    def test_create_emits_self_alias_insert(self) -> None:
        """create() must execute exactly two SQL statements: canonical INSERT,
        then entity_aliases INSERT.
        """
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        eid = uuid4()
        session = self._make_session_two_calls(eid)
        repo = CanonicalEntityRepository(session)

        result = asyncio.run(repo.create("Apple Inc.", "financial_instrument", ticker="AAPL", exchange="NASDAQ"))

        assert result == eid
        # Two execute calls: canonical INSERT + alias INSERT
        assert session.execute.await_count == 2

    def test_create_alias_insert_uses_exact_alias_type_and_canonical_name(self) -> None:
        """The alias INSERT must use alias_type='EXACT' and the canonical_name
        verbatim as alias_text. The normalized form is lowercase+stripped.
        """
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        eid = uuid4()
        session = self._make_session_two_calls(eid)
        repo = CanonicalEntityRepository(session)

        asyncio.run(repo.create("  Apple Inc.  ", "financial_instrument"))

        # Second execute() = alias INSERT
        alias_call = session.execute.await_args_list[1]
        sql = str(alias_call[0][0]).lower()
        params = alias_call[0][1]

        assert "insert into entity_aliases" in sql
        assert "'exact'" in sql
        assert "'canonical_entity_create'" in sql
        # On-conflict path must match the partial UNIQUE index from migration 0008
        assert "on conflict (entity_id, normalized_alias_text, alias_type)" in sql
        assert "where is_active = true" in sql
        assert "do nothing" in sql

        # Alias text is the canonical_name verbatim; normalized_alias_text is lowercased+stripped
        assert params["eid"] == str(eid)
        assert params["alias"] == "  Apple Inc.  "
        assert params["norm"] == "apple inc."

    def test_create_returns_entity_id_from_canonical_insert(self) -> None:
        """create() must return the UUID returned by the canonical INSERT, not
        anything from the alias INSERT.
        """
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        eid = uuid4()
        session = self._make_session_two_calls(eid)
        repo = CanonicalEntityRepository(session)

        result = asyncio.run(repo.create("Some Sector", "sector"))

        assert isinstance(result, UUID)
        assert result == eid


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

        result = asyncio.run(repo.get_batch([]))

        assert result == []
        session.execute.assert_not_awaited()

    def test_get_batch_single_entity(self) -> None:
        """get_batch with one ID returns a list with one dict."""
        import asyncio

        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )

        eid = uuid4()
        # F-101 + PLAN-0099: row now has 10 columns (description [7], sector [8], industry [9])
        row = (str(eid), "Apple Inc.", "financial_instrument", "US0378331005", "AAPL", "NASDAQ", None, None, None, None)

        session = _make_session(fetchall_return=[row])
        repo = CanonicalEntityRepository(session)

        result = asyncio.run(repo.get_batch([eid]))

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
        # F-101 + PLAN-0099: each row has 10 columns — description [7], sector [8], industry [9]
        rows = [
            (str(ids[0]), "Corp A", "financial_instrument", None, "A", "NYSE", None, None, None, None),
            (str(ids[1]), "Corp B", "financial_instrument", None, "B", "NYSE", None, None, None, None),
            (str(ids[2]), "Corp C", "financial_instrument", None, "C", "NYSE", None, None, None, None),
        ]

        session = _make_session(fetchall_return=rows)
        repo = CanonicalEntityRepository(session)

        result = asyncio.run(repo.get_batch(ids))

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

        # F-101 + PLAN-0099: row has 10 columns — description [7], sector [8], industry [9]
        row = (str(existing_id), "Only One Corp", "financial_instrument", None, "OOC", "NYSE", None, None, None, None)
        session = _make_session(fetchall_return=[row])
        repo = CanonicalEntityRepository(session)

        result = asyncio.run(repo.get_batch([existing_id, missing_id]))

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

        asyncio.run(repo.get_batch(ids))

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

        asyncio.run(
            repo.upsert(
                uuid4(),
                "definition",
                embedding=None,
                model_id=None,
                source_text="text",
                source_hash="hash",
                next_refresh_at=_NOW,
            ),
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

        asyncio.run(
            repo.upsert(
                uuid4(),
                "definition",
                embedding=None,
                model_id=None,
                source_text="text",
                source_hash="hash",
                next_refresh_at=_NOW,
            ),
        )

        call_sql = str(session.execute.call_args[0][0])
        assert "COALESCE" in call_sql.upper()
        # Both embedding and model_id should use COALESCE
        coalesce_count = call_sql.upper().count("COALESCE")
        assert coalesce_count >= 2, f"Expected ≥2 COALESCE uses, found {coalesce_count}"


# ---------------------------------------------------------------------------
# EventRepository — BP-180 regression: CAST for NULL type disambiguation
# ---------------------------------------------------------------------------


class TestEventRepositoryBP180:
    """Regression tests for BP-180: asyncpg NULL type ambiguity in search_events.

    asyncpg raises AmbiguousParameterError when a Python None is bound to a
    parameter that appears in ':param IS NULL' — it cannot infer the PostgreSQL
    type from None.  Fix: CAST(:param AS TYPE) IS NULL so the type is always
    explicit even when the value is None.
    """

    def _make_repo(self, fetchall_return: list | None = None):  # type: ignore[no-untyped-def]
        from knowledge_graph.infrastructure.intelligence_db.repositories.event_repository import (
            EventRepository,
        )

        session = _make_session(fetchall_return=fetchall_return)
        return EventRepository(session), session

    def test_search_events_sql_uses_cast_for_entity_ids(self) -> None:
        """The entity_ids filter must use CAST(:entity_ids AS UUID[]) — not bare IS NULL."""
        import asyncio

        repo, session = self._make_repo()
        asyncio.run(repo.search_events(entity_ids=[]))

        sql_text: str = str(session.execute.call_args[0][0].text)
        assert (
            "cast(:entity_ids as uuid[])" in sql_text.lower()
        ), f"BP-180 CAST for entity_ids not found in SQL: {sql_text}"

    def test_search_events_sql_uses_cast_for_event_types(self) -> None:
        """The event_types filter must use CAST(:event_types AS TEXT[]) — not bare IS NULL."""
        import asyncio

        repo, session = self._make_repo()
        asyncio.run(repo.search_events(entity_ids=[], event_types=None))

        sql_text: str = str(session.execute.call_args[0][0].text)
        assert (
            "cast(:event_types as text[])" in sql_text.lower()
        ), f"BP-180 CAST for event_types not found in SQL: {sql_text}"

    def test_search_events_none_entity_ids_passes_none_param(self) -> None:
        """Empty entity_ids list → None param (the CAST handles type disambiguation)."""
        import asyncio

        repo, session = self._make_repo()
        asyncio.run(repo.search_events(entity_ids=[]))

        params: dict = session.execute.call_args[0][1]
        # Empty list → None param (filter disabled — all entities included)
        assert params["entity_ids"] is None

    def test_search_events_none_event_types_passes_none_param(self) -> None:
        """event_types=None → None param (the CAST handles type disambiguation)."""
        import asyncio

        repo, session = self._make_repo()
        asyncio.run(repo.search_events(entity_ids=[], event_types=None))

        params: dict = session.execute.call_args[0][1]
        assert params["event_types"] is None

    def test_search_events_with_entity_ids_passes_list(self) -> None:
        """Non-empty entity_ids list is converted to string UUIDs and forwarded."""
        import asyncio

        entity_id = uuid4()
        repo, session = self._make_repo()
        asyncio.run(repo.search_events(entity_ids=[entity_id]))

        params: dict = session.execute.call_args[0][1]
        assert params["entity_ids"] == [str(entity_id)]

    def test_search_events_empty_result_returns_empty_list(self) -> None:
        """Empty DB result → returns empty list."""
        import asyncio

        repo, _ = self._make_repo(fetchall_return=[])
        result = asyncio.run(repo.search_events(entity_ids=[]))
        assert result == []
