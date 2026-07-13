"""SEC-FORM-001 regression — SEC filing form designators must not resolve as tickers.

The live failure: a filings chat query mentioning "10-K" resolved the bare
form fragment "K" to the ticker K (Kellanova), routing the whole turn to the
wrong company. This is the same class as the R1 extraction "ticker
class-blind" family — a short all-caps token matched as a ticker without
checking its surrounding context.

The fix (``resolver_gates``):
  * ``filter_resolver_candidates`` rejects a resolved candidate whose ticker is
    a bare fragment of a SEC-form designator present in the query, UNLESS the
    same fragment also appears standalone elsewhere (genuine ticker mention).
  * ``is_sec_form_designator`` lets the tool-argument resolver paths refuse a
    literal form name ("10-K") the LLM echoes into an ``entity_name`` argument.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rag_chat.application.services.resolver_gates import (
    REASON_SEC_FORM_FRAGMENT,
    GatedEntity,
    ResolverGateConfig,
    filter_resolver_candidates,
    is_sec_form_designator,
)

_CONFIG = ResolverGateConfig(stop_words=frozenset(), top_similarity_min=0.75, delta_min=0.15)

_KELLANOVA_ID = "01900000-0000-7000-8000-0000000000ka"
_APPLE_ID = "01900000-0000-7000-8000-000000001001"


def _kellanova(sim: float = 0.88) -> GatedEntity:
    """S6 mis-resolves the "K" fragment of "10-K" to Kellanova (ticker K)."""
    return GatedEntity(entity_id=_KELLANOVA_ID, canonical_name="Kellanova", similarity=sim, ticker="K")


def _apple(sim: float = 0.91) -> GatedEntity:
    return GatedEntity(entity_id=_APPLE_ID, canonical_name="Apple Inc.", similarity=sim, ticker="AAPL")


class TestSecFormFragmentGate:
    @pytest.mark.parametrize(
        "query",
        [
            "what's in Apple's latest 10-K",
            "summarize the 8-K they just filed",
            "any risk factors in the 6-K?",
            "per their 11-K plan",
        ],
    )
    def test_k_fragment_of_form_does_not_resolve_to_kellanova(self, query: str) -> None:
        """The "K" fragment of a *-K form must not resolve to ticker K."""
        accepted, rejected = filter_resolver_candidates([_kellanova()], config=_CONFIG, query_text=query)
        assert accepted == []
        assert [r.rejection_reason for r in rejected] == [REASON_SEC_FORM_FRAGMENT]

    def test_10q_q_fragment_does_not_resolve(self) -> None:
        q_ticker = GatedEntity(entity_id="q", canonical_name="Qualtrics", similarity=0.9, ticker="Q")
        accepted, _ = filter_resolver_candidates([q_ticker], config=_CONFIG, query_text="review the 10-Q")
        assert accepted == []

    def test_20f_f_fragment_does_not_resolve(self) -> None:
        f_ticker = GatedEntity(entity_id="f", canonical_name="Ford Motor", similarity=0.9, ticker="F")
        accepted, _ = filter_resolver_candidates([f_ticker], config=_CONFIG, query_text="the 20-F annual report")
        assert accepted == []

    def test_s1_s_fragment_does_not_resolve(self) -> None:
        s_ticker = GatedEntity(entity_id="s", canonical_name="SentinelOne", similarity=0.9, ticker="S")
        accepted, _ = filter_resolver_candidates(
            [s_ticker], config=_CONFIG, query_text="details from the S-1 prospectus"
        )
        assert accepted == []

    def test_real_entity_alongside_form_still_resolves(self) -> None:
        """Apple (AAPL) is untouched by the guard; only the "K" fragment is dropped."""
        accepted, rejected = filter_resolver_candidates(
            [_apple(), _kellanova()],
            config=_CONFIG,
            query_text="what's in Apple's latest 10-K",
        )
        assert [a.canonical_name for a in accepted] == ["Apple Inc."]
        assert [r.rejection_reason for r in rejected] == [REASON_SEC_FORM_FRAGMENT]

    def test_genuine_ticker_k_with_no_form_context_resolves(self) -> None:
        """A real ticker "K" query (no form context) must still resolve to Kellanova."""
        accepted, _ = filter_resolver_candidates(
            [_kellanova()],
            config=_CONFIG,
            query_text="how is Kellanova doing today?",
        )
        assert [a.canonical_name for a in accepted] == ["Kellanova"]

    def test_ticker_k_mentioned_standalone_and_in_form_still_resolves(self) -> None:
        """When the query names BOTH the form and the standalone ticker, K resolves."""
        accepted, _ = filter_resolver_candidates(
            [_kellanova()],
            config=_CONFIG,
            query_text="how is K doing after its 10-K?",
        )
        assert [a.canonical_name for a in accepted] == ["Kellanova"]

    def test_no_form_no_guard_noop(self) -> None:
        """Ordinary ticker query is completely unaffected by the guard."""
        accepted, rejected = filter_resolver_candidates(
            [_apple()], config=_CONFIG, query_text="what is AAPL trading at?"
        )
        assert [a.canonical_name for a in accepted] == ["Apple Inc."]
        assert rejected == []


class TestIsSecFormDesignator:
    @pytest.mark.parametrize(
        "token",
        [
            "10-K",
            "10-Q",
            "8-K",
            "6-K",
            "11-K",
            "20-F",
            "40-F",
            "S-1",
            "S-3",
            "F-1",
            "DEF 14A",
            "DEFA14A",
            "424B3",
            "13F",
            "13F-HR",
            "SC 13D",
            "SC 13G",
        ],
    )
    def test_recognises_form_designators(self, token: str) -> None:
        assert is_sec_form_designator(token) is True

    @pytest.mark.parametrize("token", ["AAPL", "K", "TSLA", "BRK.B", "Kellanova", "", "10", "form"])
    def test_rejects_non_forms(self, token: str) -> None:
        assert is_sec_form_designator(token) is False
