"""C3 regression — implausibly-short canonical stub guard in the resolver gate.

The ``da_apple_revenue_fy2024q4_precision`` live failure (eval run
20260708T064000Z): the query "What was Apple's reported revenue for fiscal Q4
2024…" had S6's alias-embedding search rank the one-letter canonical "S"
(ticker "S" = SentinelOne/Sprint) at similarity 0.95. That stub passed the
0.75 floor, dominated the delta gate, and was surfaced to the LLM prompt as
the resolved entity — so the model answered "revenue for S (ticker: S)" even
though it had correctly tool-called AAPL. Judge framing score = 0
("complete topic mismatch").

The fix: reject any candidate whose canonical name is 1-2 chars UNLESS the
query names it verbatim as a standalone uppercase ticker ("how is S doing?").
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rag_chat.application.services.resolver_gates import (
    REASON_IMPLAUSIBLE_SHORT,
    GatedEntity,
    ResolverGateConfig,
    filter_resolver_candidates,
)

_CONFIG = ResolverGateConfig(
    stop_words=frozenset({"stock", "the", "a"}),
    top_similarity_min=0.75,
    delta_min=0.15,
)

_S_ID = "01900000-0000-7000-8000-000000000055"
_APPLE_ID = "01900000-0000-7000-8000-000000001001"


def _s_stub(sim: float = 0.95) -> GatedEntity:
    return GatedEntity(entity_id=_S_ID, canonical_name="S", similarity=sim, ticker="S")


def _apple(sim: float = 0.90) -> GatedEntity:
    return GatedEntity(entity_id=_APPLE_ID, canonical_name="Apple Inc.", similarity=sim, ticker="AAPL")


class TestShortStubGuard:
    def test_apple_revenue_query_rejects_S_stub(self) -> None:
        """The exact live failure: 'S' stub at 0.95 must NOT be surfaced."""
        accepted, rejected = filter_resolver_candidates(
            [_s_stub(), _apple()],
            config=_CONFIG,
            query_text=(
                "What was Apple's reported revenue for fiscal Q4 2024 "
                "(quarter ending September 28, 2024), in billions?"
            ),
        )
        accepted_names = {a.canonical_name for a in accepted}
        assert "S" not in accepted_names
        assert any(r.entity_id == _S_ID and r.rejection_reason == REASON_IMPLAUSIBLE_SHORT for r in rejected)
        # Apple survives the stub pass; as the sole survivor it is accepted.
        assert accepted_names == {"Apple Inc."}

    def test_S_stub_alone_is_rejected_not_surfaced(self) -> None:
        """A lone short stub with no verbatim mention resolves to nothing."""
        accepted, rejected = filter_resolver_candidates(
            [_s_stub()],
            config=_CONFIG,
            query_text="What was Apple's revenue last quarter?",
        )
        assert accepted == []
        assert len(rejected) == 1
        assert rejected[0].rejection_reason == REASON_IMPLAUSIBLE_SHORT

    def test_explicit_uppercase_ticker_query_keeps_short_stub(self) -> None:
        """'how is S doing?' — the user explicitly names the one-letter ticker."""
        accepted, _rejected = filter_resolver_candidates(
            [_s_stub()],
            config=_CONFIG,
            query_text="How is S doing after its latest earnings?",
        )
        assert [a.entity_id for a in accepted] == [_S_ID]

    def test_two_letter_stub_rejected_without_mention(self) -> None:
        """A 2-char canonical is also a stub when unnamed."""
        it_stub = GatedEntity(
            entity_id="01900000-0000-7000-8000-000000000011",
            canonical_name="IT",
            similarity=0.93,
            ticker="IT",
        )
        accepted, rejected = filter_resolver_candidates(
            [it_stub],
            config=_CONFIG,
            query_text="What is the outlook for the technology sector?",
        )
        assert accepted == []
        assert rejected[0].rejection_reason == REASON_IMPLAUSIBLE_SHORT

    def test_long_canonical_with_short_ticker_survives(self) -> None:
        """Ford Motor Company (ticker 'F') is a real entity — never a stub."""
        ford = GatedEntity(
            entity_id="01900000-0000-7000-8000-0000000f00d",
            canonical_name="Ford Motor Company",
            similarity=0.88,
            ticker="F",
        )
        accepted, rejected = filter_resolver_candidates(
            [ford],
            config=_CONFIG,
            query_text="What is Ford's dividend yield?",
        )
        assert [a.entity_id for a in accepted] == [ford.entity_id]
        assert rejected == []

    def test_normal_multichar_resolution_unaffected(self) -> None:
        """A genuine unambiguous resolution still passes cleanly."""
        accepted, rejected = filter_resolver_candidates(
            [_apple(sim=0.92)],
            config=_CONFIG,
            query_text="What was Apple's revenue?",
        )
        assert [a.entity_id for a in accepted] == [_APPLE_ID]
        assert rejected == []
