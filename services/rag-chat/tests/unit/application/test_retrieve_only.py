"""Unit tests for the intent-free RetrieveOnlyUseCase.

The pre-agent LLM intent classifier + RetrievalPlanBuilder were retired; this
use case (the eval harness's retrieval entry point) no longer classifies intent
and instead activates every retrieval source. These tests pin that behaviour:

  - the use case constructs with NO classifier / plan_builder dependency;
  - it builds a RetrievalPlan with every ``use_*`` flag True;
  - it labels the result ``intent_free``;
  - a precomputed embedding bypasses HyDE + the embedder (CI determinism, L5).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from rag_chat.application.use_cases.retrieve_only import RetrieveOnlyUseCase
from rag_chat.domain.entities.chat import ChatContext, ChatRequest

pytestmark = pytest.mark.unit

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000020")
_USER_ID = UUID("00000000-0000-0000-0000-000000000021")


def _make_uc(retrieval: MagicMock, embedder: MagicMock, hyde: MagicMock) -> RetrieveOnlyUseCase:
    """Build a RetrieveOnlyUseCase with all collaborators mocked."""
    validator = MagicMock()
    validator.validate = MagicMock(side_effect=lambda m: m)  # identity passthrough

    s6 = MagicMock()
    s6.resolve_entities = AsyncMock(return_value=[])  # no entities → entity-gated branches no-op

    return RetrieveOnlyUseCase(
        validator=validator,
        s6_client=s6,
        hyde=hyde,
        embedder=embedder,
        retrieval=retrieval,
    )


def _make_request(text: str = "Apple Q4 revenue") -> ChatRequest:
    return ChatRequest(
        message=text,
        context=ChatContext(),
        tenant_id=_TENANT_ID,
        user_id=_USER_ID,
    )


@pytest.mark.asyncio
async def test_precomputed_embedding_activates_all_sources_and_is_intent_free() -> None:
    """With a precomputed embedding: all-source plan, intent_free label, no embedder/HyDE calls."""
    retrieval = MagicMock()
    retrieval.retrieve = AsyncMock(return_value=[])

    embedder = MagicMock()
    embedder.embed = AsyncMock()  # must NOT be called

    hyde = MagicMock()
    hyde.expand = AsyncMock()  # must NOT be called

    uc = _make_uc(retrieval, embedder, hyde)

    result = await uc.execute(_make_request(), query_embedding=[0.1] * 1024, top_k=10)

    # Intent classification retired.
    assert result.intent == "intent_free"

    # Precomputed embedding bypasses HyDE + the embedder entirely.
    hyde.expand.assert_not_awaited()
    embedder.embed.assert_not_awaited()

    # The orchestrator received an all-source plan (every use_* flag True).
    plan = retrieval.retrieve.await_args.args[0]
    for flag in (
        "use_chunks",
        "use_relations",
        "use_graph",
        "use_claims",
        "use_events",
        "use_contradictions",
        "use_financial",
        "use_portfolio",
        "use_cypher",
    ):
        assert getattr(plan, flag) is True, f"{flag} should be True in the intent-free plan"


@pytest.mark.asyncio
async def test_no_embedding_falls_back_to_embedder_without_hyde() -> None:
    """Text-only path: HyDE is HyDE-ineligible (GENERAL) so it no-ops → plain embedder is used."""
    retrieval = MagicMock()
    retrieval.retrieve = AsyncMock(return_value=[])

    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[0.2] * 1024)

    hyde = MagicMock()
    # HyDE returns (None, None) for the fixed GENERAL intent (ineligible).
    hyde.expand = AsyncMock(return_value=(None, None))

    uc = _make_uc(retrieval, embedder, hyde)

    result = await uc.execute(_make_request(), query_embedding=None, top_k=5)

    assert result.intent == "intent_free"
    hyde.expand.assert_awaited_once()
    embedder.embed.assert_awaited_once()
    # The embedder's vector is forwarded to the orchestrator.
    assert retrieval.retrieve.await_args.args[3] == [0.2] * 1024
