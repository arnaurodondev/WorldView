"""Unit tests for migration 0011 — seed deeper Polymarket-stream sources (PLAN-0056 Wave B3)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _load_migration() -> Any:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent.parent.parent / "alembic" / "versions" / "0011_seed_pm_wave2_sources.py"
    spec = importlib.util.spec_from_file_location("migration_0011", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


class TestRevisionChain:
    def test_revision_and_down_revision(self) -> None:
        m = _load_migration()
        # Deploy-fix: id shortened to ≤32 chars to fit alembic_version varchar(32).
        assert m.revision == "0011_seed_pm_wave2_sources"
        assert len(m.revision) <= 32
        # R32: chained from the verified 0010 head.
        assert m.down_revision == "0010_sec_edgar_cik_watchlist"


class TestSeededSources:
    def setup_method(self) -> None:
        self.m = _load_migration()

    def test_exactly_four_sources(self) -> None:
        assert len(self.m._WAVE2_SOURCES) == 4

    def test_source_types_are_the_four_deeper_streams(self) -> None:
        types = {s["source_type"] for s in self.m._WAVE2_SOURCES}
        assert types == {
            "polymarket_gamma_events",
            "polymarket_clob",
            "polymarket_data_trades",
            "polymarket_data_oi",
        }

    def test_source_ids_unique_and_deterministic(self) -> None:
        ids = [s["id"] for s in self.m._WAVE2_SOURCES]
        assert len(set(ids)) == 4
        assert self.m._uuid_from_seed("x") == self.m._uuid_from_seed("x")

    def test_source_ids_are_uuid_like(self) -> None:
        for s in self.m._WAVE2_SOURCES:
            assert len(s["id"]) == 36
            assert len(s["id"].split("-")) == 5

    def test_all_sources_enabled(self) -> None:
        assert all(s["enabled"] is True for s in self.m._WAVE2_SOURCES)

    def test_clob_and_trades_config_have_markets_worklist(self) -> None:
        # PLAN-0056 Wave B4: CLOB + trades now read the ``markets`` work-list
        # ({condition_id, token_ids}) instead of the flat token_ids/condition_ids
        # lists (those encoded the token_id-surrogate join bug).
        for st in ("polymarket_clob", "polymarket_data_trades"):
            row = next(s for s in self.m._WAVE2_SOURCES if s["source_type"] == st)
            assert "markets" in json.loads(row["config"])

    def test_oi_config_has_condition_ids(self) -> None:
        # OI is unchanged by B4 — it already keys on market_id = conditionId.
        row = next(s for s in self.m._WAVE2_SOURCES if s["source_type"] == "polymarket_data_oi")
        assert "condition_ids" in json.loads(row["config"])


class TestUpgradeDowngrade:
    def test_upgrade_inserts_four_rows(self) -> None:
        m = _load_migration()
        with patch.object(m, "op") as mock_op:
            m.upgrade()
        # One INSERT per source row.
        assert mock_op.execute.call_count == 4

    def test_downgrade_deletes_four_rows(self) -> None:
        m = _load_migration()
        with patch.object(m, "op") as mock_op:
            m.downgrade()
        assert mock_op.execute.call_count == 4

    def test_upgrade_uses_on_conflict_do_nothing(self) -> None:
        """Idempotency: re-running upgrade must not raise on existing rows."""
        m = _load_migration()
        captured: list[str] = []

        def _fake_execute(stmt: Any) -> MagicMock:
            captured.append(str(stmt))
            return MagicMock()

        with patch.object(m, "op") as mock_op:
            mock_op.execute.side_effect = _fake_execute
            m.upgrade()
        assert any("ON CONFLICT ON CONSTRAINT uq_sources_dedup DO NOTHING" in s for s in captured)
