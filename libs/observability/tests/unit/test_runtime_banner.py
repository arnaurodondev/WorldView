"""Tests for observability.runtime_banner.log_runtime_banner (PLAN-0107 §B.2)."""

from __future__ import annotations

import pytest
import structlog

from observability.runtime_banner import log_runtime_banner

pytestmark = pytest.mark.unit


def test_masks_secret_keys() -> None:
    """Keys matching the secret pattern (incl. nested) must be masked to '***'."""
    deps = {
        "api_token": "abc",
        "broker": "kafka:9092",
        "nested": {"db_password": "xyz", "host": "pg"},
    }
    with structlog.testing.capture_logs() as cap:
        log_runtime_banner("test-svc", dependencies=deps)

    # Find the single event we emitted; capture_logs gathers any
    # contemporaneous events, but this test only emits one.
    assert len(cap) == 1
    event = cap[0]
    masked = event["dependencies"]

    assert masked["api_token"] == "***"  # noqa: S105 — test fixture, not a real secret
    assert masked["broker"] == "kafka:9092"
    # Nested masking
    assert masked["nested"]["db_password"] == "***"  # noqa: S105 — test fixture
    assert masked["nested"]["host"] == "pg"


def test_dependency_shape_and_uptime() -> None:
    """The emitted event must have the documented shape."""
    with structlog.testing.capture_logs() as cap:
        log_runtime_banner("worker-x", dependencies={"broker": "kafka:9092"})

    assert len(cap) == 1
    event = cap[0]

    assert event["event"] == "worker-x_ready"
    assert event["service_name"] == "worker-x"
    assert "dependencies" in event
    assert event["dependencies"] == {"broker": "kafka:9092"}
    # Uptime is captured at import time so it can be 0 on a very fast
    # boot, but must never be negative.
    assert event["uptime_seconds_since_boot"] >= 0
    assert isinstance(event["registered_metric_families"], int)
