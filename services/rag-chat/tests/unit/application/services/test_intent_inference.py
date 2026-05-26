"""Tests for ``infer_intent`` (PLAN-0093 Wave E-1 T-E-1-02).

Verifies the priority rules:

1. ``compare_entities`` OR ≥ 2 distinct entity_ids → ``COMPARISON``
2. ``traverse_graph`` OR ``get_entity_paths`` → ``RELATIONSHIP``
3. ``get_fundamentals_history`` OR ``screen_universe`` → ``FINANCIAL_DATA``
4. ``get_economic_calendar`` OR ``get_temporal_events`` → ``MACRO``
5. ``search_documents`` OR ``search_claims`` → ``FACTUAL_LOOKUP``
6. Default → ``GENERAL``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from rag_chat.application.services.intent_inference import infer_intent
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit


# Lightweight tool-call stub — only ``name`` and ``input`` are read.
@dataclass
class _FakeCall:
    name: str
    input: dict[str, Any]


def _call(name: str, **kwargs: Any) -> _FakeCall:
    return _FakeCall(name=name, input=kwargs)


class TestInferIntent:
    def test_compare_entities_implies_COMPARISON(self) -> None:
        assert infer_intent([_call("compare_entities", entity_ids=["a", "b"])]) is QueryIntent.COMPARISON

    def test_two_distinct_entities_implies_COMPARISON(self) -> None:
        """Two single-entity tool calls with different entity_ids → COMPARISON.

        This is the canonical "compare two stocks" pattern — the LLM calls
        get_fundamentals_history twice with different entity_ids rather
        than the dedicated compare_entities tool.
        """
        calls = [
            _call("get_fundamentals_history", entity_id="aaaa-1111"),
            _call("get_fundamentals_history", entity_id="bbbb-2222"),
        ]
        assert infer_intent(calls) is QueryIntent.COMPARISON

    def test_same_entity_id_twice_is_not_COMPARISON(self) -> None:
        """Two tools on the SAME entity → not a comparison.

        Regression guard: cardinality of *distinct* entity_ids, not raw
        call count. Falls through to the single-tool priority ladder —
        ``get_fundamentals_history`` beats ``search_claims`` (priority 3
        vs priority 5), so the inferred intent is FINANCIAL_DATA.
        """
        calls = [
            _call("get_fundamentals_history", entity_id="aaaa-1111"),
            _call("search_claims", entity_id="aaaa-1111"),
        ]
        assert infer_intent(calls) is QueryIntent.FINANCIAL_DATA

    def test_traverse_graph_implies_RELATIONSHIP(self) -> None:
        assert infer_intent([_call("traverse_graph", entity_id="x")]) is QueryIntent.RELATIONSHIP

    def test_get_entity_paths_implies_RELATIONSHIP(self) -> None:
        assert infer_intent([_call("get_entity_paths", entity_id="x")]) is QueryIntent.RELATIONSHIP

    def test_fundamentals_implies_FINANCIAL_DATA(self) -> None:
        assert infer_intent([_call("get_fundamentals_history", entity_id="x")]) is QueryIntent.FINANCIAL_DATA

    def test_screen_universe_implies_FINANCIAL_DATA(self) -> None:
        assert infer_intent([_call("screen_universe", filters={})]) is QueryIntent.FINANCIAL_DATA

    def test_economic_calendar_implies_MACRO(self) -> None:
        assert infer_intent([_call("get_economic_calendar")]) is QueryIntent.MACRO

    def test_temporal_events_implies_MACRO(self) -> None:
        assert infer_intent([_call("get_temporal_events")]) is QueryIntent.MACRO

    def test_search_documents_implies_FACTUAL_LOOKUP(self) -> None:
        assert infer_intent([_call("search_documents", query="x")]) is QueryIntent.FACTUAL_LOOKUP

    def test_search_claims_implies_FACTUAL_LOOKUP(self) -> None:
        assert infer_intent([_call("search_claims", entity_id="x")]) is QueryIntent.FACTUAL_LOOKUP

    def test_empty_tool_calls_default_to_GENERAL(self) -> None:
        assert infer_intent([]) is QueryIntent.GENERAL

    def test_unknown_tool_defaults_to_GENERAL(self) -> None:
        assert infer_intent([_call("some_brand_new_tool")]) is QueryIntent.GENERAL

    def test_relationship_priority_over_factual_lookup(self) -> None:
        """When the LLM mixes graph + doc tools, RELATIONSHIP wins.

        Graph traversal is a stronger signal of user intent than a fallback
        doc search the LLM tossed in as a safety net.
        """
        calls = [
            _call("traverse_graph", entity_id="aaaa"),
            _call("search_documents", query="apple"),
        ]
        assert infer_intent(calls) is QueryIntent.RELATIONSHIP

    def test_comparison_beats_relationship(self) -> None:
        """Compare-entities tool wins over any single-entity intent."""
        calls = [
            _call("compare_entities", entity_ids=["aaaa", "bbbb"]),
            _call("traverse_graph", entity_id="aaaa"),
        ]
        assert infer_intent(calls) is QueryIntent.COMPARISON

    # PLAN-0095 W3 T-W3-02: three new RELATIONSHIP mappings — bundle /
    # narrative tools previously fell through to GENERAL and lost the
    # per-intent prompt addendum.
    def test_get_entity_intelligence_implies_RELATIONSHIP(self) -> None:
        assert infer_intent([_call("get_entity_intelligence", entity_id="x")]) is QueryIntent.RELATIONSHIP

    def test_search_entity_relations_implies_RELATIONSHIP(self) -> None:
        assert infer_intent([_call("search_entity_relations", entity_id="x")]) is QueryIntent.RELATIONSHIP

    def test_get_entity_narrative_implies_RELATIONSHIP(self) -> None:
        assert infer_intent([_call("get_entity_narrative", entity_id="x")]) is QueryIntent.RELATIONSHIP
