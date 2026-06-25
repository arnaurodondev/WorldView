"""PLAN-0113 FIX-2: static-membership instance-id setting defaults empty."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit


def test_content_ingestion_settings_kafka_instance_id_defaults_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(os.environ):
        if key.startswith("CONTENT_INGESTION_"):
            monkeypatch.delenv(key, raising=False)
    from content_ingestion.config import Settings

    s = Settings(_env_file=None)
    assert s.kafka_document_ready_consumer_instance_id == ""
