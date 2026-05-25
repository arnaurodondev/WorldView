"""Unit tests for the shared `_entity_summary` helper.

PLAN-0093 Wave B-4 T-B-4-02 / F-607: the helper was duplicated in
``api/cypher.py`` and ``api/routes.py``; both now import a single
``entity_summary_from_row`` from ``api/_entity_summary``.  These tests pin
the contract so a future field addition can't drift between call sites.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


def test_helper_builds_minimum_fields() -> None:
    """A row with only the required columns yields a populated EntitySummary."""
    from knowledge_graph.api._entity_summary import entity_summary_from_row

    eid = uuid4()
    summary = entity_summary_from_row(
        {
            "entity_id": eid,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
        },
    )
    assert summary.entity_id == eid
    assert summary.canonical_name == "Apple Inc."
    assert summary.entity_type == "financial_instrument"
    # Optional fields default to None.
    assert summary.isin is None
    assert summary.ticker is None
    assert summary.exchange is None
    assert summary.description is None
    assert summary.sector is None


def test_helper_forwards_optional_fields() -> None:
    """All optional fields are populated when present."""
    from knowledge_graph.api._entity_summary import entity_summary_from_row

    eid = uuid4()
    summary = entity_summary_from_row(
        {
            "entity_id": eid,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "isin": "US0378331005",
            "ticker": "AAPL",
            "exchange": "US",
            "description": "iPhone maker.",
            "sector": "Technology",
        },
    )
    assert summary.isin == "US0378331005"
    assert summary.ticker == "AAPL"
    assert summary.exchange == "US"
    assert summary.description == "iPhone maker."
    assert summary.sector == "Technology"


def test_cypher_and_routes_share_the_same_helper() -> None:
    """api/cypher.py and api/routes.py both import the same callable."""
    from knowledge_graph.api import cypher as cypher_mod
    from knowledge_graph.api import routes as routes_mod
    from knowledge_graph.api._entity_summary import entity_summary_from_row

    assert cypher_mod._entity_summary is entity_summary_from_row
    assert routes_mod._entity_summary is entity_summary_from_row
