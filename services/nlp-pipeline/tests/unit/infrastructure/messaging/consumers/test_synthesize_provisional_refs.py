"""Unit tests for synthesize_provisional_refs (PLAN-0052 round 9 / Option 2).

Validates the article-consumer's inline promotion of LLM-referenced UNRESOLVED
mentions to PROVISIONAL — closing the F-CRIT-07 silent-drop on relations
between entities the resolver couldn't auto-match.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome
from nlp_pipeline.domain.models import EntityMention
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    _collect_extraction_refs,
    synthesize_provisional_refs,
)

pytestmark = pytest.mark.unit


def _make_mention(text: str, *, resolved: bool = False, queued: bool = False) -> EntityMention:
    m = EntityMention(
        mention_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        section_id=uuid.uuid4(),
        mention_text=text,
        mention_class=MentionClass.ORGANIZATION,
        confidence=0.85,
        char_start=0,
        char_end=len(text),
    )
    if resolved:
        m.resolved_entity_id = uuid.uuid4()
        m.resolution_outcome = ResolutionOutcome.AUTO_RESOLVED
    elif queued:
        m.provisional_queue_id = uuid.uuid4()
        m.resolution_outcome = ResolutionOutcome.PROVISIONAL
    else:
        m.resolution_outcome = ResolutionOutcome.UNRESOLVED
    return m


# ── _collect_extraction_refs ─────────────────────────────────────────────────


@pytest.mark.unit
class TestCollectExtractionRefs:
    """Walks the LLM extraction output and yields all referenced surface forms."""

    def test_collects_relation_endpoints(self) -> None:
        result = {
            "relations": [
                {"subject_ref": "Endeavour Mining", "object_ref": "Ghana"},
                {"subject_ref": "Apple Inc.", "object_ref": "TSMC"},
            ],
            "events": [],
            "claims": [],
        }
        refs = _collect_extraction_refs(result)
        # Each surface generates lowercase + suffix-stripped variants
        assert "endeavour mining" in refs
        assert "ghana" in refs
        assert "apple" in refs  # suffix-stripped from "apple inc."
        assert "tsmc" in refs

    def test_collects_event_entity_refs(self) -> None:
        result = {
            "relations": [],
            "events": [{"entity_refs": ["Microsoft", "Activision"]}],
            "claims": [],
        }
        refs = _collect_extraction_refs(result)
        assert "microsoft" in refs
        assert "activision" in refs

    def test_collects_claim_entity_ref(self) -> None:
        result = {
            "relations": [],
            "events": [],
            "claims": [{"entity_ref": "Tesla"}],
        }
        refs = _collect_extraction_refs(result)
        assert "tesla" in refs

    def test_empty_extraction_returns_empty_set(self) -> None:
        assert _collect_extraction_refs({}) == set()
        assert _collect_extraction_refs({"relations": [], "events": [], "claims": []}) == set()

    def test_skips_non_string_refs(self) -> None:
        """Defensive: never crash on malformed LLM output."""
        result = {
            "relations": [{"subject_ref": None, "object_ref": 42}],
            "events": [{"entity_refs": [None, 0]}],
            "claims": [{"entity_ref": []}],
        }
        assert _collect_extraction_refs(result) == set()


# ── synthesize_provisional_refs ──────────────────────────────────────────────


def _intel_session_returning(queue_ids: list[uuid.UUID]) -> MagicMock:
    """Build an intelligence-session mock that returns a sequence of queue_ids
    on each ensure_provisional_for_mention call.

    Each call performs: 1 SELECT (churn count = 0) + 1 INSERT inside a SAVEPOINT.
    The SAVEPOINT block uses begin_nested() as an async context manager.
    """
    session = MagicMock()
    # Two execute() calls per provisional: COUNT + INSERT, repeated len(queue_ids) times.
    side_effects: list[MagicMock] = []
    for qid in queue_ids:
        count_result = MagicMock()
        count_result.scalar_one = MagicMock(return_value=0)
        insert_result = MagicMock()
        insert_result.scalar_one = MagicMock(return_value=str(qid))
        side_effects.extend([count_result, insert_result])
    session.execute = AsyncMock(side_effect=side_effects)

    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)
    return session


@pytest.mark.unit
class TestSynthesizeProvisionalRefs:
    """Round 9 Option 2 — promote LLM-referenced UNRESOLVED mentions inline."""

    @pytest.mark.asyncio
    async def test_promotes_unresolved_mention_referenced_by_llm(self) -> None:
        """Mention is UNRESOLVED, LLM references it → queue row created, queue_id stashed."""
        m = _make_mention("Endeavour Mining")
        extraction_result = {
            "relations": [{"subject_ref": "Endeavour Mining", "object_ref": "Ghana"}],
            "events": [],
            "claims": [],
        }
        # Only one provisional needed: "Ghana" mention isn't in the list, so
        # the LLM's ref to it is skipped (no candidate to promote).
        new_qid = uuid.uuid4()
        session = _intel_session_returning([new_qid])

        promoted = await synthesize_provisional_refs(
            mentions=[m],
            extraction_result=extraction_result,
            intelligence_session=session,
        )

        assert promoted == 1
        assert m.provisional_queue_id == new_qid
        assert m.resolution_outcome == ResolutionOutcome.PROVISIONAL

    @pytest.mark.asyncio
    async def test_skips_already_resolved_mention(self) -> None:
        """An AUTO_RESOLVED mention referenced by the LLM is left alone."""
        m = _make_mention("Apple Inc.", resolved=True)
        original_id = m.resolved_entity_id
        extraction_result = {
            "relations": [{"subject_ref": "Apple", "object_ref": "TSMC"}],
            "events": [],
            "claims": [],
        }
        session = _intel_session_returning([])

        promoted = await synthesize_provisional_refs(
            mentions=[m],
            extraction_result=extraction_result,
            intelligence_session=session,
        )

        assert promoted == 0
        assert m.resolved_entity_id == original_id
        assert m.provisional_queue_id is None

    @pytest.mark.asyncio
    async def test_skips_already_queued_mention(self) -> None:
        """A mention already in the provisional queue (Block 9 path) is skipped."""
        m = _make_mention("MercadoLibre", queued=True)
        original_qid = m.provisional_queue_id
        extraction_result = {
            "relations": [{"subject_ref": "MercadoLibre", "object_ref": "Brazil"}],
            "events": [],
            "claims": [],
        }
        session = _intel_session_returning([])

        promoted = await synthesize_provisional_refs(
            mentions=[m],
            extraction_result=extraction_result,
            intelligence_session=session,
        )

        assert promoted == 0
        assert m.provisional_queue_id == original_qid

    @pytest.mark.asyncio
    async def test_promotes_only_referenced_mentions(self) -> None:
        """UNRESOLVED mentions the LLM does NOT reference are left alone."""
        m_ref = _make_mention("Endeavour Mining")
        m_unref = _make_mention("Caledonia Mining")
        extraction_result = {
            "relations": [{"subject_ref": "Endeavour Mining", "object_ref": "Ghana"}],
            "events": [],
            "claims": [],
        }
        new_qid = uuid.uuid4()
        session = _intel_session_returning([new_qid])

        promoted = await synthesize_provisional_refs(
            mentions=[m_ref, m_unref],
            extraction_result=extraction_result,
            intelligence_session=session,
        )

        assert promoted == 1
        assert m_ref.provisional_queue_id == new_qid
        assert m_unref.provisional_queue_id is None
        # Caledonia was not LLM-referenced; UnresolvedResolutionWorker handles it.
        assert m_unref.resolution_outcome == ResolutionOutcome.UNRESOLVED

    @pytest.mark.asyncio
    async def test_dedupes_when_mention_referenced_multiple_times(self) -> None:
        """If the LLM references the same mention twice (subject AND object of
        different relations), it must only be queued once."""
        m = _make_mention("Tesla")
        extraction_result = {
            "relations": [
                {"subject_ref": "Tesla", "object_ref": "Some Supplier"},
                {"subject_ref": "Acme Corp", "object_ref": "Tesla"},  # second ref
            ],
            "events": [{"entity_refs": ["Tesla"]}],  # third ref
            "claims": [],
        }
        new_qid = uuid.uuid4()
        session = _intel_session_returning([new_qid])

        promoted = await synthesize_provisional_refs(
            mentions=[m],
            extraction_result=extraction_result,
            intelligence_session=session,
        )

        # Same mention referenced 3x → still only 1 promotion
        assert promoted == 1
        assert m.provisional_queue_id == new_qid

    @pytest.mark.asyncio
    async def test_empty_extraction_is_noop(self) -> None:
        m = _make_mention("Apple")
        session = _intel_session_returning([])

        promoted = await synthesize_provisional_refs(
            mentions=[m],
            extraction_result={"relations": [], "events": [], "claims": []},
            intelligence_session=session,
        )

        assert promoted == 0
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_suffix_stripped_match(self) -> None:
        """LLM ref 'Microsoft' should match mention 'Microsoft Corp' via suffix-strip."""
        m = _make_mention("Microsoft Corp")
        extraction_result = {
            "relations": [{"subject_ref": "Microsoft", "object_ref": "OpenAI"}],
            "events": [],
            "claims": [],
        }
        new_qid = uuid.uuid4()
        session = _intel_session_returning([new_qid])

        promoted = await synthesize_provisional_refs(
            mentions=[m],
            extraction_result=extraction_result,
            intelligence_session=session,
        )

        assert promoted == 1
        assert m.provisional_queue_id == new_qid
