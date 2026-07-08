"""Chat answer-composition fix regressions — 2026-07-08 two-track audit.

Covers the deterministic composition/sanitiser helpers added to
``chat_orchestrator.py`` for the D-series + Track-3 defects
(docs/plans/2026-07-08-chat-quality-two-track-audit.md):

  * D-a — phantom / non-registered citation-tag hard veto: ``[c9]`` payload
    ids, ``[REDACTED]`` placeholders, ``[tool row N]`` tags (incl. the
    narrow-no-break-space variant) and stray plain ``[n]`` with no backing
    citation are stripped, while valid ``[n]`` markers and genuine
    non-citation brackets survive.
  * D-c — a tool result reported as ``status:ok items>=1`` must never be
    described as "no data / no link / empty".
  * D-f — a runaway repeated-line / repeated-sentence decode loop is collapsed.
  * D-g — a refusal is bound to the RESOLVED entity of the current turn.
  * Track-3 — the "some figures could not be matched" caveat is absent on a
    fully-grounded answer.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from rag_chat.application.use_cases.chat_orchestrator import (
    _answer_has_bracket_citation_coverage,
    _bind_refusal_to_resolved_entity,
    _collapse_runaway_repetition,
    _falsely_claims_empty_result,
    _is_wholesale_refusal,
    _sanitize_unverified_markers,
    _strip_non_registered_citation_tags,
)

pytestmark = pytest.mark.unit


@dataclass
class _Ent:
    """Minimal resolved-entity stand-in (name + optional ticker)."""

    canonical_name: str
    ticker: str | None = None


# ── D-a: phantom / non-registered citation-tag hard veto ─────────────────────


class TestStripNonRegisteredCitationTags:
    def test_payload_embedded_c9_tag_stripped(self) -> None:
        text = "Markets rallied [c9] on strong data [1]."
        out, count = _strip_non_registered_citation_tags(text, {1})
        assert "[c9]" not in out
        assert "[1]" in out  # valid registered citation survives
        assert count == 1

    def test_redacted_placeholder_stripped(self) -> None:
        text = "The executive [REDACTED] said the deal closed [1]."
        out, count = _strip_non_registered_citation_tags(text, {1})
        assert "[REDACTED]" not in out
        assert "[1]" in out
        assert count == 1

    def test_tool_row_tag_for_empty_tool_stripped(self) -> None:
        # A [tool row N] tag misattributed to a tool that returned 0 rows.
        text = "NVDA leads AI infra [search_documents row 7]. AVGO follows [1]."
        out, count = _strip_non_registered_citation_tags(text, {1})
        assert "search_documents row 7" not in out
        assert "[1]" in out
        assert count == 1

    def test_narrow_no_break_space_row_tag_stripped(self) -> None:
        # The narrow-no-break-space (U+202F) "row 7" variant the ASCII \\s
        # regexes upstream miss must still be stripped here. Built from the
        nb = chr(0x202F)
        text = f"Data point [search_documents{nb}row{nb}7] and [1]."
        out, count = _strip_non_registered_citation_tags(text, {1})
        assert "search_documents" not in out
        assert "[1]" in out
        assert count == 1

    def test_stray_plain_orphan_marker_stripped(self) -> None:
        text = "Claim A [1] and unbacked claim [9]."
        out, count = _strip_non_registered_citation_tags(text, {1})
        assert "[9]" not in out
        assert "[1]" in out
        assert count == 1

    def test_genuine_non_citation_brackets_preserved(self) -> None:
        text = "See [docs](http://x) for [FY2024], the year [2026] and a [note] [1]."
        out, count = _strip_non_registered_citation_tags(text, {1})
        assert out == text
        assert count == 0

    def test_uppercase_period_label_preserved(self) -> None:
        # [Q1]/[H2] are financial period labels, NOT payload citation ids.
        text = "Q1 growth [Q1] beat H2 [H2] and cite [1]."
        out, count = _strip_non_registered_citation_tags(text, {1})
        assert "[Q1]" in out and "[H2]" in out
        assert count == 0

    def test_no_brackets_is_noop(self) -> None:
        text = "A plain answer with no brackets at all."
        out, count = _strip_non_registered_citation_tags(text, {1, 2})
        assert out == text
        assert count == 0


# ── D-c: false "no data / empty result" claim guard ──────────────────────────


class TestFalselyClaimsEmptyResult:
    @pytest.mark.parametrize(
        "text",
        [
            "I checked the sources but no data was found for TSMC.",
            "The screener returned no results for that filter.",
            "There is no link available for that filing.",
            "I was unable to retrieve any figures this turn.",
            "The result was empty, so I have nothing to report.",
        ],
    )
    def test_false_empty_claims_detected(self, text: str) -> None:
        assert _falsely_claims_empty_result(text) is True

    def test_substantive_answer_not_flagged(self) -> None:
        # A real, data-backed answer that merely caveats one missing sub-fact.
        text = (
            "TSMC revenue rose 40% to $20B and margins expanded; the only gap is the "
            "segment split, which was not broken out in the retrieved row."
        )
        assert _falsely_claims_empty_result(text) is False

    def test_long_answer_not_flagged(self) -> None:
        assert _falsely_claims_empty_result("no data was found. " + "x" * 400) is False

    def test_disjoint_from_wholesale_marker(self) -> None:
        # The new detector is a companion, not a replacement — the legacy
        # wholesale marker still routes through _is_wholesale_refusal.
        assert _is_wholesale_refusal("Not available in retrieved context.") is True


# ── D-f: runaway decode-loop guard ───────────────────────────────────────────


class TestCollapseRunawayRepetition:
    def test_repeated_line_loop_collapsed(self) -> None:
        text = "\n".join(["I'll start by identifying the key suppliers."] * 200)
        out, hit = _collapse_runaway_repetition(text)
        assert hit is True
        assert out.count("identifying the key suppliers") == 1

    def test_repeated_sentence_loop_collapsed(self) -> None:
        text = "I will identify the suppliers now. " * 40
        out, hit = _collapse_runaway_repetition(text)
        assert hit is True
        assert out.count("identify the suppliers now") == 1

    def test_normal_answer_is_noop(self) -> None:
        text = (
            "NVIDIA's key suppliers include TSMC for fabrication and SK Hynix for "
            "HBM memory. Supplier health looks stable heading into the next quarter."
        )
        out, hit = _collapse_runaway_repetition(text)
        assert hit is False
        assert out == text

    def test_short_repeated_word_not_collapsed(self) -> None:
        # Below the segment-length floor: an ordinary repeated short word must
        # not trip the guard.
        text = "\n".join(["ok"] * 20)
        out, hit = _collapse_runaway_repetition(text)
        assert hit is False
        assert out == text


# ── D-g: refusal bound to the resolved entity ────────────────────────────────


class TestBindRefusalToResolvedEntity:
    def test_wrong_entity_refusal_rebound(self) -> None:
        # A Microsoft question that refused while naming "Five Below".
        entities = [_Ent("Microsoft Corporation", "MSFT")]
        stale = "I couldn't find any relationship data about Five Below for this question."
        out = _bind_refusal_to_resolved_entity(stale, entities)
        assert "Microsoft Corporation" in out
        assert "MSFT" in out
        assert "Five Below" not in out

    def test_generic_refusal_gets_entity_anchor(self) -> None:
        entities = [_Ent("Microsoft Corporation", "MSFT")]
        generic = "I couldn't retrieve any data to answer this question."
        out = _bind_refusal_to_resolved_entity(generic, entities)
        assert "Microsoft Corporation (MSFT)" in out

    def test_correctly_bound_refusal_untouched(self) -> None:
        entities = [_Ent("Microsoft Corporation", "MSFT")]
        good = "I couldn't retrieve MSFT margin data right now — please try again."
        out = _bind_refusal_to_resolved_entity(good, entities)
        assert out == good

    def test_substantive_answer_untouched(self) -> None:
        entities = [_Ent("Microsoft Corporation", "MSFT")]
        answer = "Microsoft's fiscal Q2 revenue grew 15% year over year to a record high."
        out = _bind_refusal_to_resolved_entity(answer, entities)
        assert out == answer

    def test_no_resolved_entity_is_noop(self) -> None:
        stale = "I couldn't find any data about Five Below."
        out = _bind_refusal_to_resolved_entity(stale, [])
        assert out == stale


# ── Track-3: caveat absent on a fully-grounded answer ────────────────────────


class TestGroundedBannerSuppression:
    def test_fully_grounded_answer_has_no_caveat(self) -> None:
        # A grounded answer with a leaked banner: with append_disclaimer=False
        # (the caller passes this when grounding passed / bracket coverage is
        # full) the banner is scrubbed and NO caveat is appended.
        text = (
            "Apple Q2 revenue was $34.6B [get_fundamentals_history row 1].\n\n"
            "⚠ Some numbers could not be verified against retrieved data"
        )
        out = _sanitize_unverified_markers(text, append_disclaimer=False)
        assert "could not be matched to a retrieved source" not in out
        assert "could not be verified" not in out
        assert "$34.6B" in out

    def test_bracket_cited_answer_has_full_coverage(self) -> None:
        cited = "Apple Q2 revenue was $34.6B [get_fundamentals_history row 1]."
        assert _answer_has_bracket_citation_coverage(cited) is True

    def test_prose_only_answer_lacks_bracket_coverage(self) -> None:
        # Prose provenance ("according to the latest filing") is NOT a real
        # bracket citation, so coverage is False → the caveat is NOT suppressed.
        prose = "Apple Q2 revenue was $34.6B according to the latest filing."
        assert _answer_has_bracket_citation_coverage(prose) is False

    def test_ungrounded_answer_keeps_caveat(self) -> None:
        text = "Apple Q2 revenue was $34.6B [unverified]."
        out = _sanitize_unverified_markers(text, append_disclaimer=True)
        assert "could not be matched to a retrieved source" in out
