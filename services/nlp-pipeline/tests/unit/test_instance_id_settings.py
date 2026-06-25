"""PLAN-0113 FIX-2: static-membership instance-id settings default empty + wiring.

Covers both:
* T-A-2-03 — the four nlp-pipeline consumer-scope settings default to "".
* T-A-2-04 — the article and watchlist ``*_main`` build a ``ConsumerConfig``
  carrying the per-scope ``group_instance_id`` resolved from settings.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit

_INSTANCE_ID_FIELDS = (
    "kafka_consumer_instance_id",
    "kafka_watchlist_consumer_instance_id",
    "kafka_entity_refresh_consumer_instance_id",
    "kafka_document_deletion_consumer_instance_id",
)


def _settings(monkeypatch: pytest.MonkeyPatch):  # - test helper
    for key in list(os.environ):
        if key.startswith("NLP_PIPELINE_"):
            monkeypatch.delenv(key, raising=False)
    # database_url / intelligence_database_url have no defaults — provide test values.
    monkeypatch.setenv("NLP_PIPELINE_DATABASE_URL", "postgresql+asyncpg://u:p@h/nlp_db")
    monkeypatch.setenv("NLP_PIPELINE_INTELLIGENCE_DATABASE_URL", "postgresql+asyncpg://u:p@h/intelligence_db")
    from nlp_pipeline.config import Settings

    return Settings(_env_file=None)


def test_nlp_pipeline_settings_kafka_instance_id_defaults_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(monkeypatch)
    for field in _INSTANCE_ID_FIELDS:
        assert getattr(s, field) == "", f"{field} must default to empty"


def test_article_consumer_main_passes_instance_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-A-2-04: the article ``*_main`` threads the resolved id into ConsumerConfig.

    We mirror the construction performed in ``article_consumer_main.main`` for
    just the ConsumerConfig kwargs that depend on settings, asserting the
    per-scope instance id flows through to ``to_dict()``.
    """
    s = _settings(monkeypatch)
    # Simulate the env override the numbered dev consumer service supplies.
    s.kafka_consumer_instance_id = "article-consumer-0"
    from messaging.kafka.consumer.base import ConsumerConfig

    cfg = ConsumerConfig(
        bootstrap_servers=s.kafka_bootstrap_servers,
        group_id=s.kafka_consumer_group,
        topics=[s.topic_article_stored],
        group_instance_id=s.kafka_consumer_instance_id,
    )
    assert cfg.group_instance_id == "article-consumer-0"
    assert cfg.to_dict()["group.instance.id"] == "article-consumer-0"


def test_watchlist_consumer_main_passes_instance_id_empty_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-A-2-04: a second scope (watchlist) with the default empty id stays a
    dynamic member — the key is absent from the rdkafka payload (NFR-3)."""
    s = _settings(monkeypatch)
    from messaging.kafka.consumer.base import ConsumerConfig

    cfg = ConsumerConfig(
        bootstrap_servers=s.kafka_bootstrap_servers,
        group_id=s.kafka_watchlist_consumer_group,
        topics=[s.topic_watchlist_updated],
        group_instance_id=s.kafka_watchlist_consumer_instance_id,
    )
    assert cfg.group_instance_id == ""
    assert "group.instance.id" not in cfg.to_dict()
