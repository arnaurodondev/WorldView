"""Unit tests for EnrichedArticleConsumer — Valkey dedup + PLAN-0031 C-1 post-commit produce."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import (
    EnrichedArticleConsumer,
    _parse_dt_optional,
    _parse_raw_claims,
    _parse_raw_relations,
)
from structlog.testing import capture_logs

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


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
            e.get("event") == "dedup.valkey_check_failed" for e in cap
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
            e.get("event") == "dedup.valkey_mark_failed" for e in cap
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
                # PLAN-0093 B-3: claim_id + chunk_id are NOT NULL on
                # relation_evidence_raw; the writer rejects None to surface
                # the schema constraint at the call site. Fixture sets both.
                "claim_id": str(uuid4()),
                "chunk_id": str(uuid4()),
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
        """A claim dict missing required subject_entity_id is skipped.

        PLAN-0062 F-021: handler split into typed (KeyError vs ValueError)
        warnings — missing-field branch emits ``..._bad_claim_missing_field``.
        """
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
            e.get("event") == "enriched_consumer_bad_claim_missing_field" for e in cap
        ), f"Expected enriched_consumer_bad_claim_missing_field warning not found in {cap}"

    def test_invalid_uuid_skipped(self) -> None:
        """A claim with a non-UUID subject_entity_id is skipped.

        PLAN-0062 F-021: ValueError branch emits ``..._bad_claim_value_error``.
        """
        data = [
            {"subject_entity_id": "not-a-uuid", "claim_type": "test"},
        ]

        with capture_logs() as cap:
            result = _parse_raw_claims(data, is_backfill=False)

        assert len(result) == 0
        assert any(e.get("event") == "enriched_consumer_bad_claim_value_error" for e in cap)

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


class TestEnrichedConsumerAvroDeserialization:
    """PLAN-0062 Wave B: Confluent-Avro wire format with JSON fallback."""

    @pytest.mark.unit
    def test_decodes_confluent_avro_payload(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import (
            _ARTICLE_ENRICHED_SCHEMA_PATH,
        )

        from messaging.kafka.serialization_utils import serialize_confluent_avro

        consumer = _make_consumer()
        record = {
            "event_id": "01900000-0000-7000-0000-000000000020",
            "event_type": "nlp.article.enriched",
            "schema_version": 1,
            "occurred_at": "2026-05-03T12:00:00+00:00",
            "doc_id": "01234567-89ab-7def-8012-aaaaaaaaaaaa",
            "source_type": "news",
            "published_at": None,
            "is_backfill": False,
            "routing_tier": "deep",
            "routing_score": 0.7,
            "section_count": 1,
            "chunk_count": 2,
            "mention_count": 3,
            "resolved_entity_ids": [],
            "relation_count": 0,
            "claim_count": 0,
            "event_count": 0,
            "provisional_entity_count": 0,
            "extraction_model_id": None,
            "raw_relations_json": '[{"subject_entity_id": "x"}]',
            "raw_events_json": None,
            "raw_claims_json": None,
            "correlation_id": None,
        }
        wire_bytes = serialize_confluent_avro(_ARTICLE_ENRICHED_SCHEMA_PATH, record)
        decoded = consumer.deserialize_value(wire_bytes)

        assert decoded["doc_id"] == record["doc_id"]
        assert decoded["routing_tier"] == "deep"
        assert decoded["raw_relations_json"] == '[{"subject_entity_id": "x"}]'

    @pytest.mark.unit
    def test_falls_back_to_json_for_legacy_payload(self) -> None:
        import json

        consumer = _make_consumer()
        legacy = json.dumps(
            {
                "event_id": "x",
                "doc_id": "01234567-89ab-7def-8012-aaaaaaaaaaaa",
                "raw_relations": [{"subject_entity_id": "y"}],
            },
        ).encode()
        decoded = consumer.deserialize_value(legacy)
        assert decoded["doc_id"] == "01234567-89ab-7def-8012-aaaaaaaaaaaa"
        assert decoded["raw_relations"][0]["subject_entity_id"] == "y"

    # ── PLAN-0062 F-015: malformed Avro payload ───────────────────────────

    @pytest.mark.unit
    def test_malformed_avro_raises(self) -> None:
        """A payload with the magic byte but a truncated/garbage Avro body
        must surface as a non-``JSONDecodeError`` exception so the dispatch
        falls cleanly into ``MalformedDataError`` and dead-letters with the
        correct error class.
        """
        consumer = _make_consumer()
        garbage = b"\x00\x00\x00\x00\x01\x42"
        with pytest.raises(Exception) as exc_info:
            consumer.deserialize_value(garbage)
        # Must NOT be a JSONDecodeError — the magic byte routed to the Avro
        # path; failure should surface from the Avro reader.
        import json

        assert not isinstance(exc_info.value, json.JSONDecodeError)

    # ── PLAN-0062 F-018: oversized JSON-fallback payload ─────────────────

    @pytest.mark.unit
    def test_json_fallback_oversized_payload_raises_malformed_data_error(self) -> None:
        """A JSON-fallback payload above the 16 MiB cap must raise
        :class:`MalformedDataError` BEFORE ``json.loads`` is called.
        """
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

        consumer = _make_consumer()
        # 17 MiB payload — over the 16 MiB cap.
        payload = b'{"x":"' + b"a" * (17 * 1024 * 1024) + b'"}'
        with pytest.raises(MalformedDataError):
            consumer.deserialize_value(payload)


# ---------------------------------------------------------------------------
# PLAN-0062 F-013/F-014: process_message E2E coverage for raw_relations_json
# ---------------------------------------------------------------------------


def _mock_session_factory_simple() -> AsyncMock:
    """Minimal session factory whose UoW commits cleanly.  Reuses the
    pattern from :func:`_mock_session_factory` above but wraps it as a
    bound async context manager.
    """
    sf, _session = _mock_session_factory()
    return sf


class TestRawRelationsJsonProcessMessage:
    """PLAN-0062 F-013/F-014: ``process_message`` must materialize relations
    decoded from BOTH the new ``raw_relations_json`` field (post-migration)
    AND the legacy ``raw_relations`` list field (pre-migration).
    """

    @pytest.mark.unit
    async def test_decodes_raw_relations_json_through_process_message(self) -> None:
        """A message with ``raw_relations_json`` (JSON string) is decoded and
        passed through to ``materialize_graph`` with one relation.
        """
        sf = _mock_session_factory_simple()
        config = ConsumerConfig(
            group_id="kg-enriched-test",
            topics=["nlp.article.enriched.v1"],
        )
        consumer = EnrichedArticleConsumer(
            config=config,
            session_factory=sf,
            embedding_client=MagicMock(),
            direct_producer=MagicMock(),
            entity_dirtied_topic="entity.dirtied.v1",
        )

        subj = str(uuid4())
        obj = str(uuid4())
        msg = {
            "event_id": str(uuid4()),
            "doc_id": str(uuid4()),
            "resolved_entity_ids": [subj, obj],
            "is_backfill": False,
            "source_type": "news",
            "raw_relations_json": (
                '[{"subject_entity_id":"' + subj + '","object_entity_id":"' + obj + '","raw_type":"employs"}]'
            ),
            "raw_events": [],
            "raw_claims": [],
        }

        canon_result = MagicMock()
        canon_result.canonical_type = "employs"
        canon_result.semantic_mode = "RELATION_STATE"
        canon_result.decay_class = "stable"
        canon_result.decay_alpha = 0.0
        canon_result.base_confidence = 0.8
        canon_result.step = "exact"

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.materialize_graph",
            ) as mock_materialize,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.canonicalize_relation_type",
                AsyncMock(return_value=canon_result),
            ),
        ):
            mock_summary = MagicMock()
            mock_summary.entity_ids_to_dirty = frozenset()
            mock_materialize.return_value = mock_summary

            await consumer.process_message(key="test", value=msg, headers={})

        mock_materialize.assert_called_once()
        relations = mock_materialize.call_args.kwargs["relations"]
        assert len(relations) == 1, f"Expected 1 relation from raw_relations_json, got {len(relations)}"

    @pytest.mark.unit
    async def test_legacy_raw_relations_list_fallback_through_process_message(self) -> None:
        """A message with the LEGACY ``raw_relations`` list field (no
        ``_json`` suffix) still flows end-to-end with one relation — covers
        the migration window where producers may emit either shape.
        """
        sf = _mock_session_factory_simple()
        config = ConsumerConfig(
            group_id="kg-enriched-test",
            topics=["nlp.article.enriched.v1"],
        )
        consumer = EnrichedArticleConsumer(
            config=config,
            session_factory=sf,
            embedding_client=MagicMock(),
            direct_producer=MagicMock(),
            entity_dirtied_topic="entity.dirtied.v1",
        )

        msg = _enriched_message()  # uses legacy ``raw_relations`` list

        canon_result = MagicMock()
        canon_result.canonical_type = "employs"
        canon_result.semantic_mode = "RELATION_STATE"
        canon_result.decay_class = "stable"
        canon_result.decay_alpha = 0.0
        canon_result.base_confidence = 0.8
        canon_result.step = "exact"

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.materialize_graph",
            ) as mock_materialize,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.canonicalize_relation_type",
                AsyncMock(return_value=canon_result),
            ),
        ):
            mock_summary = MagicMock()
            mock_summary.entity_ids_to_dirty = frozenset()
            mock_materialize.return_value = mock_summary

            await consumer.process_message(key="test", value=msg, headers={})

        mock_materialize.assert_called_once()
        relations = mock_materialize.call_args.kwargs["relations"]
        assert len(relations) == 1, f"Expected 1 relation from legacy raw_relations, got {len(relations)}"


# ---------------------------------------------------------------------------
# PLAN-0062 F-019: text-field cap + polarity allow-list
# ---------------------------------------------------------------------------


class TestParseRawRelationsTruncationAndPolarity:
    """PLAN-0062 F-019: ``_parse_raw_relations`` must truncate oversized
    free-text and normalize out-of-vocabulary polarities, both with
    structured warnings.
    """

    @pytest.mark.unit
    def test_parse_raw_relations_truncates_oversized_evidence_text(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import (
            _MAX_TEXT_FIELD_LEN,
            _parse_raw_relations,
        )

        subj = str(uuid4())
        obj = str(uuid4())
        oversized_text = "x" * (_MAX_TEXT_FIELD_LEN + 1)
        data = [
            {
                "subject_entity_id": subj,
                "object_entity_id": obj,
                "raw_type": "employs",
                "evidence_text": oversized_text,
            },
        ]
        with capture_logs() as logs:
            results = _parse_raw_relations(data)

        assert len(results) == 1
        assert results[0].evidence_text is not None
        assert len(results[0].evidence_text) == _MAX_TEXT_FIELD_LEN
        truncation_logs = [le for le in logs if le.get("event") == "enriched_consumer_text_field_truncated"]
        assert truncation_logs, "expected truncation warning to be logged"

    @pytest.mark.unit
    def test_parse_raw_relations_normalizes_invalid_polarity(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import _parse_raw_relations

        subj = str(uuid4())
        obj = str(uuid4())
        data = [
            {
                "subject_entity_id": subj,
                "object_entity_id": obj,
                "raw_type": "employs",
                "polarity": "bogus",
            },
        ]
        with capture_logs() as logs:
            results = _parse_raw_relations(data)

        assert len(results) == 1
        assert results[0].polarity == "neutral"
        norm_logs = [le for le in logs if le.get("event") == "enriched_consumer_polarity_normalized"]
        assert norm_logs, "expected polarity-normalization warning to be logged"


class TestValidToThreading:
    """PLAN-0109 W5: per-fact valid_to flows LLM → RawRelation → upsert."""

    def test_parse_dt_optional_returns_none_when_absent(self) -> None:
        assert _parse_dt_optional(None) is None
        assert _parse_dt_optional("") is None
        assert _parse_dt_optional("not-a-date") is None

    def test_parse_dt_optional_parses_iso_date(self) -> None:
        from datetime import UTC, datetime

        assert _parse_dt_optional("2023-05-01") == datetime(2023, 5, 1, tzinfo=UTC)

    def test_raw_relation_carries_valid_to(self) -> None:
        rels = _parse_raw_relations(
            [
                {
                    "subject_entity_id": "00000000-0000-0000-0000-0000000000a1",
                    "object_entity_id": "00000000-0000-0000-0000-0000000000b2",
                    "raw_type": "has_executive",
                    "extraction_confidence": 0.9,
                    "valid_to": "2023-12-31",
                }
            ]
        )
        assert len(rels) == 1
        assert rels[0].valid_to is not None
        assert rels[0].valid_to.year == 2023

    def test_raw_relation_valid_to_none_when_omitted(self) -> None:
        rels = _parse_raw_relations(
            [
                {
                    "subject_entity_id": "00000000-0000-0000-0000-0000000000a1",
                    "object_entity_id": "00000000-0000-0000-0000-0000000000b2",
                    "raw_type": "employs",
                    "extraction_confidence": 0.8,
                }
            ]
        )
        assert rels[0].valid_to is None  # absence must NOT coerce to now()


# ---------------------------------------------------------------------------
# Prod-readiness fix (BP-720): main enriched-consumer resilient deserialize.
#
# 66b0b6416 appended nullable external_id/source_title to the enriched Avro
# schema; the no-registry schemaless_reader raises EOFError on pre-append
# backlog records → base wraps as MalformedDataError → inline dead-letter →
# dead_letter_cap (5000) force-restart → re-read the same 5000 forever, never
# reaching the new-schema NEWS tail. The override must SKIP an un-decodable
# record (offset advances) while still processing good ones and propagating
# genuine processing failures.
# ---------------------------------------------------------------------------


class _FakeKafkaMessage:
    """Minimal confluent-Kafka message stand-in for ``_handle_message`` tests."""

    def __init__(self, raw_value: bytes, *, offset: int = 6858, partition: int = 0) -> None:
        self._value = raw_value
        self._offset = offset
        self._partition = partition

    def topic(self) -> str:
        return "nlp.article.enriched.v1"

    def value(self) -> bytes:
        return self._value

    def key(self) -> bytes | None:
        return None

    def headers(self) -> list[tuple[str, bytes]]:
        return []

    def offset(self) -> int:
        return self._offset

    def partition(self) -> int:
        return self._partition


class TestEnrichedConsumerResilientDeserialize:
    """An un-decodable OLD-schema record must be SKIPPED, not crash-loop the group."""

    @pytest.mark.unit
    def test_undecodable_old_schema_record_is_skipped_not_raised(self) -> None:
        import asyncio

        consumer = _make_consumer()
        # Confluent magic byte (0x00) + a truncated body a schemaless_reader with the
        # NEW (external_id/source_title-extended) schema under-runs → EOFError →
        # base wraps in MalformedDataError. Must NOT raise (offset would advance).
        msg = _FakeKafkaMessage(b"\x00\x00\x00\x00\x01truncated")
        with capture_logs() as logs:
            asyncio.run(consumer._handle_message(msg))
        assert any(e["event"] == "enriched_consumer_deserialize_skipped" for e in logs)
        skip = next(e for e in logs if e["event"] == "enriched_consumer_deserialize_skipped")
        assert skip["offset"] == 6858  # offset carried through so the run loop commits it

    @pytest.mark.unit
    def test_raw_eoferror_from_deserialize_is_swallowed(self) -> None:
        import asyncio

        consumer = _make_consumer()
        msg = _FakeKafkaMessage(b"\x00whatever")
        # Simulate a path surfacing EOFError un-wrapped (defence-in-depth branch).
        with patch.object(consumer, "deserialize_value", side_effect=EOFError("short read")):
            asyncio.run(consumer._handle_message(msg))  # must not raise

    @pytest.mark.unit
    def test_valid_new_schema_message_processed_normally_after_poison(self) -> None:
        import asyncio

        consumer = _make_consumer()
        good_value = {"doc_id": str(uuid4())}
        good_msg = _FakeKafkaMessage(b"\x00good", offset=6900)
        with (
            patch.object(consumer, "deserialize_value", return_value=good_value),
            patch.object(consumer, "process_message", new=AsyncMock()) as proc,
        ):
            asyncio.run(consumer._handle_message(good_msg))
        proc.assert_awaited_once()

    @pytest.mark.unit
    def test_run_of_poison_records_never_wedges_no_dead_letter(self) -> None:
        import asyncio

        consumer = _make_consumer()
        # Skips must NOT touch the dead-letter counter → cap can never trip.
        assert consumer._dead_letter_count == 0
        with patch.object(consumer, "deserialize_value", side_effect=EOFError("boom")):
            for off in range(6858, 6858 + 6000):  # more than dead_letter_cap (5000)
                asyncio.run(consumer._handle_message(_FakeKafkaMessage(b"\x00x", offset=off)))
        assert consumer._dead_letter_count == 0  # never dead-lettered → never force-restarts

    @pytest.mark.unit
    def test_genuine_processing_error_still_propagates(self) -> None:
        import asyncio

        consumer = _make_consumer()
        msg = _FakeKafkaMessage(b"\x00good")
        with (
            patch.object(consumer, "deserialize_value", return_value={"doc_id": str(uuid4())}),
            patch.object(consumer, "process_message", side_effect=RuntimeError("db down")),
        ):
            with pytest.raises(RuntimeError, match="db down"):
                asyncio.run(consumer._handle_message(msg))
