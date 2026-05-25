"""Unit tests for the shared rdkafka base config.

PLAN-0093 Wave A-2 (F-LOG-003).  Verifies that every producer/consumer config
dict constructed inside ``libs/messaging`` carries:

* ``broker.address.ttl == 30000``  (re-resolve DNS every 30s)
* ``broker.address.family == "v4"`` (force IPv4)

These two keys defend the platform against the "21 consumers silently stuck on
stale Kafka IP" failure mode that motivated the wave.
"""

from __future__ import annotations

import pytest

from messaging.kafka.consumer.base import ConsumerConfig
from messaging.kafka.producer import KafkaProducerConfig
from messaging.kafka_config import (
    _BASE_RDKAFKA_CONFIG,
    apply_base_rdkafka_config,
    get_base_rdkafka_config,
)

pytestmark = pytest.mark.unit


class TestBaseRdkafkaConfig:
    """The base config constant must always carry the two F-LOG-003 keys."""

    def test_base_config_has_address_ttl_30s(self) -> None:
        assert _BASE_RDKAFKA_CONFIG["broker.address.ttl"] == 30_000

    def test_base_config_has_address_family_v4(self) -> None:
        assert _BASE_RDKAFKA_CONFIG["broker.address.family"] == "v4"

    def test_get_base_rdkafka_config_returns_fresh_dict(self) -> None:
        """Callers must be free to mutate the returned dict without
        leaking back into the module-level constant.
        """
        first = get_base_rdkafka_config()
        first["broker.address.ttl"] = 1
        second = get_base_rdkafka_config()
        assert second["broker.address.ttl"] == 30_000

    def test_apply_base_rdkafka_config_user_overrides_win(self) -> None:
        """User-provided keys must win on collision so a future per-client
        override (e.g. a more aggressive DNS TTL) does not require library
        changes.
        """
        merged = apply_base_rdkafka_config({"broker.address.ttl": 1000})
        assert merged["broker.address.ttl"] == 1000
        # ``broker.address.family`` was not overridden so the base wins.
        assert merged["broker.address.family"] == "v4"

    def test_apply_base_rdkafka_config_preserves_user_keys(self) -> None:
        merged = apply_base_rdkafka_config({"bootstrap.servers": "kafka:9092"})
        assert merged["bootstrap.servers"] == "kafka:9092"
        assert merged["broker.address.ttl"] == 30_000
        assert merged["broker.address.family"] == "v4"


class TestProducerConfigCarriesBaseKeys:
    def test_broker_address_ttl_is_30s(self) -> None:
        cfg = KafkaProducerConfig(bootstrap_servers="kafka:9092").to_dict()
        assert cfg["broker.address.ttl"] == 30_000

    def test_broker_address_family_v4(self) -> None:
        cfg = KafkaProducerConfig(bootstrap_servers="kafka:9092").to_dict()
        assert cfg["broker.address.family"] == "v4"


class TestConsumerConfigCarriesBaseKeys:
    def test_broker_address_ttl_is_30s(self) -> None:
        cfg = ConsumerConfig(bootstrap_servers="kafka:9092", group_id="g").to_dict()
        assert cfg["broker.address.ttl"] == 30_000

    def test_broker_address_family_v4(self) -> None:
        cfg = ConsumerConfig(bootstrap_servers="kafka:9092", group_id="g").to_dict()
        assert cfg["broker.address.family"] == "v4"

    def test_user_config_still_present(self) -> None:
        """Adding the base keys must not stomp on the consumer's own settings."""
        cfg = ConsumerConfig(bootstrap_servers="kafka:9092", group_id="my-grp").to_dict()
        assert cfg["bootstrap.servers"] == "kafka:9092"
        assert cfg["group.id"] == "my-grp"
        assert cfg["partition.assignment.strategy"] == "cooperative-sticky"
