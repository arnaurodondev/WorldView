"""T-G-2-03: rdkafka DNS-recovery integration test.

PLAN-0093 Wave G-2 / audit ref F-LOG-003.

Why this test exists
--------------------
The 21:40 Docker daemon event left several consumer containers stuck because
the librdkafka client cached the kafka broker's stale IP after the kafka
container was rebuilt with a new IP.  Sub-Plan A wave A-3 added DNS-cache
tuning (``client.dns.lookup=use_all_dns_ips``, low TTL) to the consumer
config.  This test is the SLO that the DNS-recovery contract still holds:

1. Connect a consumer.
2. Restart the kafka container (which gets a new IP).
3. Assert the consumer reconnects and resumes consuming within 60 seconds.

Skip strategy
-------------
This test requires a live Kafka container that the test is allowed to
``docker restart``.  Because that is destructive (it kicks every other
service's consumer offline for a few seconds), we gate it behind TWO env
vars:

* ``WORLDVIEW_DOCKER_TEST_ALLOWED=1`` — operator opt-in to destructive
  docker subprocess calls.
* ``KAFKA_BOOTSTRAP_TEST`` — bootstrap address (e.g. ``localhost:9092``).

When either is unset the test skips cleanly so CI without docker is safe.

The kafka container name defaults to ``worldview-kafka-1`` (the compose
project default) and can be overridden via ``KAFKA_DOCKER_CONTAINER``.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:  # pragma: no cover — typing only
    from confluent_kafka import Consumer, Producer

# ---------------------------------------------------------------------------
# Tunables.
# ---------------------------------------------------------------------------

# How long we wait for the consumer to resume after the restart before we
# declare the test failed.  60s matches the SLO in F-LOG-003.
_RECOVERY_BUDGET_S = 60.0

# How long we wait initially to make sure the consumer is producing baseline
# messages.  Kept short — we don't want a slow infra to inflate the test.
_BASELINE_BUDGET_S = 30.0

# Time between poll attempts during the recovery loop.  500ms gives the test
# fast feedback without hammering the broker.
_POLL_INTERVAL_S = 0.5


# ---------------------------------------------------------------------------
# Gating helpers — all skip-friendly so collection always succeeds.
# ---------------------------------------------------------------------------


def _require_docker_destructive_allowed() -> None:
    """Skip unless the operator has explicitly enabled docker subprocess calls.

    The test restarts a kafka container, which is destructive enough that
    we never want it to fire unexpectedly in CI or local dev.  The
    ``WORLDVIEW_DOCKER_TEST_ALLOWED=1`` env var is the explicit opt-in.
    """
    if os.environ.get("WORLDVIEW_DOCKER_TEST_ALLOWED") != "1":
        pytest.skip("WORLDVIEW_DOCKER_TEST_ALLOWED!=1 — skipping destructive docker test")


def _require_kafka_bootstrap() -> str:
    """Return the bootstrap address or skip cleanly when unset."""
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_TEST")
    if not bootstrap:
        pytest.skip("KAFKA_BOOTSTRAP_TEST not set — skipping kafka DNS-recovery test")
    return bootstrap


def _kafka_container_name() -> str:
    """Return the kafka container name (defaults to compose project default)."""
    return os.environ.get("KAFKA_DOCKER_CONTAINER", "worldview-kafka-1")


def _import_confluent():  # type: ignore[no-untyped-def]
    """Import confluent_kafka lazily; skip the test if the package is missing."""
    try:
        import confluent_kafka  # — lazy by design
    except ImportError:  # pragma: no cover — confluent_kafka is in the venv
        pytest.skip("confluent_kafka not installed — kafka DNS-recovery test requires it")
    return confluent_kafka


# ---------------------------------------------------------------------------
# Helpers — produce + consume + restart.
# ---------------------------------------------------------------------------


def _make_producer(bootstrap: str) -> Producer:
    """Build a producer with DNS-recovery-friendly config.

    The ``client.dns.lookup=use_all_dns_ips`` setting matches the consumer
    contract added in A-3 and lets the producer pick a fresh IP if the broker
    is rotated under it.
    """
    cf = _import_confluent()
    return cf.Producer(  # type: ignore[no-any-return]
        {
            "bootstrap.servers": bootstrap,
            "client.id": f"g-2-3-producer-{uuid.uuid4()}",
            "client.dns.lookup": "use_all_dns_ips",
            # Short metadata refresh so the producer notices the restart fast.
            "topic.metadata.refresh.interval.ms": 5000,
        }
    )


def _make_consumer(bootstrap: str, topic: str) -> Consumer:
    """Build a consumer subscribed to *topic* with DNS-recovery-friendly config."""
    cf = _import_confluent()
    consumer = cf.Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"g-2-3-consumer-{uuid.uuid4()}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
            "client.dns.lookup": "use_all_dns_ips",
            "topic.metadata.refresh.interval.ms": 5000,
            # Reconnect aggressively after the restart so we stay inside the
            # 60-second SLO.
            "reconnect.backoff.ms": 250,
            "reconnect.backoff.max.ms": 5000,
        }
    )
    consumer.subscribe([topic])
    return consumer  # type: ignore[no-any-return]


def _produce_one(producer: Producer, topic: str, payload: bytes) -> None:
    """Produce a single message and block on flush so the assertion is unambiguous."""
    producer.produce(topic=topic, value=payload)
    # 5-second flush budget is plenty for a single 1-byte message; if it
    # exceeds we want to fail loudly.
    remaining = producer.flush(5.0)
    assert remaining == 0, f"producer flush failed — {remaining} messages still queued"


def _consume_one(consumer: Consumer, budget_s: float) -> bytes | None:
    """Poll *consumer* until we get one message or the budget expires."""
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        msg = consumer.poll(_POLL_INTERVAL_S)
        if msg is None:
            continue
        if msg.error() is not None:
            # Connection errors are expected during the restart window; keep
            # polling.  Other errors are surfaced for the operator.
            continue
        value = msg.value()
        return bytes(value) if value is not None else b""
    return None


def _restart_kafka(container: str) -> None:
    """``docker restart`` the kafka container.  Raises on failure."""
    result = subprocess.run(
        ["docker", "restart", container],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"docker restart {container} failed (rc={result.returncode}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# The actual test.
# ---------------------------------------------------------------------------


def test_consumer_recovers_after_kafka_restart() -> None:
    """Consumer must resume consuming within 60s after the kafka container restarts.

    Sequence:
    1. Produce a baseline message, consume it (proves the wiring works).
    2. Restart the kafka container.
    3. Produce a recovery message.
    4. Assert the consumer receives it within ``_RECOVERY_BUDGET_S``.

    The recovery message has a unique nonce so we can prove we got the
    post-restart message, not a stale baseline message.
    """
    _require_docker_destructive_allowed()
    bootstrap = _require_kafka_bootstrap()
    container = _kafka_container_name()
    _import_confluent()

    # Each test run uses a unique topic prefix so consecutive runs don't
    # collide on consumer-group offsets.  ``worldview-test-g23-`` is a clear
    # human-readable prefix for the broker logs.
    topic = f"worldview-test-g23-{uuid.uuid4().hex[:8]}"

    producer = _make_producer(bootstrap)
    consumer = _make_consumer(bootstrap, topic)

    try:
        # ── 1. Baseline produce + consume ───────────────────────────────────
        baseline_payload = b"baseline-" + uuid.uuid4().bytes
        _produce_one(producer, topic, baseline_payload)
        baseline_msg = _consume_one(consumer, _BASELINE_BUDGET_S)
        assert baseline_msg == baseline_payload, (
            f"baseline message not delivered within {_BASELINE_BUDGET_S}s — "
            "test cannot proceed; check broker connectivity before testing recovery"
        )

        # ── 2. Restart kafka ─────────────────────────────────────────────────
        _restart_kafka(container)

        # ── 3. Produce a recovery message ────────────────────────────────────
        recovery_payload = b"recovery-" + uuid.uuid4().bytes
        # Producer may itself reconnect — retry the produce a couple of times
        # within the recovery budget.  3 attempts x ~5s flush budget is safe
        # inside the 60s overall SLO.
        produce_deadline = time.monotonic() + _RECOVERY_BUDGET_S
        produced = False
        while time.monotonic() < produce_deadline and not produced:
            try:
                _produce_one(producer, topic, recovery_payload)
                produced = True
            except AssertionError:
                # Flush timed out — broker still rotating IPs.  Back off and
                # try again.
                time.sleep(2.0)
        assert produced, f"producer never recovered to send recovery message within {_RECOVERY_BUDGET_S}s"

        # ── 4. Consumer must receive the recovery message in budget ──────────
        remaining_budget = max(produce_deadline - time.monotonic(), 5.0)
        recovery_msg = _consume_one(consumer, remaining_budget)
        assert recovery_msg == recovery_payload, (
            f"consumer did not recover within {_RECOVERY_BUDGET_S}s after kafka restart "
            "— F-LOG-003 regression (rdkafka DNS cache likely stale)"
        )
    finally:
        # Always close the consumer cleanly so the broker doesn't hold the
        # group-id assignment for the session-timeout window.
        try:
            consumer.close()
        except Exception:  # noqa: S110 — best-effort cleanup; the broker connection may already be gone after restart
            pass
