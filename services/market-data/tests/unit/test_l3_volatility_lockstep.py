"""Lock-step test for the ``volatility_30d`` screen field (migration 041 vs app.py).

The ``volatility_30d`` ``screen_field_metadata`` row lives in TWO places that
MUST stay byte-identical:
  1. ``alembic/versions/041_seed_volatility_30d_field.py::_VOLATILITY_FIELD`` —
     the fresh-deployment seed.
  2. ``app.py::_get_static_screen_fields()`` — the in-memory list re-upserted
     every 6 hours by the refresh loop.

If they diverge, the refresh loop silently overwrites the migration's row with
different label/unit/description values while CI keeps passing — the exact
silent-failure pattern the L-3 lock-step contract exists to prevent.

WHY a unit test (not integration): we only compare two Python data structures;
no DB is involved, so the contract is enforced on every commit.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


_MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "041_seed_volatility_30d_field.py"


def _load_migration_module() -> object:
    """Load migration 041 by file path (alembic versions are not a package)."""
    spec = importlib.util.spec_from_file_location("migration_041", _MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _app_volatility_field() -> object:
    from market_data.app import _get_static_screen_fields

    return next(f for f in _get_static_screen_fields() if f.name == "volatility_30d")


def test_migration_041_field_is_volatility_30d_numeric_percent_1() -> None:
    """Migration 041 defines volatility_30d as numeric / percent_1."""
    module = _load_migration_module()
    field_name, _label, field_type, unit, _description = module._VOLATILITY_FIELD  # type: ignore[attr-defined]
    assert field_name == "volatility_30d"
    assert field_type == "numeric"
    assert unit == "percent_1"


def test_app_static_field_matches_migration_byte_identical() -> None:
    """app.py's volatility_30d row must byte-match migration 041's row."""
    module = _load_migration_module()
    _, mig_label, mig_field_type, mig_unit, mig_description = module._VOLATILITY_FIELD  # type: ignore[attr-defined]

    app_field = _app_volatility_field()
    assert app_field.label == mig_label, f"label drift: app={app_field.label!r} mig={mig_label!r}"
    assert app_field.field_type == mig_field_type
    assert app_field.unit == mig_unit
    assert app_field.description == mig_description


def test_app_contributes_exactly_one_volatility_30d_row() -> None:
    """No duplicate / missing volatility_30d row in app.py's static fields."""
    from market_data.app import _get_static_screen_fields

    matches = [f for f in _get_static_screen_fields() if f.name == "volatility_30d"]
    assert len(matches) == 1
