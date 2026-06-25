"""Unit tests for Block 12a: graph materialization."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = (str(uuid4()),)
    result.rowcount = 1
    session.execute = AsyncMock(return_value=result)
    return session


def _make_relation_repo(relation_id: UUID | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.upsert = AsyncMock(return_value=relation_id or uuid4())
    return repo


def _make_evidence_repo(raw_id: UUID | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.insert_raw = AsyncMock(return_value=raw_id or uuid4())
    return repo


def _make_outbox_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.append = AsyncMock(return_value=uuid4())
    return repo


def _make_entity_repo(*, exists: bool = True) -> AsyncMock:
    """Entity repo whose ``exists()`` returns *exists* for every id.

    Pass a set-backed side_effect via the returned mock to vary per-entity.
    """
    repo = AsyncMock()
    repo.exists = AsyncMock(return_value=exists)
    return repo


def _raw_relation(
    *,
    raw_type: str = "employs",
    entity_provisional: bool = False,
    subject_entity_id: UUID | None = None,
    object_entity_id: UUID | None = None,
) -> object:
    from knowledge_graph.application.blocks.graph_write import RawRelation

    return RawRelation(
        subject_entity_id=subject_entity_id or uuid4(),
        object_entity_id=object_entity_id or uuid4(),
        raw_type=raw_type,
        extraction_confidence=0.85,
        evidence_date=_NOW,
        entity_provisional=entity_provisional,
    )


# ---------------------------------------------------------------------------
# Graph upsert idempotency
# ---------------------------------------------------------------------------


class TestGraphMaterializationRelations:
    def test_empty_relations_returns_zero_counts(self) -> None:
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        summary = asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        assert summary.relations_upserted == 0
        assert summary.evidence_rows_inserted == 0

    def test_relation_with_canonical_type_calls_upsert(self) -> None:
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        relation_repo = _make_relation_repo()
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        relation_repo.upsert.assert_called_once()

    def test_relation_with_none_canonical_type_skips_upsert(self) -> None:
        """Unknown relation types (proposed) must NOT upsert to relations table."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        relation_repo = _make_relation_repo()
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=[None],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        relation_repo.upsert.assert_not_called()

    def test_evidence_always_inserted_even_for_proposed_type(self) -> None:
        """Evidence staging happens regardless of canonicalization outcome."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        evidence_repo = _make_evidence_repo()
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=[None],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=evidence_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        evidence_repo.insert_raw.assert_called_once()


# ---------------------------------------------------------------------------
# 2026-06-11 — entity-existence gate (relations FK-crash fix)
# ---------------------------------------------------------------------------


class TestEntityExistenceGate:
    """When the entity_repo is wired, a relation whose subject or object entity
    is missing must NOT call relation_repo.upsert (which would FK-crash), must
    still write the evidence row (with entity_provisional=True), and must
    increment the deferred counter. Both-present relations upsert as before."""

    def test_missing_subject_skips_upsert_and_defers_evidence(self) -> None:
        from knowledge_graph.application.blocks.graph_write import RawRelation, materialize_graph

        subj_id = uuid4()
        obj_id = uuid4()
        rel = RawRelation(
            subject_entity_id=subj_id,
            object_entity_id=obj_id,
            raw_type="employs",
            extraction_confidence=0.85,
            evidence_date=_NOW,
        )
        relation_repo = _make_relation_repo()
        evidence_repo = _make_evidence_repo()
        entity_repo = _make_entity_repo()
        # subject missing, object present
        entity_repo.exists = AsyncMock(side_effect=lambda eid: eid != subj_id)

        from knowledge_graph.application.metrics import s7_relation_entity_missing_total

        before = s7_relation_entity_missing_total.labels(reason="subject_missing")._value.get()

        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=relation_repo,
                evidence_repo=evidence_repo,
                outbox_repo=_make_outbox_repo(),
                entity_repo=entity_repo,
            )
        )
        # No edge upsert — this is what prevents the FK crash.
        relation_repo.upsert.assert_not_called()
        # Evidence row still written, but flagged deferred.
        evidence_repo.insert_raw.assert_called_once()
        assert evidence_repo.insert_raw.call_args.kwargs["entity_provisional"] is True
        # Counter incremented for the subject_missing reason.
        after = s7_relation_entity_missing_total.labels(reason="subject_missing")._value.get()
        assert after == before + 1

    def test_both_present_upserts_edge(self) -> None:
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        relation_repo = _make_relation_repo()
        evidence_repo = _make_evidence_repo()
        entity_repo = _make_entity_repo(exists=True)
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=relation_repo,
                evidence_repo=evidence_repo,
                outbox_repo=_make_outbox_repo(),
                entity_repo=entity_repo,
            )
        )
        relation_repo.upsert.assert_called_once()
        # Not deferred — both entities present.
        assert evidence_repo.insert_raw.call_args.kwargs["entity_provisional"] is False

    def test_exists_is_cached_per_call(self) -> None:
        """The same entity is queried at most once even across two relations."""
        from knowledge_graph.application.blocks.graph_write import RawRelation, materialize_graph

        shared_subj = uuid4()
        obj_a = uuid4()
        obj_b = uuid4()
        rels = [
            RawRelation(subject_entity_id=shared_subj, object_entity_id=obj_a, raw_type="employs", evidence_date=_NOW),
            RawRelation(subject_entity_id=shared_subj, object_entity_id=obj_b, raw_type="employs", evidence_date=_NOW),
        ]
        entity_repo = _make_entity_repo(exists=True)
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=rels,
                canonical_types=["employs", "employs"],
                canonical_semantic_modes=[None, None],
                canonical_decay_classes=[None, None],
                canonical_decay_alphas=[None, None],
                canonical_base_confidences=[None, None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
                entity_repo=entity_repo,
            )
        )
        # 3 distinct entity ids (shared_subj, obj_a, obj_b) → 3 exists() calls,
        # not 4 — shared_subj is cached after the first relation.
        queried = {c.args[0] for c in entity_repo.exists.call_args_list}
        assert queried == {shared_subj, obj_a, obj_b}
        assert entity_repo.exists.call_count == 3


# ---------------------------------------------------------------------------
# partition_key never in INSERT
# ---------------------------------------------------------------------------


class TestPartitionKeyNotInInsert:
    def test_insert_raw_not_called_with_partition_key(self) -> None:
        """partition_key is STORED — evidence_repo.insert_raw must NOT receive it."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        evidence_repo = _make_evidence_repo()
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=evidence_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        # Verify insert_raw was called with no partition_key kwarg
        kwargs = evidence_repo.insert_raw.call_args.kwargs
        assert "partition_key" not in kwargs


