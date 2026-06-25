"""Unit tests for nested provider settings models in config.py."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**kwargs: str):  # type: ignore[no-untyped-def]
    """Construct Settings with env_file disabled to avoid local .env pollution."""
    from content_ingestion.config import Settings

    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestEODHDDefaults:
    def test_eodhd_defaults(self) -> None:
        s = _make_settings()
        assert s.eodhd.base_url == "https://eodhd.com/api/news"
        assert s.eodhd.page_size == 100
        assert s.eodhd.rate_limit_per_second == 10.0
        # OPT-5: per-ticker news polls hourly (quota fix), not at the global tick.
        assert s.eodhd.ticker_news_poll_interval_seconds == 3600

    def test_eodhd_ticker_news_interval_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTENT_INGESTION_EODHD__TICKER_NEWS_POLL_INTERVAL_SECONDS", "7200")
        s = _make_settings()
        assert s.eodhd.ticker_news_poll_interval_seconds == 7200


class TestFinnhubDefaults:
    def test_finnhub_defaults(self) -> None:
        s = _make_settings()
        assert s.finnhub.base_url == "https://finnhub.io/api/v1"
        assert s.finnhub.rate_limit_per_minute == 55


class TestNewsAPIDefaults:
    def test_newsapi_defaults(self) -> None:
        s = _make_settings()
        assert s.newsapi.base_url == "https://newsapi.org/v2/everything"
        assert s.newsapi.page_size == 100
        assert s.newsapi.quota_ttl_seconds == 86400


class TestSECEdgarDefaults:
    def test_sec_edgar_defaults(self) -> None:
        s = _make_settings()
        assert s.sec_edgar.efts_url == "https://efts.sec.gov/LATEST/search-index"
        assert s.sec_edgar.filing_base_url == "https://www.sec.gov/Archives/edgar/data"
        assert s.sec_edgar.default_forms == "10-K,10-Q,8-K,DEF14A"
        assert s.sec_edgar.max_concurrent == 8


class TestHTTPClientDefaults:
    def test_http_client_defaults(self) -> None:
        s = _make_settings()
        assert s.http_client.timeout_seconds == 30.0
        assert s.http_client.connect_timeout_seconds == 5.0
        assert s.http_client.max_retries == 3


# ---------------------------------------------------------------------------
# Env-var overrides (nested delimiter __)
# ---------------------------------------------------------------------------


class TestNestedEnvOverrides:
    def test_eodhd_base_url_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTENT_INGESTION_EODHD__BASE_URL", "http://mock-eodhd")
        s = _make_settings()
        assert s.eodhd.base_url == "http://mock-eodhd"

    def test_finnhub_rate_limit_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTENT_INGESTION_FINNHUB__RATE_LIMIT_PER_MINUTE", "30")
        s = _make_settings()
        assert s.finnhub.rate_limit_per_minute == 30

    def test_sec_edgar_max_concurrent_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTENT_INGESTION_SEC_EDGAR__MAX_CONCURRENT", "4")
        s = _make_settings()
        assert s.sec_edgar.max_concurrent == 4

    def test_http_timeout_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTENT_INGESTION_HTTP_CLIENT__TIMEOUT_SECONDS", "60.0")
        s = _make_settings()
        assert s.http_client.timeout_seconds == 60.0

    def test_newsapi_page_size_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTENT_INGESTION_NEWSAPI__PAGE_SIZE", "50")
        s = _make_settings()
        assert s.newsapi.page_size == 50


# ---------------------------------------------------------------------------
# Flat secrets are unaffected by nested delimiter change
# ---------------------------------------------------------------------------


class TestFlatSecretsUnaffected:
    def test_flat_secrets_default_empty(self) -> None:
        s = _make_settings()
        assert s.eodhd_api_key == ""
        assert s.finnhub_api_key == ""
        assert s.newsapi_key == ""

    def test_flat_secrets_read_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTENT_INGESTION_EODHD_API_KEY", "test-key-eodhd")
        monkeypatch.setenv("CONTENT_INGESTION_FINNHUB_API_KEY", "test-key-finnhub")
        monkeypatch.setenv("CONTENT_INGESTION_NEWSAPI_KEY", "test-key-newsapi")
        s = _make_settings()
        assert s.eodhd_api_key == "test-key-eodhd"
        assert s.finnhub_api_key == "test-key-finnhub"
        assert s.newsapi_key == "test-key-newsapi"

    def test_newsapi_daily_limit_still_flat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """newsapi_daily_limit remains a flat field — not shadowed by newsapi sub-model."""
        monkeypatch.setenv("CONTENT_INGESTION_NEWSAPI_DAILY_LIMIT", "200")
        s = _make_settings()
        assert s.newsapi_daily_limit == 200
        # nested field is still at its default
        assert s.newsapi.quota_ttl_seconds == 86400


# ---------------------------------------------------------------------------
# Scheduler / worker / read-replica config (PLAN-0006 Wave B-1)
# ---------------------------------------------------------------------------


class TestSchedulerWorkerDefaults:
    def test_scheduler_worker_defaults(self) -> None:
        s = _make_settings()
        # Read replica (SecretStr — compare via get_secret_value)
        assert s.db_url_read.get_secret_value() == ""
        # Scheduler
        assert s.scheduler_tick_interval_seconds == 60.0
        assert s.scheduler_max_tasks_per_tick == 100
        # Worker
        assert s.worker_batch_size == 5
        assert s.worker_lease_seconds == 300
        assert s.worker_idle_sleep_seconds == 5.0
        assert s.worker_concurrency == 2
        assert s.worker_task_timeout_seconds == 120.0

    def test_db_url_read_fallback_is_valid_empty(self) -> None:
        """Empty db_url_read is valid — session factory handles fallback to db_url."""
        s = _make_settings()
        assert s.db_url_read.get_secret_value() == ""
        assert s.db_url.get_secret_value() != ""

    def test_scheduler_worker_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTENT_INGESTION_SCHEDULER_TICK_INTERVAL_SECONDS", "30.0")
        monkeypatch.setenv("CONTENT_INGESTION_WORKER_BATCH_SIZE", "10")
        monkeypatch.setenv("CONTENT_INGESTION_WORKER_CONCURRENCY", "4")
        monkeypatch.setenv("CONTENT_INGESTION_DB_URL_READ", "postgresql+asyncpg://read-replica:5432/db")
        s = _make_settings()
        assert s.scheduler_tick_interval_seconds == 30.0
        assert s.worker_batch_size == 10
        assert s.worker_concurrency == 4
        assert s.db_url_read.get_secret_value() == "postgresql+asyncpg://read-replica:5432/db"


# ---------------------------------------------------------------------------
# Outbox dispatcher config — BP-612 regression guard
# ---------------------------------------------------------------------------


class TestOutboxMaxAttempts:
    def test_outbox_max_attempts_default(self) -> None:
        """outbox_max_attempts default must be 20 (raised from 5 in BP-612).

        5 attempts with 60 s max backoff exhausts in ~5 min - shorter than a
        typical rolling restart or Kafka blip (30-90 min).  20 attempts gives
        ~20 min coverage before dead-lettering events.
        """
        s = _make_settings()
        assert s.outbox_max_attempts == 20, (
            "outbox_max_attempts was lowered - raises BP-612 risk of dead-lettering "
            "events during short consumer downtime windows. If you need a lower value, "
            "override via env var CONTENT_INGESTION_OUTBOX_MAX_ATTEMPTS."
        )

    def test_outbox_max_attempts_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Operators can override outbox_max_attempts via env var."""
        monkeypatch.setenv("CONTENT_INGESTION_OUTBOX_MAX_ATTEMPTS", "30")
        s = _make_settings()
        assert s.outbox_max_attempts == 30
