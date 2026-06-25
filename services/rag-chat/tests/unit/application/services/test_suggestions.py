"""Tests for server-derived follow-up suggestions (suggestions SSE event).

Derivation is deterministic (no LLM call) from the turn's resolved entities
+ executed tool names. Contract: ALWAYS exactly 3 strings.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from rag_chat.application.services.suggestions import derive_followup_suggestions

pytestmark = pytest.mark.unit


def _entity(name: str, ticker: str | None = None) -> Any:
    e = MagicMock()
    e.canonical_name = name
    e.ticker = ticker
    return e


class TestDeriveFollowupSuggestions:
    def test_always_returns_exactly_three(self) -> None:
        for entities, tools in [
            ([], []),
            ([_entity("Apple Inc.", "AAPL")], []),
            ([_entity("Apple Inc.", "AAPL"), _entity("Microsoft", "MSFT")], ["get_price_history"]),
        ]:
            assert len(derive_followup_suggestions(entities, tools)) == 3

    def test_entity_suggestions_mention_the_entity(self) -> None:
        suggestions = derive_followup_suggestions([_entity("Apple Inc.", "AAPL")], ["get_entity_intelligence"])
        assert any("Apple Inc." in s or "AAPL" in s for s in suggestions)

    def test_orthogonal_data_preferred_over_already_seen(self) -> None:
        """A turn that already used news tools should NOT lead with a news follow-up."""
        suggestions = derive_followup_suggestions([_entity("Apple Inc.", "AAPL")], ["get_entity_news"])
        assert "What's the latest news on Apple Inc.?" != suggestions[0]

    def test_two_entities_produce_comparison_suggestion(self) -> None:
        suggestions = derive_followup_suggestions(
            [_entity("Apple Inc.", "AAPL"), _entity("Microsoft Corporation", "MSFT")],
            [],
        )
        assert any("Compare" in s for s in suggestions)

    def test_no_entities_falls_back_to_generic(self) -> None:
        suggestions = derive_followup_suggestions([], ["search_documents"])
        assert len(suggestions) == 3
        assert "What are today's biggest market movers?" in suggestions

    def test_portfolio_intent_leads_with_portfolio_suggestion(self) -> None:
        suggestions = derive_followup_suggestions([], [], intent="PORTFOLIO")
        assert suggestions[0] == "Which of my holdings carry the most risk right now?"

    def test_entities_without_names_degrade_to_generic(self) -> None:
        suggestions = derive_followup_suggestions([_entity("", None)], [])
        assert len(suggestions) == 3
