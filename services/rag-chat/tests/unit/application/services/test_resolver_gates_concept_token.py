"""D-i regression — generic-concept ticker guard in the resolver gate.

The ``ru_ai_semi_screener`` live failure: the query "AI semiconductor" had S6's
alias-embedding search rank C3.ai (ticker "AI") at high similarity for the
concept phrase. That candidate was surfaced to the prompt as the resolved
entity, so the whole turn misrouted to C3.ai and refused — even though the
screener had returned good AI-semiconductor rows.

The fix: reject any candidate whose ticker is a generic technology/theme concept
token ("AI", "EV", "IoT", …) UNLESS the query distinctively names the company
(a non-generic token of its canonical name appears verbatim — e.g. "C3.ai").
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rag_chat.application.services.resolver_gates import (
    REASON_CONCEPT_TOKEN,
    GatedEntity,
    ResolverGateConfig,
    filter_resolver_candidates,
)

_CONFIG = ResolverGateConfig(
    stop_words=frozenset({"stock", "the", "a"}),
    top_similarity_min=0.75,
    delta_min=0.15,
)

_C3_ID = "01900000-0000-7000-8000-0000000000a1"
_NVDA_ID = "01900000-0000-7000-8000-000000001002"


def _c3ai(sim: float = 0.92) -> GatedEntity:
    return GatedEntity(entity_id=_C3_ID, canonical_name="C3.ai, Inc.", similarity=sim, ticker="AI")


def _nvda(sim: float = 0.80) -> GatedEntity:
    return GatedEntity(entity_id=_NVDA_ID, canonical_name="NVIDIA Corporation", similarity=sim, ticker="NVDA")


class TestConceptTokenGuard:
    def test_ai_semiconductor_query_rejects_c3ai(self) -> None:
        """The exact live failure: 'AI' concept must NOT resolve to C3.ai."""
        accepted, rejected = filter_resolver_candidates(
            [_c3ai()],
            config=_CONFIG,
            query_text="Show me AI semiconductor stocks above $50B market cap",
        )
        assert not accepted, "C3.ai must not be surfaced for an 'AI' concept query"
        assert any(r.entity_id == _C3_ID and r.rejection_reason == REASON_CONCEPT_TOKEN for r in rejected)

    def test_concept_guard_lets_other_candidates_through(self) -> None:
        """Rejecting the concept candidate must not drop legitimate co-candidates."""
        accepted, _ = filter_resolver_candidates(
            [_c3ai(), _nvda()],
            config=_CONFIG,
            query_text="Which AI semiconductor names look cheap?",
        )
        names = {a.canonical_name for a in accepted}
        assert "C3.ai, Inc." not in names
        assert "NVIDIA Corporation" in names

    def test_explicit_company_mention_still_resolves(self) -> None:
        """A query that distinctively names the company ('C3.ai') keeps it."""
        accepted, _ = filter_resolver_candidates(
            [_c3ai()],
            config=_CONFIG,
            query_text="How is C3.ai doing after its latest earnings?",
        )
        assert {a.canonical_name for a in accepted} == {"C3.ai, Inc."}

    def test_non_concept_ticker_unaffected(self) -> None:
        """A normal ticker (NVDA) is never touched by the concept guard."""
        accepted, rejected = filter_resolver_candidates(
            [_nvda()],
            config=_CONFIG,
            query_text="What is NVIDIA's revenue?",
        )
        assert {a.canonical_name for a in accepted} == {"NVIDIA Corporation"}
        assert not any(r.rejection_reason == REASON_CONCEPT_TOKEN for r in rejected)
