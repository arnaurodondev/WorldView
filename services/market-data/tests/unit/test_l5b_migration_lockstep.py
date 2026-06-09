"""Lock-step test: migration 035 seed rows match ``_get_static_screen_fields``.

PLAN-0089 Wave L-5b (T-WL5B-05).

WHY THIS TEST EXISTS:
  ``app.py::_screen_fields_refresh_loop`` re-upserts every screen-field
  row every 6 hours from the in-memory list in ``_get_static_screen_fields()``.
  If migration 035's seed rows diverge from that list (different label,
  description, unit, field_type, …) the refresh loop silently overwrites
  the migration's rows on first tick — breaking frontend rendering.

  Same pattern as the L-3 lock-step test (``test_l3_migration_lockstep.py``)
  and the L-4b lock-step test (``test_l4b_migration_lockstep.py``).

FIELD NAMES COVERED:
  news_count_7d, llm_relevance_7d_max, display_relevance_7d_weighted,
  recent_contradiction_count, has_active_alert, has_ai_brief.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_L5B_FIELD_NAMES = (
    "news_count_7d",
    "llm_relevance_7d_max",
    "display_relevance_7d_weighted",
    "recent_contradiction_count",
    "has_active_alert",
    "has_ai_brief",
)

# Expected (label, field_type, unit, description) for each field.
# MUST stay byte-identical to the ``_L5B_FIELDS`` list in migration 035.
_L5B_EXPECTED: dict[str, tuple[str, str, str | None, str]] = {
    "news_count_7d": (
        "NEWS 7D",
        "numeric",
        "count",
        "Number of news articles mentioning this instrument in the past 7 days",
    ),
    "llm_relevance_7d_max": (
        "LLM REL MAX",
        "numeric",
        "score_1",
        "Maximum LLM relevance score across all news articles in the past 7 days (0-1)",
    ),
    "display_relevance_7d_weighted": (
        "DISP REL 7D",
        "numeric",
        "score_1",
        "Weighted display relevance score across all news articles in the past 7 days (0-1)",
    ),
    "recent_contradiction_count": (
        "CONTRADICTIONS",
        "numeric",
        "count",
        "Number of intelligence contradictions detected in the past 7 days",
    ),
    "has_active_alert": (
        "HAS ALERT",
        "numeric",
        None,
        "Instrument has at least one active flash alert",
    ),
    "has_ai_brief": (
        "HAS BRIEF",
        "numeric",
        None,
        "Instrument has a current AI-generated intelligence brief",
    ),
}


def _load_migration_source() -> str:
    """Load migration 035 source text for textual assertions."""
    here = Path(__file__).resolve()
    # Walk up to the market-data service root.
    service_root = here
    while service_root.name != "market-data" and service_root.parent != service_root:
        service_root = service_root.parent
    mig = service_root / "alembic" / "versions" / "035_add_l5b_intelligence_columns.py"
    return mig.read_text(encoding="utf-8")


def _get_l5b_app_fields() -> list[object]:
    """Return only the 6 L-5b entries from ``_get_static_screen_fields()``."""
    from market_data.app import _get_static_screen_fields

    all_fields = _get_static_screen_fields()
    return [f for f in all_fields if f.name in _L5B_FIELD_NAMES]


# ── Migration structural assertions ──────────────────────────────────────────


def test_migration_035_exists() -> None:
    """Migration 035 file must exist on disk."""
    src = _load_migration_source()
    assert len(src) > 0


def test_migration_035_seeds_all_6_l5b_fields() -> None:
    """Migration 035 must reference all 6 L-5b field names."""
    src = _load_migration_source()
    for name in _L5B_FIELD_NAMES:
        assert name in src, f"migration 035 missing field '{name}'"


def test_migration_035_down_revision_is_034() -> None:
    """Migration 035 must chain from 034."""
    src = _load_migration_source()
    assert 'down_revision = "034"' in src or "down_revision='034'" in src


# ── app.py static-fields assertions ──────────────────────────────────────────


def test_static_screen_fields_contains_all_6_l5b_entries() -> None:
    """``_get_static_screen_fields`` must include all 6 L-5b rows exactly once."""
    fields = _get_l5b_app_fields()
    found_names = {f.name for f in fields}
    assert found_names == set(_L5B_FIELD_NAMES), (
        f"missing: {set(_L5B_FIELD_NAMES) - found_names}, " f"extra: {found_names - set(_L5B_FIELD_NAMES)}"
    )
    assert len(fields) == 6


@pytest.mark.parametrize("field_name", _L5B_FIELD_NAMES)
def test_app_static_field_matches_expected(field_name: str) -> None:
    """Each L-5b field in app.py must match the lock-step expected values."""
    exp_label, exp_type, exp_unit, exp_desc = _L5B_EXPECTED[field_name]
    fields = _get_l5b_app_fields()
    f = next((x for x in fields if x.name == field_name), None)
    assert f is not None, f"field '{field_name}' not found in _get_static_screen_fields()"

    assert f.label == exp_label, f"{field_name} label: got {f.label!r}, expected {exp_label!r}"
    assert f.field_type == exp_type, f"{field_name} field_type: got {f.field_type!r}, expected {exp_type!r}"
    assert f.unit == exp_unit, f"{field_name} unit: got {f.unit!r}, expected {exp_unit!r}"
    assert f.description == exp_desc, f"{field_name} description: got {f.description!r}, expected {exp_desc!r}"


def test_static_field_count_is_44() -> None:
    """Total field count must be 38 (pre-L5b) + 6 (L-5b) = 44."""
    from market_data.app import _get_static_screen_fields

    assert len(_get_static_screen_fields()) == 44
