"""Unit tests for the prod-smoke `idle in transaction` check (BP-731, 2026-07-23).

BP-731 found ~27 nlp-pipeline `idle in transaction` Postgres backends holding
snapshots/locks for up to 5m16s — the proximate cause of a recurring
postgres-0 OOM. Before this check (``scripts/prod_e2e_smoke.py
check_idle_in_transaction``) there was ZERO automated production visibility
into this failure class; every past incident was found by a human running an
ad-hoc ``pg_stat_activity`` query DURING an active outage.

These tests import the harness module by file path (mirroring
``tests/scripts/test_expected_alembic_heads.py``'s pattern for this
script-not-package module), monkeypatch its ``_psql`` helper to return
synthetic ``pg_stat_activity`` aggregates (no real cluster/Docker needed), and
assert the PASS/WARN/FAIL classification against the module's own threshold
constants.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_smoke_module() -> Any:
    """Import ``scripts/prod_e2e_smoke.py`` by file path (it is a standalone
    script, not an installed package) — fresh module object per test so each
    test's monkeypatching of module-level globals (``R``, ``_psql``) never
    leaks into another test.
    """
    path = _REPO_ROOT / "scripts" / "prod_e2e_smoke.py"
    spec = importlib.util.spec_from_file_location("_prod_e2e_smoke_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _last_row(mod: Any) -> tuple[str, str, str, str]:
    """The most recent (layer, name, status, detail) row Report.add() recorded."""
    assert mod.R.rows, "check_idle_in_transaction() never called R.add()"
    row: tuple[str, str, str, str] = mod.R.rows[-1]
    return row


def test_zero_idle_connections_passes() -> None:
    mod = _load_smoke_module()
    mod._psql = lambda db, sql: "0|0"

    mod.check_idle_in_transaction()

    _layer, name, status, detail = _last_row(mod)
    assert name == "idle-in-transaction connections"
    assert status == mod.PASS
    assert "0 idle-in-transaction" in detail


def test_below_warn_threshold_passes() -> None:
    mod = _load_smoke_module()
    below_warn = mod.IDLE_IN_TXN_WARN - 1
    mod._psql = lambda db, sql: f"{below_warn}|5"

    mod.check_idle_in_transaction()

    assert _last_row(mod)[2] == mod.PASS


def test_at_warn_threshold_warns() -> None:
    mod = _load_smoke_module()
    calls: list[str] = []

    def fake_psql(db: str, sql: str) -> str:
        calls.append(sql)
        if "string_agg" in sql:
            return "nlp_db=10"
        return f"{mod.IDLE_IN_TXN_WARN}|30"

    mod._psql = fake_psql
    mod.check_idle_in_transaction()

    _layer, _name, status, detail = _last_row(mod)
    assert status == mod.WARN
    assert "nlp_db=10" in detail, "WARN/FAIL detail must include the per-db breakdown"


def test_at_fail_count_threshold_fails() -> None:
    """BP-731's incident count (~27) must classify as FAIL, not WARN."""
    mod = _load_smoke_module()
    mod._psql = lambda db, sql: "intelligence_db=27" if "string_agg" in sql else f"{mod.IDLE_IN_TXN_FAIL_COUNT}|60"

    mod.check_idle_in_transaction()

    assert _last_row(mod)[2] == mod.FAIL


def test_single_long_transaction_age_fails_even_with_low_count() -> None:
    """A single connection at/above the incident's observed max age (5m16s)
    must FAIL regardless of how few connections are currently idle — age is an
    OR condition with count, not an AND (see check_idle_in_transaction's
    docstring: BP-731 ages reached 5m16s, well past the 2-minute floor)."""
    mod = _load_smoke_module()
    mod._psql = lambda db, sql: "nlp_db=1" if "string_agg" in sql else f"1|{mod.IDLE_IN_TXN_FAIL_AGE_S}"

    mod.check_idle_in_transaction()

    _layer, _name, status, detail = _last_row(mod)
    assert status == mod.FAIL
    assert f"max age {mod.IDLE_IN_TXN_FAIL_AGE_S}s" in detail


def test_unparseable_psql_output_warns_instead_of_crashing() -> None:
    """`_psql` returns '' when the query errors or the pod is unreachable
    (see its own docstring) — the check must degrade to a WARN, never raise,
    so one broken probe doesn't crash the whole smoke run."""
    mod = _load_smoke_module()
    mod._psql = lambda db, sql: ""

    mod.check_idle_in_transaction()

    assert _last_row(mod)[2] == mod.WARN


def test_registered_in_layer0() -> None:
    """Guards against the check being written but never wired into layer0()
    — a real risk this class of harness has hit before (a check function that
    exists but nothing calls)."""
    mod = _load_smoke_module()
    import inspect

    source = inspect.getsource(mod.layer0)
    assert "check_idle_in_transaction()" in source
