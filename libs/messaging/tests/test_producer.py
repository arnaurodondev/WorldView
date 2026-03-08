"""Tests for Kafka producer configuration and value types (T-032)."""

from __future__ import annotations

import pytest

from messaging.kafka.producer import (
    KafkaEventValueSerializer,
    KafkaProducerConfig,
    OutboxKafkaValue,
)


class TestKafkaProducerConfig:
    def test_defaults(self) -> None:
        cfg = KafkaProducerConfig()
        assert cfg.acks == "all"
        assert cfg.enable_idempotence is True
        assert cfg.compression_type == "snappy"
        assert cfg.retries == 5
        assert "localhost:9092" in cfg.bootstrap_servers

    def test_to_dict_keys(self) -> None:
        cfg = KafkaProducerConfig(bootstrap_servers="broker:9092")
        d = cfg.to_dict()
        assert d["bootstrap.servers"] == "broker:9092"
        assert d["acks"] == "all"
        assert d["enable.idempotence"] is True
        assert "linger.ms" in d
        assert "batch.size" in d
        assert "delivery.timeout.ms" in d

    def test_custom_values(self) -> None:
        cfg = KafkaProducerConfig(linger_ms=50, batch_size=32_768)
        d = cfg.to_dict()
        assert d["linger.ms"] == 50
        assert d["batch.size"] == 32_768


class TestOutboxKafkaValue:
    def test_construction(self) -> None:
        val = OutboxKafkaValue(event_type="market.dataset.fetched", payload={"key": "v1/foo"})
        assert val.event_type == "market.dataset.fetched"
        assert val.payload == {"key": "v1/foo"}

    def test_to_dict(self) -> None:
        val = OutboxKafkaValue(event_type="portfolio.events.v1", payload={"id": "123"})
        d = val.to_dict()
        assert d["event_type"] == "portfolio.events.v1"
        assert d["payload"] == {"id": "123"}

    def test_empty_payload(self) -> None:
        val = OutboxKafkaValue(event_type="test.event", payload={})
        assert val.to_dict()["payload"] == {}


class TestKafkaEventValueSerializer:
    def test_raises_on_unknown_event_type(self) -> None:
        serializer = KafkaEventValueSerializer(serializers={})
        value = OutboxKafkaValue(event_type="unknown.event", payload={})
        with pytest.raises(KeyError, match=r"unknown\.event"):
            serializer(value, ctx=None)

    def test_returns_none_for_none_value(self) -> None:
        serializer = KafkaEventValueSerializer(serializers={})
        assert serializer(None, ctx=None) is None

    def test_routes_to_correct_serializer(self) -> None:
        captured: list[tuple] = []

        def fake_serializer(val: object, ctx: object) -> bytes:
            captured.append((val, ctx))
            return b"serialized"

        serializer = KafkaEventValueSerializer(serializers={"my.event": fake_serializer})
        value = OutboxKafkaValue(event_type="my.event", payload={"x": 1})
        result = serializer(value, ctx="ctx_obj")
        assert result == b"serialized"
        assert len(captured) == 1
        assert captured[0][1] == "ctx_obj"


class TestRootImport:
    def test_import_from_root(self) -> None:
        from messaging import (  # noqa: F401
            KafkaProducerConfig,
            OutboxKafkaValue,
            build_serializing_producer,
        )
