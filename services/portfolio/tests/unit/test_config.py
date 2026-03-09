"""Unit tests for portfolio service Settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from portfolio.config import Settings


def test_defaults() -> None:
    s = Settings(_env_file=None)  # bypass dev.local.env to test pure defaults
    assert s.service_name == "portfolio"
    assert s.host == "0.0.0.0"  # noqa: S104
    assert s.port == 8001
    assert s.debug is False
    assert "portfolio_db" in s.database_url
    assert s.kafka_bootstrap_servers == "localhost:9092"
    assert s.kafka_schema_registry_url == "http://localhost:8081"
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
    assert s.otlp_endpoint is None


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


def test_kafka_schema_registry_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTFOLIO_KAFKA_SCHEMA_REGISTRY_URL", "http://registry:8082")
    s = Settings()
    assert s.kafka_schema_registry_url == "http://registry:8082"
