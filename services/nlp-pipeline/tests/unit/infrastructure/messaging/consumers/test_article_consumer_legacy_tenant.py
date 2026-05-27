"""PLAN-0096 Wave 4 (BP-575) — Legacy tenant_id passthrough regression tests.

Pre-PLAN-0086 Wave A-1 Avro article payloads have no ``tenant_id`` field.
Migration 0020 added ``NOT NULL`` on ``entity_mentions.tenant_id``.  Without a
sentinel, the consumer would die on every legacy message and the topic would
stall (BP-575).  These tests pin the sentinel-substitution behaviour:

* T-W4-01 — unit test: payload without ``tenant_id`` → sentinel applied +
  WARN log emitted with ``article_id`` / ``topic`` / ``partition`` / ``offset``.
* T-W4-04 — regression test: simulate the exact pre-PLAN-0086 Avro shape
  (no ``tenant_id`` field anywhere, headers also empty) and assert the
  consumer accepts it with the sentinel and does NOT raise.

We exercise ``process_message`` directly with ``_run_pipeline`` patched out so
the test stays a true unit test (no DB, no Kafka, no MinIO).  All we care
about is the tenant-resolution branch at the top of ``process_message``.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)
from structlog.testing import capture_logs

from common.ids import PUBLIC_TENANT_ID  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings() -> MagicMock:
    """Minimal Settings stub; ``process_message`` only reads ``silver_bucket``."""
    s = MagicMock()
    s.silver_bucket = "silver"
    s.min_word_count = 50
    return s


def _make_session_factory() -> tuple[AsyncMock, MagicMock]:
    """Async context-manager factory yielding a mocked session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = cm
    return session, factory


def _make_consumer() -> ArticleProcessingConsumer:
    """Build a consumer with all I/O mocked so process_message can run dry."""
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    _nlp_s, nlp_sf = _make_session_factory()
    _intel_s, intel_sf = _make_session_factory()

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-group",
        topics=["content.article.stored.v1"],
    )
    return ArticleProcessingConsumer(
        config=config,
        settings=_make_settings(),
        nlp_session_factory=nlp_sf,
        intelligence_session_factory=intel_sf,
        storage=MagicMock(),
        watchlist_cache=MagicMock(),
        ner_client=MagicMock(),
        embedding_client=MagicMock(),
        extraction_client=MagicMock(),
        backpressure=MagicMock(),
    )


