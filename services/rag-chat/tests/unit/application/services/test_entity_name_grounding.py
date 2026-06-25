"""Tests for ``EntityNameGroundingValidator`` (F-LIVE-NEW-002).

Sibling test module to ``test_numeric_grounding.py`` — same shape, same
conventions. Covers the canonical hallucination this validator was
built to catch: the empty-result branch in the chat orchestrator
previously substituted ServiceNow for a Tesla question; the validator
must surface "ServiceNow" as ungrounded when it is not in the resolved
entity set or any tool-result payload.
"""

from __future__ import annotations

import pytest
from rag_chat.application.services.entity_name_grounding import (
    EntityNameGroundingValidator,
    NameKind,
)

pytestmark = pytest.mark.unit


class TestEntityNameGroundingValidator:
    def setup_method(self) -> None:
        self.v = EntityNameGroundingValidator()

    def test_grounded_entity_passes(self) -> None:
        """Tesla mentioned + Tesla in grounded set → passes."""
        result = self.v.validate(
            response="Tesla reported strong Q2 deliveries.",
            grounded_entity_names={"Tesla Inc", "Tesla", "TSLA"},
            tool_result_entity_refs={"tesla"},
        )
        assert result.passed, result.unsupported

    def test_ungrounded_entity_fails(self) -> None:
        """ServiceNow not in grounded set → fails (F-LIVE-NEW-002 regression)."""
        result = self.v.validate(
            response="ServiceNow is a leading enterprise software provider.",
            grounded_entity_names={"Tesla Inc", "Tesla", "TSLA"},
            tool_result_entity_refs={"tesla"},
        )
        assert not result.passed
        # The validator should surface ServiceNow as ungrounded.
        assert any("servicenow" in u.normalized for u in result.unsupported), result.unsupported

    def test_country_proper_noun_ignored(self) -> None:
        """'United States' is a stop-noun — not flagged even though absent."""
        result = self.v.validate(
            response="Tesla operates primarily in the United States and China.",
            grounded_entity_names={"Tesla Inc", "Tesla", "TSLA"},
            tool_result_entity_refs=set(),
        )
        # United States / China are stop-nouns → not in unsupported.
        assert all("united states" not in u.normalized for u in result.unsupported)
        assert all("china" not in u.normalized for u in result.unsupported)

    def test_ticker_normalisation(self) -> None:
        """$TSLA in response matches TSLA in grounded set."""
        result = self.v.validate(
            response="The $TSLA chart shows momentum.",
            grounded_entity_names={"TSLA", "Tesla"},
            tool_result_entity_refs=set(),
        )
        assert result.passed, result.unsupported

    def test_alias_match(self) -> None:
        """'Tesla Motors' in response matches 'Tesla' in grounded set via substring."""
        result = self.v.validate(
            response="Tesla Motors leads the EV market.",
            grounded_entity_names={"Tesla"},
            tool_result_entity_refs=set(),
        )
        # "tesla" ⊂ "tesla motors" → loose substring acceptance kicks in.
        assert result.passed, result.unsupported

    def test_corporate_suffix_stripping(self) -> None:
        """'Apple Inc.' in grounded matches 'Apple' in response."""
        result = self.v.validate(
            response="Apple unveiled the next iPhone.",
            grounded_entity_names={"Apple Inc."},
            tool_result_entity_refs=set(),
        )
        assert result.passed, result.unsupported

    def test_multiple_ungrounded_entities_all_listed(self) -> None:
        """When 2 ungrounded companies appear, both are surfaced."""
        result = self.v.validate(
            response="ServiceNow and Snowflake both reported strong earnings.",
            grounded_entity_names={"Tesla", "TSLA"},
            tool_result_entity_refs=set(),
        )
        assert not result.passed
        names = {u.normalized for u in result.unsupported}
        assert "servicenow" in names or any("servicenow" in n for n in names)
        assert "snowflake" in names or any("snowflake" in n for n in names)

    def test_empty_grounded_set_flags_any_company(self) -> None:
        """With no grounded entities, any company-shaped token fails closed."""
        result = self.v.validate(
            response="Microsoft reported revenue.",
            grounded_entity_names=set(),
            tool_result_entity_refs=set(),
        )
        # Microsoft is COMPANY (fail-closed) → must be in unsupported.
        assert not result.passed
        assert any("microsoft" in u.normalized for u in result.unsupported)

    def test_citation_markers_stripped(self) -> None:
        """[N7] inside the response is not misread as a company name."""
        result = self.v.validate(
            response="Tesla revenue grew [N3] year over year.",
            grounded_entity_names={"Tesla"},
            tool_result_entity_refs=set(),
        )
        assert result.passed, result.unsupported

    def test_classifier_company_vs_ticker(self) -> None:
        """Plain TSLA → TICKER; 'Tesla Inc' → COMPANY."""
        from rag_chat.application.services.entity_name_grounding import _classify_kind

        assert _classify_kind("TSLA") is NameKind.TICKER
        assert _classify_kind("Tesla Inc") is NameKind.COMPANY

    def test_possessive_tesla_apostrophe_s_matches_grounded_tesla(self) -> None:
        """PLAN-0104 W47 regression — possessive ``Tesla's`` must NOT be flagged.

        Round 7 v2 Q4 (TSLA gross-margin trend) failed because the COMPANY
        regex captured ``Tesla's`` (with the apostrophe-S) and the lookup
        against ``{"tesla","tsla"}`` missed.  The validator then routed the
        possessive into the rewrite prompt's unsupported-candidate list,
        and the LLM dutifully echoed it in a refusal text overwriting a
        correct streamed answer.  After v1.8 ``_normalize`` strips trailing
        ``'s`` so the possessive form normalises to the canonical entity.
        """
        result = self.v.validate(
            response="Tesla's gross margin trended up steadily over the year.",
            grounded_entity_names={"Tesla", "TSLA"},
            tool_result_entity_refs=set(),
        )
        assert result.passed, [u.name for u in result.unsupported]

    def test_discourse_token_here_not_flagged(self) -> None:
        """PLAN-0104 W47 regression — ``Here`` is a discourse marker, not an entity.

        Round 7 v2 Q4 streamed "Here is the quarterly progression…" and the
        sentence-leading ``Here`` was captured as a COMPANY candidate by
        the title-cased regex.  v1.8 adds the discourse-token expansion to
        the stop-noun list so framing words at sentence start drop out
        before set-membership lookup.
        """
        result = self.v.validate(
            response="Tesla's gross margin has improved. Here is the trend: Q1 16.31%, Q2 17.24%.",
            grounded_entity_names={"Tesla", "TSLA"},
            tool_result_entity_refs=set(),
        )
        # Both "Tesla's" (via apostrophe-S normalisation) and "Here" (via
        # discourse stop-noun) must drop out; the candidate set must NOT
        # produce a refusal.
        assert result.passed, [u.name for u in result.unsupported]
        # And specifically, "Here" must not appear as a candidate at all.
        assert not any(u.normalized == "here" for u in result.unsupported)


