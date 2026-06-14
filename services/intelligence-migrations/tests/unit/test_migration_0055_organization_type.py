"""Static regression test for migration 0055 — add 'organization' entity_type (FR-12).

Runs on every CI path WITHOUT live Postgres (mirrors the migration-0053 static
test pattern).  These assertions lock the structural invariants of the migration
source so a future edit can't silently regress them:
  • the widened CHECK includes ``organization`` AND all 12 post-0053 values;
  • the downgrade GUARDS against existing ``organization`` rows (refuses, FAIL-LOUD);
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
_MIGRATION_0055 = _MIGRATIONS_DIR / "0055_add_organization_entity_type.py"


def _load_module() -> ModuleType:
    """Import the migration module so we can inspect its RENDERED SQL bodies.

    The CHECK VALUES list is built from a Python tuple via ``_values_sql`` at
    module-load, so asserting against the rendered ``_UPGRADE``/``_DOWNGRADE``
    strings is more faithful than scanning the raw source (where the values live
    as double-quoted tuple members, not single-quoted SQL literals)."""
    spec = importlib.util.spec_from_file_location("migration_0055", _MIGRATION_0055)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The 12 post-0053 values that MUST remain valid after 0055.
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
    "exchange",
    "currency",
    "unknown",
)


def _source() -> str:
    return _MIGRATION_0055.read_text(encoding="utf-8")


def test_migration_0055_revision_chain() -> None:
    src = _source()
    assert 'revision: str = "0055"' in src
    assert 'down_revision: str = "0054"' in src


def test_upgrade_check_includes_organization_and_all_original_values() -> None:
    """The widened (rendered) CHECK must accept ``organization`` plus every original value."""
    mod = _load_module()
    upgrade_sql = mod._UPGRADE
    assert "'organization'" in upgrade_sql, "organization not present in migration 0055 upgrade SQL"
    for value in _ORIGINAL_VALUES:
        assert f"'{value}'" in upgrade_sql, f"original entity_type {value!r} dropped by 0055 — would break R5"


def test_downgrade_check_restores_original_12_values_without_organization() -> None:
    """The rendered downgrade CHECK restores the 12 originals and OMITS organization."""
    mod = _load_module()
    downgrade_sql = mod._DOWNGRADE
    for value in _ORIGINAL_VALUES:
        assert f"'{value}'" in downgrade_sql, f"downgrade must restore {value!r}"
    # The narrowed CHECK clause itself must not list 'organization' (the guard
    # text mentions it, so we check the rendered V2 values tuple instead).
    assert "organization" not in set(mod._CANONICAL_KINDS_V2)


def test_downgrade_guards_against_existing_organization_rows() -> None:
    """Downgrade must refuse to narrow the CHECK while ``organization`` rows exist."""
    src = _source()
    assert "downgrade REFUSED" in src, "0055 downgrade must FAIL LOUD on existing organization rows"
    assert "entity_type = ''organization''" in src or "entity_type = 'organization'" in src


def test_upgrade_fails_loud_on_silent_noop() -> None:
    """BP-688: upgrade must assert the constraint materialised and RAISE otherwise."""
    src = _source()
    assert "Migration 0055 FAILED" in src
    assert "RAISE EXCEPTION" in src


def test_upgrade_resolves_schema_dynamically() -> None:
    """0052 lesson: resolve canonical_entities schema (public vs ag_catalog)."""
    src = _source()
    assert "canonical_entities" in src
    assert "ORDER BY (n.nspname = 'public') DESC" in src


def test_values_sql_doubles_single_quotes() -> None:
    """BP from 0053: values rendered into a plpgsql EXECUTE literal must DOUBLE quotes."""
    mod = _load_module()
    rendered = mod._values_sql(("organization", "person"))
    assert "''organization''" in rendered
    assert "''person''" in rendered
