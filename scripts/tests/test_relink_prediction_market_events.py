"""Tests for scripts/ops/relink_prediction_market_events.py.

Covers the pure resolution logic (slug / market_id / unlinkable branches), the
idempotent keyset relink loop against a fake asyncpg connection, dry-run, and the
summary formatter. Mirrors the import-by-path style used by the other ops-script
tests so the module runs without being an installed package.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "ops", "relink_prediction_market_events.py"),
)
_spec = importlib.util.spec_from_file_location("relink_prediction_market_events", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
relink_mod = importlib.util.module_from_spec(_spec)
sys.modules["relink_prediction_market_events"] = relink_mod
_spec.loader.exec_module(relink_mod)


# ── pure resolution logic ────────────────────────────────────────────────────


def test_resolve_by_slug_takes_priority() -> None:
    # slug matches an event → linked_by_slug even though market_id could also match.
    events = frozenset({"grp-slug", "0xabc"})
    resolved, reason = relink_mod.resolve_event_id("grp-slug", "0xabc", events)
    assert resolved == "grp-slug"
    assert reason == relink_mod.LINKED_BY_SLUG


def test_resolve_by_market_id_when_slug_absent() -> None:
    events = frozenset({"0xabc"})
    resolved, reason = relink_mod.resolve_event_id(None, "0xabc", events)
    assert resolved == "0xabc"
    assert reason == relink_mod.LINKED_BY_MARKET_ID


def test_resolve_by_market_id_when_slug_present_but_no_match() -> None:
    events = frozenset({"0xabc"})
    resolved, reason = relink_mod.resolve_event_id("unknown-slug", "0xabc", events)
    assert resolved == "0xabc"
    assert reason == relink_mod.LINKED_BY_MARKET_ID


def test_unlinkable_slug_null() -> None:
    resolved, reason = relink_mod.resolve_event_id(None, "0xdead", frozenset({"other"}))
    assert resolved is None
    assert reason == relink_mod.UNLINKABLE_NO_SLUG


def test_unlinkable_slug_present_but_no_event() -> None:
    resolved, reason = relink_mod.resolve_event_id("some-slug", "0xdead", frozenset({"other"}))
    assert resolved is None
    assert reason == relink_mod.UNLINKABLE_SLUG_PRESENT


def test_blank_slug_is_treated_as_absent() -> None:
    resolved, reason = relink_mod.resolve_event_id("   ", "0xdead", frozenset())
    assert resolved is None
    assert reason == relink_mod.UNLINKABLE_NO_SLUG


# ── fake asyncpg connection ──────────────────────────────────────────────────


class _FakeConn:
    """Minimal async stand-in for asyncpg.Connection.

    ``markets`` is the live table: list of dicts with id/market_id/market_slug/
    event_id. ``event_ids`` seeds prediction_events. ``fetch`` handles both the
    event-id load and the keyset market page; ``executemany`` applies the guarded
    UPDATE (only when event_id is still NULL — proving idempotency).
    """

    def __init__(self, markets: list[dict[str, Any]], event_ids: list[str]) -> None:
        self.markets = markets
        self.event_ids = event_ids
        self.executemany_calls = 0

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "FROM prediction_events" in query:
            return [{"event_id": e} for e in self.event_ids]
        # Keyset page over NULL-event_id markets ordered by id::text.
        cursor, limit = args
        pending = sorted(
            (m for m in self.markets if m["event_id"] is None and str(m["id"]) > cursor),
            key=lambda m: str(m["id"]),
        )
        return pending[:limit]

    async def executemany(self, query: str, args: list[tuple[str, str]]) -> None:
        self.executemany_calls += 1
        by_id = {str(m["id"]): m for m in self.markets}
        for event_id, market_row_id in args:
            m = by_id.get(str(market_row_id))
            if m is not None and m["event_id"] is None:  # guarded UPDATE
                m["event_id"] = event_id


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def _market(_id: str, market_id: str, slug: str | None) -> dict[str, Any]:
    return {"id": _id, "market_id": market_id, "market_slug": slug, "event_id": None}


# ── relink loop ──────────────────────────────────────────────────────────────


def test_relink_links_slug_and_market_id_and_reports_unlinkable() -> None:
    markets = [
        _market("00000000-0000-0000-0000-000000000001", "0xaaa", "grp-slug"),  # linked by slug
        _market("00000000-0000-0000-0000-000000000002", "0xbbb", None),  # linked by market_id
        _market("00000000-0000-0000-0000-000000000003", "0xccc", None),  # unlinkable, no slug
        _market("00000000-0000-0000-0000-000000000004", "0xddd", "orphan"),  # unlinkable, slug present
    ]
    conn = _FakeConn(markets, event_ids=["grp-slug", "0xbbb"])

    tally = _run(relink_mod.relink(conn, batch_size=2, dry_run=False))

    assert tally["total"] == 4
    assert tally[relink_mod.LINKED_BY_SLUG] == 1
    assert tally[relink_mod.LINKED_BY_MARKET_ID] == 1
    assert tally[relink_mod.UNLINKABLE_NO_SLUG] == 1
    assert tally[relink_mod.UNLINKABLE_SLUG_PRESENT] == 1
    # Writes applied.
    assert markets[0]["event_id"] == "grp-slug"
    assert markets[1]["event_id"] == "0xbbb"
    assert markets[2]["event_id"] is None
    assert markets[3]["event_id"] is None


def test_relink_dry_run_writes_nothing() -> None:
    markets = [_market("00000000-0000-0000-0000-000000000001", "0xaaa", "grp-slug")]
    conn = _FakeConn(markets, event_ids=["grp-slug"])

    tally = _run(relink_mod.relink(conn, batch_size=10, dry_run=True))

    assert tally[relink_mod.LINKED_BY_SLUG] == 1
    assert conn.executemany_calls == 0
    assert markets[0]["event_id"] is None  # untouched


def test_relink_is_idempotent_on_second_pass() -> None:
    markets = [
        _market("00000000-0000-0000-0000-000000000001", "0xaaa", "grp-slug"),
        _market("00000000-0000-0000-0000-000000000002", "0xbbb", None),
    ]
    conn = _FakeConn(markets, event_ids=["grp-slug", "0xbbb"])

    first = _run(relink_mod.relink(conn, batch_size=10, dry_run=False))
    assert first["total"] == 2
    calls_after_first = conn.executemany_calls

    # Second pass: everything already linked → no NULL rows → nothing visited/written.
    second = _run(relink_mod.relink(conn, batch_size=10, dry_run=False))
    assert second["total"] == 0
    assert conn.executemany_calls == calls_after_first


def test_relink_all_unlinkable_matches_prod_reality() -> None:
    # Mirrors live prod: 3 markets, all NULL slug, no matching prediction_events.
    markets = [_market(f"00000000-0000-0000-0000-00000000000{i}", f"0x{i}", None) for i in (1, 2, 3)]
    conn = _FakeConn(markets, event_ids=["2890", "2891"])  # disjoint historical events

    tally = _run(relink_mod.relink(conn, batch_size=500, dry_run=False))

    assert tally["total"] == 3
    assert tally[relink_mod.LINKED_BY_SLUG] == 0
    assert tally[relink_mod.LINKED_BY_MARKET_ID] == 0
    assert tally[relink_mod.UNLINKABLE_NO_SLUG] == 3
    assert conn.executemany_calls == 0
    assert all(m["event_id"] is None for m in markets)


# ── summary + env helpers ────────────────────────────────────────────────────


def test_format_summary_reports_counts() -> None:
    tally = {
        "total": 4,
        relink_mod.LINKED_BY_SLUG: 1,
        relink_mod.LINKED_BY_MARKET_ID: 1,
        relink_mod.UNLINKABLE_NO_SLUG: 1,
        relink_mod.UNLINKABLE_SLUG_PRESENT: 1,
    }
    out = relink_mod._format_summary(tally, dry_run=False)
    assert "4 prediction markets with NULL event_id" in out
    assert "linked 2" in out
    assert "2 unlinkable" in out

    dry = relink_mod._format_summary(tally, dry_run=True)
    assert "would link 2" in dry


def test_env_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RELINK_BATCH_SIZE", raising=False)
    assert relink_mod._env_int("RELINK_BATCH_SIZE", 500) == 500
    monkeypatch.setenv("RELINK_BATCH_SIZE", "10")
    assert relink_mod._env_int("RELINK_BATCH_SIZE", 500) == 10
    monkeypatch.setenv("RELINK_BATCH_SIZE", "0")  # non-positive → default
    assert relink_mod._env_int("RELINK_BATCH_SIZE", 500) == 500
    monkeypatch.setenv("RELINK_BATCH_SIZE", "bad")
    assert relink_mod._env_int("RELINK_BATCH_SIZE", 500) == 500

    monkeypatch.setenv("RELINK_DRY_RUN", "true")
    assert relink_mod._env_bool("RELINK_DRY_RUN", False) is True
    monkeypatch.setenv("RELINK_DRY_RUN", "no")
    assert relink_mod._env_bool("RELINK_DRY_RUN", True) is False
