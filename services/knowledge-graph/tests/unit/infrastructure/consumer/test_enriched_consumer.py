"""Unit tests for EnrichedArticleConsumer — Valkey dedup + PLAN-0031 C-1 post-commit produce."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import (
    EnrichedArticleConsumer,
    _parse_raw_claims,
)
from structlog.testing import capture_logs

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]


def _make_consumer(*, dedup_client: object | None = None) -> EnrichedArticleConsumer:
    config = ConsumerConfig(
        group_id="kg-enriched-test",
        topics=["nlp.article.enriched.v1"],
    )
    consumer = EnrichedArticleConsumer(
        config=config,
        session_factory=MagicMock(),
        embedding_client=MagicMock(),
        direct_producer=MagicMock(),
        entity_dirtied_topic="entity.dirtied.v1",
        dedup_client=dedup_client,
    )
    return consumer


class TestEnrichedConsumerValkey:
    @pytest.mark.unit
    async def test_is_duplicate_none_client_returns_false(self) -> None:
        """Without dedup client, is_duplicate always returns False."""
        consumer = _make_consumer()
        assert await consumer.is_duplicate("any-id") is False

    @pytest.mark.unit
    async def test_is_duplicate_valkey_error_returns_false(self) -> None:
        """When Valkey raises, is_duplicate returns False without propagating."""
        mock_client = AsyncMock()
        mock_client.exists = AsyncMock(side_effect=ConnectionError("valkey down"))
        consumer = _make_consumer(dedup_client=mock_client)

        with capture_logs() as cap:
            result = await consumer.is_duplicate("evt-001")

        assert result is False
        assert any(
            e.get("event") == "enriched_consumer.valkey_check_failed" for e in cap
        ), f"Expected warning log not found in {cap}"

    @pytest.mark.unit
    async def test_mark_processed_valkey_error_logs_warning(self) -> None:
        """When Valkey raises on set, mark_processed logs warning and returns silently."""
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(side_effect=ConnectionError("valkey down"))
        consumer = _make_consumer(dedup_client=mock_client)

        with capture_logs() as cap:
            # Must not raise
            await consumer.mark_processed("evt-002")

        assert any(
            e.get("event") == "enriched_consumer.valkey_mark_failed" for e in cap
        ), f"Expected warning log not found in {cap}"


# ---------------------------------------------------------------------------
# PLAN-0031 C-1: entity.dirtied.v1 produced AFTER session.commit()
# ---------------------------------------------------------------------------


def _mock_session_factory() -> tuple[AsyncMock, AsyncMock]:
    """Return a mock session factory + the mock session it yields.

    The session is an async context manager (``async with self._sf() as session``).
    """
    session = AsyncMock()
    # session.execute returns a result mock (for raw SQL)
    result = MagicMock()
    result.fetchone.return_value = (str(uuid4()),)
    result.rowcount = 1
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    # session_factory() returns an async context manager that yields session
    sf = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    sf.return_value = ctx

    return sf, session


def _enriched_message(
    *,
    doc_id: str | None = None,
    raw_relations: list | None = None,
) -> dict:
    """Minimal enriched article message payload."""
    subj = str(uuid4())
    obj = str(uuid4())
    return {
        "event_id": str(uuid4()),
        "doc_id": doc_id or str(uuid4()),
        "resolved_entity_ids": [subj, obj],
        "is_backfill": False,
        "source_type": "news",
        "raw_relations": raw_relations
        or [
            {
                "subject_entity_id": subj,
                "object_entity_id": obj,
                "raw_type": "employs",
                "extraction_confidence": 0.85,
            },
        ],
        "raw_events": [],
        "raw_claims": [],
    }


class TestPostCommitDirtiedProduce:
    """PLAN-0031 C-1: entity.dirtied.v1 Kafka messages must only be produced
    AFTER the intelligence_db session has been committed."""

    @pytest.mark.unit
    async def test_consumer_produces_dirtied_after_commit(self) -> None:
        """produce_bytes() is called AFTER session.commit(), not before."""
        sf, session = _mock_session_factory()
        config = ConsumerConfig(
            group_id="kg-enriched-test",
            topics=["nlp.article.enriched.v1"],
        )

        mock_producer = MagicMock()
        # Track call order: record which method was called when
        call_order: list[str] = []
        original_commit = session.commit

        async def _tracking_commit() -> None:
            call_order.append("commit")
            await original_commit()

        session.commit = _tracking_commit
        mock_producer.produce_bytes = MagicMock(
            side_effect=lambda **kw: call_order.append("produce"),
        )

        consumer = EnrichedArticleConsumer(
            config=config,
            session_factory=sf,
            embedding_client=MagicMock(),
            direct_producer=mock_producer,
            entity_dirtied_topic="entity.dirtied.v1",
        )

        # Patch canonicalize_relation_type to return a fixed canonical result
        with patch(
            "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.canonicalize_relation_type",
        ) as mock_canon:
            mock_result = MagicMock()
            mock_result.canonical_type = "employs"
            mock_result.semantic_mode = None
            mock_result.decay_class = None
            mock_result.decay_alpha = None
            mock_result.base_confidence = None
            mock_canon.return_value = mock_result

            await consumer.process_message(
                key="test",
                value=_enriched_message(),
                headers={},
            )

        # Verify ordering: commit BEFORE produce
        assert "commit" in call_order, "session.commit() was never called"
        assert "produce" in call_order, "produce_bytes() was never called"
        commit_idx = call_order.index("commit")
        produce_idx = call_order.index("produce")
        assert (
            commit_idx < produce_idx
        ), f"produce_bytes() called at index {produce_idx} but session.commit() at {commit_idx} — must be commit FIRST"

    @pytest.mark.unit
    async def test_consumer_produces_for_all_dirty_entities(self) -> None:
        """All entity IDs from summary.entity_ids_to_dirty get a produce call."""
        sf, _session = _mock_session_factory()
        config = ConsumerConfig(
            group_id="kg-enriched-test",
            topics=["nlp.article.enriched.v1"],
        )
        mock_producer = MagicMock()

        consumer = EnrichedArticleConsumer(
            config=config,
            session_factory=sf,
            embedding_client=MagicMock(),
            direct_producer=mock_producer,
            entity_dirtied_topic="entity.dirtied.v1",
        )

        msg = _enriched_message()
        # Extract the subject/object IDs from the message to verify later
        subj_id = msg["raw_relations"][0]["subject_entity_id"]
        obj_id = msg["raw_relations"][0]["object_entity_id"]

        with patch(
            "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.canonicalize_relation_type",
        ) as mock_canon:
            mock_result = MagicMock()
            mock_result.canonical_type = "employs"
            mock_result.semantic_mode = None
            mock_result.decay_class = None
            mock_result.decay_alpha = None
            mock_result.base_confidence = None
            mock_canon.return_value = mock_result

            await consumer.process_message(
                key="test",
                value=msg,
                headers={},
            )

        # produce_bytes should have been called for both subject and object
        produce_calls = mock_producer.produce_bytes.call_args_list
        produced_keys = {c.kwargs["key"].decode() for c in produce_calls}
        assert subj_id in produced_keys, f"Subject {subj_id} not in produced keys: {produced_keys}"
        assert obj_id in produced_keys, f"Object {obj_id} not in produced keys: {produced_keys}"

    @pytest.mark.unit
    async def test_consumer_no_produce_on_commit_failure(self) -> None:
        """If session.commit() raises, produce_bytes() is never called."""
        sf, session = _mock_session_factory()
        session.commit = AsyncMock(side_effect=RuntimeError("DB commit failed"))

        config = ConsumerConfig(
            group_id="kg-enriched-test",
            topics=["nlp.article.enriched.v1"],
        )
        mock_producer = MagicMock()

        consumer = EnrichedArticleConsumer(
            config=config,
            session_factory=sf,
            embedding_client=MagicMock(),
            direct_producer=mock_producer,
            entity_dirtied_topic="entity.dirtied.v1",
        )

        with patch(
            "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.canonicalize_relation_type",
        ) as mock_canon:
            mock_result = MagicMock()
            mock_result.canonical_type = "employs"
            mock_result.semantic_mode = None
            mock_result.decay_class = None
            mock_result.decay_alpha = None
            mock_result.base_confidence = None
            mock_canon.return_value = mock_result

            with pytest.raises(RuntimeError, match="DB commit failed"):
                await consumer.process_message(
                    key="test",
                    value=_enriched_message(),
                    headers={},
                )

        # produce_bytes must NOT have been called since commit failed
        mock_producer.produce_bytes.assert_not_called()


# ---------------------------------------------------------------------------
# KG-002 closure: _parse_raw_claims() deserialization tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseRawClaims:
    """Validate _parse_raw_claims() correctly deserializes claim dicts into
    typed RawClaim dataclass objects, handling optional fields and bad data."""

    def test_full_claim_parsed_correctly(self) -> None:
        """All fields present → RawClaim with correct types."""
        subject_id = str(uuid4())
        claimer_id = str(uuid4())
        chunk_id = str(uuid4())
        data = [
            {
                "subject_entity_id": subject_id,
                "claim_type": "analyst_rating",
                "polarity": "positive",
                "claim_text": "Upgraded to Buy",
                "extraction_confidence": 0.92,
                "claimer_entity_id": claimer_id,
                "chunk_id": chunk_id,
            },
        ]

        result = _parse_raw_claims(data, is_backfill=False)

        assert len(result) == 1
        claim = result[0]
        assert str(claim.subject_entity_id) == subject_id
        assert claim.claim_type == "analyst_rating"
        assert claim.polarity == "positive"
        assert claim.claim_text == "Upgraded to Buy"
        assert claim.extraction_confidence == pytest.approx(0.92)
        assert str(claim.claimer_entity_id) == claimer_id
        assert str(claim.chunk_id) == chunk_id
        assert claim.is_backfill is False

    def test_optional_fields_default_gracefully(self) -> None:
        """Missing optional fields (polarity, claim_text, claimer, chunk) use defaults."""
        subject_id = str(uuid4())
        data = [
            {
                "subject_entity_id": subject_id,
                "claim_type": "revenue_guidance",
            },
        ]

        result = _parse_raw_claims(data, is_backfill=True)

        assert len(result) == 1
        claim = result[0]
        assert claim.polarity == "neutral"
        assert claim.claim_text == ""
        assert claim.extraction_confidence == pytest.approx(0.5)
        assert claim.claimer_entity_id is None
        assert claim.chunk_id is None
        assert claim.is_backfill is True

    def test_invalid_claim_skipped_with_warning(self) -> None:
        """A claim dict missing required subject_entity_id is skipped."""
        good_id = str(uuid4())
        data = [
            {"claim_type": "bad_claim"},  # missing subject_entity_id
            {"subject_entity_id": good_id, "claim_type": "good_claim"},
        ]

        with capture_logs() as cap:
            result = _parse_raw_claims(data, is_backfill=False)

        assert len(result) == 1
        assert result[0].claim_type == "good_claim"
        assert any(
            e.get("event") == "enriched_consumer_bad_claim" for e in cap
        ), f"Expected warning log for bad claim not found in {cap}"

    def test_invalid_uuid_skipped(self) -> None:
        """A claim with a non-UUID subject_entity_id is skipped."""
        data = [
            {"subject_entity_id": "not-a-uuid", "claim_type": "test"},
        ]

        with capture_logs() as cap:
            result = _parse_raw_claims(data, is_backfill=False)

        assert len(result) == 0
        assert any(e.get("event") == "enriched_consumer_bad_claim" for e in cap)

    def test_empty_list_returns_empty(self) -> None:
        """Empty input produces empty output."""
        result = _parse_raw_claims([], is_backfill=False)
        assert result == []

    def test_multiple_claims_parsed(self) -> None:
        """Multiple valid claims are all parsed."""
        data = [{"subject_entity_id": str(uuid4()), "claim_type": f"type_{i}"} for i in range(5)]

        result = _parse_raw_claims(data, is_backfill=False)

        assert len(result) == 5
        for i, claim in enumerate(result):
            assert claim.claim_type == f"type_{i}"


# ---------------------------------------------------------------------------
# KG-002 closure: enriched consumer processes claims end-to-end
# ---------------------------------------------------------------------------


def _enriched_message_with_claims(
    *,
    doc_id: str | None = None,
) -> dict:
    """Enriched article message payload that includes raw_claims."""
    subj = str(uuid4())
    return {
        "event_id": str(uuid4()),
        "doc_id": doc_id or str(uuid4()),
        "resolved_entity_ids": [subj],
        "is_backfill": False,
        "source_type": "news",
        "raw_relations": [],
        "raw_events": [],
        "raw_claims": [
            {
                "subject_entity_id": subj,
                "claim_type": "analyst_rating",
                "polarity": "positive",
                "claim_text": "Buy rating issued",
                "extraction_confidence": 0.88,
            },
            {
                "subject_entity_id": subj,
                "claim_type": "revenue_guidance",
                "polarity": "negative",
                "claim_text": "Revenue below expectations",
                "extraction_confidence": 0.75,
            },
        ],
    }


class TestEnrichedConsumerClaimsE2E:
    """KG-002 closure: verify that raw_claims in the enriched message
    are parsed and passed through to materialize_graph, resulting in
    claims_inserted > 0 in the materialization summary."""

    @pytest.mark.unit
    async def test_consumer_materializes_claims_from_enriched_message(self) -> None:
        """Claims in the enriched message flow through to graph_write."""
        sf, _ = _mock_session_factory()
        config = ConsumerConfig(
            group_id="kg-enriched-test",
            topics=["nlp.article.enriched.v1"],
        )
        mock_producer = MagicMock()

        consumer = EnrichedArticleConsumer(
            config=config,
            session_factory=sf,
            embedding_client=MagicMock(),
            direct_producer=mock_producer,
            entity_dirtied_topic="entity.dirtied.v1",
        )

        msg = _enriched_message_with_claims()

        with patch(
            "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.materialize_graph",
        ) as mock_materialize:
            # Return a summary that includes claims_inserted
            mock_summary = MagicMock()
            mock_summary.entity_ids_to_dirty = frozenset()
            mock_materialize.return_value = mock_summary

            await consumer.process_message(
                key="test",
                value=msg,
                headers={},
            )

        # Verify materialize_graph was called with non-empty claims list
        mock_materialize.assert_called_once()
        call_kwargs = mock_materialize.call_args.kwargs
        claims = call_kwargs["claims"]
        assert len(claims) == 2, f"Expected 2 claims, got {len(claims)}"
        assert claims[0].claim_type == "analyst_rating"
        assert claims[1].claim_type == "revenue_guidance"
