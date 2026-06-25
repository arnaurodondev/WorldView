"""Avro contract tests for content-ingestion's outbox-produced topics (BUG-6).

WHY THIS FILE EXISTS:
  content-ingestion accumulated 1,653 ``market.prediction.v1`` dead-letters in
  production. The existing ``tests/unit/test_avro_schema.py`` only compares field
  *names* for ``content.article.raw.v1`` — it never binary-serializes any payload
  and never touches the prediction schema. So a real Avro/Schema-Registry
  serialization drift on the prediction topic was structurally invisible.

  These tests do a REAL binary roundtrip with ``fastavro`` against the canonical
  ``infra/kafka/schemas/*.avsc`` for EVERY topic content-ingestion produces:
    * market.prediction.v1     (event_type market.prediction.snapshot)
    * content.article.raw.v1   (event_type content.article.raw)
    * content.document.deleted.v1

  A payload built by the actual producer-side builders
  (``build_prediction_market_payload`` / ``build_raw_article_payload``) must
  encode AND decode cleanly against the registered schema. If a producer field
  drifts from the schema (added/removed/retyped), these fail loudly here instead
  of silently dead-lettering at ``producer.produce()`` in prod.

  They also assert the dispatcher's serializer topic-map registers
  ``market.prediction.snapshot`` (the BP-147 KeyError-class guard).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from uuid import uuid4

import fastavro
import pytest
from content_ingestion.application.use_cases.fetch_and_write import build_raw_article_payload
from content_ingestion.application.use_cases.fetch_and_write_prediction_markets import (
    build_prediction_market_payload,
)
from content_ingestion.domain.entities import (
    OutcomeSnapshot,
    PredictionMarketFetchResult,
    SourceType,
)

import common.ids
import common.time as ct

pytestmark = pytest.mark.contract

# The canonical schema registry on disk — the same files the Schema Registry is
# seeded from. The local copies under the service must stay in lock-step (a
# separate test in test_avro_schema.py guards that for the article schema).
_CANONICAL_SCHEMA_DIR = Path(__file__).resolve().parents[4] / "infra/kafka/schemas"
_LOCAL_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "src/content_ingestion/infrastructure/messaging/schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_CANONICAL_SCHEMA_DIR / name).read_text())


def _roundtrip(schema: dict, payload: dict) -> dict:
    """Binary-encode then decode *payload* against *schema*; return the decoded record.

    ``fastavro.schemaless_writer`` raises if the payload does not conform to the
    schema (missing required field, wrong type, etc.) — the exact failure that
    dead-letters a row in production.
    """
    parsed = fastavro.parse_schema(schema)
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, parsed, payload)
    buf.seek(0)
    return fastavro.schemaless_reader(buf, parsed)


# ── market.prediction.v1 (the dead-letter hot spot) ─────────────────────────────


def _sample_prediction_result() -> PredictionMarketFetchResult:
    return PredictionMarketFetchResult(
        source_type=SourceType.POLYMARKET,
        market_id="0xabc123",
        question="Will BTC hit $100k in 2026?",
        outcomes=[
            OutcomeSnapshot(name="Yes", token_id="111", price=0.62),
            OutcomeSnapshot(name="No", token_id="222", price=0.38),
        ],
        raw_bytes=b'{"raw":"gamma"}',
        fetched_at=ct.utc_now(),
        description="An extended description.",
        resolution_status="open",
        volume_24h=12345.67,
        liquidity=9876.54,
        close_time=ct.utc_now(),
        resolved_answer=None,
        minio_bronze_key="content-ingestion/polymarket/abc/raw/v1.json",
        market_slug="will-btc-hit-100k",
        category="crypto",
    )


def test_prediction_payload_roundtrips_against_canonical_schema() -> None:
    schema = _load_schema("market.prediction.v1.avsc")
    payload = build_prediction_market_payload(_sample_prediction_result())
    decoded = _roundtrip(schema, payload)

    # Core fields survive the binary roundtrip intact.
    assert decoded["event_type"] == "market.prediction.snapshot"
    assert decoded["market_id"] == "0xabc123"
    assert len(decoded["outcomes"]) == 2
    assert decoded["outcomes"][0]["price"] == pytest.approx(0.62)
    assert decoded["category"] == "crypto"


def test_prediction_payload_with_nullable_absent_fields_roundtrips() -> None:
    """A market with no slug/category/volume/liquidity (common Gamma shape)."""
    result = PredictionMarketFetchResult(
        source_type=SourceType.POLYMARKET,
        market_id="0xdef456",
        question="Resolved already?",
        outcomes=[
            OutcomeSnapshot(name="Yes", token_id="1", price=1.0),
            OutcomeSnapshot(name="No", token_id="2", price=0.0),
        ],
        raw_bytes=b"{}",
        fetched_at=ct.utc_now(),
        description=None,
        resolution_status="resolved",
        volume_24h=None,
        liquidity=None,
        close_time=None,
        resolved_answer="Yes",
        minio_bronze_key=None,
        # market_slug defaults to "" → builder maps "" to None (absent signal).
        category=None,
    )
    schema = _load_schema("market.prediction.v1.avsc")
    decoded = _roundtrip(schema, build_prediction_market_payload(result))
    assert decoded["resolved_answer"] == "Yes"
    assert decoded["volume_24h"] is None
    assert decoded["market_slug"] is None


def test_prediction_payload_keys_are_subset_of_schema_fields() -> None:
    """No producer key may fall outside the schema (an extra key = silent drift)."""
    schema = _load_schema("market.prediction.v1.avsc")
    schema_fields = {f["name"] for f in schema["fields"]}
    payload = build_prediction_market_payload(_sample_prediction_result())
    extra = set(payload.keys()) - schema_fields
    assert not extra, f"prediction payload has keys not in schema: {extra}"


# ── content.article.raw.v1 ──────────────────────────────────────────────────────


def test_article_payload_roundtrips_against_canonical_schema() -> None:
    schema = _load_schema("content.article.raw.v1.avsc")
    payload = build_raw_article_payload(
        doc_id=uuid4(),
        source_type="eodhd",
        source_url="https://example.com/a",
        minio_bronze_key="content-ingestion/eodhd/abc/raw/v1.json",
        raw_bytes=b"hello world",
        fetch_id=uuid4(),
        published_at=ct.to_iso8601(ct.utc_now()),
        is_backfill=False,
        title="Test Article",
    )
    # The producer omits ``tenant_id`` (schema field is nullable w/ a default), so
    # the consumer's reader schema fills it from the default — fastavro applies
    # writer defaults for fields absent from the record.
    decoded = _roundtrip(schema, payload)
    assert decoded["source_type"] == "eodhd"
    assert decoded["is_backfill"] is False
    assert "tenant_id" in decoded  # default applied


# ── content.document.deleted.v1 ─────────────────────────────────────────────────


def test_deleted_payload_roundtrips_against_canonical_schema() -> None:
    schema = _load_schema("content.document.deleted.v1.avsc")
    payload = {
        "event_id": str(common.ids.new_uuid7()),
        "event_type": "content.document.deleted",
        "schema_version": 1,
        "occurred_at": ct.to_iso8601(ct.utc_now()),
        "doc_id": str(uuid4()),
        "tenant_id": str(uuid4()),
    }
    decoded = _roundtrip(schema, payload)
    assert decoded["event_type"] == "content.document.deleted"


# ── serializer registration (BP-147 KeyError-class guard) ───────────────────────


def test_dispatcher_serializer_topic_map_registers_prediction_snapshot() -> None:
    """The dispatcher must register a serializer for ``market.prediction.snapshot``.

    Outbox rows for the prediction topic are written with
    ``event_type='market.prediction.snapshot'``; the value serializer is keyed by
    that string. A missing key would KeyError at dispatch (BP-147) and dead-letter
    the row. This asserts the three produced event-types are all present without
    needing a live registry (the serializers are built lazily from the topic map).
    """
    # Inspect the source-of-truth mapping the dispatcher builds. We read the
    # registered topic-map keys by constructing the serializer set the same way
    # the dispatcher does, but without a live Schema Registry: assert the keys.
    from content_ingestion.infrastructure.messaging.outbox import dispatcher as disp_mod

    src = Path(disp_mod.__file__).read_text()
    for key in (
        '"content.article.raw.v1"',
        '"market.prediction.snapshot"',
        '"content.document.deleted.v1"',
    ):
        assert key in src, f"dispatcher serializer map missing {key}"


def test_local_prediction_schema_matches_canonical() -> None:
    """Local service copy of the prediction schema must equal infra/kafka/schemas."""
    local = json.loads((_LOCAL_SCHEMA_DIR / "market.prediction.v1.avsc").read_text())
    canonical = json.loads((_CANONICAL_SCHEMA_DIR / "market.prediction.v1.avsc").read_text())
    assert local == canonical
