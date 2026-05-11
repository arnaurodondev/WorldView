"""Unit tests for ``EnrichedArticleConsumer`` source_name propagation (D-INIT-6).

These tests cover the post-fix behaviour for D-INIT-6 (2026-05-09):

* When the inbound ``nlp.article.enriched.v1`` event payload contains
  ``source_name``, the consumer forwards it to ``materialize_graph`` directly
  and never queries ``document_source_metadata``.
* When the inbound payload omits ``source_name`` (or has it explicitly None),
  the consumer logs a single ``evidence_source_metadata_missing`` warning,
  forwards ``source_name=None`` and ``source_type_metadata=value.get("source_type")``
  to ``materialize_graph``, and crucially does **not** attempt any cross-DB
  fallback. The previous ``RelationEvidenceRepository.lookup_source_metadata``
  fallback queried an ``nlp_db`` table from the ``intelligence_db`` session pool
  (R7 cross-service-DB violation) — that method has been removed.

Strategy: patch ``materialize_graph`` at the call site so we can capture the
kwargs forwarded to it. Patch ``RelationEvidenceRepository`` at its import site
in the consumer module so we can assert that no DB lookup methods were called.
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
# Patch targets (module-import sites in enriched_consumer.py)
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
    """Build a minimal async-context-manager session factory."""
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


def _make_mock_repos() -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Return (mock_ev_repo, mock_rel_repo, mock_outbox_repo, mock_registry_repo).

    The evidence-repo mock has *no* ``lookup_source_metadata`` attribute — that
    method was removed in the D-INIT-6 fix. Tests assert via ``hasattr`` /
    ``assert_not_called`` semantics that the consumer never tries to invoke it.
    """
    # ``spec_set=[]`` would be too strict (the consumer constructs the repo and
    # passes it into materialize_graph which is patched), so we just create a
    # plain AsyncMock and rely on assertions about what was called.
    mock_ev = AsyncMock()
    mock_rel = AsyncMock()
    mock_out = AsyncMock()
    mock_reg = AsyncMock()
    return mock_ev, mock_rel, mock_out, mock_reg


def _canonicalize_returning_none() -> object:
    """Build a stand-in for ``canonicalize_relation_type``.

    The real function is async; the consumer awaits it once per relation. Our
    payloads have zero raw_relations so the function is never actually called,
    but we still need a callable that returns an awaitable to satisfy the
    patch at import time.
    """
    return lambda *args, **kwargs: AsyncMock(
        return_value=MagicMock(
            canonical_type=None,
            semantic_mode=None,
            decay_class=None,
            decay_alpha=None,
            base_confidence=None,
        )
    )


# ---------------------------------------------------------------------------
# D-INIT-6 tests
# ---------------------------------------------------------------------------


