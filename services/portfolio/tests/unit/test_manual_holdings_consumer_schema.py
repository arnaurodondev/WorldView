"""Regression tests for the manual-holdings recompute consumer schema path.

Audit 2026-07-19 (docs/audits/2026-07-19-portfolio-value-news-bug.md):
``get_schema_path`` derived the Avro schema filename with
``topic.replace('.', '_')`` → ``portfolio_holding_recompute_requested_v1.avsc``
(trailing ``_v1``), but the real file (and the producer's explicit map in
serialization.py) is ``portfolio_holding_recompute_requested.v1.avsc`` (the
version dot is preserved). The missing file made ``get_schema_path`` return
``None`` → the consumer fell back to ``json.loads()`` on Confluent-Avro bytes →
``UnicodeDecodeError`` → every recompute event dead-lettered → the ``holdings``
table stayed empty → portfolio value = $0 + no per-stock dashboard news.

These tests lock in:
  1. get_schema_path returns the correct *dotted* filename for the topic.
  2. A real Confluent-Avro message deserializes (NOT via json.loads).
  3. The missing-schema case FAILS LOUD (raises) instead of silently
     dead-lettering with a cryptic UnicodeDecodeError.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from portfolio.infrastructure.messaging.consumers.manual_holdings_consumer import (
    ManualHoldingsRecomputeConsumer,
)

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_TOPIC = "portfolio.holding.recompute_requested.v1"
_EXPECTED_FILENAME = "portfolio_holding_recompute_requested.v1.avsc"


def _make_consumer() -> ManualHoldingsRecomputeConsumer:
    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="portfolio-manual-holdings-recompute",
        topics=[_TOPIC],
    )
    return ManualHoldingsRecomputeConsumer(config=config, session_factory=MagicMock())


def test_get_schema_path_returns_dotted_filename() -> None:
    """The resolved path must keep the version dot (``.v1.avsc``), not ``_v1``."""
    consumer = _make_consumer()

    path = consumer.get_schema_path(_TOPIC)

    assert path is not None, "schema path must resolve for the recompute topic"
    assert path.endswith(_EXPECTED_FILENAME), f"expected {_EXPECTED_FILENAME}, got {path}"
    # Guard against a regression to the lossy ``replace('.', '_')`` derivation.
    assert "_v1.avsc" not in path, "schema filename must preserve the '.v1' version dot"


def test_real_confluent_avro_message_deserializes() -> None:
    """A real Confluent-Avro payload round-trips via Avro (not json.loads)."""
    consumer = _make_consumer()
    schema_path = consumer.get_schema_path(_TOPIC)
    assert schema_path is not None

    record = {
        "event_id": str(uuid4()),
        "event_type": "portfolio.holding.recompute_requested",
        "aggregate_type": "portfolio",
        "aggregate_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "occurred_at": "2026-07-19T22:46:31Z",
        "schema_version": 1,
        "correlation_id": None,
        "causation_id": None,
        "portfolio_id": str(uuid4()),
        "owner_id": str(uuid4()),
    }
    wire = serialize_confluent_avro(schema_path, record)
    # Sanity: this is genuinely Confluent-Avro (leading magic byte), the exact
    # payload shape that used to crash json.loads() with UnicodeDecodeError.
    assert wire[:1] == b"\x00"

    result = consumer.deserialize_value(wire, schema_path)

    assert result["event_id"] == record["event_id"]
    assert result["portfolio_id"] == record["portfolio_id"]
    assert result["owner_id"] == record["owner_id"]


def test_confluent_avro_without_schema_fails_loud() -> None:
    """Avro bytes with no schema path must FAIL LOUD, not json.loads() silently.

    This is the exact silent-failure the audit traced: json.loads() on the
    0x00-prefixed Confluent frame raised a cryptic UnicodeDecodeError and
    dead-lettered the event. We now raise an explicit, diagnosable error.
    """
    consumer = _make_consumer()
    schema_path = consumer.get_schema_path(_TOPIC)
    assert schema_path is not None
    wire = serialize_confluent_avro(
        schema_path,
        {
            "event_id": str(uuid4()),
            "aggregate_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "occurred_at": "2026-07-19T22:46:31Z",
            "portfolio_id": str(uuid4()),
            "owner_id": str(uuid4()),
        },
    )

    # No schema_path passed → must refuse to json.loads() the Avro bytes.
    with pytest.raises(MalformedDataError, match="Confluent-Avro payload"):
        consumer.deserialize_value(wire, None)


def test_missing_schema_file_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the mapped schema file is absent on disk, fail loud (FileNotFoundError)."""
    import portfolio.infrastructure.messaging.consumers.manual_holdings_consumer as mod

    consumer = _make_consumer()
    # Simulate a broken deploy: the topic is known but the .avsc is not packaged.
    monkeypatch.setitem(mod._TOPIC_SCHEMA_FILES, _TOPIC, "does_not_exist.v1.avsc")

    with pytest.raises(FileNotFoundError, match="not found"):
        consumer.get_schema_path(_TOPIC)


def test_plain_json_without_schema_still_supported() -> None:
    """Local-dev plain-JSON payloads (no Avro magic byte) still deserialize."""
    consumer = _make_consumer()
    payload = {"event_id": str(uuid4()), "portfolio_id": str(uuid4())}
    raw = json.dumps(payload).encode()

    result = consumer.deserialize_value(raw, None)

    assert result["event_id"] == payload["event_id"]
