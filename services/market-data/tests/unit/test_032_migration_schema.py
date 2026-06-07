"""Migration 032 correctness tests — verify the L-4b schema replacement.

PLAN-0089 Wave L-4b bug fix: migration 030 silently no-op'd because
``CREATE TABLE IF NOT EXISTS`` found the legacy 001-era ``insider_transactions``
table and skipped the DDL. Migration 032 drops + recreates the table with the
correct schema.

These tests verify:
  1. Migration 032 exists and has ``down_revision = "031"``.
  2. The migration source contains the expected columns (net_value_usd, filer_name).
  3. The ORM model (InsiderTransactionModel) declares all expected columns.
  4. The rollup SQL references net_value_usd (confirming the use case is aligned).

WHY unit tests (no DB required):
  We are testing textual/structural properties of the migration source and ORM
  definition — no Postgres connection needed. The integration smoke test in
  ``test_infra_smoke.py`` covers the actual DB state.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "032_replace_insider_transactions_schema.py"
)


def _load_migration_source() -> str:
    """Read migration 032 source text for assertion purposes."""
    return _MIGRATION_PATH.read_text(encoding="utf-8")


def _load_migration_module() -> object:
    """Import migration 032 via importlib (not a normal package — no __init__)."""
    spec = importlib.util.spec_from_file_location("migration_032", _MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Migration metadata checks ─────────────────────────────────────────────────


def test_migration_032_file_exists() -> None:
    """Migration 032 source file must exist at the expected path."""
    assert _MIGRATION_PATH.exists(), f"Migration file not found: {_MIGRATION_PATH}"


def test_migration_032_revision_and_chain() -> None:
    """Migration 032 must declare revision='032' and down_revision='031'."""
    module = _load_migration_module()
    assert module.revision == "032"  # type: ignore[attr-defined]
    assert module.down_revision == "031"  # type: ignore[attr-defined]


# ── DDL content checks ────────────────────────────────────────────────────────


def test_migration_032_creates_net_value_usd_column() -> None:
    """Migration 032 upgrade SQL must contain the net_value_usd column definition."""
    src = _load_migration_source()
    # Must appear in the CREATE TABLE block.
    assert "net_value_usd" in src, "net_value_usd column missing from migration 032 DDL"


def test_migration_032_creates_filer_name_column() -> None:
    """Migration 032 upgrade SQL must contain the filer_name column (not owner_name in DDL)."""
    src = _load_migration_source()
    assert "filer_name" in src, "filer_name column missing from migration 032 DDL"
    # The upgrade() function body must not define owner_name as a column.
    # Split on "def upgrade" to isolate the upgrade function body, then check up
    # to "def downgrade" so we don't match the downgrade section (which does
    # restore the 001-era table with owner_name).
    after_upgrade_def = src.split("def upgrade")[1]
    upgrade_body = after_upgrade_def.split("def downgrade")[0]
    # owner_name only appears in the docstring/comments above def upgrade()
    # or in the downgrade section — never in the actual CREATE TABLE DDL of
    # the upgrade body.
    assert "owner_name" not in upgrade_body, "Legacy owner_name column found in upgrade() body"


def test_migration_032_creates_natural_key_constraint() -> None:
    """Migration 032 DDL must declare the uq_insider_transactions_natural_key UNIQUE constraint."""
    src = _load_migration_source()
    assert "uq_insider_transactions_natural_key" in src


def test_migration_032_creates_check_constraint() -> None:
    """Migration 032 DDL must declare the ck_insider_transactions_type CHECK constraint."""
    src = _load_migration_source()
    assert "ck_insider_transactions_type" in src
    assert "BUY" in src
    assert "SELL" in src
    assert "GIFT" in src
    assert "OTHER" in src


def test_migration_032_uses_drop_table_before_create() -> None:
    """Migration 032 must DROP TABLE before CREATE TABLE to replace the broken schema."""
    src = _load_migration_source()
    # Isolate the upgrade() function body (after "def upgrade" up to "def downgrade").
    after_upgrade_def = src.split("def upgrade")[1]
    upgrade_body = after_upgrade_def.split("def downgrade")[0]
    drop_pos = upgrade_body.find("DROP TABLE")
    create_pos = upgrade_body.find("CREATE TABLE")
    assert drop_pos != -1, "No DROP TABLE in upgrade() body"
    assert create_pos != -1, "No CREATE TABLE in upgrade() body"
    assert drop_pos < create_pos, "DROP TABLE must precede CREATE TABLE in upgrade()"


def test_migration_032_uses_timestamptz_for_ingested_at() -> None:
    """ingested_at must use TIMESTAMPTZ (not plain TIMESTAMP) — R07 UTC requirement."""
    src = _load_migration_source()
    upgrade_section = src.split("def downgrade")[0]
    assert "TIMESTAMPTZ" in upgrade_section, "ingested_at must be TIMESTAMPTZ in upgrade section"


# ── ORM model alignment checks ────────────────────────────────────────────────


def test_orm_model_has_net_value_usd_column() -> None:
    """InsiderTransactionModel must declare the net_value_usd mapped column."""
    from market_data.infrastructure.db.models.insider_transactions import InsiderTransactionModel

    # mapped_column attributes are registered on the ORM class's __table__.
    col_names = {col.name for col in InsiderTransactionModel.__table__.columns}
    assert "net_value_usd" in col_names, f"net_value_usd missing from ORM model; found: {col_names}"


def test_orm_model_has_filer_name_column() -> None:
    """InsiderTransactionModel must declare filer_name (not owner_name)."""
    from market_data.infrastructure.db.models.insider_transactions import InsiderTransactionModel

    col_names = {col.name for col in InsiderTransactionModel.__table__.columns}
    assert "filer_name" in col_names, "filer_name missing from ORM model"
    assert "owner_name" not in col_names, "Legacy owner_name still present in ORM model"


def test_orm_model_has_natural_key_constraint() -> None:
    """InsiderTransactionModel must declare the uq_insider_transactions_natural_key UNIQUE constraint."""
    from market_data.infrastructure.db.models.insider_transactions import InsiderTransactionModel
    from sqlalchemy import UniqueConstraint

    unique_names = {c.name for c in InsiderTransactionModel.__table__.constraints if isinstance(c, UniqueConstraint)}
    assert (
        "uq_insider_transactions_natural_key" in unique_names
    ), f"uq_insider_transactions_natural_key missing; found: {unique_names}"


# ── Rollup use case alignment check ──────────────────────────────────────────


def test_rollup_use_case_references_net_value_usd() -> None:
    """The rollup use case SQL must reference net_value_usd (not a legacy column)."""
    rollup_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "market_data"
        / "application"
        / "use_cases"
        / "rollup_insider_90d.py"
    )
    assert rollup_path.exists(), f"Rollup use case not found: {rollup_path}"
    src = rollup_path.read_text(encoding="utf-8")
    assert "net_value_usd" in src, "rollup_insider_90d.py does not reference net_value_usd"
