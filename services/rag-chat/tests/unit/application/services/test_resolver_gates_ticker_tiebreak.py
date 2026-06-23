"""BP-661 regression — query-ticker tiebreak in the shared resolver gate.

The "what is AAPL?" bug: S6 returned a BP-459 phantom twin ("AAPL Stock",
sim 0.95) and the real canonical ("Apple Inc.", sim 0.90) — both above the
0.75 floor but within the 0.15 delta window, so the gate rejected BOTH and
the turn proceeded with zero resolved entities. The LLM then passed the raw
string "AAPL" as entity_id, the intelligence tool returned empty, and the
user saw "I cannot find a matching entity".

The fix: when the query literally contains a candidate's ticker as a token,
that candidate wins the delta tie — preferring candidates whose canonical
name does NOT embed the ticker (phantom-shape filter).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rag_chat.application.services.resolver_gates import (
    ACCEPTED_QUERY_TICKER_MATCH,
    REASON_DELTA_BELOW_THRESHOLD,
    GatedEntity,
    ResolverGateConfig,
    filter_resolver_candidates,
)

_CONFIG = ResolverGateConfig(stop_words=frozenset({"stock", "the", "a"}), top_similarity_min=0.75, delta_min=0.15)

_APPLE_ID = "01900000-0000-7000-8000-000000001001"
_PHANTOM_ID = "52a92aa8-750e-4b97-8838-521ce2ce9f74"


def _apple() -> GatedEntity:
    return GatedEntity(entity_id=_APPLE_ID, canonical_name="Apple Inc.", similarity=0.90, ticker="AAPL")


def _phantom() -> GatedEntity:
    return GatedEntity(entity_id=_PHANTOM_ID, canonical_name="AAPL Stock", similarity=0.95, ticker="AAPL")


class TestQueryTickerTiebreak:
    def test_aapl_query_resolves_real_canonical_over_phantom_twin(self) -> None:
        """The exact live failure: phantom twin outranks Apple Inc. on similarity.

        Both carry ticker=AAPL; the phantom embeds the ticker in its name so
        the phantom-shape filter must pick Apple Inc. despite lower similarity.
        """
        accepted, rejected = filter_resolver_candidates(
            [_phantom(), _apple()],
            config=_CONFIG,
            query_text="In one short sentence, what is AAPL?",
        )
        assert len(accepted) == 1
        assert accepted[0].entity_id == _APPLE_ID
        assert accepted[0].accepted_reason == ACCEPTED_QUERY_TICKER_MATCH
        # The phantom is rejected with the delta reason (auditable).
        assert [r.entity_id for r in rejected] == [_PHANTOM_ID]
        assert rejected[0].rejection_reason == REASON_DELTA_BELOW_THRESHOLD

    def test_no_ticker_in_query_still_rejects_all_as_ambiguous(self) -> None:
        """Legacy behaviour preserved: delta-ambiguous + no ticker token → reject all."""
        accepted, rejected = filter_resolver_candidates(
            [_phantom(), _apple()],
            config=_CONFIG,
            query_text="what is the iphone maker doing?",
        )
        assert accepted == []
        assert {r.rejection_reason for r in rejected} == {REASON_DELTA_BELOW_THRESHOLD}

    def test_query_text_none_keeps_legacy_behaviour(self) -> None:
        """Callers that do not pass query_text get byte-identical legacy gating."""
        accepted, rejected = filter_resolver_candidates([_phantom(), _apple()], config=_CONFIG)
        assert accepted == []
        assert len(rejected) == 2

    def test_ticker_match_is_token_level_not_substring(self) -> None:
        """'AAPLE' in the query must NOT match ticker AAPL (no substring matching)."""
        accepted, _ = filter_resolver_candidates(
            [_phantom(), _apple()],
            config=_CONFIG,
            query_text="tell me about AAPLE",
        )
        assert accepted == []

    def test_ticker_match_is_case_insensitive_and_strips_punctuation(self) -> None:
        """'aapl?' (lowercase + trailing punctuation) still matches ticker AAPL."""
        accepted, _ = filter_resolver_candidates(
            [_phantom(), _apple()],
            config=_CONFIG,
            query_text="what is aapl?",
        )
        assert len(accepted) == 1
        assert accepted[0].entity_id == _APPLE_ID

    def test_all_phantom_shaped_matches_still_resolve_highest_similarity(self) -> None:
        """When EVERY ticker match embeds the ticker, take the highest-similarity one.

        Resolving to a phantom twin still beats refusing outright — the twin
        may carry a narrative; refusal guarantees the 'cannot find' answer.
        """
        twin_a = GatedEntity(
            entity_id="a" * 8 + "-0000-0000-0000-000000000001",
            canonical_name="AAPL Stock",
            similarity=0.95,
            ticker="AAPL",
        )
        twin_b = GatedEntity(
            entity_id="b" * 8 + "-0000-0000-0000-000000000002", canonical_name="AAPL.US", similarity=0.90, ticker="AAPL"
        )
        accepted, _ = filter_resolver_candidates([twin_a, twin_b], config=_CONFIG, query_text="what is AAPL?")
        assert len(accepted) == 1
        assert accepted[0].entity_id == twin_a.entity_id

    def test_xml_wrapped_validated_message_still_matches_ticker(self) -> None:
        """The orchestrator passes the InputValidator-wrapped message.

        Live failure (2026-06-10): ``<Q_abc12345>...what is AAPL?</Q_abc12345>``
        made the trailing token ``aapl?</q_abc12345>`` so the ticker never
        matched and the gate still rejected both candidates. The gate must
        unwrap the envelope before tokenising.
        """
        accepted, _ = filter_resolver_candidates(
            [_phantom(), _apple()],
            config=_CONFIG,
            query_text="<Q_deadbeef>In one short sentence, what is AAPL?</Q_deadbeef>",
        )
        assert len(accepted) == 1
        assert accepted[0].entity_id == _APPLE_ID

    def test_dotted_class_share_ticker_matches(self) -> None:
        """Dotted tickers (BRK.B) survive tokenisation as a single token."""
        brk = GatedEntity(entity_id=_APPLE_ID, canonical_name="Berkshire Hathaway", similarity=0.90, ticker="BRK.B")
        twin = GatedEntity(entity_id=_PHANTOM_ID, canonical_name="BRK.B Stock", similarity=0.95, ticker="BRK.B")
        accepted, _ = filter_resolver_candidates(
            [twin, brk],
            config=_CONFIG,
            query_text="what is BRK.B?",
        )
        assert len(accepted) == 1
        assert accepted[0].entity_id == _APPLE_ID

    def test_unambiguous_results_do_not_invoke_tiebreak(self) -> None:
        """Clear delta (>0.15) keeps both candidates accepted, no tiebreak reason set."""
        clear_apple = GatedEntity(entity_id=_APPLE_ID, canonical_name="Apple Inc.", similarity=0.98, ticker="AAPL")
        weak_other = GatedEntity(
            entity_id=_PHANTOM_ID, canonical_name="Applied Materials", similarity=0.78, ticker="AMAT"
        )
        accepted, rejected = filter_resolver_candidates(
            [clear_apple, weak_other],
            config=_CONFIG,
            query_text="what is AAPL?",
        )
        assert len(accepted) == 2
        assert all(a.accepted_reason == "" for a in accepted)
        assert rejected == []


class TestBP668CommonWordHijack:
    """BP-668 regression — lowercase English words must not act as ticker evidence.

    Live failures (2026-06-11):
      * "What is BTC-USD trading at right **now**?" → NOW → ServiceNow Inc
      * "What's the latest news **on** Apple Inc.?" → ON  → ON Semiconductor
    The hijacked resolution then poisoned the BP-605 grounding gate
    (question_entity_ids = ServiceNow) which REPLACED a correct streamed
    price answer with the "data returned referenced different entities"
    refusal, and the suggestions builder advertised the hijacker entity.
    """

    def _servicenow(self, sim: float = 0.95) -> GatedEntity:
        return GatedEntity(
            entity_id="8be3d480-46fd-41a9-9ec0-ea94c84b7022",
            canonical_name="ServiceNow Inc",
            similarity=sim,
            ticker="NOW",
        )

    def _btc_usd(self, sim: float = 0.90) -> GatedEntity:
        return GatedEntity(
            entity_id="019e0db3-6c19-77b6-86c4-43fa2dd47b49",
            canonical_name="BTC-USD",
            similarity=sim,
            ticker="BTC-USD",
        )

    def test_lowercase_now_does_not_resolve_servicenow(self) -> None:
        """The exact BTC-USD live failure: 'right now' must not match ticker NOW."""
        accepted, rejected = filter_resolver_candidates(
            [self._servicenow(), GatedEntity(entity_id=_APPLE_ID, canonical_name="Bitcoin", similarity=0.92)],
            config=_CONFIG,
            query_text="What is something trading at right now?",
        )
        # No ticker evidence → legacy ambiguous bail (reject all), NOT a
        # hijacked ServiceNow resolution.
        assert accepted == []
        assert {r.rejection_reason for r in rejected} == {REASON_DELTA_BELOW_THRESHOLD}

    def test_lowercase_on_does_not_resolve_on_semiconductor(self) -> None:
        """The Apple-news live failure: 'news on Apple' must not match ticker ON."""
        on_semi = GatedEntity(
            entity_id="3f9abc7b-4346-4d48-8556-d67d079bfbe9",
            canonical_name="ON Semiconductor Corp.",
            similarity=0.95,
            ticker="ON",
        )
        apple = GatedEntity(entity_id=_APPLE_ID, canonical_name="Apple Inc.", similarity=0.90, ticker="AAPL")
        accepted, _ = filter_resolver_candidates(
            [on_semi, apple],
            config=_CONFIG,
            query_text="What's the latest news on Apple Inc.?",
        )
        assert all(a.canonical_name != "ON Semiconductor Corp." for a in accepted)

    def test_uppercase_now_still_resolves_servicenow(self) -> None:
        """Explicit caps is explicit intent: 'what is NOW trading at?' means the ticker."""
        other = GatedEntity(entity_id=_APPLE_ID, canonical_name="Now Foods LLC", similarity=0.90)
        accepted, _ = filter_resolver_candidates(
            [self._servicenow(), other],
            config=_CONFIG,
            query_text="what is NOW trading at?",
        )
        assert len(accepted) == 1
        assert accepted[0].canonical_name == "ServiceNow Inc"
        assert accepted[0].accepted_reason == ACCEPTED_QUERY_TICKER_MATCH

    def test_hyphenated_crypto_pair_wins_tiebreak(self) -> None:
        """BTC-USD (name == ticker) must win the tie, not be phantom-penalised.

        Live failure compounded two bugs: (a) lowercase 'now' matched
        ServiceNow, and (b) the phantom-shape filter penalised the real
        'BTC-USD' canonical because its NAME embeds its own ticker — for
        crypto/FX pairs the ticker IS the canonical name.
        """
        accepted, _ = filter_resolver_candidates(
            [self._servicenow(), self._btc_usd()],
            config=_CONFIG,
            query_text="What is BTC-USD trading at right now?",
        )
        assert len(accepted) == 1
        assert accepted[0].canonical_name == "BTC-USD"
        # "BTC-USD" is both the canonical NAME and the ticker; the verbatim
        # name tiebreak fires first (stronger evidence, same winner).
        assert accepted[0].accepted_reason in (ACCEPTED_QUERY_TICKER_MATCH, "query_name_exact_match")

    def test_name_equals_ticker_beats_embedding_phantom(self) -> None:
        """'BTC-USD' (name==ticker) outranks 'BTC-USD Pair' (embeds ticker + noise)."""
        phantom = GatedEntity(
            entity_id=_PHANTOM_ID,
            canonical_name="BTC-USD Pair",
            similarity=0.95,
            ticker="BTC-USD",
        )
        accepted, _ = filter_resolver_candidates(
            [phantom, self._btc_usd(sim=0.90)],
            config=_CONFIG,
            query_text="price of BTC-USD?",
        )
        assert len(accepted) == 1
        assert accepted[0].canonical_name == "BTC-USD"


class TestFinancialAcronymFragmentsNotTickers:
    """BP-661 P/E→Pandora (2026-06-12) — ratio fragments must not match tickers.

    Live failure (``da_aapl_pe_dec2024``): "What was AAPL's P/E ratio as of
    December 31, 2024?" tokenised "P/E" into "P" (uppercase, ticker-shaped),
    which exactly matched ticker "P" → Pandora. Pandora was ranked #1 and
    overrode the LLM's correct AAPL. The gate must reject single-letter
    fragments and financial-ratio acronyms (P/E, EPS, ROE, …) as ticker
    evidence regardless of case.
    """

    def _pandora(self) -> GatedEntity:
        return GatedEntity(
            entity_id="f5d35022-0000-7000-8000-000000000abc",
            canonical_name="Pandora A/S",
            similarity=0.95,
            ticker="P",
        )

    def _apple(self) -> GatedEntity:
        return GatedEntity(entity_id=_APPLE_ID, canonical_name="Apple Inc.", similarity=0.90, ticker="AAPL")

    def test_pe_fragment_does_not_resolve_pandora(self) -> None:
        """The exact live failure: 'P/E' must not match ticker P (Pandora).

        The Pandora candidate must never win the tiebreak. With the "P"
        fragment excluded the pair is delta-ambiguous with no ticker evidence,
        so the gate bails (reject all) — the orchestrator then proceeds with no
        wrong entity and the LLM's AAPL is honoured tool-side.
        """
        accepted, _ = filter_resolver_candidates(
            [self._pandora(), self._apple()],
            config=_CONFIG,
            query_text="What was the P/E ratio of AAPL as of December 31, 2024?",
        )
        # AAPL still resolves (real ticker token present); Pandora never does.
        assert all(a.canonical_name != "Pandora A/S" for a in accepted)
        assert [a.entity_id for a in accepted] == [_APPLE_ID]

    def test_query_ticker_tokens_excludes_pe_fragments_and_acronyms(self) -> None:
        from rag_chat.application.services.resolver_gates import _query_ticker_tokens

        tokens = _query_ticker_tokens("What is the P/E, EPS, ROE and P/B of AAPL versus MSFT?")
        # Real tickers survive; ratio fragments/acronyms do not.
        assert "aapl" in tokens
        assert "msft" in tokens
        for fragment in ("p", "e", "b", "pe", "eps", "roe", "pb"):
            assert fragment not in tokens

    def test_single_letter_uppercase_token_is_not_ticker_evidence(self) -> None:
        """A bare single uppercase letter is too ambiguous to win a tiebreak."""
        from rag_chat.application.services.resolver_gates import _query_ticker_tokens

        assert _query_ticker_tokens("Compare F and T performance") == set()

    def test_real_two_letter_ticker_still_matches(self) -> None:
        """Guard rails: a genuine 2+ letter uppercase ticker still counts (GE)."""
        from rag_chat.application.services.resolver_gates import _query_ticker_tokens

        assert "ge" in _query_ticker_tokens("How is GE doing this quarter?")

    def test_lowercase_non_word_ticker_still_matches(self) -> None:
        """BP-661 convenience preserved: lowercase 'aapl' is not an English word."""
        accepted, _ = filter_resolver_candidates(
            [_phantom(), _apple()],
            config=_CONFIG,
            query_text="what is aapl?",
        )
        assert len(accepted) == 1
        assert accepted[0].entity_id == _APPLE_ID


class TestQueryNameTiebreak:
    """BP-668 — verbatim canonical-name tiebreak (the Apple-news anchor loss).

    After the common-word fix, "latest news on Apple Inc.?" no longer
    hijacked to ON Semiconductor — but the delta gate then rejected BOTH
    candidates (ON Semi 0.95 vs Apple 0.90, no ticker token in the query)
    and the turn lost its entity anchor entirely. The query literally names
    "Apple Inc." — that exact-name evidence must win the tie.
    """

    def _apple_inc(self) -> GatedEntity:
        return GatedEntity(entity_id=_APPLE_ID, canonical_name="Apple Inc.", similarity=0.90, ticker="AAPL")

    def _on_semi(self) -> GatedEntity:
        return GatedEntity(
            entity_id="3f9abc7b-4346-4d48-8556-d67d079bfbe9",
            canonical_name="ON Semiconductor Corp.",
            similarity=0.95,
            ticker="ON",
        )

    def test_verbatim_name_wins_over_higher_similarity(self) -> None:
        from rag_chat.application.services.resolver_gates import ACCEPTED_QUERY_NAME_MATCH

        accepted, rejected = filter_resolver_candidates(
            [self._on_semi(), self._apple_inc()],
            config=_CONFIG,
            query_text="What's the latest news on Apple Inc.?",
        )
        assert len(accepted) == 1
        assert accepted[0].entity_id == _APPLE_ID
        assert accepted[0].accepted_reason == ACCEPTED_QUERY_NAME_MATCH
        assert [r.canonical_name for r in rejected] == ["ON Semiconductor Corp."]

    def test_name_match_requires_word_boundaries(self) -> None:
        """'Applesauce Inc.' in the query must NOT match 'Apple Inc.'."""
        accepted, _ = filter_resolver_candidates(
            [self._on_semi(), self._apple_inc()],
            config=_CONFIG,
            query_text="latest news about Applesauce Inc. earnings",
        )
        assert accepted == []

    def test_two_distinct_names_in_query_is_ambiguous(self) -> None:
        """Comparison queries naming both candidates fall through to reject."""
        msft = GatedEntity(
            entity_id=_PHANTOM_ID, canonical_name="Microsoft Corporation", similarity=0.92, ticker="MSFT"
        )
        accepted, _ = filter_resolver_candidates(
            [msft, self._apple_inc()],
            config=_CONFIG,
            query_text="Compare Apple Inc. against Microsoft Corporation on margins",
        )
        assert accepted == []

    def test_short_or_common_word_names_never_match(self) -> None:
        """A hypothetical entity named 'Now' must not re-open the BP-668 hijack."""
        now_entity = GatedEntity(entity_id=_PHANTOM_ID, canonical_name="Now", similarity=0.95)
        other = GatedEntity(entity_id=_APPLE_ID, canonical_name="Bitcoin", similarity=0.92)
        accepted, _ = filter_resolver_candidates(
            [now_entity, other],
            config=_CONFIG,
            query_text="what is trading well right now?",
        )
        assert all(a.canonical_name != "Now" for a in accepted)