def _legacy_payload(doc_id: uuid.UUID) -> dict[str, object]:
    """An exact pre-PLAN-0086 ``content.article.stored.v1`` payload shape.

    Critically: NO ``tenant_id`` field anywhere.  This mirrors the 94 stuck
    messages from the 2026-05-26 DLQ-stall investigation report.
    """
    return {
        "doc_id": str(doc_id),
        "minio_silver_key": "silver/legacy/foo.json",
        "source_type": "finnhub",
        "title": "Legacy headline",
        "is_backfill": False,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestLegacyTenantPassthrough:
    """T-W4-01 + T-W4-04: missing tenant_id → sentinel substitution + WARN."""

    @pytest.mark.asyncio
    async def test_missing_tenant_id_substitutes_public_sentinel(self) -> None:
        """When the payload + headers carry no tenant_id, ``process_message``
        must substitute :data:`PUBLIC_TENANT_ID` and forward it to
        ``_run_pipeline`` rather than raising or passing ``None``.
        """
        consumer = _make_consumer()
        doc_id = uuid.uuid4()

        # Patch the routing-decision lookup so idempotency check returns None,
        # and patch _run_pipeline so we can capture the kwargs without running
        # any real pipeline work.  Also patch the source-metadata write.
        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.RoutingDecisionRepository",
            ) as routing_repo_cls,
            patch.object(consumer, "_run_pipeline", new=AsyncMock()) as run_pipeline_mock,
            patch.object(consumer, "_write_source_metadata", new=AsyncMock()),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.extract_url_from_silver",
                new=AsyncMock(return_value=None),
            ),
        ):
            routing_repo_cls.return_value.get_by_doc = AsyncMock(return_value=None)

            await consumer.process_message(
                key=None,
                value=_legacy_payload(doc_id),
                headers={},
            )

        run_pipeline_mock.assert_awaited_once()
        kwargs = run_pipeline_mock.await_args.kwargs
        assert (
            kwargs["tenant_id"] == PUBLIC_TENANT_ID
        ), f"Expected legacy passthrough sentinel, got tenant_id={kwargs['tenant_id']!r}"

    @pytest.mark.asyncio
    async def test_missing_tenant_id_emits_structured_warn(self) -> None:
        """The sentinel substitution must be visible to operators via a
        structured WARN log that includes article_id, topic, partition and
        offset (the fields needed to triage a legacy-passthrough burst).
        """
        consumer = _make_consumer()
        doc_id = uuid.uuid4()

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.RoutingDecisionRepository",
            ) as routing_repo_cls,
            patch.object(consumer, "_run_pipeline", new=AsyncMock()),
            patch.object(consumer, "_write_source_metadata", new=AsyncMock()),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.extract_url_from_silver",
                new=AsyncMock(return_value=None),
            ),
            capture_logs() as log_output,
        ):
            routing_repo_cls.return_value.get_by_doc = AsyncMock(return_value=None)

            await consumer.process_message(
                key=None,
                value=_legacy_payload(doc_id),
                headers={"__partition": "3", "__offset": "12345"},
            )

        events = [e for e in log_output if e.get("event") == "article_consumer.legacy_tenant_id_sentinel_applied"]
        assert len(events) == 1, f"expected exactly one sentinel-applied warn, got {log_output}"
        evt = events[0]
        assert evt["log_level"] == "warning"
        assert evt["article_id"] == str(doc_id)
        assert evt["topic"] == "content.article.stored.v1"
        assert evt["partition"] == "3"
        assert evt["offset"] == "12345"
        assert evt["sentinel"] == str(PUBLIC_TENANT_ID)

    @pytest.mark.asyncio
    async def test_present_tenant_id_does_not_trigger_sentinel(self) -> None:
        """Regression: a payload that does carry a valid tenant_id must NOT
        be sentinel-substituted and must NOT emit the WARN.  Without this
        guard the sentinel would silently overwrite real tenants.
        """
        consumer = _make_consumer()
        doc_id = uuid.uuid4()
        real_tenant = uuid.uuid4()

        payload = _legacy_payload(doc_id) | {"tenant_id": str(real_tenant)}

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.RoutingDecisionRepository",
            ) as routing_repo_cls,
            patch.object(consumer, "_run_pipeline", new=AsyncMock()) as run_pipeline_mock,
            patch.object(consumer, "_write_source_metadata", new=AsyncMock()),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.extract_url_from_silver",
                new=AsyncMock(return_value=None),
            ),
            capture_logs() as log_output,
        ):
            routing_repo_cls.return_value.get_by_doc = AsyncMock(return_value=None)

            await consumer.process_message(key=None, value=payload, headers={})

        run_pipeline_mock.assert_awaited_once()
        assert run_pipeline_mock.await_args.kwargs["tenant_id"] == real_tenant
        events = [e for e in log_output if e.get("event") == "article_consumer.legacy_tenant_id_sentinel_applied"]
        assert events == [], "Sentinel must not fire when a real tenant is present"

    @pytest.mark.asyncio
    async def test_pre_plan_0086_avro_payload_accepted_without_raise(self) -> None:
        """T-W4-04 regression: simulate the exact pre-PLAN-0086 Avro envelope
        (no ``tenant_id`` field, empty headers) and assert process_message
        completes without raising.  Before this fix the same payload looped
        forever on the IntegrityError shown in the 2026-05-26 audit.
        """
        consumer = _make_consumer()
        doc_id = uuid.uuid4()

        with (
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.RoutingDecisionRepository",
            ) as routing_repo_cls,
            patch.object(consumer, "_run_pipeline", new=AsyncMock()),
            patch.object(consumer, "_write_source_metadata", new=AsyncMock()),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.extract_url_from_silver",
                new=AsyncMock(return_value=None),
            ),
        ):
            routing_repo_cls.return_value.get_by_doc = AsyncMock(return_value=None)

            # Must not raise — the pre-fix code raised IntegrityError downstream.
            await consumer.process_message(
                key=None,
                value=_legacy_payload(doc_id),
                headers={},
            )