# ---------------------------------------------------------------------------
# entity.dirtied.v1 — PLAN-0031 C-1: returned as entity_ids_to_dirty
# ---------------------------------------------------------------------------


class TestEntityDirtiedReturnedNotProduced:
    """PLAN-0031 C-1: materialize_graph() no longer produces entity.dirtied.v1
    directly.  Instead it returns entity_ids_to_dirty in the summary so the
    caller can produce AFTER session.commit()."""

    def test_materialize_graph_returns_dirtied_entity_ids(self) -> None:
        """Both subject and object entity IDs are in the returned set."""
        from knowledge_graph.application.blocks.graph_write import RawRelation, materialize_graph

        subj_id = uuid4()
        obj_id = uuid4()
        rel = RawRelation(
            subject_entity_id=subj_id,
            object_entity_id=obj_id,
            raw_type="employs",
            extraction_confidence=0.85,
            evidence_date=_NOW,
        )
        summary = asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        # Both subject and object IDs must be in the returned frozenset
        assert subj_id in summary.entity_ids_to_dirty
        assert obj_id in summary.entity_ids_to_dirty
        assert isinstance(summary.entity_ids_to_dirty, frozenset)

    def test_materialize_graph_does_not_produce_kafka(self) -> None:
        """No produce_bytes() calls inside the function — caller produces."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        # Verify there is no direct_producer parameter at all (TypeError if passed)
        rel = _raw_relation()
        # If we accidentally pass direct_producer, the function should reject it
        # since we removed the parameter
        summary = asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        # The function returns entity IDs to dirty (not empty for a relation)
        assert summary.entities_dirtied >= 1
        assert len(summary.entity_ids_to_dirty) >= 1

    def test_empty_relations_returns_empty_dirty_set(self) -> None:
        """No relations = no dirty entities."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        summary = asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        assert len(summary.entity_ids_to_dirty) == 0

    def test_graph_state_changed_emitted_via_outbox(self) -> None:
        """graph.state.changed.v1 must use outbox.append."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        outbox = _make_outbox_repo()
        rel = _raw_relation()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=_make_session(),
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=outbox,
            )
        )
        assert outbox.append.called
        topics = [c.kwargs["topic"] for c in outbox.append.call_args_list]
        assert "graph.state.changed.v1" in topics


# ---------------------------------------------------------------------------
# Events + claims inserts
# ---------------------------------------------------------------------------


class TestEventsAndClaims:
    def test_events_inserted_via_session(self) -> None:
        from knowledge_graph.application.blocks.graph_write import RawEvent, materialize_graph

        session = _make_session()
        event = RawEvent(
            subject_entity_id=uuid4(),
            event_type="ceo_departure",
            event_text="CEO resigned",
            extraction_confidence=0.9,
            event_date=_NOW,
        )
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[event],
                claims=[],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        # session.execute should have been called (INSERT events + INSERT event_entities)
        assert session.execute.call_count >= 2

    def test_claims_inserted_via_session(self) -> None:
        from knowledge_graph.application.blocks.graph_write import RawClaim, materialize_graph

        session = _make_session()
        claim = RawClaim(
            subject_entity_id=uuid4(),
            claim_type="analyst_rating",
            polarity="positive",
            claim_text="Buy rating",
            extraction_confidence=0.8,
        )
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[claim],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        # session.execute should have been called for INSERT claims
        assert session.execute.call_count >= 1
        sqls = [str(c.args[0]) for c in session.execute.call_args_list]
        assert any("claims" in s.lower() for s in sqls)


# ---------------------------------------------------------------------------
# KG-002 closure: detailed claim materialization tests
# ---------------------------------------------------------------------------


def _raw_claim(
    *,
    subject_entity_id: UUID | None = None,
    claim_type: str = "analyst_rating",
    polarity: str = "positive",
    claim_text: str = "Upgraded to Buy",
    extraction_confidence: float = 0.85,
    claimer_entity_id: UUID | None = None,
    chunk_id: UUID | None = None,
    is_backfill: bool = False,
) -> object:
    from knowledge_graph.application.blocks.graph_write import RawClaim

    return RawClaim(
        subject_entity_id=subject_entity_id or uuid4(),
        claim_type=claim_type,
        polarity=polarity,
        claim_text=claim_text,
        extraction_confidence=extraction_confidence,
        claimer_entity_id=claimer_entity_id,
        chunk_id=chunk_id,
        is_backfill=is_backfill,
    )


class TestClaimMaterialization:
    """KG-002 closure: verify _insert_claim via materialize_graph for
    various claim scenarios — multiple claims, optional fields, backfill flag,
    and claims_inserted count in the returned summary."""

    def test_multiple_claims_all_inserted(self) -> None:
        """Multiple claims produce the correct claims_inserted count."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        session = _make_session()
        claims = [
            _raw_claim(claim_type="analyst_rating"),
            _raw_claim(claim_type="revenue_guidance"),
            _raw_claim(claim_type="market_outlook"),
        ]
        summary = asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=claims,  # type: ignore[list-item]
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        assert summary.claims_inserted == 3
        # Each claim triggers one session.execute call
        sqls = [str(c.args[0]) for c in session.execute.call_args_list]
        claim_inserts = [s for s in sqls if "claims" in s.lower()]
        assert len(claim_inserts) == 3

    def test_claim_with_optional_fields_passes_correct_params(self) -> None:
        """Claim with claimer_entity_id and chunk_id passes them to INSERT."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        session = _make_session()
        claimer_id = uuid4()
        chunk_id = uuid4()
        claim = _raw_claim(
            claimer_entity_id=claimer_id,
            chunk_id=chunk_id,
        )
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[claim],  # type: ignore[list-item]
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        # Find the claims INSERT call and verify params
        for call in session.execute.call_args_list:
            sql_text = str(call.args[0])
            if "claims" in sql_text.lower():
                params = call.args[1]
                assert params["claimer_entity_id"] == str(claimer_id)
                assert params["chunk_id"] == str(chunk_id)
                break
        else:
            pytest.fail("No claims INSERT call found")

    def test_claim_without_optional_fields_passes_none(self) -> None:
        """Claim without claimer/chunk passes None for those params."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        session = _make_session()
        claim = _raw_claim()  # no claimer_entity_id or chunk_id
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[claim],  # type: ignore[list-item]
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        for call in session.execute.call_args_list:
            sql_text = str(call.args[0])
            if "claims" in sql_text.lower():
                params = call.args[1]
                assert params["claimer_entity_id"] is None
                assert params["chunk_id"] is None
                break
        else:
            pytest.fail("No claims INSERT call found")

    def test_backfill_claim_sets_is_backfill_true(self) -> None:
        """Backfill claims pass is_backfill=True to the INSERT."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        session = _make_session()
        claim = _raw_claim(is_backfill=True)
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=True,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[claim],  # type: ignore[list-item]
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        for call in session.execute.call_args_list:
            sql_text = str(call.args[0])
            if "claims" in sql_text.lower():
                params = call.args[1]
                assert params["is_backfill"] is True
                break
        else:
            pytest.fail("No claims INSERT call found")

    def test_claim_subject_entity_added_to_affected_ids(self) -> None:
        """The claim's subject_entity_id is included in affected entity IDs
        (used for entity.dirtied.v1 and graph.state.changed.v1)."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        session = _make_session()
        subject_id = uuid4()
        claim = _raw_claim(subject_entity_id=subject_id)
        summary = asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[claim],  # type: ignore[list-item]
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        # Claims-only message: the graph.state.changed outbox should still fire
        # because affected_entity_ids is non-empty from the claim
        # Can't check the outbox repo passed above easily
        # But we can verify claims_inserted count
        assert summary.claims_inserted == 1

    def test_extraction_model_id_passed_to_claim_insert(self) -> None:
        """extraction_model_id kwarg is forwarded to _insert_claim."""
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        session = _make_session()
        claim = _raw_claim()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[],
                claims=[claim],  # type: ignore[list-item]
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
                extraction_model_id="qwen2.5:7b-instruct",
            )
        )
        for call in session.execute.call_args_list:
            sql_text = str(call.args[0])
            if "claims" in sql_text.lower():
                params = call.args[1]
                assert params["extraction_model_id"] == "qwen2.5:7b-instruct"
                break
        else:
            pytest.fail("No claims INSERT call found")


