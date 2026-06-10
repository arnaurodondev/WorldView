"""Base librdkafka client config shared by every producer and consumer.

PLAN-0093 Wave A-2 (audit ref F-LOG-003) — fixes the "21 consumers silently
stuck on stale Kafka IP after broker restart" failure mode by forcing
librdkafka to:

1. Re-resolve DNS every 30 seconds (``broker.address.ttl=30000``).
   The librdkafka default of 1000 ms is documented to be buggy in practice:
   once a TCP connection is established the resolver cache is not consulted
   again, so a broker rotation that changes the broker IP can leave a healthy
   client connected to a stale address with no broker on the other end.
   30 s strikes a balance between fast failover and resolver-load.

2. Force IPv4 (``broker.address.family=v4``).
   IPv6-only DNS records cause silent connect-failures on hosts whose
   networking stack does not have outbound IPv6 — most Compose / k3s networks
   fall into that bucket.  Pinning v4 removes a class of "connects in dev,
   times out in CI" surprises.

These two keys are spread into every librdkafka config dict BEFORE the
user-provided keys, so a service-specific override (e.g. a future
``broker.address.ttl=10000``) still wins.  The module is intentionally
free of any confluent_kafka import so it stays cheap to load and importable
from environments without the C library.
"""

from __future__ import annotations

from typing import Any

# ── Base librdkafka client configuration ──────────────────────────────────────
#
# Both producers and consumers route through ``apply_base_rdkafka_config`` so
# the two keys below land on EVERY client we construct.  Changing the value
# here changes it everywhere in one shot — that is the explicit point of the
# module.
_BASE_RDKAFKA_CONFIG: dict[str, Any] = {
    # Re-resolve broker DNS every 30 s.  See module docstring for rationale.
    "broker.address.ttl": 30_000,
    # Force IPv4 -- avoid IPv6-only resolution surprises in container networks.
    "broker.address.family": "v4",
    # ── PLAN-0109 F-1-03: keepalive + reconnect tuning ──────────────────────
    # Root cause: macOS host-sleep silently breaks TCP connections without
    # sending FIN/RST.  librdkafka then sits on a stale socket until the next
    # message attempt fails, which (with default 5-minute delivery timeout and
    # exponential broker backoff) caused the 2026-05-20 14-hour dispatcher
    # stall.  These keys force the kernel to probe the connection, cap the
    # reconnect backoff, and refresh metadata regularly so a stale leader is
    # noticed in <= 3 minutes instead of hours.  Filed as BP-661.
    "socket.keepalive.enable": True,
    "socket.timeout.ms": 30_000,
    "socket.connection.setup.timeout.ms": 30_000,
    "reconnect.backoff.ms": 500,
    "reconnect.backoff.max.ms": 10_000,
    "metadata.max.age.ms": 180_000,
    "metadata.request.timeout.ms": 30_000,
    # Note: ``delivery.timeout.ms`` is producer-only and is set on the
    # ``KafkaProducerConfig`` dataclass (raised to 120_000 in F-1-03) rather
    # than here so consumers don't pick up an irrelevant key.
}


def get_base_rdkafka_config() -> dict[str, Any]:
    """Return a fresh copy of the base librdkafka client config.

    Returns a new dict on every call so callers can mutate the result
    without affecting other clients or the module-level constant.
    """
    return dict(_BASE_RDKAFKA_CONFIG)


def apply_base_rdkafka_config(user_config: dict[str, Any]) -> dict[str, Any]:
    """Merge *user_config* on top of the base librdkafka config.

    Order matters: the base keys are placed first, then ``user_config`` is
    spread on top.  That means a caller (typically the existing
    ``ConsumerConfig.to_dict()`` / ``KafkaProducerConfig.to_dict()``) can
    still override either base key without further plumbing.

    Args:
        user_config: Caller-provided librdkafka config dict.  Not mutated.

    Returns:
        A new dict containing both base keys and the caller's keys, with
        the caller's values taking precedence on collision.
    """
    merged: dict[str, Any] = get_base_rdkafka_config()
    merged.update(user_config)
    return merged
