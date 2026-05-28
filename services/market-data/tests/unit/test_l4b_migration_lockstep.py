"""Lock-step test: migration 030 seed row matches ``_get_static_screen_fields``.

PLAN-0089 Wave L-4b (T-WL4B-07).

WHY THIS TEST EXISTS:
  ``app.py::_screen_fields_refresh_loop`` re-upserts every screen-field
  row every 6 hours from the in-memory list in ``_get_static_screen_fields()``.
  If migration 030's seed row diverges from that list (different label,
  description, unit, …) the refresh loop will silently overwrite the
  migration's row on first tick, surfacing as broken frontend rendering.

  Same pattern as the L-3 lock-step test (``test_l3_migration_lockstep.py``).
"""

from __future__ import annotations

from pathlib import Path


def _load_migration_source() -> str:
    """Load migration 030 source as a string for textual byte-equality checks."""
    here = Path(__file__).resolve()
    repo_root = here
    # Walk up to the worldview repo root.
    while repo_root.name != "market-data" and repo_root.parent != repo_root:
        repo_root = repo_root.parent
    mig = repo_root / "alembic" / "versions" / "030_add_insider_transactions_table.py"
    return mig.read_text(encoding="utf-8")


def test_migration_030_seeds_insider_net_buy_90d_field() -> None:
    """Migration 030 must contain a screen_field_metadata INSERT for the new field."""
    src = _load_migration_source()
    assert "insider_net_buy_90d" in src
    assert "INSIDER 90D" in src
    assert "currency_compact" in src
    assert 'field_type="numeric"' in src


def test_static_screen_fields_contains_insider_net_buy_90d() -> None:
    """``_get_static_screen_fields`` must include the L-4b row exactly once."""
    from market_data.app import _get_static_screen_fields

    fields = _get_static_screen_fields()
    matches = [f for f in fields if f.name == "insider_net_buy_90d"]
    assert len(matches) == 1, f"expected exactly one insider_net_buy_90d row, got {len(matches)}"

    row = matches[0]
    # Byte-identical to migration 030's seed values.
    assert row.label == "INSIDER 90D"
    assert row.field_type == "numeric"
    assert row.unit == "currency_compact"
    assert row.description == "Trailing 90-day net dollar value of insider transactions"


def test_static_field_count_is_38() -> None:
    """L-1 (12 base + 4 attr) + L-2 (7) + L-4a (4) + L-5c (2) + L-3 (8) + L-4b (1) = 38 total."""
    from market_data.app import _get_static_screen_fields

    assert len(_get_static_screen_fields()) == 38
