"""Static regression test for migration 0053 — add 'exchange' entity_type (FR-12).

Runs on every CI path WITHOUT live Postgres (mirrors the BUG-A static test
pattern).  The DB-backed apply/rollback round-trip lives in
``tests/test_migration_0053.py`` (marked ``integration``) and skips when no
Postgres is available.

These assertions lock the structural invariants of the migration source so a
future edit can't silently regress them:
  • the widened CHECK includes ``exchange`` AND all 11 original values;
  • the downgrade GUARDS against existing ``exchange`` rows (refuses, FAIL-LOUD);
  • the upgrade resolves the schema dynamically + asserts the constraint
    materialised (BP-688 FAIL-LOUD).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "alembic" / "versions"
_MIGRATION_0053 = _MIGRATIONS_DIR / "0053_add_exchange_entity_type.py"


def _load_module() -> ModuleType:
    """Import the migration module so we can inspect its RENDERED SQL bodies.

    The CHECK VALUES list is built from a Python tuple via ``_values_sql`` at
    module-load, so asserting against the rendered ``_UPGRADE``/``_DOWNGRADE``
    strings is more faithful than scanning the raw source (where the values live
    as double-quoted tuple members, not single-quoted SQL literals)."""
    spec = importlib.util.spec_from_file_location("migration_0053", _MIGRATION_0053)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The 11 original (migration-0039) values that MUST remain valid after 0053.
_ORIGINAL_VALUES = (
    "financial_instrument",
    "person",
    "event",
    "sector",
    "industry",
    "macro_indicator",
    "place",
    "product",
    "index",
    "currency",
    "unknown",
)


def _source() -> str:
    return _MIGRATION_0053.read_text(encoding="utf-8")


def test_migration_0053_revision_chain() -> None:
    src = _source()
    assert 'revision: str = "0053"' in src
    assert 'down_revision: str = "0052"' in src


def test_upgrade_check_includes_exchange_and_all_original_values() -> None:
    """The widened (rendered) CHECK must accept ``exchange`` plus every original value."""
    mod = _load_module()
    upgrade_sql = mod._UPGRADE
    assert "'exchange'" in upgrade_sql, "exchange not present in migration 0053 upgrade SQL"
    for value in _ORIGINAL_VALUES:
        assert f"'{value}'" in upgrade_sql, f"original entity_type {value!r} dropped by 0053 — would break R5"


def test_downgrade_check_restores_original_11_values_without_exchange() -> None:
    """The rendered downgrade CHECK restores the 11 originals and OMITS exchange."""
    mod = _load_module()
    downgrade_sql = mod._DOWNGRADE
    for value in _ORIGINAL_VALUES:
        assert f"'{value}'" in downgrade_sql, f"downgrade must restore {value!r}"
    # The narrowed CHECK clause itself must not list 'exchange' (the guard text
    # mentions it, so we check the rendered V1 values tuple instead).
    assert "exchange" not in set(mod._CANONICAL_KINDS_V1)


def test_downgrade_guards_against_existing_exchange_rows() -> None:
    """Downgrade must refuse to narrow the CHECK while ``exchange`` rows exist."""
    src = _source()
    assert "downgrade REFUSED" in src, "0053 downgrade must FAIL LOUD on existing exchange rows"
    assert "entity_type = ''exchange''" in src or "entity_type = 'exchange'" in src


def test_upgrade_fails_loud_on_silent_noop() -> None:
    """BP-688: upgrade must assert the constraint materialised and RAISE otherwise."""
    src = _source()
    assert "Migration 0053 FAILED" in src
    assert "RAISE EXCEPTION" in src


def test_upgrade_resolves_schema_dynamically() -> None:
    """0052 lesson: resolve canonical_entities schema (public vs ag_catalog)."""
    src = _source()
    assert "canonical_entities" in src
    assert "ORDER BY (n.nspname = 'public') DESC" in src
