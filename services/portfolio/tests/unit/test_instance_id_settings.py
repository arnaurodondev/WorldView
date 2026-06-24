"""PLAN-0113 FIX-2: static-membership instance-id setting defaults empty."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit


def test_portfolio_settings_kafka_instance_id_defaults_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(os.environ):
        if key.startswith("PORTFOLIO_"):
            monkeypatch.delenv(key, raising=False)
    # storage_access_key / storage_secret_key have no defaults (C-001).
    monkeypatch.setenv("PORTFOLIO_STORAGE_ACCESS_KEY", "test-key")
    monkeypatch.setenv("PORTFOLIO_STORAGE_SECRET_KEY", "test-secret")
    from portfolio.config import Settings

    s = Settings(_env_file=None)
    assert s.kafka_instrument_consumer_instance_id == ""
