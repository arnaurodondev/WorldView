"""PLAN-0113 FIX-2: static-membership instance-id settings default empty."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit

_INSTANCE_ID_FIELDS = (
    "kafka_ohlcv_consumer_instance_id",
    "kafka_quotes_consumer_instance_id",
    "kafka_fundamentals_consumer_instance_id",
    "kafka_insider_transactions_consumer_instance_id",
    "kafka_intraday_resampling_consumer_instance_id",
    "kafka_prediction_market_consumer_instance_id",
)


def test_market_data_settings_kafka_instance_id_defaults_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(os.environ):
        if key.startswith("MARKET_DATA_"):
            monkeypatch.delenv(key, raising=False)
    # storage_access_key / storage_secret_key are required SecretStr fields.
    monkeypatch.setenv("MARKET_DATA_STORAGE_ACCESS_KEY", "test-key")
    monkeypatch.setenv("MARKET_DATA_STORAGE_SECRET_KEY", "test-secret")
    from market_data.config import Settings

    s = Settings(_env_file=None)
    for field in _INSTANCE_ID_FIELDS:
        assert getattr(s, field) == "", f"{field} must default to empty"
