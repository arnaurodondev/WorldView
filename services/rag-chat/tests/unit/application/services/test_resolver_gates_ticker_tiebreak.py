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
