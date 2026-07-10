"""PLAN-0056 Wave C3 — source_title passthrough on the enriched event (S6).

``_enqueue_enriched`` must ride the inbound document title verbatim onto the
``nlp.article.enriched.v1`` payload as ``source_title`` so the KG
PredictionEnrichedConsumer can title the prediction temporal event and classify
per-entity polarity (for a Polymarket synthetic doc the title IS the market
question).  When the value is absent (ordinary articles / legacy events) the
payload carries ``source_title=None``.

We call ``_enqueue_enriched`` directly with a patched Avro serializer so we can
capture the exact payload dict without touching Kafka/DB/MinIO.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_BLOCK = "nlp_pipeline.infrastructure.messaging.consumers.blocks.enriched_event"
_DOC_ID = uuid.UUID("01920000-0000-7000-8000-0000000000cc")


def _routing_decision() -> MagicMock:
    rd = MagicMock()
    rd.final_routing_tier = None
    tier = MagicMock()
    tier.value = "medium"
    rd.routing_tier = tier
    rd.composite_score = 0.55
    return rd


async def _run(source_title: str | None) -> dict:
    """Invoke _enqueue_enriched and return the captured payload dict."""
    from nlp_pipeline.infrastructure.messaging.consumers.blocks.enriched_event import _enqueue_enriched

    settings = MagicMock()
    settings.topic_article_enriched = "nlp.article.enriched.v1"

    outbox_repo = AsyncMock()
    outbox_repo.add = AsyncMock()

    captured: dict = {}

    def _fake_serialize(schema_path: str, payload: dict) -> bytes:
        captured.update(payload)
        return b"\x00serialized"

    with patch(f"{_BLOCK}.serialize_confluent_avro", _fake_serialize):
        await _enqueue_enriched(
            outbox_repo=outbox_repo,
            settings=settings,
            doc_id=_DOC_ID,
            source_type="polymarket",
            source_name=None,
            external_id="polymarket:0xcond",
            source_title=source_title,
            published_at=None,
            is_backfill=False,
            routing_decision=_routing_decision(),
            sections=[],
            chunks=[],
            mentions=[],
            extraction_result={},
            correlation_id=None,
            schema_dir=Path("test-schemas"),
        )

    outbox_repo.add.assert_awaited_once()
    return captured


class TestEnrichedEventSourceTitle:
    async def test_source_title_rides_through_to_payload(self) -> None:
        payload = await _run("Will Company X miss Q3 earnings?")
        assert payload["source_title"] == "Will Company X miss Q3 earnings?"

    async def test_source_title_none_when_absent(self) -> None:
        payload = await _run(None)
        assert payload["source_title"] is None