class TestBP670HeadingAndToolTextGrounding:
    """BP-670 — live Apple-news false positives (2026-06-11).

    The validator flagged 19 "ungrounded entities" in a correctly-cited news
    answer: markdown section headings ("Recent Headlines", "Product
    Launches", "Siri Overhaul") parsed as COMPANY candidates, and proper
    nouns the LLM copied verbatim from retrieved article titles ("Morgan
    Stanley", "Siri") missing from the structured grounded set. The repair
    rewrite then timed out (+15s) and the user got the
    "validator timeout" banner on a good answer.
    """

    def test_month_abbreviations_are_stop_nouns(self) -> None:
        """BP-670: '(Jun 10)' date stamps must not yield a 'Jun' COMPANY candidate."""
        validator = EntityNameGroundingValidator()
        response = "Apple EU AI Delay Puts Spotlight on Valuation *(Jun 10)* and more *(Sept 3)*."
        result = validator.validate(response, {"Apple Inc", "AAPL", "Apple", "EU AI Delay Puts Spotlight"})
        assert all(u.name not in ("Jun", "Sept") for u in result.unsupported), [u.name for u in result.unsupported]

    def test_markdown_heading_lines_are_not_entity_candidates(self) -> None:
        validator = EntityNameGroundingValidator()
        response = (
            "### Apple News Roundup\n"
            "**Recent Headlines & Developments**\n"
            "**Key Catalysts to Watch:**\n"
            "Apple shipped a new product this quarter.\n"
        )
        result = validator.validate(response, {"Apple Inc", "AAPL", "Apple"})
        assert result.passed, [u.name for u in result.unsupported]

    def test_inline_bold_inside_sentence_is_still_validated(self) -> None:
        """Only WHOLE-line bold headings are stripped — inline bold still checks."""
        validator = EntityNameGroundingValidator()
        response = "The filing shows **Hallucinated Globocorp** beat estimates."
        result = validator.validate(response, {"Apple Inc"})
        assert not result.passed
        assert any("Globocorp" in u.name for u in result.unsupported)

    def test_tool_text_verbatim_name_is_grounded(self) -> None:
        """A name copied straight out of a retrieved article title is grounded."""
        validator = EntityNameGroundingValidator()
        response = "Morgan Stanley warns that Siri may be held back by aging devices."
        tool_text = "Apple's AI Siri will be held back by aging devices, Morgan Stanley says"
        result = validator.validate(response, {"Apple Inc", "AAPL"}, tool_text=tool_text)
        assert result.passed, [u.name for u in result.unsupported]

    def test_name_absent_from_tool_text_still_flagged(self) -> None:
        """tool_text must not weaken the check for genuinely invented names."""
        validator = EntityNameGroundingValidator()
        response = "Hallucinated Globocorp announced a merger."
        tool_text = "Apple's AI Siri will be held back by aging devices, Morgan Stanley says"
        result = validator.validate(response, {"Apple Inc", "AAPL"}, tool_text=tool_text)
        assert not result.passed
        assert any("Globocorp" in u.name for u in result.unsupported)
