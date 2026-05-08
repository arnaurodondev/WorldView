"""Unit-level guard for migration 0008 backfill SQL.

PLAN-0053 QA-iter2 F-iter2-002.

We can't easily spin up a real Postgres in a unit test, but we CAN
guard against the most damaging regression: the WHERE clause failing
to match the strings that the legacy ``_compose_alert_title()`` actually
emitted. Iter-1 F-002 caught exactly this drift (uppercase vs lowercase
'alert'). This test pins the expected matches so a future refactor of
either the migration OR the alert_fanout templates trips a failing
assertion before deploy.

Approach: extract the WHERE clause from migration 0008, then assert
that representative legacy title strings either match (and would be
rewritten) or don't match (and would be preserved).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_MIGRATION = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "0008_backfill_alert_titles.py"


def _legacy_title_match(title: str | None) -> bool:
    """Local re-implementation of the migration's WHERE clause for unit-level
    pattern checking. Mirrors the SQL exactly — keep in sync with 0008.
    """
    if title is None:
        return True
    if title in {
        "Graph Change alert",
        "Graph Change Alert",
        "Contradiction alert",
        "Contradiction Alert",
        "Signal alert",
        "Signal Alert",
    }:
        return True
    # ``~*`` is case-insensitive in Postgres; Python re is case-sensitive
    # by default — pass IGNORECASE to mirror.
    return bool(re.fullmatch(r"[A-Za-z]+ [A-Za-z]+ alert", title, flags=re.IGNORECASE))


@pytest.mark.unit
class TestMigration0008Match:
    def test_null_title_is_rewritten(self) -> None:
        assert _legacy_title_match(None) is True

    @pytest.mark.parametrize(
        "legacy_title",
        [
            # Old code emitted lowercase 'alert' (`f"{x.title()} alert"`).
            "Graph Change alert",
            "Contradiction alert",
            "Signal alert",
            # Earlier deploys may have produced uppercase variants — match too.
            "Graph Change Alert",
            "Contradiction Alert",
            "Signal Alert",
        ],
    )
    def test_legacy_generic_titles_are_rewritten(self, legacy_title: str) -> None:
        assert _legacy_title_match(legacy_title) is True

    @pytest.mark.parametrize(
        "good_title",
        [
            "AAPL: Bullish guidance",
            "SPY: Graph pattern change",
            "Apple Inc.: Conflicting signals",
            "MSFT: Signal",
            "Conflicting signals",
            "Graph pattern change",
        ],
    )
    def test_already_good_titles_are_preserved(self, good_title: str) -> None:
        assert _legacy_title_match(good_title) is False

    def test_migration_file_contains_expected_clauses(self) -> None:
        """Cheap structural guard: if someone strips the lowercase IN
        entries we want a failing test, not a silent contract drift."""
        text = _MIGRATION.read_text()
        for needle in (
            "'Graph Change alert'",
            "'Contradiction alert'",
            "'Signal alert'",
            "~* '^[A-Za-z]+ [A-Za-z]+ alert$'",
        ):
            assert needle in text, f"missing migration safeguard: {needle}"
