"""Unit tests for the FR-12 deterministic re-type backfill.

The pure classification core (``classify_retype`` / ``plan_retypes``) is tested
directly; the DB plumbing (``main`` dry-run vs --apply, ``_apply_retypes``) is
tested against a minimal fake psycopg connection so no live DB is needed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import retype_mishtyped_entities as mod
from retype_mishtyped_entities import (
    Retype,
    classify_retype,
    plan_retypes,
)

pytestmark = pytest.mark.unit


# ── Pure classification ───────────────────────────────────────────────────────


def test_exchange_from_financial_instrument() -> None:
    """NYSE typed as financial_instrument -> exchange."""
    r = classify_retype("e1", "NYSE", "financial_instrument")
    assert r is not None
    assert r.new_type == "exchange" and r.old_type == "financial_instrument"
    assert r.rule == "exchange"


def test_exchange_from_index() -> None:
    """NASDAQ typed as index -> exchange (the prompt-taught mistype)."""
    r = classify_retype("e2", "NASDAQ", "index")
    assert r is not None and r.new_type == "exchange"


def test_exchange_case_insensitive() -> None:
    r = classify_retype("e3", "nasdaqgs", "index")
    assert r is not None and r.new_type == "exchange"


def test_exchange_already_correct_is_noop() -> None:
    """Idempotent: a row already typed exchange is not re-planned."""
    assert classify_retype("e4", "NYSE", "exchange") is None


def test_country_from_currency() -> None:
    """'U.S.' typed as currency -> place."""
    r = classify_retype("c1", "U.S.", "currency")
    assert r is not None and r.new_type == "place" and r.rule == "country"


def test_country_from_unknown() -> None:
    """'United States of America' typed as unknown -> place."""
    r = classify_retype("c2", "United States of America", "unknown")
    assert r is not None and r.new_type == "place"


def test_country_not_touched_when_already_place() -> None:
    """Idempotent: a country already typed place is not re-planned."""
    assert classify_retype("c3", "China", "place") is None


def test_country_only_from_polluted_buckets() -> None:
    """A country name typed financial_instrument is NOT touched (out of scope —
    only currency/unknown are the documented polluted source buckets)."""
    assert classify_retype("c4", "China", "financial_instrument") is None


def test_unrelated_name_is_noop() -> None:
    assert classify_retype("x1", "Apple Inc.", "financial_instrument") is None
    assert classify_retype("x2", "Tim Cook", "person") is None


def test_plan_retypes_filters_nones() -> None:
    rows = [
        ("e1", "NYSE", "financial_instrument"),
        ("x1", "Apple Inc.", "financial_instrument"),
        ("c1", "U.S.", "currency"),
        ("e2", "NYSE", "exchange"),  # idempotent no-op
    ]
    planned = plan_retypes(rows)
    assert {p.entity_id for p in planned} == {"e1", "c1"}


# ── DB plumbing against a fake connection ─────────────────────────────────────


@dataclass
class _FakeResult:
    rowcount: int

    def fetchall(self) -> list[tuple[str, str, str]]:
        return self._rows  # type: ignore[attr-defined]


class _FakeConn:
    """Minimal psycopg-connection stand-in.

    ``execute`` distinguishes the SELECT (returns the seeded candidate rows) from
    the UPDATE (records the params and returns rowcount=1).  Supports the
    context-manager protocol so ``with psycopg.connect(...) as intel`` works.
    """

    def __init__(self, rows: list[tuple[str, str, str]]) -> None:
        self._rows = rows
        self.updates: list[dict[str, str]] = []
        self.committed = False

    def execute(self, sql: str, params: dict[str, str] | None = None):
        if sql.strip().upper().startswith("SELECT"):
            res = _FakeResult(rowcount=len(self._rows))
            res._rows = self._rows  # type: ignore[attr-defined]
            return res
        # UPDATE path
        assert params is not None
        self.updates.append(params)
        return _FakeResult(rowcount=1)

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


_CANDIDATES = [
    ("e1", "NYSE", "financial_instrument"),
    ("e2", "NASDAQ", "index"),
    ("c1", "U.S.", "currency"),
    ("x1", "Apple Inc.", "financial_instrument"),
]


def test_main_dry_run_writes_nothing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _FakeConn(_CANDIDATES)
    monkeypatch.setattr(mod.psycopg, "connect", lambda _dsn: fake)

    rc = mod.main([])  # no --apply => dry run
    assert rc == 0
    assert fake.updates == [], "dry run must not issue UPDATEs"
    assert not fake.committed, "dry run must not commit"

    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "exchanges -> 'exchange': 2" in out
    assert "countries -> 'place'   : 1" in out


def test_main_apply_executes_and_commits(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _FakeConn(_CANDIDATES)
    monkeypatch.setattr(mod.psycopg, "connect", lambda _dsn: fake)

    rc = mod.main(["--apply"])
    assert rc == 0
    # 3 planned re-types (NYSE, NASDAQ, U.S.) — Apple Inc. is untouched.
    assert len(fake.updates) == 3
    assert fake.committed
    # Each UPDATE re-checks the old type in its WHERE binding (concurrency-safe).
    by_eid = {u["eid"]: u for u in fake.updates}
    assert by_eid["e1"]["new"] == "exchange" and by_eid["e1"]["old"] == "financial_instrument"
    assert by_eid["c1"]["new"] == "place" and by_eid["c1"]["old"] == "currency"

    out = capsys.readouterr().out
    assert "APPLIED — 3 row(s) re-typed" in out


def test_apply_retypes_returns_update_count() -> None:
    fake = _FakeConn([])
    planned = [
        Retype("e1", "NYSE", "financial_instrument", "exchange", "exchange"),
        Retype("c1", "U.S.", "currency", "place", "country"),
    ]
    n = mod._apply_retypes(fake, planned)
    assert n == 2
    assert len(fake.updates) == 2
