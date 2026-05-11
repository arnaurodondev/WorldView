"""Unit tests for S6 domain enumerations (T-C-1-05)."""

from __future__ import annotations

import pytest
from nlp_pipeline.domain.enums import (
    DataQuality,
    EmbeddingStatus,
    MentionClass,
    ResolutionOutcome,
    RoutingTier,
    WindowType,
)

pytestmark = pytest.mark.unit


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
    def test_has_6_outcomes(self) -> None:
        """PLAN-0033 T-C-1-01: extended from 3 to 6 values."""
        assert len(ResolutionOutcome) == 6

    def test_original_values(self) -> None:
        assert ResolutionOutcome.AUTO_RESOLVED == "auto_resolved"
        assert ResolutionOutcome.PROVISIONAL == "provisional"
        assert ResolutionOutcome.UNRESOLVED == "unresolved"

    def test_new_values(self) -> None:
        """PLAN-0033 T-C-1-01: three new values added for re-resolution worker."""
        assert ResolutionOutcome.ESCALATED == "escalated"
        assert ResolutionOutcome.ENTITY_CREATED == "entity_created"
        assert ResolutionOutcome.NOISE == "noise"

    def test_membership_by_value(self) -> None:
        assert ResolutionOutcome("noise") == ResolutionOutcome.NOISE
        assert ResolutionOutcome("escalated") == ResolutionOutcome.ESCALATED
        assert ResolutionOutcome("entity_created") == ResolutionOutcome.ENTITY_CREATED


@pytest.mark.unit
class TestWindowType:
    """PRD-0026 T-A-1-01: WindowType enum for article_impact_windows table."""

    def test_has_6_members(self) -> None:
        """4 active daily windows + 2 reserved intraday = 6 total."""
        assert len(WindowType) == 6

    def test_day_window_values(self) -> None:
        assert WindowType.DAY_T0 == "day_t0"
        assert WindowType.DAY_T1 == "day_t1"
        assert WindowType.DAY_T2 == "day_t2"
        assert WindowType.DAY_T5 == "day_t5"

    def test_reserved_intraday_values_exist(self) -> None:
        """Reserved values must exist in the enum even though not computed yet."""
        assert WindowType.INTRADAY_1H == "intraday_1h"
        assert WindowType.INTRADAY_4H == "intraday_4h"

    def test_membership_by_value(self) -> None:
        assert WindowType("day_t0") == WindowType.DAY_T0
        assert WindowType("intraday_1h") == WindowType.INTRADAY_1H


@pytest.mark.unit
class TestDataQuality:
    """PRD-0026 T-A-1-01: DataQuality enum for price measurement source."""

    def test_has_2_members(self) -> None:
        assert len(DataQuality) == 2

    def test_values(self) -> None:
        assert DataQuality.DAILY_PROXY == "daily_proxy"
        assert DataQuality.EXACT_INTRADAY == "exact_intraday"

    def test_membership_by_value(self) -> None:
        assert DataQuality("daily_proxy") == DataQuality.DAILY_PROXY
