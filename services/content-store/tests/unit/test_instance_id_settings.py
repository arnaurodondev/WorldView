"""PLAN-0113 FIX-2: static-membership instance-id settings default empty."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit


def test_content_store_settings_kafka_instance_id_defaults_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(os.environ):
        if key.startswith("CONTENT_STORE_"):
            monkeypatch.delenv(key, raising=False)
    from content_store.config import Settings

    s = Settings(_env_file=None)
    assert s.kafka_article_consumer_instance_id == ""
    assert s.kafka_dedup_consumer_instance_id == ""
