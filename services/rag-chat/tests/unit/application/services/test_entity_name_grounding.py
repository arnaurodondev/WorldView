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
