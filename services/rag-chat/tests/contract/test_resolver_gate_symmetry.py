"""F-LIVE-NEW-003 — resolver-gate symmetry guard.

Background
----------
Two resolver paths exist in rag-chat:

* IntelligenceHandler (tool path) → stop-word + floor + delta gates
* ChatOrchestrator (pre-prompt path) → calls S6 then surfaces resolved
  entities directly in the system prompt under
  ``Entities resolved from this query:``.

Until F-LIVE-NEW-003 the orchestrator path bypassed all gates so
generic stop-word substrings (``space``, ``delta``, ``shell``,
``block``, ``square``) leaked through and bound to real public
companies (SpaceX, Delta Air Lines, Shell plc, Block Inc., Square
Inc.) at sim ~0.62. The LLM then hallucinated about those companies
even when retrieval returned zero matching documents.

This contract test exercises ``ChatPipeline.resolve_entities`` — the
single shared post-S6 hook where the gate now applies — and asserts
that low-confidence candidates whose canonical name happens to share a
substring with a stop-word in the user query do NOT survive. The five
parametrised cases mirror the smoking-gun queries from the audit at
``docs/audits/2026-05-28-inv-iter11-findings-rootcause.md`` (Finding 2).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.contract


# Canonical UUIDv7s — values irrelevant, only used to populate
# ResolvedEntity rows. Kept stable per case for assertion clarity.
_FAKE_BAD_ID = UUID("018f0000-0000-7000-8000-000000bad000")
_FAKE_OK_ID = UUID("018f0000-0000-7000-8000-00000000600d")


def _resolved_entity(
    *,
    name: str,
    confidence: float,
    ticker: str | None = None,
    entity_id: UUID | None = None,
) -> Any:
    """Build a ResolvedEntity row as returned by S6Client.resolve_entities()."""
    from rag_chat.domain.entities.chat import ResolvedEntity

    return ResolvedEntity(
        entity_id=entity_id or _FAKE_BAD_ID,
        canonical_name=name,
        entity_type="ORG",
        confidence=confidence,
        matched_text=name,
        ticker=ticker,
    )


def _make_pipeline(s6_return: list) -> Any:
    """Build a minimal ChatPipeline with only ``s6_client`` wired.

    All other collaborators are dataclass-required so we pass ``None``
    where the field permits and trivial stubs everywhere else — the
    test only calls ``resolve_entities`` which touches s6_client only.
    """
    from rag_chat.application.pipeline.chat_pipeline import ChatPipeline

    s6 = AsyncMock()
    s6.resolve_entities = AsyncMock(return_value=s6_return)

    # ChatPipeline is a frozen dataclass with several required fields.
    # We bypass __init__'s collaborator wiring by passing AsyncMock()
    # for each — none are called by resolve_entities().
    return ChatPipeline(
        validator=AsyncMock(),
        rate_limiter=AsyncMock(),
        cache=AsyncMock(),
        get_thread=AsyncMock(),
        s6_client=s6,
        hyde=AsyncMock(),
        embedder=AsyncMock(),
        reranker=AsyncMock(),
        llm_chain=AsyncMock(),
        persistence=AsyncMock(),
    )


@pytest.mark.parametrize(
    ("query", "leaky_entity_name", "leaky_confidence"),
    [
        # Each row: user query, the noisy substring-alias canonical the
        # ungated path used to surface, and the actual S6 similarity
        # observed in the iter11 audit (all ~0.62 — well below the 0.75
        # floor).
        ("Find me companies in the AI semiconductor space with rising sentiment", "SpaceX", 0.62),
        ("Which delta-positive stocks broke out last week", "Delta Air Lines", 0.61),
        ("What does Shell think about renewables", "Shell plc", 0.64),
        ("Block-based startups gaining traction", "Block Inc.", 0.60),
        ("Square competitors", "Square Inc.", 0.63),
    ],
)
async def test_orchestrator_path_applies_resolver_gates(
    query: str,
    leaky_entity_name: str,
    leaky_confidence: float,
) -> None:
    """Symmetric-gate guard for the orchestrator S6 path.

    Sets up S6 to return a noisy low-confidence candidate (the
    "SpaceX-ish" entity from the audit). After F-LIVE-NEW-003 the
    pipeline's resolver-gate MUST drop that candidate so it never
    reaches the prompt-rendering step in chat_orchestrator.py.
    """
    pipeline = _make_pipeline(
        s6_return=[
            # The noisy false-positive that the ungated path used to surface.
            _resolved_entity(name=leaky_entity_name, confidence=leaky_confidence),
        ]
    )

    accepted = await pipeline.resolve_entities(query)

    # Core assertion: the leaky canonical name MUST NOT appear in the
    # accepted set. We check by substring (case-insensitive) so a
    # variant like "SpaceX" / "Space X" / "SpaceX Inc." all fail
    # symmetrically — the prompt builder takes whatever canonical_name
    # field S6 returned, so substring containment is the right test.
    leaky_lower = leaky_entity_name.lower()
    for a in accepted:
        assert leaky_lower not in a.canonical_name.lower(), (
            f"Resolver gate failed to drop noisy candidate {a.canonical_name!r} "
            f"(confidence={a.confidence}) for query {query!r}. Expected the "
            f"0.75 absolute-similarity floor to reject this row."
        )


async def test_orchestrator_path_preserves_high_confidence_candidates() -> None:
    """Sanity: the gate MUST NOT drop legitimate high-confidence hits.

    Catches the regression risk of an over-eager gate that would also
    reject "Apple Inc." on a query like "How is Apple doing?".
    """
    pipeline = _make_pipeline(
        s6_return=[
            # Above-floor confidence — must pass through.
            _resolved_entity(name="Apple Inc.", confidence=0.92, ticker="AAPL"),
            # Below-floor noise — must be dropped.
            _resolved_entity(name="Apple Computer Holdings", confidence=0.55),
        ]
    )

    accepted = await pipeline.resolve_entities("How is Apple doing this quarter?")

    names = [a.canonical_name for a in accepted]
    assert "Apple Inc." in names
    assert "Apple Computer Holdings" not in names


async def test_orchestrator_path_drops_ambiguous_when_delta_below_threshold() -> None:
    """Delta gate: 2+ above-floor candidates within 0.15 → reject all.

    Mirrors the IntelligenceHandler ambiguity behaviour so the
    orchestrator never surfaces two near-identical similarity rows as
    if both were confident matches.
    """
    pipeline = _make_pipeline(
        s6_return=[
            _resolved_entity(name="Apple Inc.", confidence=0.82),
            _resolved_entity(name="Apple Corp", confidence=0.80),  # delta 0.02 < 0.15
        ]
    )

    accepted = await pipeline.resolve_entities("Apple")

    assert accepted == [], (
        "Delta gate failed — 0.02 gap is below the 0.15 default; both "
        "candidates should be rejected. Got: "
        f"{[(a.canonical_name, a.confidence) for a in accepted]}"
    )


async def test_orchestrator_path_empty_s6_result_is_noop() -> None:
    """No candidates → no-op; gate must not crash on an empty list."""
    pipeline = _make_pipeline(s6_return=[])
    accepted = await pipeline.resolve_entities("totally unknown query string")
    assert accepted == []
