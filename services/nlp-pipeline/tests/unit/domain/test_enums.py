"""Unit tests for S6 domain enumerations (T-C-1-05)."""

from __future__ import annotations

import pytest
from nlp_pipeline.domain.enums import EmbeddingStatus, MentionClass, ResolutionOutcome, RoutingTier


@pytest.mark.unit
class TestMentionClass:
    def test_has_exactly_11_members(self) -> None:
        """T-C-1-05: MentionClass must have exactly 11 members (incl. macroeconomic_indicator)."""
        assert len(MentionClass) == 11

    def test_contains_macroeconomic_indicator(self) -> None:
        """Critical: macroeconomic_indicator is the 11th class added in v1."""
        assert MentionClass.MACROECONOMIC_INDICATOR in MentionClass

    def test_all_expected_classes_present(self) -> None:
        expected = {
            "organization",
            "government_body",
            "regulatory_body",
            "financial_institution",
            "person",
            "financial_instrument",
            "location",
            "commodity",
            "index",
            "currency",
            "macroeconomic_indicator",
        }
        assert {m.value for m in MentionClass} == expected

    def test_str_enum_values(self) -> None:
        assert MentionClass.ORGANIZATION == "organization"
        assert MentionClass.MACROECONOMIC_INDICATOR == "macroeconomic_indicator"

    def test_membership_by_value(self) -> None:
        assert MentionClass("currency") == MentionClass.CURRENCY

    def test_all_lowercase_values(self) -> None:
        for member in MentionClass:
            assert member.value == member.value.lower(), f"{member.value!r} is not lowercase"


@pytest.mark.unit
class TestRoutingTier:
    def test_has_4_members(self) -> None:
        assert len(RoutingTier) == 4

    def test_values(self) -> None:
        assert RoutingTier.DEEP == "deep"
        assert RoutingTier.MEDIUM == "medium"
        assert RoutingTier.LIGHT == "light"
        assert RoutingTier.SUPPRESS == "suppress"

    def test_ordering_is_defined(self) -> None:
        """All 4 tiers exist and can be compared by identity."""
        tiers = {RoutingTier.SUPPRESS, RoutingTier.LIGHT, RoutingTier.MEDIUM, RoutingTier.DEEP}
        assert len(tiers) == 4

    def test_cast_from_string(self) -> None:
        assert RoutingTier("deep") == RoutingTier.DEEP
        assert RoutingTier("suppress") == RoutingTier.SUPPRESS


@pytest.mark.unit
class TestEmbeddingStatus:
    def test_has_3_members(self) -> None:
        assert len(EmbeddingStatus) == 3

    def test_values(self) -> None:
        assert EmbeddingStatus.READY == "ready"
        assert EmbeddingStatus.PENDING == "pending"
        assert EmbeddingStatus.FAILED == "failed"


@pytest.mark.unit
class TestResolutionOutcome:
    def test_has_3_outcomes(self) -> None:
        assert len(ResolutionOutcome) == 3

    def test_values(self) -> None:
        assert ResolutionOutcome.AUTO_RESOLVED == "auto_resolved"
        assert ResolutionOutcome.PROVISIONAL == "provisional"
        assert ResolutionOutcome.UNRESOLVED == "unresolved"
