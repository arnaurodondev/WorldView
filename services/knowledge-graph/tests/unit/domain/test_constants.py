"""Unit tests for domain membership/traversable relation constants (PLAN-0112 T-2-03)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestMembershipRelations:
    def test_membership_relations_frozen(self) -> None:
        """MEMBERSHIP_RELATIONS is a frozenset of the 6 uppercase AGE labels."""
        from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS

        assert isinstance(MEMBERSHIP_RELATIONS, frozenset)
        assert MEMBERSHIP_RELATIONS == {
            "IS_IN_SECTOR",
            "IS_IN_INDUSTRY",
            "LISTED_ON",
            "OPERATES_IN_COUNTRY",
            "REVENUE_FROM_COUNTRY",
            "HEADQUARTERED_IN",
        }
        # Uppercase AGE-label strings (NOT lowercase RelationType enum values).
        for label in MEMBERSHIP_RELATIONS:
            assert label == label.upper()

    def test_is_in_industry_and_revenue_from_country_are_membership(self) -> None:
        """PLAN-0113: IS_IN_INDUSTRY + REVENUE_FROM_COUNTRY are pruned as membership.

        These two high-fan-out labels were added to MEMBERSHIP_RELATIONS so the
        connection-discovery engines (AGE + relational) prune them, matching the
        existing IS_IN_SECTOR / OPERATES_IN_COUNTRY treatment.
        """
        from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS

        assert "IS_IN_INDUSTRY" in MEMBERSHIP_RELATIONS
        assert "REVENUE_FROM_COUNTRY" in MEMBERSHIP_RELATIONS

    def test_membership_subset_of_age_labels(self) -> None:
        """All 6 membership labels exist in the AGE edge-label whitelist."""
        from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS
        from knowledge_graph.infrastructure.workers.age_sync_worker import _VALID_EDGE_LABELS

        assert MEMBERSHIP_RELATIONS <= _VALID_EDGE_LABELS

    def test_traversable_excludes_membership(self) -> None:
        """TRAVERSABLE_RELATIONS = AGE whitelist - membership relations."""
        from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS
        from knowledge_graph.infrastructure.age.graph_path_engine import TRAVERSABLE_RELATIONS
        from knowledge_graph.infrastructure.workers.age_sync_worker import _VALID_EDGE_LABELS

        assert TRAVERSABLE_RELATIONS == frozenset(_VALID_EDGE_LABELS) - MEMBERSHIP_RELATIONS
        assert MEMBERSHIP_RELATIONS.isdisjoint(TRAVERSABLE_RELATIONS)
        # A known traversable label is present.
        assert "PARTNER_OF" in TRAVERSABLE_RELATIONS


class TestSymmetricRelations:
    def test_symmetric_relations_frozen(self) -> None:
        """SYMMETRIC_RELATIONS is exactly the 2 direction-agnostic AGE labels."""
        from knowledge_graph.domain.constants import SYMMETRIC_RELATIONS

        assert isinstance(SYMMETRIC_RELATIONS, frozenset)
        assert SYMMETRIC_RELATIONS == {"PARTNER_OF", "COMPETES_WITH"}
        for label in SYMMETRIC_RELATIONS:
            assert label == label.upper()

    def test_symmetric_subset_of_age_labels(self) -> None:
        """Both symmetric labels exist in the AGE edge-label whitelist."""
        from knowledge_graph.domain.constants import SYMMETRIC_RELATIONS
        from knowledge_graph.infrastructure.workers.age_sync_worker import _VALID_EDGE_LABELS

        assert SYMMETRIC_RELATIONS <= _VALID_EDGE_LABELS

    def test_symmetric_disjoint_from_membership(self) -> None:
        """Symmetric and membership relations do not overlap."""
        from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS, SYMMETRIC_RELATIONS

        assert SYMMETRIC_RELATIONS.isdisjoint(MEMBERSHIP_RELATIONS)
