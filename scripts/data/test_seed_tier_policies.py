"""Unit tests for the Tier-1/Tier-2 polling-policy seeder.

Covers the pure policy-template builder and the dry-run / apply orchestration
against a minimal fake psycopg connection.  No live DB.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import seed_tier_policies as mod
from seed_tier_policies import (
    Candidate,
    build_policy_rows,
    seed,
)

pytestmark = pytest.mark.unit


# ── Policy template builder ───────────────────────────────────────────────────


def test_full_set_has_five_policies() -> None:
    rows = build_policy_rows(Candidate("MRVL", "US", 1), only_ohlcv=False)
    assert len(rows) == 5
    kinds = {(r.provider, r.dataset_type, r.timeframe) for r in rows}
    assert kinds == {
        ("alpaca", "ohlcv", "1m"),
        ("eodhd", "ohlcv", "1d"),
        ("eodhd", "ohlcv", "1w"),
        ("eodhd", "ohlcv", "1mo"),
        ("eodhd", "fundamentals", None),
    }


def test_only_ohlcv_drops_fundamentals() -> None:
    rows = build_policy_rows(Candidate("MRVL", "US", 1), only_ohlcv=True)
    assert len(rows) == 4
    assert all(r.dataset_type != "fundamentals" for r in rows)


def test_alpaca_1m_tracks_candidate_tier_eodhd_stays_2() -> None:
    rows = build_policy_rows(Candidate("MRVL", "US", 1), only_ohlcv=False)
    alpaca = next(r for r in rows if r.provider == "alpaca")
    assert alpaca.tier == 1
    assert alpaca.timeframe == "1m"
    assert alpaca.base_interval_sec == 60
    assert alpaca.priority == 100
    for r in rows:
        if r.provider == "eodhd":
            assert r.tier == 2


def test_tier2_candidate_alpaca_tier_is_2() -> None:
    rows = build_policy_rows(Candidate("FOO", "US", 2), only_ohlcv=False)
    alpaca = next(r for r in rows if r.provider == "alpaca")
    assert alpaca.tier == 2


def test_exact_tuple_values_mirror_live_data() -> None:
    rows = {
        (r.provider, r.dataset_type, r.timeframe): r
        for r in build_policy_rows(Candidate("X", "US", 2), only_ohlcv=False)
    }
    # 1d
    d = rows[("eodhd", "ohlcv", "1d")]
    assert (d.base_interval_sec, d.min_interval_sec, d.jitter_sec, d.priority) == (21600, 3600, 60, 5)
    # 1w
    w = rows[("eodhd", "ohlcv", "1w")]
    assert (w.base_interval_sec, w.min_interval_sec, w.jitter_sec, w.priority) == (43200, 3600, 60, 4)
    # 1mo
    m = rows[("eodhd", "ohlcv", "1mo")]
    assert (m.base_interval_sec, m.min_interval_sec, m.jitter_sec, m.priority) == (86400, 3600, 60, 3)
    # fundamentals
    f = rows[("eodhd", "fundamentals", None)]
    assert f.dataset_variant == "General"
    assert (f.base_interval_sec, f.min_interval_sec, f.jitter_sec, f.priority) == (86400, 3600, 300, 2)


def test_match_key_is_six_tuple() -> None:
    r = build_policy_rows(Candidate("MRVL", "US", 1), only_ohlcv=False)[0]
    assert r.match_key == (r.provider, r.dataset_type, r.dataset_variant, r.symbol, r.exchange, r.timeframe)


# ── Fake psycopg connection ───────────────────────────────────────────────────


class _FakeCursor:
    """Minimal cursor: tracks existing match-keys + records inserts.

    ``existing`` is a set of 6-tuples that ``_policy_exists`` should report present.
    """

    def __init__(self, existing: set[tuple[Any, ...]]) -> None:
        self._existing = existing
        self.inserts: list[tuple[Any, ...]] = []
        self._last: Any = None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        s = " ".join(sql.split())
        if s.startswith("SELECT 1 FROM polling_policies"):
            # params order: provider, dataset_type, dataset_variant, symbol, exchange, timeframe
            self._last = 1 if tuple(params) in self._existing else None
        elif s.startswith("INSERT INTO polling_policies"):
            self.inserts.append(tuple(params))
            self._last = None

    def fetchone(self) -> Any:
        return (self._last,) if self._last is not None else None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *a: Any) -> None:
        return None


class _FakeConn:
    def __init__(self, existing: set[tuple[Any, ...]]) -> None:
        self.cursor_obj = _FakeCursor(existing)
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *a: Any) -> None:
        return None


@pytest.fixture
def patch_connect(monkeypatch: pytest.MonkeyPatch) -> Any:
    holder: dict[str, _FakeConn] = {}

    def _make(existing: set[tuple[Any, ...]]) -> None:
        conn = _FakeConn(existing)
        holder["conn"] = conn
        monkeypatch.setattr(mod.psycopg, "connect", lambda _dsn: conn)

    _make.holder = holder  # type: ignore[attr-defined]
    return _make


def test_dry_run_writes_nothing_and_rolls_back(patch_connect: Any) -> None:
    patch_connect(set())
    cands = [Candidate("MRVL", "US", 1)]
    to_insert, skipped = seed(cands, apply=False, only_ohlcv=False)
    conn = patch_connect.holder["conn"]
    assert len(to_insert) == 5
    assert skipped == []
    assert conn.cursor_obj.inserts == []  # nothing written
    assert conn.rolled_back is True
    assert conn.committed is False


def test_apply_inserts_and_commits(patch_connect: Any) -> None:
    patch_connect(set())
    cands = [Candidate("MRVL", "US", 1)]
    to_insert, skipped = seed(cands, apply=True, only_ohlcv=False)
    conn = patch_connect.holder["conn"]
    assert len(to_insert) == 5
    assert len(conn.cursor_obj.inserts) == 5
    assert conn.committed is True


def test_idempotent_skips_existing(patch_connect: Any) -> None:
    # Pre-mark the alpaca 1m policy for MRVL as existing.
    existing = {("alpaca", "ohlcv", None, "MRVL", "US", "1m")}
    patch_connect(existing)
    cands = [Candidate("MRVL", "US", 1)]
    to_insert, skipped = seed(cands, apply=True, only_ohlcv=False)
    conn = patch_connect.holder["conn"]
    assert len(to_insert) == 4  # 5 - 1 skipped
    assert len(skipped) == 1
    assert skipped[0].provider == "alpaca"
    assert len(conn.cursor_obj.inserts) == 4


def test_fully_covered_symbol_inserts_zero(patch_connect: Any) -> None:
    cand = Candidate("MU", "US", 1)
    existing = {r.match_key for r in build_policy_rows(cand, only_ohlcv=False)}
    patch_connect(existing)
    to_insert, skipped = seed([cand], apply=True, only_ohlcv=False)
    assert to_insert == []
    assert len(skipped) == 5


def test_only_ohlcv_seed_excludes_fundamentals(patch_connect: Any) -> None:
    patch_connect(set())
    to_insert, _ = seed([Candidate("MRVL", "US", 1)], apply=False, only_ohlcv=True)
    assert len(to_insert) == 4
    assert all(r.dataset_type != "fundamentals" for r in to_insert)


def test_tier1_us_candidate_list_is_clean() -> None:
    syms = [c.symbol for c in mod.TIER1_US_CANDIDATES]
    assert len(syms) == len(set(syms)), "duplicate symbols in TIER1_US_CANDIDATES"
    assert all(c.exchange == "US" for c in mod.TIER1_US_CANDIDATES)
    assert all(c.tier == 1 for c in mod.TIER1_US_CANDIDATES)
    # No exchange-qualified / foreign-listing artifacts.
    assert all("." not in s or s.endswith(".B") for s in syms)
    assert all(":" not in s for s in syms)
