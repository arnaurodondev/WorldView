"""Unit tests for the survivor-selection rule in merge_duplicate_instruments.

The re-pointing SQL itself is exercised against the live DB via the script's
default DRY-RUN mode (transactional rollback); these tests pin the pure,
deterministic survivor-selection logic that decides which instrument wins a
same-ISIN merge — the part that must NEVER pick a blank-exchange row or the
retired side of a ticker rename.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_duplicate_instruments import Cluster, Member, _choose_survivor

pytestmark = pytest.mark.unit


def _m(
    iid: str,
    symbol: str,
    exchange: str,
    *,
    ohlcv: bool = False,
    deps: int = 0,
    price: int = 0,
) -> Member:
    """Build a cluster Member (security_id is irrelevant to survivor choice)."""
    return Member(
        instrument_id=iid,
        security_id=f"sec-{iid}",
        symbol=symbol,
        exchange=exchange,
        has_ohlcv=ohlcv,
        has_quotes=False,
        has_fundamentals=True,
        name=symbol,
        dep_count=deps,
        price_count=price,
    )


def test_notation_dup_matches_unambiguous_canonical_dash() -> None:
    """BRK-A case: canonical side has ONE ticker (BRK-A, dash) → that row wins,
    even though the blank-exchange dot row has MORE total deps."""
    cluster = Cluster(
        isin="US0846701086",
        members=[
            _m("dash", "BRK-A", "US", ohlcv=True, deps=7587, price=272),
            _m("dot-blank", "BRK.A", "", deps=9062, price=0),  # blank exchange
        ],
    )
    survivor = _choose_survivor(cluster, canonical_tickers={"BRK-A"})
    assert survivor.symbol == "BRK-A"


def test_notation_dup_matches_unambiguous_canonical_dot() -> None:
    """BRK.B case: canonical side is the DOT form → BRK.B wins even though the
    dash row (BRK-B) carries marginally MORE price bars (the re-point recovers
    them). Matching the canonical side beats a few extra bars."""
    cluster = Cluster(
        isin="US0846707026",
        members=[
            _m("dot", "BRK.B", "US", ohlcv=True, deps=10063, price=845),
            _m("dash", "BRK-B", "US", ohlcv=True, deps=8291, price=939),  # more bars
        ],
    )
    survivor = _choose_survivor(cluster, canonical_tickers={"BRK.B"})
    assert survivor.symbol == "BRK.B"


def test_rename_uses_price_signal_when_canonical_ambiguous() -> None:
    """ABC→COR rename: BOTH tickers still have canonicals (ambiguous match), so the
    rule falls back to the price-data signal — COR receives OHLCV (live), ABC does
    not (retired). COR wins, never ABC, despite both having a US exchange."""
    cluster = Cluster(
        isin="US03073E1055",
        members=[
            _m("abc", "ABC", "US", ohlcv=False, deps=8208, price=0),  # retired
            _m("cor", "COR", "US", ohlcv=True, deps=8957, price=760),  # live
        ],
    )
    survivor = _choose_survivor(cluster, canonical_tickers={"ABC", "COR"})
    assert survivor.symbol == "COR"


def test_three_way_picks_data_bearing_dot_over_dash_and_blank() -> None:
    """BF.B case: three rows (dot-US, dash-US, dot-blank). Canonical=BF.B(dot);
    exactly one non-blank member matches → the dot-US row wins; the blank row is
    never elected."""
    cluster = Cluster(
        isin="US1156372096",
        members=[
            _m("dot-us", "BF.B", "US", ohlcv=True, deps=10139, price=437),
            _m("dash-us", "BF-B", "US", ohlcv=True, deps=8411, price=272),
            _m("dot-blank", "BF.B", "", deps=8397, price=0),  # blank exchange
        ],
    )
    survivor = _choose_survivor(cluster, canonical_tickers={"BF.B"})
    assert survivor.symbol == "BF.B"
    assert survivor.exchange == "US"  # the data-bearing one, not the blank twin


def test_never_blank_exchange_even_without_canonical() -> None:
    """No canonical available: still never pick the blank-exchange row; prefer the
    one with price data."""
    cluster = Cluster(
        isin="XX0000000001",
        members=[
            _m("blank", "FOO", "", deps=5000, price=0),  # most deps but blank
            _m("live", "FOO", "US", ohlcv=True, deps=100, price=50),
        ],
    )
    survivor = _choose_survivor(cluster, canonical_tickers=set())
    assert survivor.exchange == "US"
    assert survivor.instrument_id == "live"


def test_canonical_only_as_blank_falls_back_to_data_bearing() -> None:
    """If the canonical ticker matches ONLY a blank-exchange row, do NOT elect it
    (rule 3 forbids blank survivors) — fall back to the data-bearing row."""
    cluster = Cluster(
        isin="XX0000000002",
        members=[
            _m("blank", "WXY", "", deps=9000, price=0),  # matches canonical but blank
            _m("live", "WXY.US", "US", ohlcv=True, deps=80, price=40),
        ],
    )
    survivor = _choose_survivor(cluster, canonical_tickers={"WXY"})
    assert survivor.exchange == "US"
    assert survivor.instrument_id == "live"