class TestSourceNamePopulatedFromPayload:
    def test_source_name_populated_from_event_payload(self) -> None:
        """When event payload has source_name, it is passed to materialize_graph without DB lookup."""
        doc_id = str(uuid4())
        payload = _base_payload(doc_id, source_name="Reuters", source_type="newswire")

        sf = _make_sf()
        consumer = _make_consumer(sf)
        mock_ev, mock_rel, mock_out, mock_reg = _make_mock_repos()

        captured_kwargs: dict = {}
        summary = _make_empty_materialize_summary()

        async def _fake_materialize(**kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return summary

        with (
            patch(_GRAPH_WRITE, side_effect=_fake_materialize),
            patch(_CANONICALIZE, new_callable=_canonicalize_returning_none),
            patch(_EV_REPO_CLS, return_value=mock_ev),
            patch(_REL_REPO_CLS, return_value=mock_rel),
            patch(_OUTBOX_REPO_CLS, return_value=mock_out),
            patch(_REGISTRY_REPO_CLS, return_value=mock_reg),
        ):
            asyncio.run(consumer.process_message(key=doc_id, value=payload, headers={}))  # type: ignore[attr-defined]

        # source_name and source_type_metadata must be passed straight from the payload.
        assert captured_kwargs.get("source_name") == "Reuters"
        assert captured_kwargs.get("source_type_metadata") == "newswire"

        # Critical: the consumer must NEVER call any DB-lookup method on the
        # evidence repo. ``lookup_source_metadata`` was removed (R7 violation)
        # and any new lookup-style method would re-introduce the bug.
        assert "lookup_source_metadata" not in dir(mock_ev) or not mock_ev.lookup_source_metadata.called


class TestSourceNameMissingNoFallbackQuery:
    """D-INIT-6: when source_name is missing the consumer must NOT query nlp_db.

    The previous behaviour fell back to ``RelationEvidenceRepository.lookup_source_metadata``
    which executed ``SELECT ... FROM document_source_metadata`` against the
    intelligence_db session — a guaranteed UndefinedTableError because that
    table only exists in nlp_db. The fix removes the lookup method entirely
    and replaces the fallback with a single warning.
    """

    def test_source_name_missing_logs_warning_and_continues(self) -> None:
        """When payload lacks source_name, consumer warns and forwards None — no DB lookup."""
        doc_id = str(uuid4())
        # No source_name in payload — only source_type. This used to trigger the
        # fallback DB query; now it should just log a warning.
        payload = _base_payload(doc_id, source_type="news")

        sf = _make_sf()
        consumer = _make_consumer(sf)
        mock_ev, mock_rel, mock_out, mock_reg = _make_mock_repos()

        captured_kwargs: dict = {}
        summary = _make_empty_materialize_summary()

        async def _fake_materialize(**kwargs: object) -> object:
            captured_kwargs.update(kwargs)
            return summary

        with capture_logs() as cap:
            with (
                patch(_GRAPH_WRITE, side_effect=_fake_materialize),
                patch(_CANONICALIZE, new_callable=_canonicalize_returning_none),
                patch(_EV_REPO_CLS, return_value=mock_ev),
                patch(_REL_REPO_CLS, return_value=mock_rel),
                patch(_OUTBOX_REPO_CLS, return_value=mock_out),
                patch(_REGISTRY_REPO_CLS, return_value=mock_reg),
            ):
                asyncio.run(consumer.process_message(key=doc_id, value=payload, headers={}))  # type: ignore[attr-defined]

        # source_name forwarded as None; source_type_metadata still flows through.
        assert captured_kwargs.get("source_name") is None
        assert captured_kwargs.get("source_type_metadata") == "news"

        # The warning must be emitted.
        warning_events = [e.get("event") for e in cap]
        assert (
            "evidence_source_metadata_missing" in warning_events
        ), f"Expected evidence_source_metadata_missing warning; got: {warning_events}"

        # No DB lookup method was called on the evidence repo. The legacy
        # ``lookup_source_metadata`` was removed; if any future code path
        # re-introduces a lookup-style helper, this assertion will catch it.
        for attr in dir(mock_ev):
            if "lookup" in attr.lower():
                lookup_attr = getattr(mock_ev, attr)
                assert not getattr(lookup_attr, "called", False), (
                    f"Evidence repo method {attr!r} was called — D-INIT-6 regression: "
                    f"the consumer must NOT fall back to a DB lookup when source_name is missing"
                )


class TestRelationEvidenceRepositoryHasNoLookup:
    """Architectural regression test: the R7-violating method must stay deleted."""

    def test_repository_has_no_lookup_source_metadata_method(self) -> None:
        """``RelationEvidenceRepository`` must not expose ``lookup_source_metadata``.

        That method queried ``document_source_metadata`` — an nlp_db table — from
        the intelligence_db session pool. It was removed as part of D-INIT-6 to
        eliminate the R7 cross-service-DB violation. If a future change re-adds
        it (e.g. via a copy-paste from git history), this test fails immediately.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
            RelationEvidenceRepository,
        )

        assert not hasattr(RelationEvidenceRepository, "lookup_source_metadata"), (
            "RelationEvidenceRepository.lookup_source_metadata was removed in D-INIT-6 "
            "(R7 cross-service-DB violation: queried document_source_metadata from nlp_db "
            "via the intelligence_db session). Do NOT re-introduce — propagate source_name "
            "through the nlp.article.enriched.v1 event payload instead."
        )
