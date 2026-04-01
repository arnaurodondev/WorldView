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
    def test_exactly_eight_values(self) -> None:
        assert len(RelationType) == 8

    def test_well_known_types_present(self) -> None:
        expected = {
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
        assert actual == expected

    def test_is_str_enum(self) -> None:
        assert isinstance(RelationType.EMPLOYS, str)
