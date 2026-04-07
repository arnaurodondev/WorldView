"""Unit tests for portfolio service Settings."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit

from portfolio.config import Settings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Remove any PORTFOLIO_* process env vars so we test pure field defaults,
    # not whatever dev.local.env injected via `make test-all`.
    for key in list(os.environ):
        if key.startswith("PORTFOLIO_"):
            monkeypatch.delenv(key, raising=False)
    # storage_access_key / storage_secret_key have no defaults (C-001 security
    # hardening) — provide explicit values so Settings() can be instantiated.
    monkeypatch.setenv("PORTFOLIO_STORAGE_ACCESS_KEY", "test-key")
    monkeypatch.setenv("PORTFOLIO_STORAGE_SECRET_KEY", "test-secret")
    s = Settings(_env_file=None)  # also skip any env file on disk
    assert s.service_name == "portfolio"
    assert s.host == "0.0.0.0"  # noqa: S104
    assert s.port == 8001
    assert s.debug is False
    assert "portfolio_db" in s.database_url
    assert s.database_url_read == ""  # R23: empty → fallback to database_url
    assert s.db_pool_size == 10
    assert s.db_max_overflow == 20
    assert s.db_pool_size_read == 20
    assert s.db_max_overflow_read == 30
    assert s.kafka_bootstrap_servers == "localhost:9092"
    assert s.schema_registry_url == "http://localhost:8081"
    assert s.kafka_auto_register_schemas is True
    assert s.topic_portfolio_events == "portfolio.events.v1"
    assert s.topic_instrument_created == "market.instrument.created"
    assert s.topic_instrument_updated == "market.instrument.updated"
    assert s.consumer_group_instrument == "portfolio-instrument-sync"
    assert s.dispatcher_immediate_batch_size == 100
    assert s.dispatcher_poll_interval_seconds == 5.0
    assert s.dispatcher_lease_seconds == 30
    assert s.dispatcher_max_attempts == 10
    assert s.dispatcher_backoff_base_seconds == 1.0
    assert s.valkey_url == "redis://localhost:6379/0"
    assert s.log_level == "INFO"
    assert s.log_format == "json"
    assert s.otlp_endpoint == ""


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTFOLIO_PORT", "9999")
    monkeypatch.setenv("PORTFOLIO_DEBUG", "true")
    monkeypatch.setenv("PORTFOLIO_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PORTFOLIO_OTLP_ENDPOINT", "http://otel:4317")
    monkeypatch.setenv("PORTFOLIO_DISPATCHER_MAX_ATTEMPTS", "5")

    s = Settings()

    assert s.port == 9999
    assert s.debug is True
    assert s.log_level == "DEBUG"
    assert s.otlp_endpoint == "http://otel:4317"
    assert s.dispatcher_max_attempts == 5


def test_schema_registry_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTFOLIO_SCHEMA_REGISTRY_URL", "http://registry:8082")
    s = Settings()
    assert s.schema_registry_url == "http://registry:8082"
