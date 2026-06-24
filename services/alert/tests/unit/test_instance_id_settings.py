"""PLAN-0113 FIX-2: per-scope static-membership instance-id settings default empty.

These settings opt a consumer into static group membership (KIP-345). The
default MUST be the empty string so a service that does not set them is
behaviourally unchanged (NFR-3 — byte-identical rdkafka config).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit


def _settings(monkeypatch: pytest.MonkeyPatch):  # - test helper
    # Strip any ALERT_* env so we test pure field defaults, not dev.local.env.
    for key in list(os.environ):
        if key.startswith("ALERT_"):
            monkeypatch.delenv(key, raising=False)
    from alert.config import Settings

    return Settings(_env_file=None)


def test_alert_settings_kafka_instance_id_defaults_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(monkeypatch)
    assert s.kafka_intelligence_consumer_instance_id == ""
    assert s.kafka_watchlist_consumer_instance_id == ""
