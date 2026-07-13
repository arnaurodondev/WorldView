"""Static regression tests for migration 0066 — PLAN-0056 Wave C1 (PRD-0033).

DB-FREE: these import the migration module / read its source and assert the
structural invariants of the rendered SQL so a future edit cannot silently
regress them. They mirror the migration-0055 static test pattern.

Locked invariants:
  • revision/down_revision chain 0066 → 0065;
  • upgrade widens ck_temporal_event_type to add 'prediction' AND keeps every
    pre-0066 value (R5 additive);
  • upgrade adds nullable polarity + polarity_confidence columns (no default);
  • the polarity CHECK accepts bullish/bearish/neutral OR NULL (BP-007 VARCHAR,
    not a PG enum);
  • downgrade drops both columns, removes 'prediction' rows, and restores the
    pre-0066 constraint WITHOUT 'prediction'.

The apply/idempotency/downgrade contract against a live Postgres is exercised by
the generic integration suite (tests/integration/test_migration_apply.py etc.)
which runs ``alembic upgrade head`` — that path is DB-dependent and is NOT run
here (no database in this environment).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "alembic" / "versions"
_MIGRATION_0066 = _MIGRATIONS_DIR / "0066_prediction_event_type_and_exposure_polarity.py"

# The 7 pre-0066 event_type values that MUST remain valid after 0066 (R5).
_PRE_0066_EVENT_TYPES = (
    "geopolitical",
    "regulatory",
    "macro",
    "sanctions",
    "natural_disaster",
    "other",
    "corporate",
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0066", _MIGRATION_0066)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source() -> str:
    return _MIGRATION_0066.read_text(encoding="utf-8")


def test_revision_chains_to_0065() -> None:
    mod = _load_module()
    assert mod.revision == "0066"
    assert mod.down_revision == "0065"


def test_upgrade_check_adds_prediction_and_keeps_all_prior_values() -> None:
    """Widened CHECK must accept 'prediction' plus every pre-0066 value (R5)."""
    mod = _load_module()
    add_sql = mod._ADD_NEW_CONSTRAINT
    assert "'prediction'" in add_sql, "prediction missing from 0066 upgrade CHECK"
    for value in _PRE_0066_EVENT_TYPES:
        assert f"'{value}'" in add_sql, f"pre-0066 event_type {value!r} dropped — breaks R5"


def test_upgrade_adds_nullable_polarity_columns_without_default() -> None:
    """Both columns are nullable and carry NO default (existing rows keep NULL)."""
    mod = _load_module()
    cols_sql = mod._ADD_POLARITY_COLUMNS
    assert "polarity VARCHAR(20) NULL" in cols_sql
    assert "polarity_confidence DOUBLE PRECISION NULL" in cols_sql
    # No default value on either column — additive/forward-compatible.
    assert "DEFAULT" not in cols_sql.upper()


def test_polarity_check_accepts_three_values_or_null() -> None:
    """BP-007: polarity is VARCHAR+CHECK (not a PG enum) allowing NULL."""
    mod = _load_module()
    check_sql = mod._ADD_POLARITY_CHECK
    for value in ("bullish", "bearish", "neutral"):
        assert f"'{value}'" in check_sql, f"polarity CHECK missing {value!r}"
    assert "polarity IS NULL" in check_sql, "polarity CHECK must permit NULL"
    # BP-007: never a Postgres enum — no CREATE TYPE ... AS ENUM anywhere.
    assert "CREATE TYPE" not in _source().upper(), "0066 must not create a PG enum type"


def test_downgrade_drops_both_columns() -> None:
    mod = _load_module()
    drop_sql = mod._DROP_POLARITY_COLUMNS
    assert "DROP COLUMN IF EXISTS polarity_confidence" in drop_sql
    assert "DROP COLUMN IF EXISTS polarity" in drop_sql


def test_downgrade_restores_pre_0066_constraint_without_prediction() -> None:
    """Downgrade restores the 7 pre-0066 values and OMITS 'prediction'."""
    mod = _load_module()
    restore_sql = mod._RESTORE_OLD_CONSTRAINT
    for value in _PRE_0066_EVENT_TYPES:
        assert f"'{value}'" in restore_sql, f"downgrade must restore {value!r}"
    assert "'prediction'" not in restore_sql, "downgrade must NOT list prediction"
    # And it deletes prediction rows first so the narrower CHECK cannot fail.
    assert "DELETE FROM temporal_events WHERE event_type = 'prediction'" in mod._DELETE_PREDICTION_ROWS


def test_upgrade_and_downgrade_are_defined() -> None:
    mod = _load_module()
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)
