"""Unit tests for PathTemplateMatcher application service (T-E1-03)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


def _make_raw_path(
    node_types: tuple[str, ...] = ("company", "company", "company"),
    rel_types: tuple[str, ...] = ("SUPPLIES_TO", "MANUFACTURES_FOR"),
    edge_confs: tuple[float, ...] = (0.8, 0.7),
) -> object:
    from knowledge_graph.infrastructure.age.path_discovery import RawPath

    n = len(node_types)
    return RawPath(
        node_ids=tuple(str(uuid4()) for _ in range(n)),
        node_names=tuple(f"E{i}" for i in range(n)),
        node_types=node_types,
        rel_types=rel_types,
        edge_confs=edge_confs,
    )


def _supply_chain_3hop_template() -> dict:
    return {
        "template_name": "supply_chain_3hop",
        "entity_type_sequence": ["company", "company", "company"],
        "relation_type_sequence": ["SUPPLIES_TO|MANUFACTURES_FOR", "SUPPLIES_TO|MANUFACTURES_FOR"],
    }


def _financial_holding_template() -> dict:
    return {
        "template_name": "financial_holding_chain",
        "entity_type_sequence": ["company", "company", "person"],
        "relation_type_sequence": ["OWNS|ACQUIRED", "EMPLOYED_BY|LEADS"],
    }


class TestPathTemplateMatcher:
    def _make_matcher(self) -> object:
        """Build a PathTemplateMatcher with a mock session factory."""
        from unittest.mock import AsyncMock, MagicMock

        from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher

        session = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=None)
        return PathTemplateMatcher(factory)

    def test_template_matches_supply_chain_3hop(self) -> None:
        """supply_chain_3hop template matches 3-company path with SUPPLIES_TO edges."""
        from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher

        matcher = self._make_matcher()
        assert isinstance(matcher, PathTemplateMatcher)

        raw = _make_raw_path(
            node_types=("company", "company", "company"),
            rel_types=("SUPPLIES_TO", "MANUFACTURES_FOR"),
        )
        templates = [_supply_chain_3hop_template()]
        result = asyncio.run(matcher.match(raw, templates=templates))
        assert result == "supply_chain_3hop"

    def test_template_alternation_or_semantics(self) -> None:
        """Template with 'SUPPLIES_TO|MANUFACTURES_FOR' matches either alternative."""
        from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher

        matcher = self._make_matcher()
        assert isinstance(matcher, PathTemplateMatcher)

        # Use MANUFACTURES_FOR (second alternative)
        raw = _make_raw_path(
            node_types=("company", "company", "company"),
            rel_types=("MANUFACTURES_FOR", "SUPPLIES_TO"),
        )
        templates = [_supply_chain_3hop_template()]
        result = asyncio.run(matcher.match(raw, templates=templates))
        assert result == "supply_chain_3hop"

    def test_template_no_match_returns_none(self) -> None:
        """When no template matches, match() returns None."""
        from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher

        matcher = self._make_matcher()
        assert isinstance(matcher, PathTemplateMatcher)

        raw = _make_raw_path(
            node_types=("company", "fund", "index"),
            rel_types=("INVESTS_IN", "TRACKS"),
        )
        templates = [_supply_chain_3hop_template()]
        result = asyncio.run(matcher.match(raw, templates=templates))
        assert result is None

    def test_template_wrong_entity_type_no_match(self) -> None:
        """A path with wrong entity types does not match even if rel types align."""
        from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher

        matcher = self._make_matcher()
        assert isinstance(matcher, PathTemplateMatcher)

        # Wrong type: person instead of company in second position
        raw = _make_raw_path(
            node_types=("company", "person", "company"),
            rel_types=("SUPPLIES_TO", "SUPPLIES_TO"),
        )
        templates = [_supply_chain_3hop_template()]
        result = asyncio.run(matcher.match(raw, templates=templates))
        assert result is None

    def test_template_wrong_length_no_match(self) -> None:
        """A 3-hop path does not match a 2-hop template."""
        from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher

        matcher = self._make_matcher()
        assert isinstance(matcher, PathTemplateMatcher)

        # 3-hop path (4 nodes, 3 edges)
        raw = _make_raw_path(
            node_types=("company", "company", "company", "company"),
            rel_types=("SUPPLIES_TO", "SUPPLIES_TO", "MANUFACTURES_FOR"),
            edge_confs=(0.8, 0.7, 0.6),
        )
        templates = [_supply_chain_3hop_template()]
        result = asyncio.run(matcher.match(raw, templates=templates))
        assert result is None

    def test_financial_holding_template_matches(self) -> None:
        """financial_holding_chain template matches company→company→person paths."""
        from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher

        matcher = self._make_matcher()
        assert isinstance(matcher, PathTemplateMatcher)

        raw = _make_raw_path(
            node_types=("company", "company", "person"),
            rel_types=("OWNS", "LEADS"),
        )
        templates = [_financial_holding_template()]
        result = asyncio.run(matcher.match(raw, templates=templates))
        assert result == "financial_holding_chain"

    def test_first_matching_template_returned(self) -> None:
        """When multiple templates match, the first is returned."""
        from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher

        matcher = self._make_matcher()
        assert isinstance(matcher, PathTemplateMatcher)

        raw = _make_raw_path(
            node_types=("company", "company", "company"),
            rel_types=("SUPPLIES_TO", "SUPPLIES_TO"),
        )
        # Both templates could match (both have company→company→company)
        templates = [
            {
                "template_name": "first_match",
                "entity_type_sequence": ["company", "company", "company"],
                "relation_type_sequence": ["SUPPLIES_TO", "SUPPLIES_TO"],
            },
            {
                "template_name": "second_match",
                "entity_type_sequence": ["company", "company", "company"],
                "relation_type_sequence": ["SUPPLIES_TO", "SUPPLIES_TO"],
            },
        ]
        result = asyncio.run(matcher.match(raw, templates=templates))
        assert result == "first_match"

    def test_case_insensitive_entity_type_matching(self) -> None:
        """Entity type matching is case-insensitive."""
        from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher

        matcher = self._make_matcher()
        assert isinstance(matcher, PathTemplateMatcher)

        # Node types with mixed case
        raw = _make_raw_path(
            node_types=("Company", "COMPANY", "company"),
            rel_types=("SUPPLIES_TO", "SUPPLIES_TO"),
        )
        templates = [_supply_chain_3hop_template()]
        result = asyncio.run(matcher.match(raw, templates=templates))
        assert result == "supply_chain_3hop"
