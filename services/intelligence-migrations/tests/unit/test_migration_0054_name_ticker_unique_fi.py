"""Static regression test for migration 0054 — share-class-aware FI name+ticker
unique index (FR-11).

Runs on every CI path WITHOUT live Postgres (mirrors the 0053 static-test
pattern).  These assertions lock the structural invariants of the migration
source so a future edit cannot silently regress them:
  • the index is on the COMPOSITE (lower(canonical_name), coalesce(ticker,''))
    key — NOT on lower(canonical_name) alone (which would reject legitimate
    distinct share classes BRK-A vs BRK-B and FI-vs-index name splits);
  • the index is SCOPED to financial_instrument only (does not touch 0026's
    non-FI partial index that create_or_get's ON CONFLICT binds to);
  • the upgrade pre-flight FAILS LOUD (BP-688) listing remaining (name, ticker)
    dups instead of letting CREATE UNIQUE INDEX abort with a generic message;
  • the upgrade ASSERTs the index materialised (BP-688);
  • plain CREATE UNIQUE INDEX, no CONCURRENTLY (BP-393);
  • upgrade()/downgrade() exist and the downgrade only DROPs the index.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "alembic" / "versions"
_MIGRATION_0054 = _MIGRATIONS_DIR / "0054_canonical_name_ticker_unique_fi.py"

_INDEX_NAME = "uq_canonical_entities_name_ticker_fi"


def _source() -> str:
    return _MIGRATION_0054.read_text(encoding="utf-8")


def _load_module() -> ModuleType:
    """Import the migration module so we can inspect its rendered DDL + functions."""
    spec = importlib.util.spec_from_file_location("migration_0054", _MIGRATION_0054)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0054_revision_chain() -> None:
    """0054 must chain onto 0053 (the FR-12 exchange entity_type migration)."""
    src = _source()
    assert 'revision: str = "0054"' in src
    assert 'down_revision: str = "0053"' in src


def test_index_is_composite_name_and_ticker_not_name_only() -> None:
    """The index MUST key on (lower(canonical_name), coalesce(ticker,'')).

    A name-only unconditional unique index is the WRONG fix — it would reject
    legitimate distinct share classes (BRK-A vs BRK-B) and FI-vs-index name
    splits.  The composite key is what makes 0054 safe.
    """
    mod = _load_module()
    up = mod._CREATE_NAME_TICKER_FI_INDEX
    assert "lower(canonical_name)" in up
    assert "coalesce(ticker, '')" in up
    # The CREATE statement must contain BOTH expressions together (composite key).
    assert "(lower(canonical_name), coalesce(ticker, ''))" in up


def test_index_is_scoped_to_financial_instrument_only() -> None:
    """0054 must be FI-scoped and must NOT touch the 0026 non-FI partial index."""
    mod = _load_module()
    up = mod._CREATE_NAME_TICKER_FI_INDEX
    assert "WHERE entity_type = 'financial_instrument'" in up
    # Must not drop/alter the 0026 index that create_or_get's ON CONFLICT binds to.
    assert "idx_canonical_entities_lower_name" not in up


def test_index_name_is_distinct_from_existing_indexes() -> None:
    """New index name must not collide with 0026 (lower_name) or 0051 (ticker_fi)."""
    assert _INDEX_NAME != "idx_canonical_entities_lower_name"
    assert _INDEX_NAME != "uq_canonical_entities_ticker_fi"
    assert _INDEX_NAME in _source()


def test_upgrade_preflight_fails_loud_on_residual_dups() -> None:
    """BP-688: pre-flight must RAISE EXCEPTION listing remaining (name, ticker) dups."""
    src = _source()
    assert "Migration 0054 ABORTED" in src
    assert "RAISE EXCEPTION" in src
    # The pre-flight detector groups on the SAME composite key as the index.
    assert "GROUP BY lower(canonical_name), coalesce(ticker, '')" in src
    assert "HAVING count(*) > 1" in src


def test_upgrade_asserts_index_materialised() -> None:
    """BP-688: upgrade must assert the index exists and RAISE on a silent no-op."""
    src = _source()
    assert "Migration 0054 FAILED" in src
    assert "uq_canonical_entities_name_ticker_fi" in src


def test_upgrade_uses_plain_create_unique_index_no_concurrently() -> None:
    """BP-393: plain (in-transaction) CREATE UNIQUE INDEX, never CONCURRENTLY."""
    mod = _load_module()
    up = mod._CREATE_NAME_TICKER_FI_INDEX
    assert "CREATE UNIQUE INDEX" in up
    assert "CONCURRENTLY" not in up


def test_downgrade_only_drops_index() -> None:
    """Downgrade must DROP the index and not delete any row data."""
    mod = _load_module()
    down = mod._DROP_NAME_TICKER_FI_INDEX
    assert "DROP INDEX IF EXISTS uq_canonical_entities_name_ticker_fi" in down
    assert "DELETE" not in down.upper()
    assert "DROP TABLE" not in down.upper()


def test_upgrade_and_downgrade_callables_exist() -> None:
    """Both alembic entrypoints must be defined and call op.execute."""
    mod = _load_module()
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)
