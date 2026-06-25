"""Producer reconnect / keep-alive config test.

PLAN-0109 Wave F-1 / task T-F-1-04.

WHY THIS FILE EXISTS
====================
The 2026-05-20 outage saw the portfolio outbox dispatcher sit idle for ~14h
because the macOS host went to sleep, the kernel never sent FIN/RST to the
Kafka broker, and librdkafka happily kept reusing the now-dead TCP socket.
The fix (T-F-1-03) wires a handful of keep-alive / reconnect tuning keys into
``libs.messaging.kafka_config._BASE_RDKAFKA_CONFIG`` plus raises the producer
``delivery.timeout.ms`` from 30s -> 120s so the retry budget actually surfaces
a failure (and triggers a reconnect) instead of silently lapsing.

INTEGRATION TEST GAP
====================
The "real" version of this test should:

1. ``testcontainers.kafka.KafkaContainer().start()``
2. produce one message, await delivery callback,
3. ``docker pause`` the broker container for 30s,
4. ``docker unpause``,
5. produce a second message and assert delivery within
   ``delivery.timeout.ms``.

We currently have *no* testcontainers harness in ``libs/messaging/tests/``
(verified 2026-06-10 -- zero imports of ``testcontainers`` under the package).
Standing one up requires Docker-in-CI, a wired-up ``KafkaContainer`` fixture,
and the confluent-kafka C library available in the test image.  That is
infra work beyond the F-1 wave's "0.5 d, LOW risk" budget.

So this file ships the **unit-fallback** the wave spec explicitly allows:
verify the new config keys are present, correctly typed, and propagate into a
real ``KafkaProducerConfig.to_dict()`` so a future refactor cannot silently
drop them.  The TODO below tracks the integration upgrade.

TODO(PLAN-0109 follow-up): replace the unit-fallback below with the broker
pause/unpause flow once ``libs/messaging`` gains a testcontainers fixture.
Tracking issue: F-1-04 (see ``docs/plans/0109-platform-remediation-plan.md``).
"""

from __future__ import annotations

import pytest

from messaging.kafka.producer import KafkaProducerConfig
from messaging.kafka_config import _BASE_RDKAFKA_CONFIG, get_base_rdkafka_config

# These tests are pure config-shape assertions -- no broker required.
pytestmark = pytest.mark.unit


# The full list of keep-alive / reconnect knobs that T-F-1-03 added to the
# base config.  Centralised here so the assertions below stay readable and a
# single rename only needs editing in one place.
EXPECTED_KEEPALIVE_KEYS: dict[str, object] = {
    # OS-level TCP keep-alive probes -- without this the kernel never notices
    # a half-open socket after host-sleep.
    "socket.keepalive.enable": True,
    # Hard cap on a single socket read/write so a stalled broker surfaces in
    # 30s instead of librdkafka's much-longer default.
    "socket.timeout.ms": 30_000,
    # Bound the TCP-handshake setup time so a flaky DNS resolve fails fast.
    "socket.connection.setup.timeout.ms": 30_000,
    # Reconnect backoff envelope: start at 500ms, cap at 10s.  Keeps a
    # flapping broker from being hammered while still healing within ~10s
    # under normal recovery.
    "reconnect.backoff.ms": 500,
    "reconnect.backoff.max.ms": 10_000,
    # Force metadata refresh every 3 minutes so a stale leader/topic
    # discovery cannot stall delivery beyond that window.
    "metadata.max.age.ms": 180_000,
    "metadata.request.timeout.ms": 30_000,
}


