"""Regression tests for the prod-smoke migration-drift check.

``check_migration_drift`` used to emit a critical-paging FAIL whenever the
applied DB head differed from the hard-coded ``EXPECTED_ALEMBIC_HEADS`` constant
— even when the LIVE deployed pod and the DB agreed (``db@048 == image@048``),
which is the true healthy state. Because the deployed smoke image lags the source
map whenever a migration merges, that produced a false-positive ``STALE IMAGE``
FAIL (mislabelled: the image was AHEAD of the constant, not behind) that tripped
the critical ``ProdSmokeTestFailed`` page. Observed live on 2026-07-25:
``market_data_db`` DB@048, pod@048, source map@048, but the STALE deployed smoke
image pinned 045 → false critical page.

The fix makes the runtime check trust the authoritative live pair (applied DB
head vs the head baked into the running pod): FAIL only on a genuine
DB-vs-running-code divergence; a stale constant on an otherwise self-consistent
prod degrades to WARN. These tests pin that contract.
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
    """Import ``scripts/prod_e2e_smoke.py`` as a standalone stdlib-only module."""
    path = _REPO_ROOT / "scripts" / "prod_e2e_smoke.py"
    spec = importlib.util.spec_from_file_location("_prod_e2e_smoke", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_drift(
    monkeypatch: pytest.MonkeyPatch,
    *,
    db_head: dict[str, str],
    image_head: dict[str, str],
) -> dict[str, tuple[str, str]]:
    """Drive ``check_migration_drift`` with mocked live reads.

    Returns {db: (status, detail)} for the ``migrations <db>`` rows produced,
    with a fresh Report so module-global accumulation does not leak between runs.
    """
    smoke = _load_smoke_module()

    # Isolate to a single, simple DB so we assert one row deterministically.
    monkeypatch.setattr(smoke, "EXPECTED_ALEMBIC_HEADS", {"market_data_db": "045"})
    monkeypatch.setattr(smoke, "DB_TO_DEPLOYMENT", {"market_data_db": "market-data"})
    monkeypatch.setattr(smoke, "R", smoke.Report())

    def fake_psql(db: str, sql: str) -> str:
        assert "alembic_version" in sql
        return db_head.get(db, "")

    # _deployment_pod returns a pod name; _alembic_image_head maps pod → head.
    monkeypatch.setattr(smoke, "_psql", fake_psql)
    monkeypatch.setattr(smoke, "_deployment_pod", lambda dep: f"{dep}-pod" if dep else "")
    monkeypatch.setattr(
        smoke,
        "_alembic_image_head",
        lambda pod: image_head.get(pod, ""),
    )

    smoke.check_migration_drift()
    rows: dict[str, tuple[str, str]] = {}
    for layer, name, status, detail in smoke.R.rows:
        assert layer == "0"
        assert name.startswith("migrations ")
        rows[name.removeprefix("migrations ")] = (status, detail)
    return rows


def test_stale_constant_but_prod_in_sync_is_warn_not_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB and running pod agree (@048) but the pinned constant is stale (045).

    This is the exact 2026-07-25 false-positive: prod is healthy, only the
    hard-coded map is behind. Must NOT be a (critical-paging) FAIL.
    """
    rows = _run_drift(
        monkeypatch,
        db_head={"market_data_db": "048"},
        image_head={"market-data-pod": "048"},
    )
    status, detail = rows["market_data_db"]
    assert status == "WARN", f"expected WARN, got {status}: {detail}"
    assert "in sync" in detail and "048" in detail


def test_db_behind_running_image_is_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """migrate Job PENDING: running code expects 048, DB still at 047 → FAIL."""
    rows = _run_drift(
        monkeypatch,
        db_head={"market_data_db": "047"},
        image_head={"market-data-pod": "048"},
    )
    status, detail = rows["market_data_db"]
    assert status == "FAIL", f"expected FAIL, got {status}: {detail}"
    assert "047" in detail and "048" in detail


def test_db_ahead_of_running_image_is_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """STALE IMAGE: DB migrated to 048 but a pod still serves 047 → FAIL."""
    rows = _run_drift(
        monkeypatch,
        db_head={"market_data_db": "048"},
        image_head={"market-data-pod": "047"},
    )
    status, detail = rows["market_data_db"]
    assert status == "FAIL", f"expected FAIL, got {status}: {detail}"


def test_no_owner_pod_downgrades_to_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Job-run migrator (no pod to read image head) cannot page on a stale map."""
    rows = _run_drift(
        monkeypatch,
        db_head={"market_data_db": "048"},
        image_head={},  # image head unreadable → cannot confirm against live code
    )
    status, detail = rows["market_data_db"]
    assert status == "WARN", f"expected WARN, got {status}: {detail}"
    assert "no owner pod" in detail


def test_db_matches_pinned_head_is_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the DB already equals the pinned head, it is a plain PASS."""
    rows = _run_drift(
        monkeypatch,
        db_head={"market_data_db": "045"},  # equals the pinned expected
        image_head={"market-data-pod": "045"},
    )
    status, detail = rows["market_data_db"]
    assert status == "PASS", f"expected PASS, got {status}: {detail}"
