"""Unit tests for the survivor-selection rule in merge_ticker_duplicates (BP-459).

The re-pointing SQL itself is exercised against the live DB via the script's
``--dry-run`` mode (transactional rollback); these tests pin the pure,
deterministic survivor-selection logic that decides which canonical wins a
same-ticker merge.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_ticker_duplicates import Cluster, _choose_survivor

pytestmark = pytest.mark.unit

_INSTRUMENT = UUID("a770802d-66df-48f6-aecc-90b0dd025edf")
_NEWS = UUID("5d294bd2-f602-4449-8642-4f6707e24c96")
_OTHER = UUID("0195daad-d001-7000-8000-000000000001")


def _member(eid: UUID, exch: str | None, day: int) -> dict[str, object]:
    return {
        "entity_id": eid,
        "canonical_name": str(eid)[:6],
        "exchange": exch,
        "created_at": datetime(2026, 5, day, tzinfo=UTC),
    }


def test_prefers_instrument_anchored_row() -> None:
    """Rule 1: the row that exists in market_data.instruments wins (the SHEL case)."""
    cluster = Cluster(
        ticker="SHEL",
        members=[
            _member(_NEWS, None, 10),  # news-minted, NULL exchange, older
            _member(_INSTRUMENT, "US", 11),  # the tradable instrument
        ],
    )
    survivor = _choose_survivor(cluster, anchored={str(_INSTRUMENT)})
    assert survivor["entity_id"] == _INSTRUMENT


def test_prefers_exchange_when_no_anchor() -> None:
    """Rule 2: with no instrument-anchored row, the one WITH an exchange wins."""
    cluster = Cluster(
        ticker="PG",
        members=[
            _member(_NEWS, None, 10),
            _member(_OTHER, "US", 12),
        ],
    )
    survivor = _choose_survivor(cluster, anchored=set())
    assert survivor["entity_id"] == _OTHER


def test_tiebreak_oldest_created_at() -> None:
    """Rule 3: when neither anchored nor exchange disambiguates, oldest wins."""
    cluster = Cluster(
        ticker="SNDK",
        members=[
            _member(_OTHER, None, 15),
            _member(_NEWS, None, 9),  # oldest
        ],
    )
    survivor = _choose_survivor(cluster, anchored=set())
    assert survivor["entity_id"] == _NEWS


def test_multiple_anchored_falls_back_to_exchange_then_age() -> None:
    """Two instrument-anchored rows (dual-listing) → fall back to exchange/age."""
    cluster = Cluster(
        ticker="XYZ",
        members=[
            _member(_NEWS, "US", 11),
            _member(_OTHER, "US", 9),  # both anchored + exchange → oldest wins
        ],
    )
    survivor = _choose_survivor(cluster, anchored={str(_NEWS), str(_OTHER)})
    assert survivor["entity_id"] == _OTHER
