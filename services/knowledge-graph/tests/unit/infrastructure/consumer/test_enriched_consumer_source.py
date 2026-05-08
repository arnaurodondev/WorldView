"""Unit tests for EnrichedArticleConsumer — T-B-03 source_name/source_type population.

Tests cover:
  - source_name populated directly from event payload when present.
  - source_name resolved via document_source_metadata JOIN when absent from payload.
  - source_name left NULL when neither payload nor metadata provides it (warning emitted).

Strategy: patch ``materialize_graph`` at the call site so we can capture the
kwargs passed to it.  Patch ``RelationEvidenceRepository`` at its import site
in the consumer module so we can control ``lookup_source_metadata``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_GRAPH_WRITE = "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.materialize_graph"
_CANONICALIZE = "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.canonicalize_relation_type"
_EV_REPO_CLS = "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.RelationEvidenceRepository"
_REL_REPO_CLS = "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.RelationRepository"
_OUTBOX_REPO_CLS = "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.OutboxRepository"
_REGISTRY_REPO_CLS = (
    "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.RelationTypeRegistryRepository"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sf() -> MagicMock:
    """Minimal async context-manager session factory."""
    session = AsyncMock()
    session.commit = AsyncMock()
    sf = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    sf.return_value = ctx
    return sf


def _make_empty_materialize_summary() -> object:
    from knowledge_graph.application.blocks.graph_write import MaterializationSummary

    return MaterializationSummary(
        relations_upserted=0,
        evidence_rows_inserted=0,
        events_inserted=0,
        claims_inserted=0,
        entities_dirtied=0,
    )


def _make_consumer(sf: MagicMock) -> object:
    from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import EnrichedArticleConsumer

    config = ConsumerConfig(group_id="test", topics=["nlp.article.enriched.v1"])
    return EnrichedArticleConsumer(
        config=config,
        session_factory=sf,
        embedding_client=MagicMock(),
        direct_producer=MagicMock(),
        entity_dirtied_topic="entity.dirtied.v1",
    )


def _base_payload(doc_id: str, **extra: object) -> dict:
    return {
        "event_id": str(uuid4()),
        "doc_id": doc_id,
        "resolved_entity_ids": [],
        "is_backfill": False,
        "raw_relations": [],
        "raw_events": [],
        "raw_claims": [],
        **extra,
    }


def _make_mock_repos(
    lookup_return: tuple,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Return (mock_ev_repo, mock_rel_repo, mock_outbox_repo, mock_registry_repo)."""
    mock_ev = AsyncMock()
    mock_ev.lookup_source_metadata = AsyncMock(return_value=lookup_return)

    mock_rel = AsyncMock()
    mock_out = AsyncMock()
    mock_reg = AsyncMock()
    return mock_ev, mock_rel, mock_out, mock_reg


# ---------------------------------------------------------------------------
# T-B-03 tests
# ---------------------------------------------------------------------------


