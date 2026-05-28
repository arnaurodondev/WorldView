"""PLAN-0089 Wave L-3 lock-step test for migration 029 vs app.py.

The L-3 ``screen_field_metadata`` rows live in TWO places:
  1. ``alembic/versions/029_seed_l3_computed_metrics_fields.py::_L3_FIELDS`` —
     the fresh-deployment seed.
  2. ``app.py::_get_static_screen_fields()`` — the in-memory list re-upserted
     every 6 hours by the refresh loop.

If these diverge, the refresh loop silently overwrites the migration's rows
with potentially different label/unit/description values — and any frontend
mapping that keys off ``unit='percent_1'`` will break in production while CI
continues to pass.

This test enforces byte-equality between the two sources for the 8 L-3 fields.

WHY a unit test (not integration): we are only comparing two Python data
structures. No DB is involved. Adding it to the unit suite means the lock-step
contract is enforced on every commit, not just on alembic upgrade runs.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "029_seed_l3_computed_metrics_fields.py"
)

_L3_FIELD_NAMES = (
    "dist_from_52w_high_pct",
    "dist_from_52w_low_pct",
    "return_1m",
    "return_3m",
    "return_6m",
    "return_ytd",
    "return_1y",
    "return_3y",
)


def _load_migration_module() -> object:
    """Load migration 029 by file path (it is not a normal importable package).

    Alembic versions live under ``alembic/versions/`` which is not a Python
    package; we bypass the import system with ``importlib.util.spec_from_file_location``.
    """
    spec = importlib.util.spec_from_file_location("migration_029", _MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_app_static_fields() -> list[object]:
    """Return the 8 L-3 entries from ``app.py::_get_static_screen_fields()``."""
    from market_data.app import _get_static_screen_fields

    all_fields = _get_static_screen_fields()
    return [f for f in all_fields if f.name in _L3_FIELD_NAMES]


def test_migration_029_seeds_all_8_l3_fields() -> None:
    """Migration 029 must define exactly the 8 L-3 metric names."""
    module = _load_migration_module()
    field_names = {row[0] for row in module._L3_FIELDS}  # type: ignore[attr-defined]
    assert field_names == set(_L3_FIELD_NAMES)


def test_migration_029_field_type_is_numeric_for_all() -> None:
    """All 8 fields use field_type='numeric' (check constraint admits only numeric/text)."""
    module = _load_migration_module()
    for row in module._L3_FIELDS:  # type: ignore[attr-defined]
        assert row[2] == "numeric", f"{row[0]} has wrong field_type: {row[2]}"


def test_migration_029_unit_is_percent_1_for_all() -> None:
    """All 8 fields use unit='percent_1' (frontend x100 on render)."""
    module = _load_migration_module()
    for row in module._L3_FIELDS:  # type: ignore[attr-defined]
        assert row[3] == "percent_1", f"{row[0]} has wrong unit: {row[3]}"


@pytest.mark.parametrize("field_name", _L3_FIELD_NAMES)
def test_app_static_fields_match_migration_byte_identical(field_name: str) -> None:
    """For each L-3 field, app.py's row must byte-match migration 029's row.

    Compares (label, field_type, unit, description). Divergence in any tuple
    element fails this test — which is the whole point of the lock-step
    requirement.
    """
    module = _load_migration_module()
    migration_row = next(r for r in module._L3_FIELDS if r[0] == field_name)  # type: ignore[attr-defined]
    _, mig_label, mig_field_type, mig_unit, mig_description = migration_row

    app_field = next(f for f in _load_app_static_fields() if f.name == field_name)
    assert app_field.label == mig_label, f"{field_name} label drift: app={app_field.label!r} mig={mig_label!r}"
    assert (
        app_field.field_type == mig_field_type
    ), f"{field_name} field_type drift: app={app_field.field_type!r} mig={mig_field_type!r}"
    assert app_field.unit == mig_unit, f"{field_name} unit drift: app={app_field.unit!r} mig={mig_unit!r}"
    assert (
        app_field.description == mig_description
    ), f"{field_name} description drift: app={app_field.description!r} mig={mig_description!r}"


def test_app_static_fields_contains_all_8_l3_entries() -> None:
    """app.py must contribute exactly 8 L-3 rows (no missing/extra)."""
    fields = _load_app_static_fields()
    assert len(fields) == 8
    assert {f.name for f in fields} == set(_L3_FIELD_NAMES)
