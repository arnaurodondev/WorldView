"""Tests for Settings configuration (T-MI-25)."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch):
    """Settings loads with sane defaults (storage credentials must be provided)."""
    # Remove any MARKET_INGESTION_* process env vars so we test pure field defaults,
    # not whatever dev.local.env injected via `make test-all`.
    for key in list(os.environ):
        if key.startswith("MARKET_INGESTION_"):
            monkeypatch.delenv(key, raising=False)
    # storage_access_key / storage_secret_key have no defaults (C-001 security
    # hardening) — provide explicit values so Settings() can be instantiated.
    monkeypatch.setenv("MARKET_INGESTION_STORAGE_ACCESS_KEY", "test-key")
    monkeypatch.setenv("MARKET_INGESTION_STORAGE_SECRET_KEY", "test-secret")

    import warnings

    from market_ingestion.config import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # suppress EODHD demo-key warning in this test
        s = Settings()
    assert s.port == 8002
    assert s.host == Settings.model_fields["host"].default
    assert s.debug is False
    assert "postgresql" in s.database_url
    assert s.eodhd_api_key == "demo"
    assert s.storage_bucket == "market-ingestion"
    assert s.bronze_bucket == "market-bronze"
    assert s.canonical_bucket == "market-canonical"
    assert s.scheduler_tick_interval_seconds == 60.0
    assert s.scheduler_max_tasks_per_tick == 1000
    assert s.worker_batch_size == 10
    assert s.worker_lease_seconds == 300
    assert s.worker_concurrency == 4
    assert s.dispatcher_batch_size == 50
    assert s.dispatcher_poll_interval_seconds == 1.0
    assert s.dispatcher_lease_seconds == 60
    assert s.dispatcher_max_attempts == 5
    assert s.otlp_endpoint == ""
    assert s.log_level == "INFO"


def test_settings_env_prefix(monkeypatch):
    """Settings reads MARKET_INGESTION_ prefixed env vars."""
    monkeypatch.setenv("MARKET_INGESTION_PORT", "9999")
    monkeypatch.setenv("MARKET_INGESTION_DEBUG", "true")

    from market_ingestion.config import Settings

    s = Settings()
    assert s.port == 9999
    assert s.debug is True


def test_settings_eodhd_api_key_from_env(monkeypatch):
    monkeypatch.setenv("MARKET_INGESTION_EODHD_API_KEY", "live-key-123")

    from market_ingestion.config import Settings

    s = Settings()
    assert s.eodhd_api_key == "live-key-123"


def test_settings_scheduler_fields_from_env(monkeypatch):
    monkeypatch.setenv("MARKET_INGESTION_SCHEDULER_TICK_INTERVAL_SECONDS", "30.0")
    monkeypatch.setenv("MARKET_INGESTION_SCHEDULER_MAX_TASKS_PER_TICK", "500")

    from market_ingestion.config import Settings

    s = Settings()
    assert s.scheduler_tick_interval_seconds == 30.0
    assert s.scheduler_max_tasks_per_tick == 500


def test_settings_worker_fields_from_env(monkeypatch):
    monkeypatch.setenv("MARKET_INGESTION_WORKER_BATCH_SIZE", "20")
    monkeypatch.setenv("MARKET_INGESTION_WORKER_LEASE_SECONDS", "600")
    monkeypatch.setenv("MARKET_INGESTION_WORKER_CONCURRENCY", "8")

    from market_ingestion.config import Settings

    s = Settings()
    assert s.worker_batch_size == 20
    assert s.worker_lease_seconds == 600
    assert s.worker_concurrency == 8


def test_settings_dispatcher_fields_from_env(monkeypatch):
    monkeypatch.setenv("MARKET_INGESTION_DISPATCHER_BATCH_SIZE", "100")
    monkeypatch.setenv("MARKET_INGESTION_DISPATCHER_MAX_ATTEMPTS", "10")

    from market_ingestion.config import Settings

    s = Settings()
    assert s.dispatcher_batch_size == 100
    assert s.dispatcher_max_attempts == 10


def test_settings_otlp_endpoint_from_env(monkeypatch):
    monkeypatch.setenv("MARKET_INGESTION_OTLP_ENDPOINT", "http://otel-collector:4317")

    from market_ingestion.config import Settings

    s = Settings()
    assert s.otlp_endpoint == "http://otel-collector:4317"


def test_settings_database_url_read_fallback():
    """database_url_read defaults to empty string (falls back to database_url)."""
    from market_ingestion.config import Settings

    s = Settings()
    assert s.database_url_read == ""


def test_settings_bucket_fields_configurable(monkeypatch):
    monkeypatch.setenv("MARKET_INGESTION_BRONZE_BUCKET", "custom-bronze")
    monkeypatch.setenv("MARKET_INGESTION_CANONICAL_BUCKET", "custom-canonical")

    from market_ingestion.config import Settings

    s = Settings()
    assert s.bronze_bucket == "custom-bronze"
    assert s.canonical_bucket == "custom-canonical"


def test_settings_provider_keys_optional():
    """Finnhub, Polygon, Alpha Vantage keys default to empty strings."""
    from market_ingestion.config import Settings

    s = Settings()
    assert s.finnhub_api_key == ""
    assert s.polygon_api_key == ""
    assert s.alpha_vantage_api_key == ""
