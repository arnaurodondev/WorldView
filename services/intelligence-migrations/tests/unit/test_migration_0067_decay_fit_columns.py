"""Static regression tests for migration 0067 — PLAN-0123 Wave 1 (PRD-0120).

DB-FREE: these import the migration module / read its source and assert the
structural invariants of the rendered SQL so a future edit cannot silently
regress them. They mirror the migration-0066 static test pattern.

Locked invariants:
  • revision/down_revision chain 0067 → 0066;
  • upgrade adds 5 nullable columns to relation_type_registry with NO default
    (decay_alpha, half_life_days, alpha_fit_n, alpha_fit_method, alpha_fit_at);
  • downgrade drops all 5 columns;
  • no PG enum is introduced (BP-007 — not applicable here since these are
    scalar/text columns, but asserted for consistency with the family).

The apply/idempotency/downgrade contract against a live Postgres is exercised
by the generic integration suite (tests/integration/test_migration_apply.py,
test_migration_idempotency.py, test_migration_rollback.py, plus the naming/
chain-integrity tests in test_migration_naming.py) which iterate over every
migration file generically — that path is DB-dependent and is NOT run here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "alembic" / "versions"
_MIGRATION_0067 = _MIGRATIONS_DIR / "0067_add_relation_type_decay_fit_columns.py"

_NEW_COLUMNS = (
    "decay_alpha FLOAT NULL",
    "half_life_days FLOAT NULL",
    "alpha_fit_n INTEGER NULL",
    "alpha_fit_method TEXT NULL",
    "alpha_fit_at TIMESTAMPTZ NULL",
)

_NEW_COLUMN_NAMES = (
    "decay_alpha",
    "half_life_days",
    "alpha_fit_n",
    "alpha_fit_method",
    "alpha_fit_at",
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0067", _MIGRATION_0067)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source() -> str:
    return _MIGRATION_0067.read_text(encoding="utf-8")


def test_revision_chains_to_0066() -> None:
    mod = _load_module()
    assert mod.revision == "0067"
    assert mod.down_revision == "0066"


def test_upgrade_targets_relation_type_registry() -> None:
    mod = _load_module()
    assert "ALTER TABLE relation_type_registry" in mod._ADD_DECAY_FIT_COLUMNS


def test_upgrade_adds_all_five_nullable_columns_without_default() -> None:
    """All 5 columns are nullable and carry NO default (existing rows keep NULL)."""
    mod = _load_module()
    cols_sql = mod._ADD_DECAY_FIT_COLUMNS
    for col in _NEW_COLUMNS:
        assert col in cols_sql, f"missing column definition: {col!r}"
    # No default value on any column — additive/forward-compatible (R11).
    assert "DEFAULT" not in cols_sql.upper()
    # Idempotent add.
    assert cols_sql.count("ADD COLUMN IF NOT EXISTS") == 5


def test_downgrade_drops_all_five_columns() -> None:
    mod = _load_module()
    drop_sql = mod._DROP_DECAY_FIT_COLUMNS
    for name in _NEW_COLUMN_NAMES:
        assert f"DROP COLUMN IF EXISTS {name}" in drop_sql, f"downgrade must drop {name!r}"


def test_no_pg_enum_introduced() -> None:
    """BP-007 family consistency check: no CREATE TYPE ... AS ENUM anywhere."""
    assert "CREATE TYPE" not in _source().upper(), "0067 must not create a PG enum type"


def test_upgrade_and_downgrade_are_defined() -> None:
    mod = _load_module()
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)
