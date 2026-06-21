"""Unit tests for producer connection-resilience config (BP-704).

The market-ingestion / portfolio / market-data / content-* outbox dispatchers
wedge with rdkafka ``Connection setup timed out in state CONNECT (after
~31000ms)`` to ``kafka:29092`` and never recover without a restart.  ~31s ==
librdkafka's default ``socket.connection.setup.timeout.ms`` (30s), which the
shared base config (owned by the consumer/reconnect workstream) still pins.

The producer therefore carries its OWN faster connection knobs that override
the slow base values (producer keys are spread on top of the base, so they win
on collision).  These tests pin:

1. the hardened keys are present in ``to_dict()`` with fast defaults,
2. the producer overrides the slow shared-base values (does NOT inherit 30s),
3. the keys are env-overridable (configurable per deployment),
4. R19: nothing weakens the existing PLAN-0109 keep-alive contract.
"""

from __future__ import annotations

import importlib

import pytest

from messaging.kafka.producer import KafkaProducerConfig
from messaging.kafka_config import _BASE_RDKAFKA_CONFIG

pytestmark = pytest.mark.unit


# Fast connection-resilience defaults the producer must emit so a lost
# connection re-establishes in seconds rather than wedging for ~31s.
EXPECTED_FAST_KEYS: dict[str, object] = {
    "socket.connection.setup.timeout.ms": 10_000,
    "request.timeout.ms": 20_000,
    "reconnect.backoff.ms": 250,
    "reconnect.backoff.max.ms": 5_000,
    "metadata.max.age.ms": 60_000,
    "connections.max.idle.ms": 240_000,
}


class TestProducerEmitsFastConnectionKeys:
    @pytest.mark.parametrize(("key", "expected"), list(EXPECTED_FAST_KEYS.items()))
    def test_key_present_with_fast_default(self, key: str, expected: object) -> None:
        cfg = KafkaProducerConfig(bootstrap_servers="kafka:9092").to_dict()
        assert key in cfg, f"producer.to_dict() missing {key}"
        assert cfg[key] == expected, f"{key}: expected {expected!r}, got {cfg[key]!r}"

    def test_connection_setup_timeout_is_faster_than_base_30s(self) -> None:
        """The whole point: producer must NOT inherit the slow 30s base value.

        If the shared base (consumer-owned) still pins 30s, the producer
        override must win and bring it down to 10s.
        """
        cfg = KafkaProducerConfig(bootstrap_servers="kafka:9092").to_dict()
        assert cfg["socket.connection.setup.timeout.ms"] == 10_000
        # And confirm we are genuinely overriding a slower base value, i.e.
        # this is a real override, not a coincidental match.
        assert _BASE_RDKAFKA_CONFIG["socket.connection.setup.timeout.ms"] == 30_000
        assert cfg["socket.connection.setup.timeout.ms"] < _BASE_RDKAFKA_CONFIG["socket.connection.setup.timeout.ms"]

    def test_metadata_max_age_overrides_slower_base(self) -> None:
        cfg = KafkaProducerConfig(bootstrap_servers="kafka:9092").to_dict()
        assert cfg["metadata.max.age.ms"] == 60_000
        assert cfg["metadata.max.age.ms"] < _BASE_RDKAFKA_CONFIG["metadata.max.age.ms"]

    def test_keepalive_still_enabled_for_producer(self) -> None:
        """R19 / PLAN-0109: keep-alive must remain on (inherited from base)."""
        cfg = KafkaProducerConfig(bootstrap_servers="kafka:9092").to_dict()
        assert cfg["socket.keepalive.enable"] is True

    def test_delivery_timeout_unchanged(self) -> None:
        """PLAN-0109 F-1-03 contract must hold (no weakening)."""
        cfg = KafkaProducerConfig().to_dict()
        assert cfg["delivery.timeout.ms"] == 120_000

    def test_request_timeout_within_delivery_budget(self) -> None:
        """request.timeout.ms must fit inside delivery.timeout.ms so retries
        actually get attempted (rdkafka requires request <= delivery)."""
        cfg = KafkaProducerConfig().to_dict()
        assert cfg["request.timeout.ms"] <= cfg["delivery.timeout.ms"]


class TestProducerConnectionKeysAreEnvConfigurable:
    """Each knob must be overridable via env so deployments can re-tune."""

    @pytest.mark.parametrize(
        ("env_var", "field_name", "key", "value"),
        [
            (
                "KAFKA_PRODUCER_CONN_SETUP_TIMEOUT_MS",
                "socket_connection_setup_timeout_ms",
                "socket.connection.setup.timeout.ms",
                7_500,
            ),
            ("KAFKA_PRODUCER_REQUEST_TIMEOUT_MS", "request_timeout_ms", "request.timeout.ms", 15_000),
            ("KAFKA_PRODUCER_RECONNECT_BACKOFF_MS", "reconnect_backoff_ms", "reconnect.backoff.ms", 100),
            ("KAFKA_PRODUCER_RECONNECT_BACKOFF_MAX_MS", "reconnect_backoff_max_ms", "reconnect.backoff.max.ms", 3_000),
            ("KAFKA_PRODUCER_METADATA_MAX_AGE_MS", "metadata_max_age_ms", "metadata.max.age.ms", 45_000),
            ("KAFKA_PRODUCER_CONNECTIONS_MAX_IDLE_MS", "connections_max_idle_ms", "connections.max.idle.ms", 120_000),
        ],
    )
    def test_env_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        env_var: str,
        field_name: str,
        key: str,
        value: int,
    ) -> None:
        monkeypatch.setenv(env_var, str(value))
        # default_factory reads the env at instantiation time.
        cfg = KafkaProducerConfig(bootstrap_servers="kafka:9092")
        assert getattr(cfg, field_name) == value
        assert cfg.to_dict()[key] == value

    def test_malformed_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A typo in an env var must never wedge startup -- fall back safely."""
        monkeypatch.setenv("KAFKA_PRODUCER_CONN_SETUP_TIMEOUT_MS", "not-an-int")
        cfg = KafkaProducerConfig(bootstrap_servers="kafka:9092")
        assert cfg.socket_connection_setup_timeout_ms == 10_000

    def test_empty_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAFKA_PRODUCER_REQUEST_TIMEOUT_MS", "")
        cfg = KafkaProducerConfig(bootstrap_servers="kafka:9092")
        assert cfg.request_timeout_ms == 20_000


def test_module_imports_cleanly() -> None:
    """Defensive: the env-reading helper must not break module import."""
    mod = importlib.import_module("messaging.kafka.producer")
    assert hasattr(mod, "KafkaProducerConfig")
