"""Unit tests for domain membership/traversable relation constants (PLAN-0112 T-2-03)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestMembershipRelations:
    def test_membership_relations_frozen(self) -> None:
        """MEMBERSHIP_RELATIONS is a frozenset of the 4 uppercase AGE labels."""
        from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS

        assert isinstance(MEMBERSHIP_RELATIONS, frozenset)
        assert MEMBERSHIP_RELATIONS == {
            "IS_IN_SECTOR",
            "LISTED_ON",
            "OPERATES_IN_COUNTRY",
            "HEADQUARTERED_IN",
        }
        # Uppercase AGE-label strings (NOT lowercase RelationType enum values).
        for label in MEMBERSHIP_RELATIONS:
            assert label == label.upper()

    def test_membership_subset_of_age_labels(self) -> None:
        """All 4 membership labels exist in the AGE edge-label whitelist."""
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