class TestSourceNamePopulatedFromPayload:
    def test_source_name_populated_from_event_payload(self) -> None:
        """When event payload has source_name, it is passed to materialize_graph without DB lookup."""
        doc_id = str(uuid4())
        payload = _base_payload(doc_id, source_name="Reuters", source_type="newswire")

        sf = _make_sf()
        consumer = _make_consumer(sf)
        mock_ev, mock_rel, mock_out, mock_reg = _make_mock_repos(("Reuters", "newswire"))

        captured_kwargs: dict = {}
        summary = _make_empty_materialize_summary()

        async def _fake_materialize(**kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return summary

        with (
            patch(_GRAPH_WRITE, side_effect=_fake_materialize),
            patch(
                _CANONICALIZE,
                new_callable=lambda: (
                    lambda *a, **kw: AsyncMock(
                        return_value=MagicMock(
                            canonical_type=None,
                            semantic_mode=None,
                            decay_class=None,
                            decay_alpha=None,
                            base_confidence=None,
                        )
                    )
                ),
            ),
            patch(_EV_REPO_CLS, return_value=mock_ev),
            patch(_REL_REPO_CLS, return_value=mock_rel),
            patch(_OUTBOX_REPO_CLS, return_value=mock_out),
            patch(_REGISTRY_REPO_CLS, return_value=mock_reg),
        ):
            asyncio.run(consumer.process_message(key=doc_id, value=payload, headers={}))  # type: ignore[attr-defined]

        # source_name and source_type_metadata must be passed from the payload.
        assert captured_kwargs.get("source_name") == "Reuters"
        assert captured_kwargs.get("source_type_metadata") == "newswire"
        # The DB fallback must NOT have been called since payload had source_name.
        mock_ev.lookup_source_metadata.assert_not_awaited()


class TestSourceNameFallbackJoinMetadata:
    def test_source_name_fallback_join_metadata(self) -> None:
        """When payload lacks source_name, lookup_source_metadata is called and result propagated."""
        doc_id = str(uuid4())
        # No source_name in payload — only source_type; triggers fallback.
        payload = _base_payload(doc_id, source_type="news")

        sf = _make_sf()
        consumer = _make_consumer(sf)
        mock_ev, mock_rel, mock_out, mock_reg = _make_mock_repos(("Bloomberg", "financial_wire"))

        captured_kwargs: dict = {}
        summary = _make_empty_materialize_summary()

        async def _fake_materialize(**kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return summary

        with (
            patch(_GRAPH_WRITE, side_effect=_fake_materialize),
            patch(
                _CANONICALIZE,
                new_callable=lambda: (
                    lambda *a, **kw: AsyncMock(
                        return_value=MagicMock(
                            canonical_type=None,
                            semantic_mode=None,
                            decay_class=None,
                            decay_alpha=None,
                            base_confidence=None,
                        )
                    )
                ),
            ),
            patch(_EV_REPO_CLS, return_value=mock_ev),
            patch(_REL_REPO_CLS, return_value=mock_rel),
            patch(_OUTBOX_REPO_CLS, return_value=mock_out),
            patch(_REGISTRY_REPO_CLS, return_value=mock_reg),
        ):
            asyncio.run(consumer.process_message(key=doc_id, value=payload, headers={}))  # type: ignore[attr-defined]

        # Fallback must have been called.
        mock_ev.lookup_source_metadata.assert_awaited_once()
        # The resolved values from metadata must be forwarded.
        assert captured_kwargs.get("source_name") == "Bloomberg"
        assert captured_kwargs.get("source_type_metadata") == "financial_wire"


class TestSourceNameNullWhenMetadataMissing:
    def test_source_name_null_when_metadata_missing(self) -> None:
        """When neither payload nor metadata has source_name, NULL is passed and warning emitted."""
        doc_id = str(uuid4())
        # No source_name or source_type in payload at all.
        payload = _base_payload(doc_id)

        sf = _make_sf()
        consumer = _make_consumer(sf)
        # Metadata lookup returns (None, None) — row not found.
        mock_ev, mock_rel, mock_out, mock_reg = _make_mock_repos((None, None))

        captured_kwargs: dict = {}
        summary = _make_empty_materialize_summary()

        async def _fake_materialize(**kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return summary

        with capture_logs() as cap:
            with (
                patch(_GRAPH_WRITE, side_effect=_fake_materialize),
                patch(
                    _CANONICALIZE,
                    new_callable=lambda: (
                        lambda *a, **kw: AsyncMock(
                            return_value=MagicMock(
                                canonical_type=None,
                                semantic_mode=None,
                                decay_class=None,
                                decay_alpha=None,
                                base_confidence=None,
                            )
                        )
                    ),
                ),
                patch(_EV_REPO_CLS, return_value=mock_ev),
                patch(_REL_REPO_CLS, return_value=mock_rel),
                patch(_OUTBOX_REPO_CLS, return_value=mock_out),
                patch(_REGISTRY_REPO_CLS, return_value=mock_reg),
            ):
                asyncio.run(consumer.process_message(key=doc_id, value=payload, headers={}))  # type: ignore[attr-defined]

        # source_name and source_type_metadata must be None (NULL-safe).
        assert captured_kwargs.get("source_name") is None
        assert captured_kwargs.get("source_type_metadata") is None

        # Warning must have been emitted.
        warning_events = [e.get("event") for e in cap]
        assert (
            "evidence_source_metadata_missing" in warning_events
        ), f"Expected evidence_source_metadata_missing warning; got: {warning_events}"
