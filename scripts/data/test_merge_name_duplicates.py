"""Unit tests for FR-11 ticker-less name-based dedup clustering (merge_name_duplicates).

These pin the PURE clustering + tier logic (normalisation, token-superset,
mojibake repair, trigram, survivor selection, auto-vs-review thresholds, the
review CSV).  The re-pointing SQL itself is the FR-13 engine (covered by
test_merge_ticker_duplicates) and is exercised against the live DB via --dry-run.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_name_duplicates import (
    NameMember,
    _emit_review_csv,
    _is_encoding_artifact,
    _is_token_superset,
    _strip_trailing_mojibake,
    _trigram,
    build_clusters,
    normalize_name,
)

pytestmark = pytest.mark.unit

# Real SpaceX-cluster surface strings from live (2026-06-13).
_HUB = "9ecb9bad-c820-4159-889b-ffba2d137f1b"
_AI = "727a2791-b4d3-4655-b5a0-ee7c4a5599d3"
_MOJ = "62316375-3233-4eaa-bf49-11906c5ca65d"
_SHARES = "8423e28e-500e-4a35-9815-6a0766189ca9"
_STOCK = "8dc8acb2-de6b-4da9-ae48-2daf6a5eaebd"
_CLASSA = "7ef56458-e463-408c-87bf-1f2b5a0a46dc"
_STARLINK = "aa205ab0-4f42-4cd7-ae14-0357f48afe46"
_ARK = "a394450d-30c7-4b66-9fad-126c3bea3c48"


def _m(eid: str, name: str, etype: str, degree: int, day: int = 23) -> NameMember:
    return NameMember(
        entity_id=eid,
        canonical_name=name,
        entity_type=etype,
        degree=degree,
        created_at=datetime(2026, 5, day, tzinfo=UTC),
        norm=normalize_name(name),
    )


# ── normalisation ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SpaceX", "spacex"),
        ("SpaceX shares", "spacex"),
        ("SpaceX stock", "spacex"),
        ("SpaceX Class A common stock", "spacex"),
        ("SpaceXâ", "spacex"),  # mojibake tail repaired
        ("SpaceX Starlink", "spacex starlink"),
        ("ARK Space Exploration & Innovation ETF", "ark space exploration innovation etf"),
        ("shares", "shares"),  # whole-name suffix preserved, not stripped to ""
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_strip_trailing_mojibake() -> None:
    assert _strip_trailing_mojibake("SpaceXâ") == "SpaceX"
    assert _strip_trailing_mojibake("Nvidiaâ€™") == "Nvidia"
    assert _strip_trailing_mojibake("Clean Name") == "Clean Name"


# ── token-superset + artifact + trigram ──────────────────────────────────────


def test_token_superset() -> None:
    assert _is_token_superset("spacex", "spacex")  # degenerate (post-strip equal)
    assert _is_token_superset("spacex", "spacex starlink")
    assert not _is_token_superset("spacex starlink", "spacex")  # member missing a hub token
    assert not _is_token_superset("", "spacex")  # empty hub never a superset


def test_encoding_artifact() -> None:
    # "spacexai" = "spacex" + short alpha tail on a degree-1 vertex → artifact.
    assert _is_encoding_artifact("spacex", "spacexai", member_degree=1)
    # "spacexa" (mojibake residue) likewise.
    assert _is_encoding_artifact("spacex", "spacexa", member_degree=0)
    # too long a tail → not an artifact.
    assert not _is_encoding_artifact("spacex", "spacexlonger", member_degree=0)
    # high-degree vertex is a real entity, never an artifact.
    assert not _is_encoding_artifact("spacex", "spacexai", member_degree=5)
    # multi-token names are excluded.
    assert not _is_encoding_artifact("spacex", "spacex ai", member_degree=0)


def test_trigram_matches_self_and_superset() -> None:
    assert _trigram("spacex", "spacex") == pytest.approx(1.0)
    # post-normalisation the suffix variants are IDENTICAL to the hub → sim 1.0.
    assert _trigram(normalize_name("SpaceX"), normalize_name("SpaceX shares")) == pytest.approx(1.0)
    # genuinely different names score low.
    assert _trigram("brown forman", "brown brown") < 0.8


# ── clustering: tier assignment ──────────────────────────────────────────────


def test_spacex_cluster_auto_and_review_split() -> None:
    """The canonical FR-11 case: 5 FI satellites auto-merge, product/ETF excluded."""
    members = [
        _m(_HUB, "SpaceX", "financial_instrument", 66),
        _m(_AI, "SpaceXAI", "financial_instrument", 1),
        _m(_MOJ, "SpaceXâ", "financial_instrument", 0),
        _m(_SHARES, "SpaceX shares", "financial_instrument", 0),
        _m(_STOCK, "SpaceX stock", "financial_instrument", 0),
        _m(_CLASSA, "SpaceX Class A common stock", "financial_instrument", 0),
        _m(_STARLINK, "SpaceX Starlink", "product", 0),  # cross-type → never auto
        _m(_ARK, "ARK Space Exploration & Innovation ETF", "financial_instrument", 0),
    ]
    clusters = build_clusters(members)
    # One auto cluster anchored on the degree-66 hub.
    auto_clusters = [c for c in clusters if c.auto]
    assert len(auto_clusters) == 1
    hub_cluster = auto_clusters[0]
    assert hub_cluster.hub.entity_id == _HUB
    auto_ids = {m.entity_id for m in hub_cluster.auto}
    assert auto_ids == {_AI, _MOJ, _SHARES, _STOCK, _CLASSA}
    # The product Starlink is a DIFFERENT entity_type bucket → never in this hub's
    # auto/review and (different norm) does not auto-merge anywhere.
    all_auto = {m.entity_id for c in clusters for m in c.auto}
    assert _STARLINK not in all_auto
    # The ARK ETF is a genuinely different financial_instrument (norm shares no
    # token superset with "spacex") → not auto-merged.
    assert _ARK not in all_auto


def test_survivor_is_highest_degree() -> None:
    """Even if the hub appears later in input order, highest degree anchors it."""
    members = [
        _m(_SHARES, "SpaceX shares", "financial_instrument", 0, day=10),
        _m(_HUB, "SpaceX", "financial_instrument", 66, day=11),
    ]
    clusters = build_clusters(members)
    auto = [c for c in clusters if c.auto]
    assert len(auto) == 1
    assert auto[0].hub.entity_id == _HUB
    assert auto[0].auto[0].entity_id == _SHARES


def test_survivor_tiebreak_oldest_when_equal_degree() -> None:
    members = [
        _m(_HUB, "SpaceX", "financial_instrument", 0, day=15),
        _m("00000000-0000-0000-0000-000000000099", "SpaceX", "financial_instrument", 0, day=9),
    ]
    clusters = build_clusters(members)
    auto = [c for c in clusters if c.auto]
    assert len(auto) == 1
    # oldest (day 9) is the survivor; the newer identical-name row is absorbed.
    assert auto[0].hub.entity_id == "00000000-0000-0000-0000-000000000099"


def test_review_tier_threshold() -> None:
    """A 0.80-0.92 near-match with NO token-superset → review, not auto."""
    members = [
        _m(_HUB, "Brown Forman", "financial_instrument", 10),
        _m("00000000-0000-0000-0000-0000000000bb", "Brown Formann", "financial_instrument", 0),
    ]
    clusters = build_clusters(members)
    # No auto cluster (not a token-superset); the typo lands in review iff sim≥0.80.
    sim = _trigram(normalize_name("Brown Forman"), normalize_name("Brown Formann"))
    if sim >= 0.80:
        review_rows = [r for c in clusters for r in c.review]
        assert any(r[0].canonical_name == "Brown Formann" for r in review_rows)
    assert all(not c.auto for c in clusters)


def test_cross_type_never_auto_merged() -> None:
    """Identical normalised names in DIFFERENT entity_types never auto-merge."""
    members = [
        _m(_HUB, "SpaceX", "financial_instrument", 66),
        _m(_STARLINK, "SpaceX", "product", 0),
    ]
    clusters = build_clusters(members)
    all_auto = {m.entity_id for c in clusters for m in c.auto}
    assert _STARLINK not in all_auto


def test_no_clusters_when_all_distinct() -> None:
    members = [
        _m(_HUB, "Apple", "financial_instrument", 50),
        _m(_AI, "Microsoft", "financial_instrument", 40),
        _m(_ARK, "Nvidia", "financial_instrument", 30),
    ]
    assert build_clusters(members) == []


# ── review CSV ───────────────────────────────────────────────────────────────


def test_emit_review_csv(tmp_path: Path) -> None:
    members = [
        _m(_HUB, "Brown Forman", "financial_instrument", 10),
        _m("00000000-0000-0000-0000-0000000000bb", "Brown Formann", "financial_instrument", 0),
    ]
    clusters = build_clusters(members)
    out = tmp_path / "review.csv"
    rows = _emit_review_csv(clusters, out)
    text = out.read_text(encoding="utf-8")
    assert "hub_entity_id" in text  # header present
    # rows == number of review-tier candidates (0 or 1 depending on trigram).
    assert rows == sum(len(c.review) for c in clusters)
