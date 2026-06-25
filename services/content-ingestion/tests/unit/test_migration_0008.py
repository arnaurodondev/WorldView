"""Unit tests for migration 0008 — seed default sources (PLAN-0106 Wave B-1).

Tests verify:
  1. The 4 default source rows have distinct deterministic IDs.
     NOTE: the ``finnhub-news`` row (config={}) was removed from 0008 because
     Finnhub's company-news endpoint requires a per-ticker symbol — there is no
     global-feed on the free tier.  Migration 0009 also cleans up any existing
     bad rows that may have been inserted by earlier deployments.
  2. Each source row has the expected name, source_type, config, and enabled flag.
  3. The config guard (_warn_on_missing_api_keys) emits a structlog WARNING for
     each API key that is missing/empty, and does NOT raise.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Import helpers from the migration module itself so we test the real logic.
# ---------------------------------------------------------------------------


def _load_migration() -> Any:
    """Import the migration module by path (it has a numeric prefix)."""
    import importlib.util
    from pathlib import Path

    migration_path = Path(__file__).parent.parent.parent / "alembic" / "versions" / "0008_seed_default_sources.py"
    spec = importlib.util.spec_from_file_location("migration_0008", migration_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


# ---------------------------------------------------------------------------
# Migration data tests
# ---------------------------------------------------------------------------


class TestDefaultSourceRows:
    def setup_method(self) -> None:
        self.m = _load_migration()

    def test_exactly_four_sources(self) -> None:
        # finnhub-news (config={}) was removed; Finnhub requires a per-ticker symbol.
        assert len(self.m._DEFAULT_SOURCES) == 4

    def test_source_ids_are_unique(self) -> None:
        ids = [src["id"] for src in self.m._DEFAULT_SOURCES]
        assert len(set(ids)) == 4, "All 4 source IDs must be unique"

    def test_source_ids_are_deterministic(self) -> None:
        # Calling _ulid_from_seed twice with the same seed must produce the
        # same UUID string — idempotency across re-deploys depends on this.
        seed = "source:eodhd:global-news"
        assert self.m._ulid_from_seed(seed) == self.m._ulid_from_seed(seed)

    def test_source_id_format_is_uuid_like(self) -> None:
        # Should be 8-4-4-4-12 hyphenated hex string (36 chars total).
        for src in self.m._DEFAULT_SOURCES:
            parts = src["id"].split("-")
            assert len(parts) == 5
            assert len(src["id"]) == 36

    def test_expected_source_types(self) -> None:
        # finnhub removed from seed — per-ticker sources are seeded separately.
        types = {src["source_type"] for src in self.m._DEFAULT_SOURCES}
        assert types == {"eodhd", "newsapi", "sec_edgar", "polymarket"}

    def test_expected_source_names(self) -> None:
        # finnhub-news removed from seed (no symbol → HTTP 422 on every tick).
        names = {src["name"] for src in self.m._DEFAULT_SOURCES}
        assert names == {
            "eodhd-news",
            "newsapi-news",
            "sec-edgar-filings",
            "polymarket-predictions",
        }

    def test_finnhub_not_in_seed(self) -> None:
        """Finnhub must NOT be in the default seed (requires per-ticker symbol)."""
        types = [src["source_type"] for src in self.m._DEFAULT_SOURCES]
        assert "finnhub" not in types, "finnhub global seed removed — use per-ticker sources instead"

    def test_all_sources_enabled(self) -> None:
        for src in self.m._DEFAULT_SOURCES:
            assert src["enabled"] is True, f"{src['name']} should be enabled"

    def test_eodhd_config_has_max_pages(self) -> None:
        import json

        eodhd = next(s for s in self.m._DEFAULT_SOURCES if s["source_type"] == "eodhd")
        config = json.loads(eodhd["config"])
        assert config.get("max_pages_per_cycle") == 3

    def test_sec_edgar_config_has_user_agent(self) -> None:
        import json

        sec = next(s for s in self.m._DEFAULT_SOURCES if s["source_type"] == "sec_edgar")
        config = json.loads(sec["config"])
        assert "user_agent" in config


# ---------------------------------------------------------------------------
# Startup config guard tests (SchedulerProcess._warn_on_missing_api_keys)
# ---------------------------------------------------------------------------


class TestWarnOnMissingApiKeys:
    """Tests for the advisory API-key guard added to SchedulerProcess."""

    def _make_settings(
        self,
        *,
        eodhd_api_key: str = "",
        finnhub_api_key: str = "",
        newsapi_key: str = "",
        scheduler_tick_interval_seconds: float = 0.05,
        scheduler_max_tasks_per_tick: int = 10,
        scheduler_interval_seconds: int = 300,
    ) -> MagicMock:
        s = MagicMock()
        s.db_url = MagicMock()
        s.db_url.get_secret_value.return_value = "postgresql+asyncpg://u:p@localhost:5432/test"
        s.db_url_read = ""
        s.eodhd_api_key = eodhd_api_key
        s.finnhub_api_key = finnhub_api_key
        s.newsapi_key = newsapi_key
        s.scheduler_tick_interval_seconds = scheduler_tick_interval_seconds
        s.scheduler_max_tasks_per_tick = scheduler_max_tasks_per_tick
        s.scheduler_interval_seconds = scheduler_interval_seconds
        s.ticker_news_sync_enabled = False  # don't spawn background task in tests
        s.worker_lease_seconds = 300
        return s

    @patch("content_ingestion.infrastructure.scheduler.scheduler_main._build_factories")
    def test_no_warning_when_all_keys_present(self, mock_build: MagicMock) -> None:
        mock_build.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
        from content_ingestion.infrastructure.scheduler.scheduler_main import SchedulerProcess

        settings = self._make_settings(
            eodhd_api_key="key1",
            finnhub_api_key="key2",
            newsapi_key="key3",
        )
        process = SchedulerProcess(settings=settings)

        # Should not raise
        process._warn_on_missing_api_keys()

    @patch("content_ingestion.infrastructure.scheduler.scheduler_main._build_factories")
    def test_warning_logged_for_missing_eodhd_key(self, mock_build: MagicMock) -> None:
        mock_build.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
        from content_ingestion.infrastructure.scheduler.scheduler_main import SchedulerProcess

        settings = self._make_settings(eodhd_api_key="")  # missing
        process = SchedulerProcess(settings=settings)

        # Patch the module-level logger used inside scheduler_main
        with patch("content_ingestion.infrastructure.scheduler.scheduler_main.logger") as mock_logger:
            process._warn_on_missing_api_keys()
            # At least one warning for eodhd missing key
            warning_calls_list = mock_logger.warning.call_args_list
            events = [c[0][0] for c in warning_calls_list]
            assert "source_api_key_missing" in events

    @patch("content_ingestion.infrastructure.scheduler.scheduler_main._build_factories")
    def test_does_not_raise_on_missing_keys(self, mock_build: MagicMock) -> None:
        mock_build.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
        from content_ingestion.infrastructure.scheduler.scheduler_main import SchedulerProcess

        settings = self._make_settings(
            eodhd_api_key="",
            finnhub_api_key="",
            newsapi_key="",
        )
        process = SchedulerProcess(settings=settings)

        # Must not raise — advisory only
        with patch("content_ingestion.infrastructure.scheduler.scheduler_main.logger"):
            process._warn_on_missing_api_keys()

    @patch("content_ingestion.infrastructure.scheduler.scheduler_main._build_factories")
    def test_three_warnings_when_all_keys_missing(self, mock_build: MagicMock) -> None:
        mock_build.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
        from content_ingestion.infrastructure.scheduler.scheduler_main import SchedulerProcess

        settings = self._make_settings(
            eodhd_api_key="",
            finnhub_api_key="",
            newsapi_key="",
        )
        process = SchedulerProcess(settings=settings)

        with patch("content_ingestion.infrastructure.scheduler.scheduler_main.logger") as mock_logger:
            process._warn_on_missing_api_keys()
            # eodhd, finnhub, newsapi — 3 warnings expected
            assert mock_logger.warning.call_count == 3

    @patch("content_ingestion.infrastructure.scheduler.scheduler_main._build_factories")
    def test_sec_edgar_and_polymarket_never_warned(self, mock_build: MagicMock) -> None:
        mock_build.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
        from content_ingestion.infrastructure.scheduler.scheduler_main import SchedulerProcess

        # All keyed providers have keys — only sec_edgar and polymarket have no keys
        # but they need no keys, so zero warnings expected.
        settings = self._make_settings(
            eodhd_api_key="k1",
            finnhub_api_key="k2",
            newsapi_key="k3",
        )
        process = SchedulerProcess(settings=settings)

        with patch("content_ingestion.infrastructure.scheduler.scheduler_main.logger") as mock_logger:
            process._warn_on_missing_api_keys()
            mock_logger.warning.assert_not_called()
