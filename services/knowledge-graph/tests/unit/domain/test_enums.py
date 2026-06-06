"""Unit tests for domain enumerations."""

from __future__ import annotations

import pytest
from knowledge_graph.domain.enums import DecayClass, RelationType, SemanticMode

pytestmark = pytest.mark.unit


class TestSemanticMode:
    def test_exactly_two_values(self) -> None:
        assert len(SemanticMode) == 2

    def test_relation_state_value(self) -> None:
        assert SemanticMode.RELATION_STATE == "RELATION_STATE"

    def test_temporal_claim_value(self) -> None:
        assert SemanticMode.TEMPORAL_CLAIM == "TEMPORAL_CLAIM"

    def test_is_str_enum(self) -> None:
        assert isinstance(SemanticMode.RELATION_STATE, str)


class TestDecayClass:
    def test_exactly_two_values(self) -> None:
        assert len(DecayClass) == 2

    def test_standard_value(self) -> None:
        assert DecayClass.STANDARD == "STANDARD"

    def test_temporal_value(self) -> None:
        assert DecayClass.TEMPORAL == "TEMPORAL"

    def test_is_str_enum(self) -> None:
        assert isinstance(DecayClass.STANDARD, str)


class TestRelationType:
    def test_exactly_sixteen_values(self) -> None:
        # 8 original (PRD §6.7 Block 11) + 3 PRD-0018 (migration 0004) + 5 PLAN-0089 Lever-4 (migration 0041)
        assert len(RelationType) == 16

    def test_original_eight_types_present(self) -> None:
        original = {
            "employs",
            "board_member_of",
            "subsidiary_of",
            "acquired_by",
            "listed_on",
            "supplier_of",
            "partner_of",
            "competes_with",
        }
        actual = {rt.value for rt in RelationType}
        assert original.issubset(actual)

    def test_prd_0018_new_types_present(self) -> None:
        # PRD-0018 §6.4 — seeded in migration 0004
        assert RelationType.HAS_EXECUTIVE == "has_executive"
        assert RelationType.REVENUE_FROM_COUNTRY == "revenue_from_country"
        assert RelationType.OPERATES_IN_COUNTRY == "operates_in_country"

    def test_plan_0089_lever4_types_present(self) -> None:
        # PLAN-0089 Lever-4 — seeded in migration 0041
        assert RelationType.APPOINTED_AS == "appointed_as"
        assert RelationType.DIVESTED_FROM == "divested_from"
        assert RelationType.DOWNGRADED_BY == "downgraded_by"
        assert RelationType.FILED_LAWSUIT_AGAINST == "filed_lawsuit_against"
        assert RelationType.REPORTED_REVENUE_OF == "reported_revenue_of"

    def test_all_values_unique(self) -> None:
        values = [rt.value for rt in RelationType]
        assert len(values) == len(set(values))

    def test_is_str_enum(self) -> None:
        assert isinstance(RelationType.EMPLOYS, str)
