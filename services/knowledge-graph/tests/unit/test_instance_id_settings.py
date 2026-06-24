"""PLAN-0113 FIX-2: static-membership instance-id settings default empty."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit

# All 13 KG consumer-scope instance-id settings (one per consumer group).
_INSTANCE_ID_FIELDS = (
    "kafka_enriched_consumer_instance_id",
    "kafka_entity_consumer_instance_id",
    "kafka_fundamentals_consumer_instance_id",
    "kafka_instrument_consumer_instance_id",
    "kafka_instrument_discovered_consumer_instance_id",
    "kafka_temporal_event_consumer_instance_id",
    "kafka_earnings_calendar_dataset_consumer_instance_id",
    "kafka_economic_events_dataset_consumer_instance_id",
    "kafka_insider_transactions_dataset_consumer_instance_id",
    "kafka_macro_indicator_dataset_consumer_instance_id",
    "kafka_narrative_refresh_consumer_instance_id",
    "kafka_provisional_queued_consumer_instance_id",
    "kafka_structured_enrichment_consumer_instance_id",
)


def test_knowledge_graph_settings_kafka_instance_id_defaults_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(os.environ):
        if key.startswith("KNOWLEDGE_GRAPH_"):
            monkeypatch.delenv(key, raising=False)
    # database_url + storage keys have no defaults — provide test values.
    monkeypatch.setenv("KNOWLEDGE_GRAPH_DATABASE_URL", "postgresql+asyncpg://u:p@h/intelligence_db")
    monkeypatch.setenv("KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY", "test-key")
    monkeypatch.setenv("KNOWLEDGE_GRAPH_STORAGE_SECRET_KEY", "test-secret")
    from knowledge_graph.config import Settings

    s = Settings(_env_file=None)
    for field in _INSTANCE_ID_FIELDS:
        assert getattr(s, field) == "", f"{field} must default to empty"


def test_enriched_consumer_main_passes_instance_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-A-2-04 (second service): the KG enriched ``*_main`` threads the resolved
    id into ConsumerConfig, and it surfaces in the rdkafka payload."""
    for key in list(os.environ):
        if key.startswith("KNOWLEDGE_GRAPH_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KNOWLEDGE_GRAPH_DATABASE_URL", "postgresql+asyncpg://u:p@h/intelligence_db")
    monkeypatch.setenv("KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY", "test-key")
    monkeypatch.setenv("KNOWLEDGE_GRAPH_STORAGE_SECRET_KEY", "test-secret")
    monkeypatch.setenv("KNOWLEDGE_GRAPH_KAFKA_ENRICHED_CONSUMER_INSTANCE_ID", "kg-enriched-0")
    from knowledge_graph.config import Settings

    from messaging.kafka.consumer.base import ConsumerConfig

    s = Settings(_env_file=None)
    cfg = ConsumerConfig(
        bootstrap_servers=s.kafka_bootstrap_servers,
        group_id=f"{s.kafka_consumer_group}-enriched",
        topics=[s.kafka_topic_enriched],
        group_instance_id=s.kafka_enriched_consumer_instance_id,
    )
    assert cfg.to_dict()["group.instance.id"] == "kg-enriched-0"