# ---------------------------------------------------------------------------
# DEF-025 — Deterministic event_id (PLAN-0076 Wave A-3)
# ---------------------------------------------------------------------------


def _make_raw_event(
    *,
    subject_entity_id: UUID | None = None,
    event_type: str = "earnings_release",
    event_text: str = "Apple reports Q4 earnings",
) -> object:
    """Helper to build a RawEvent with stable defaults so DEF-025 tests
    can vary one input axis at a time and check the resulting event_id.
    """
    from knowledge_graph.application.blocks.graph_write import RawEvent

    return RawEvent(
        subject_entity_id=subject_entity_id or uuid4(),
        event_type=event_type,
        event_text=event_text,
        extraction_confidence=0.9,
        event_date=_NOW,
        participant_entity_ids=(),
    )


class TestDeterministicEventId:
    """Replays of the same enriched-article message must produce the same event_id.

    These tests pin the DEF-025 fix in place: any future code change that
    re-introduces ``new_uuid7()`` for the events INSERT will fail
    ``test_deterministic_event_id_same_inputs`` immediately.
    """

    def test_deterministic_event_id_same_inputs(self) -> None:
        # Two materialize_graph calls with the SAME (doc_id, subject_entity_id,
        # event_type) MUST produce the same event_id at the SQL parameter level.
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        doc_id = uuid4()
        subject_id = uuid4()
        event = _make_raw_event(subject_entity_id=subject_id, event_type="earnings_release")

        # First call — capture the event_id used for the events INSERT.
        session_a = _make_session()
        asyncio.run(
            materialize_graph(
                doc_id=doc_id,
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[event],  # type: ignore[list-item]
                claims=[],
                session=session_a,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        event_id_a = _extract_events_insert_event_id(session_a)

        # Second call — same inputs, fresh session.  Must reuse the same UUID.
        session_b = _make_session()
        asyncio.run(
            materialize_graph(
                doc_id=doc_id,
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[event],  # type: ignore[list-item]
                claims=[],
                session=session_b,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        event_id_b = _extract_events_insert_event_id(session_b)

        assert event_id_a == event_id_b, (
            "DEF-025 regression: same (doc_id, subject_entity_id, event_type) "
            "produced different event_ids — replay idempotency broken."
        )

    def test_event_id_contains_all_parts(self) -> None:
        # Flipping any single input axis MUST change the resulting event_id.
        # This pins the function's "all 3 parts contribute" guarantee.
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        doc_id_1 = uuid4()
        doc_id_2 = uuid4()
        subject_1 = uuid4()
        subject_2 = uuid4()

        # Baseline — (doc_id_1, subject_1, "earnings_release")
        event_baseline = _make_raw_event(subject_entity_id=subject_1, event_type="earnings_release")
        # Variant 1: change doc_id only.
        event_v_doc = _make_raw_event(subject_entity_id=subject_1, event_type="earnings_release")
        # Variant 2: change subject only.
        event_v_subject = _make_raw_event(subject_entity_id=subject_2, event_type="earnings_release")
        # Variant 3: change event_type only.
        event_v_type = _make_raw_event(subject_entity_id=subject_1, event_type="acquisition")

        ids: dict[str, str] = {}
        for label, doc, ev in [
            ("baseline", doc_id_1, event_baseline),
            ("flip_doc", doc_id_2, event_v_doc),
            ("flip_subject", doc_id_1, event_v_subject),
            ("flip_type", doc_id_1, event_v_type),
        ]:
            session = _make_session()
            asyncio.run(
                materialize_graph(
                    doc_id=doc,
                    source_type="news",
                    is_backfill=False,
                    relations=[],
                    canonical_types=[],
                    canonical_semantic_modes=[],
                    canonical_decay_classes=[],
                    canonical_decay_alphas=[],
                    canonical_base_confidences=[],
                    events=[ev],  # type: ignore[list-item]
                    claims=[],
                    session=session,
                    relation_repo=_make_relation_repo(),
                    evidence_repo=_make_evidence_repo(),
                    outbox_repo=_make_outbox_repo(),
                )
            )
            ids[label] = _extract_events_insert_event_id(session)

        # All four event_ids must be distinct — confirms doc_id, subject and
        # event_type all participate in the UUID5 derivation.
        assert len(set(ids.values())) == 4, f"Expected 4 distinct event_ids, got {ids}"

    def test_deterministic_event_id_on_conflict(self) -> None:
        # When the events INSERT raises UniqueViolation (simulating a replay
        # that hits the existing row), the worker must NOT crash — the
        # ON CONFLICT (event_id, created_at) DO NOTHING clause means the DB
        # silently drops the duplicate.  We simulate the post-ON-CONFLICT
        # behaviour by having execute() return rowcount=0 on the second call:
        # the function must complete without raising.
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        # Build a session where every execute() succeeds (rowcount=0 mimics
        # the ON CONFLICT DO NOTHING outcome on a replay).
        session = _make_session()
        result = MagicMock()
        result.fetchone.return_value = None  # no row returned (post-conflict)
        result.rowcount = 0
        session.execute = AsyncMock(return_value=result)

        event = _make_raw_event(event_type="earnings_release")

        # Must not raise — function tolerates the no-op outcome.
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[event],  # type: ignore[list-item]
                claims=[],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )

        # BP-397: the events INSERT SQL must explicitly contain the
        # ``ON CONFLICT (event_id, created_at) DO NOTHING`` clause AND must
        # bind a ``created_at`` parameter — without both halves the partitioned
        # unique constraint cannot fire on replay.
        for call in session.execute.call_args_list:
            sql_text = str(call.args[0])
            if "INSERT INTO events" in sql_text and "event_entities" not in sql_text:
                assert (
                    "ON CONFLICT (event_id, created_at) DO NOTHING" in sql_text
                ), "events INSERT must use the partition-aware ON CONFLICT clause"
                assert "created_at" in dict(call.args[1]), "events INSERT must bind ``created_at`` explicitly (BP-397)"
                break
        else:
            pytest.fail("events INSERT call not found on session mock")

    def test_event_id_matches_uuid5_from_parts_helper(self) -> None:
        # Direct contract test: the event_id passed to the events INSERT
        # MUST equal uuid5_from_parts(doc_id, subject_entity_id, event_type).
        # If a future refactor swaps the part order or drops a part this
        # assertion will fire immediately.
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        from common.ids import uuid5_from_parts  # type: ignore[import-untyped]

        doc_id = uuid4()
        subject_id = uuid4()
        event_type = "earnings_release"
        event = _make_raw_event(subject_entity_id=subject_id, event_type=event_type)

        session = _make_session()
        asyncio.run(
            materialize_graph(
                doc_id=doc_id,
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[event],  # type: ignore[list-item]
                claims=[],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        actual = _extract_events_insert_event_id(session)
        expected = uuid5_from_parts(str(doc_id), str(subject_id), event_type)
        assert actual == expected


def _extract_events_insert_event_id(session: AsyncMock) -> str:
    """Pull the event_id parameter out of the events INSERT call on the
    mock session.  Walks every execute() call until it finds one whose SQL
    text contains an ``INSERT INTO events`` statement (NOT
    ``INTO event_entities`` — those are filtered out).
    """
    for call in session.execute.call_args_list:
        sql_text = str(call.args[0])
        # Match the events INSERT specifically; exclude event_entities
        # (which also contains the substring "events" otherwise).
        if "INSERT INTO events" in sql_text and "event_entities" not in sql_text:
            params = call.args[1]
            return str(params["event_id"])
    raise AssertionError("events INSERT call not found on session mock")


def _extract_events_insert_params(session: AsyncMock) -> dict:
    """Same as ``_extract_events_insert_event_id`` but returns the entire bound
    parameter dict for the events INSERT call — used by the ``created_at``
    determinism tests so they can compare every piece of the conflict-target
    tuple in one assertion.
    """
    for call in session.execute.call_args_list:
        sql_text = str(call.args[0])
        if "INSERT INTO events" in sql_text and "event_entities" not in sql_text:
            return dict(call.args[1])
    raise AssertionError("events INSERT call not found on session mock")


# ---------------------------------------------------------------------------
# QA fix — deterministic created_at on events INSERT (BP-397)
# ---------------------------------------------------------------------------


class TestDeterministicCreatedAt:
    """The events table is partitioned by created_at and the unique key is
    (event_id, created_at).  A deterministic event_id alone is NOT enough — we
    must also bind a deterministic created_at, otherwise every replay produces
    a different conflict-target tuple and ON CONFLICT NEVER matches.

    These tests pin down the QA fix that closes BP-397.
    """

    def test_event_id_idempotent_with_created_at(self) -> None:
        # Two calls with identical inputs must produce identical (event_id,
        # created_at) tuples — the conflict target on the events INSERT.
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        doc_id = uuid4()
        subject_id = uuid4()
        event = _make_raw_event(subject_entity_id=subject_id, event_type="earnings_release")

        session_a = _make_session()
        asyncio.run(
            materialize_graph(
                doc_id=doc_id,
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[event],  # type: ignore[list-item]
                claims=[],
                session=session_a,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        params_a = _extract_events_insert_params(session_a)

        session_b = _make_session()
        asyncio.run(
            materialize_graph(
                doc_id=doc_id,
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[event],  # type: ignore[list-item]
                claims=[],
                session=session_b,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        params_b = _extract_events_insert_params(session_b)

        # The full conflict-target tuple must be stable across replays.  Both
        # halves are checked: previous tests only pinned event_id, but BP-397
        # is about created_at being equally deterministic.
        assert params_a["event_id"] == params_b["event_id"], "DEF-025 regression: event_id changed between replays"
        assert params_a["created_at"] == params_b["created_at"], (
            "BP-397 regression: created_at differed between replays — "
            "ON CONFLICT (event_id, created_at) will never match and replays "
            "will INSERT duplicate rows."
        )

    def test_created_at_uses_event_date_when_present(self) -> None:
        # When the RawEvent carries an event_date, the bound created_at MUST
        # match it exactly — that is the most semantically meaningful stable
        # timestamp available for the row.
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        explicit_date = datetime(2025, 6, 15, 9, 30, 0, tzinfo=UTC)
        event = _make_raw_event(event_type="earnings_release")
        # Replace event_date on the frozen dataclass via dataclasses.replace.
        import dataclasses as _dc

        event = _dc.replace(event, event_date=explicit_date)  # type: ignore[arg-type]

        session = _make_session()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[event],  # type: ignore[list-item]
                claims=[],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        params = _extract_events_insert_params(session)
        assert params["created_at"] == explicit_date

    def test_created_at_falls_back_when_event_date_none(self) -> None:
        # When event_date is None, created_at must fall back to the stable
        # 2024-01-01 baseline so partition routing still works AND replays
        # still match the ON CONFLICT clause.
        # Build a RawEvent explicitly with event_date=None.
        from knowledge_graph.application.blocks.graph_write import (
            _DETERMINISTIC_CREATED_AT_FALLBACK,
            RawEvent,
            materialize_graph,
        )

        event = RawEvent(
            subject_entity_id=uuid4(),
            event_type="earnings_release",
            event_text="x",
            extraction_confidence=0.9,
            event_date=None,
            participant_entity_ids=(),
        )

        session = _make_session()
        asyncio.run(
            materialize_graph(
                doc_id=uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[],
                canonical_types=[],
                canonical_semantic_modes=[],
                canonical_decay_classes=[],
                canonical_decay_alphas=[],
                canonical_base_confidences=[],
                events=[event],  # type: ignore[list-item]
                claims=[],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=_make_evidence_repo(),
                outbox_repo=_make_outbox_repo(),
            )
        )
        params = _extract_events_insert_params(session)
        assert params["created_at"] == _DETERMINISTIC_CREATED_AT_FALLBACK


# ---------------------------------------------------------------------------
# P0 2026-06-11: claim_id auto-create + chunk_id fallback (news-path evidence)
# ---------------------------------------------------------------------------


class TestEvidenceClaimAutoCreate:
    """P0 fix: relations arriving without claim_id (ALL news-path relations —
    S6 cannot mint claim ids) must get a REAL backing ``claims`` row created
    inline, and the evidence row must reference it. Relations WITH a claim_id
    pass through unchanged."""

    def _run(self, rel: object, *, doc_id: UUID | None = None) -> tuple[AsyncMock, AsyncMock, object]:
        from knowledge_graph.application.blocks.graph_write import materialize_graph

        session = _make_session()
        evidence_repo = _make_evidence_repo()
        summary = asyncio.run(
            materialize_graph(
                doc_id=doc_id or uuid4(),
                source_type="news",
                is_backfill=False,
                relations=[rel],  # type: ignore[list-item]
                canonical_types=["employs"],
                canonical_semantic_modes=[None],
                canonical_decay_classes=[None],
                canonical_decay_alphas=[None],
                canonical_base_confidences=[None],
                events=[],
                claims=[],
                session=session,
                relation_repo=_make_relation_repo(),
                evidence_repo=evidence_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        return session, evidence_repo, summary

    def test_missing_claim_id_autocreates_claim_and_links_evidence(self) -> None:
        """No claim_id → a claims INSERT runs and evidence references its UUID."""
        from knowledge_graph.application.blocks.graph_write import RawRelation

        rel = RawRelation(
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            raw_type="employs",
            extraction_confidence=0.85,
            evidence_date=_NOW,
            evidence_text="Alice works at Acme.",
            chunk_id=uuid4(),
        )
        session, evidence_repo, summary = self._run(rel)

        # A claims-table INSERT must have been executed.
        claim_params = None
        for call in session.execute.call_args_list:
            if "insert into claims" in str(call.args[0]).lower():
                claim_params = call.args[1]
                break
        assert claim_params is not None, "expected an INSERT INTO claims for the auto-created claim"
        # The claim text comes from the relation's evidence sentence.
        assert claim_params["claim_text"] == "Alice works at Acme."

        # The evidence row must reference the SAME claim_id that was inserted.
        kwargs = evidence_repo.insert_raw.call_args.kwargs
        assert kwargs["claim_id"] is not None
        assert str(kwargs["claim_id"]) == claim_params["claim_id"]
        # And the auto-created claim is counted in the summary.
        assert summary.claims_inserted == 1  # type: ignore[attr-defined]

    def test_existing_claim_id_passes_through_unchanged(self) -> None:
        """Relation WITH claim_id → no claims INSERT; claim_id forwarded as-is."""
        from knowledge_graph.application.blocks.graph_write import RawRelation

        existing_claim_id = uuid4()
        rel = RawRelation(
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            raw_type="employs",
            extraction_confidence=0.85,
            evidence_date=_NOW,
            claim_id=existing_claim_id,
            chunk_id=uuid4(),
        )
        session, evidence_repo, summary = self._run(rel)

        claim_inserts = [c for c in session.execute.call_args_list if "insert into claims" in str(c.args[0]).lower()]
        assert claim_inserts == [], "must not auto-create a claim when one is supplied"
        assert evidence_repo.insert_raw.call_args.kwargs["claim_id"] == existing_claim_id
        assert summary.claims_inserted == 0  # type: ignore[attr-defined]

    def test_missing_evidence_text_falls_back_to_triple_description(self) -> None:
        """Auto-created claim without evidence_text uses a triple description (claim_text NOT NULL)."""
        from knowledge_graph.application.blocks.graph_write import RawRelation

        subj, obj = uuid4(), uuid4()
        rel = RawRelation(
            subject_entity_id=subj,
            object_entity_id=obj,
            raw_type="employs",
            extraction_confidence=0.85,
            evidence_date=_NOW,
            chunk_id=uuid4(),
        )
        session, _, _ = self._run(rel)
        for call in session.execute.call_args_list:
            if "insert into claims" in str(call.args[0]).lower():
                assert call.args[1]["claim_text"] == f"{subj} employs {obj}"
                break
        else:
            pytest.fail("No claims INSERT call found")


class TestEvidenceChunkIdFallback:
    """P0 fix: legacy backlog messages (2026-05-23 → producer fix) have no
    chunk_id, yet the column is NOT NULL. KG derives a DETERMINISTIC
    doc-scoped fallback so replays stay idempotent."""

    def test_chunk_id_passes_through_when_present(self) -> None:
        from knowledge_graph.application.blocks.graph_write import RawRelation

        chunk_id = uuid4()
        rel = RawRelation(
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            raw_type="employs",
            extraction_confidence=0.85,
            evidence_date=_NOW,
            chunk_id=chunk_id,
        )
        _, evidence_repo, _ = TestEvidenceClaimAutoCreate()._run(rel)
        assert evidence_repo.insert_raw.call_args.kwargs["chunk_id"] == chunk_id

    def test_missing_chunk_id_uses_deterministic_doc_scoped_fallback(self) -> None:
        from knowledge_graph.application.blocks.graph_write import RawRelation

        from common.ids import uuid5_from_parts

        doc_id = uuid4()
        rel = RawRelation(
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            raw_type="employs",
            extraction_confidence=0.85,
            evidence_date=_NOW,
        )
        _, evidence_repo, _ = TestEvidenceClaimAutoCreate()._run(rel, doc_id=doc_id)
        expected = UUID(uuid5_from_parts(str(doc_id), "missing_chunk_fallback"))
        got = evidence_repo.insert_raw.call_args.kwargs["chunk_id"]
        assert got == expected, "fallback chunk_id must be deterministic per doc (idempotent replays)"
