"""Unit tests for Block 11: relation type canonicalization."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry_repo(
    exact_return: object = None,
    ann_return: object = None,
) -> AsyncMock:
    repo = AsyncMock()
    repo.find_exact = AsyncMock(return_value=exact_return)
    repo.find_by_embedding = AsyncMock(return_value=ann_return)
    return repo


def _make_outbox_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.append = AsyncMock(return_value=uuid4())
    return repo


def _make_embedding_client(vec: list[float] | None = None) -> AsyncMock:
    client = AsyncMock()
    client.embed = AsyncMock(return_value=vec or [0.1, 0.2, 0.3])
    return client


_EXACT_ROW: dict[str, object] = {
    "type_id": uuid4(),
    "canonical_type": "employs",
    "semantic_mode": "RELATION_STATE",
    "decay_class": "STANDARD",
    "base_confidence": 0.70,
    "decay_alpha": 0.000950,
}

_SOFT_ROW: dict[str, object] = {
    "type_id": uuid4(),
    "canonical_type": "board_member_of",
    "semantic_mode": "RELATION_STATE",
    "decay_class": "DURABLE",
    "base_confidence": 0.65,
    "cosine_distance": 0.28,
}


# ---------------------------------------------------------------------------
# Step 1: Exact match
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_exact_match_returns_canonical_type(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        registry = _make_registry_repo(exact_return=_EXACT_ROW)
        result = asyncio.run(
            canonicalize_relation_type(
                raw_type="employs",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=uuid4(),
                registry_repo=registry,
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.canonical_type == "employs"
        assert result.step == "exact"

    def test_exact_match_does_not_call_embedding(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        registry = _make_registry_repo(exact_return=_EXACT_ROW)
        emb = _make_embedding_client()
        asyncio.run(
            canonicalize_relation_type(
                raw_type="employs",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=uuid4(),
                registry_repo=registry,
                outbox_repo=_make_outbox_repo(),
                embedding_client=emb,
            )
        )
        emb.embed.assert_not_called()

    def test_exact_match_does_not_emit_proposal(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        outbox = _make_outbox_repo()
        asyncio.run(
            canonicalize_relation_type(
                raw_type="employs",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=_EXACT_ROW),
                outbox_repo=outbox,
                embedding_client=_make_embedding_client(),
            )
        )
        outbox.append.assert_not_called()

    def test_exact_match_returns_correct_decay_alpha(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        result = asyncio.run(
            canonicalize_relation_type(
                raw_type="employs",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=_EXACT_ROW),
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.decay_alpha == pytest.approx(0.000950)


# ---------------------------------------------------------------------------
# Step 2: ANN soft-map
# ---------------------------------------------------------------------------


class TestSoftMap:
    def test_soft_map_returns_closest_type(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        result = asyncio.run(
            canonicalize_relation_type(
                raw_type="serves_on_board_of",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=_SOFT_ROW),
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.canonical_type == "board_member_of"
        assert result.step == "soft_mapped"

    def test_soft_map_calls_embedding(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        emb = _make_embedding_client()
        asyncio.run(
            canonicalize_relation_type(
                raw_type="serves_on_board_of",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=_SOFT_ROW),
                outbox_repo=_make_outbox_repo(),
                embedding_client=emb,
            )
        )
        emb.embed.assert_called_once_with("serves_on_board_of")

    def test_soft_map_does_not_emit_proposal(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        outbox = _make_outbox_repo()
        asyncio.run(
            canonicalize_relation_type(
                raw_type="serves_on_board_of",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=_SOFT_ROW),
                outbox_repo=outbox,
                embedding_client=_make_embedding_client(),
            )
        )
        outbox.append.assert_not_called()


# ---------------------------------------------------------------------------
# Step 3: Propose (no match)
# ---------------------------------------------------------------------------


class TestPropose:
    def test_propose_returns_none_canonical_type(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        result = asyncio.run(
            canonicalize_relation_type(
                raw_type="invented_by",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=None),
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.canonical_type is None
        assert result.step == "proposed"

    def test_propose_does_not_raise(self) -> None:
        """Unknown types MUST NOT raise — they emit a proposal and return None."""
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        # Should not raise
        result = asyncio.run(
            canonicalize_relation_type(
                raw_type="invented_by",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=uuid4(),
                registry_repo=_make_registry_repo(exact_return=None, ann_return=None),
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.step == "proposed"

    def test_propose_emits_to_outbox(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        outbox = _make_outbox_repo()
        asyncio.run(
            canonicalize_relation_type(
                raw_type="invented_by",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=None),
                outbox_repo=outbox,
                embedding_client=_make_embedding_client(),
            )
        )
        outbox.append.assert_called_once()
        call_kwargs = outbox.append.call_args.kwargs
        assert call_kwargs["topic"] == "relation.type.proposed.v1"

    def test_propose_payload_contains_proposed_type(self) -> None:
        # PLAN-0062 F-006: outbox payload is Confluent-Avro framed bytes
        # (5-byte ``\x00<schema-id>`` header + Avro body), not raw JSON.
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
        from messaging.kafka.serialization_utils import (  # type: ignore[import-untyped]
            deserialize_confluent_avro,
        )

        outbox = _make_outbox_repo()
        asyncio.run(
            canonicalize_relation_type(
                raw_type="invented_by",
                semantic_mode_hint="TEMPORAL_CLAIM",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=None),
                outbox_repo=outbox,
                embedding_client=_make_embedding_client(),
            )
        )
        raw_payload = outbox.append.call_args.kwargs["payload_avro"]
        # Confluent magic byte present → decode via Avro path.
        assert raw_payload[:1] == b"\x00", "expected Confluent-Avro framed bytes"
        payload = deserialize_confluent_avro(
            get_schema_path("relation.type.proposed.v1.avsc"),
            raw_payload,
        )
        assert payload["proposed_type"] == "invented_by"
        assert payload["semantic_mode"] == "TEMPORAL_CLAIM"


# ---------------------------------------------------------------------------
# PLAN-0072 T-72-1-02 — case normalization before exact match
# ---------------------------------------------------------------------------


class TestCaseNormalization:
    """Step 1 exact match is now case-insensitive (PLAN-0072 T-72-1-02)."""

    def test_exact_match_case_insensitive(self) -> None:
        """UPPERCASE raw_type resolves to lowercase canonical via exact match."""
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        row = dict(_EXACT_ROW, canonical_type="competes_with")
        # Registry receives the normalized lowercase key and returns the row.
        registry = _make_registry_repo(exact_return=row)

        result = asyncio.run(
            canonicalize_relation_type(
                raw_type="COMPETES_WITH",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=registry,
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.canonical_type == "competes_with"
        assert result.step == "exact"
        # find_exact must have been called with the lowercased key, not the original.
        registry.find_exact.assert_called_once_with("competes_with")

    def test_uppercase_llm_output_canonicalized(self) -> None:
        """Mixed-case LLM output like 'HAS_EXECUTIVE' resolves via normalized exact match."""
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        row = dict(_EXACT_ROW, canonical_type="has_executive")
        registry = _make_registry_repo(exact_return=row)

        result = asyncio.run(
            canonicalize_relation_type(
                raw_type="HAS_EXECUTIVE",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=registry,
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.step == "exact"
        registry.find_exact.assert_called_once_with("has_executive")

    def test_unknown_type_still_proposed(self) -> None:
        """Truly unknown type falls through to Step 3 (proposal) even after normalization."""
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        registry = _make_registry_repo(exact_return=None, ann_return=None)
        outbox = _make_outbox_repo()

        result = asyncio.run(
            canonicalize_relation_type(
                raw_type="INVENTED_BY",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=registry,
                outbox_repo=outbox,
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.canonical_type is None
        assert result.step == "proposed"
        # Registry received normalized key, still found nothing.
        registry.find_exact.assert_called_once_with("invented_by")


# ---------------------------------------------------------------------------
# PRD-0120 / PLAN-0123 Wave 1 (T-A-1-03): fitted per-type decay_alpha flows
# through unmodified — canonicalization does not clamp/override whatever the
# repository resolves (class value or per-type fit), it just forwards it.
# ---------------------------------------------------------------------------


class TestFittedDecayAlphaPassthrough:
    def test_exact_match_forwards_fitted_per_type_alpha_unmodified(self) -> None:
        """A per-type fitted alpha (not the class value) passes through as-is."""
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        fitted_row = {
            **_EXACT_ROW,
            "canonical_type": "analyst_rating",
            "decay_class": "FAST",
            # 0.0088 is a fitted per-type value, deliberately NOT equal to the
            # FAST class prior (0.049510) or any other class constant — proves
            # the value isn't silently re-resolved to a class constant anywhere
            # downstream of the repository.
            "decay_alpha": 0.0088,
        }
        registry = _make_registry_repo(exact_return=fitted_row)

        result = asyncio.run(
            canonicalize_relation_type(
                raw_type="analyst_rating",
                semantic_mode_hint="TEMPORAL_CLAIM",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=uuid4(),
                registry_repo=registry,
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )

        assert result.decay_alpha == pytest.approx(0.0088)

    def test_soft_match_forwards_fitted_per_type_alpha_unmodified(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        fitted_soft_row = {
            **_SOFT_ROW,
            "decay_alpha": 0.0088,
        }
        registry = _make_registry_repo(exact_return=None, ann_return=fitted_soft_row)

        result = asyncio.run(
            canonicalize_relation_type(
                raw_type="rated_by_analyst",
                semantic_mode_hint="TEMPORAL_CLAIM",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=uuid4(),
                registry_repo=registry,
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )

        assert result.decay_alpha == pytest.approx(0.0088)