class TestKeepaliveConfigPresentInBase:
    """Each new F-1-03 key must appear in the module-level base config dict.

    These are deliberately individual tests (one per key) so a failure points
    straight at the missing/renamed knob rather than a single mega-assertion.
    """

    @pytest.mark.parametrize(("key", "expected"), list(EXPECTED_KEEPALIVE_KEYS.items()))
    def test_key_present_with_expected_value(self, key: str, expected: object) -> None:
        assert key in _BASE_RDKAFKA_CONFIG, f"{key} missing from _BASE_RDKAFKA_CONFIG"
        assert _BASE_RDKAFKA_CONFIG[key] == expected, f"{key} expected {expected!r}, got {_BASE_RDKAFKA_CONFIG[key]!r}"

    def test_get_base_rdkafka_config_includes_all_keepalive_keys(self) -> None:
        """``get_base_rdkafka_config()`` returns a fresh copy on every call.

        Verify that every key we added survives the copy -- a defensive
        regression test against someone accidentally hand-picking keys.
        """
        cfg = get_base_rdkafka_config()
        for key, expected in EXPECTED_KEEPALIVE_KEYS.items():
            assert cfg[key] == expected


# BP-704: the producer now carries its OWN faster connection-resilience
# overrides (see ``messaging.kafka.producer.KafkaProducerConfig`` and
# ``tests/unit/test_producer_connection_resilience.py``).  Because producer
# keys are spread on TOP of the base, the producer's ``to_dict()`` value for
# these keys is the FAST override, not the slower base value asserted above.
# This is an intentional improvement over the 30s-then-wedge behaviour, not a
# weakening: the keep-alive contract still holds, the connect just heals
# faster.  The map below records the value the *producer* is expected to emit.
PRODUCER_OVERRIDDEN_VALUES: dict[str, object] = {
    "socket.connection.setup.timeout.ms": 10_000,
    "reconnect.backoff.ms": 250,
    "reconnect.backoff.max.ms": 5_000,
    "metadata.max.age.ms": 60_000,
}


class TestProducerInheritsKeepaliveKeys:
    """End-to-end check: a real ``KafkaProducerConfig`` carries the keep-alive
    keys, using the producer override value where BP-704 tightened them.

    The producer goes through ``apply_base_rdkafka_config(...)`` which spreads
    the base on the bottom and the producer's own keys on top.  Keys the
    producer does not override keep their base value; the four BP-704 keys
    take the faster producer value.
    """

    @pytest.mark.parametrize("key", list(EXPECTED_KEEPALIVE_KEYS))
    def test_producer_config_carries_key(self, key: str) -> None:
        cfg = KafkaProducerConfig(bootstrap_servers="kafka:9092").to_dict()
        assert key in cfg, f"producer.to_dict() missing {key}"
        # Use the producer override value where one exists (BP-704), else the
        # shared-base keep-alive value (PLAN-0109 F-1-03).
        expected = PRODUCER_OVERRIDDEN_VALUES.get(key, EXPECTED_KEEPALIVE_KEYS[key])
        assert cfg[key] == expected


class TestDeliveryTimeoutRaised:
    """``delivery.timeout.ms`` must be 120_000ms so a retry actually happens.

    Pre-F-1-03 the default was 30_000ms (30s) which, combined with
    librdkafka's exponential broker backoff, meant a single stale TCP socket
    could exhaust the retry budget before the kernel even noticed the
    connection was dead.  Raising to 120_000ms gives reconnect logic enough
    headroom to recover.
    """

    def test_producer_delivery_timeout_default_is_120s(self) -> None:
        cfg = KafkaProducerConfig()
        assert cfg.delivery_timeout_ms == 120_000

    def test_producer_to_dict_delivery_timeout_is_120s(self) -> None:
        cfg_dict = KafkaProducerConfig().to_dict()
        assert cfg_dict["delivery.timeout.ms"] == 120_000

    def test_delivery_timeout_not_in_base_config(self) -> None:
        """``delivery.timeout.ms`` is producer-only.

        Keeping it on the dataclass (not in the shared base) avoids polluting
        consumer config dicts with an irrelevant key.  This test pins the
        layering decision so a future refactor doesn't quietly move it.
        """
        assert "delivery.timeout.ms" not in _BASE_RDKAFKA_CONFIG
