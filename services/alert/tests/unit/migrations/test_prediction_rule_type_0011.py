"""Unit-level guards for migration 0011 (PLAN-0056 Wave D3).

Without spinning up Postgres we pin the load-bearing facts:
  - the revision chains 0011 → 0010 (R32),
  - the upgrade CHECK admits 'PREDICTION' (and keeps the original five types),
  - the downgrade reverses to the narrower five-value CHECK and first deletes
    any PREDICTION rows so the constraint re-applies cleanly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_VERSIONS = Path(__file__).resolve().parents[3] / "alembic" / "versions"
_MIGRATION = _VERSIONS / "0011_add_prediction_rule_type.py"


def _load_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("alert_migration_0011", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigration0011Chain:
    def test_revision_identifiers(self) -> None:
        mod = _load_module()
        assert mod.revision == "0011"
        assert mod.down_revision == "0010"

    def test_upgrade_admits_prediction(self) -> None:
        text = _MIGRATION.read_text()
        assert "'PREDICTION'" in text
        # All five original types must survive the widen.
        for original in ("PRICE_CROSS", "NEWS_COUNT", "NEWS_MOMENTUM", "KG_CONNECTION", "FUNDAMENTAL_CROSS"):
            assert f"'{original}'" in text

    def test_downgrade_reverses_and_purges(self) -> None:
        text = _MIGRATION.read_text()
        # Downgrade removes PREDICTION rows before re-adding the narrower CHECK.
        assert "DELETE FROM alert_rules WHERE rule_type = 'PREDICTION'" in text
        assert "def downgrade" in text

    def test_defines_upgrade_and_downgrade(self) -> None:
        mod = _load_module()
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)

    def test_check_constraint_name_unchanged(self) -> None:
        # The constraint name must match the ORM model + migration 0010 so the
        # drop-and-recreate targets the right object.
        text = _MIGRATION.read_text()
        assert "ck_alert_rules_rule_type" in text
