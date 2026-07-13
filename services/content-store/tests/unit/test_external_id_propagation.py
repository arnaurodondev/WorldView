"""Unit tests for PLAN-0056 Wave C2b — external_id passthrough through S5.

The synthetic prediction document (S4 Wave B2) stamps
``external_id = "polymarket:<condition_id>"`` on ``content.article.raw.v1``.  S5
(content-store) must carry that value verbatim onto ``content.article.stored.v1``
so S6 can ride it onward to the KG.  These tests verify:

1. ``_parse_raw_event`` extracts external_id from the raw Avro dict (present /
   absent / empty-string paths).
2. ``_build_stored_payload`` re-emits external_id onto the stored payload.
"""

from __future__ import annotations

from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_DOC_UUID = UUID("11111111-2222-3333-4444-555555555555")
_EXTERNAL_ID = "polymarket:0xcond123"


class TestParseRawEventExternalId:
    """_parse_raw_event must propagate external_id from the Avro dict."""

    def _base_value(self) -> dict:
        return {
            "event_id": "evt-001",
            "doc_id": "doc-001",
            "source_type": "polymarket",
            "source_url": None,
            "minio_bronze_key": "key",
            "content_hash": "hash",
        }

    def test_extracts_external_id_when_present(self) -> None:
        from content_store.infrastructure.messaging.consumers.article_consumer import _parse_raw_event

        value = {**self._base_value(), "external_id": _EXTERNAL_ID}
        assert _parse_raw_event(value).external_id == _EXTERNAL_ID

    def test_returns_none_when_absent(self) -> None:
        from content_store.infrastructure.messaging.consumers.article_consumer import _parse_raw_event

        assert _parse_raw_event(self._base_value()).external_id is None

    def test_returns_none_when_empty_string(self) -> None:
        from content_store.infrastructure.messaging.consumers.article_consumer import _parse_raw_event

        value = {**self._base_value(), "external_id": ""}
        assert _parse_raw_event(value).external_id is None


class TestBuildStoredPayloadExternalId:
    """_build_stored_payload must re-emit external_id from the raw event."""

    def _make_doc(self) -> object:
        from content_store.domain.entities import CanonicalDocument

        doc = CanonicalDocument(
            id=_DOC_UUID,
            source_type="polymarket",
            content_hash="abc",
            normalized_hash="def",
        )
        # minio_silver_key must be set before building the stored payload.
        object.__setattr__(doc, "minio_silver_key", "silver/key")
        return doc

    def _make_article(self, external_id: str | None) -> object:
        from content_store.application.use_cases.process_article import RawArticleEvent

        return RawArticleEvent(
            event_id="evt-001",
            doc_id=str(_DOC_UUID),
            source_type="polymarket",
            source_url="https://polymarket.com/event/x",
            minio_bronze_key="bronze/key",
            content_hash="abc",
            title="Will X win?",
            published_at=None,
            is_backfill=False,
            external_id=external_id,
        )

    def test_stored_payload_carries_external_id(self) -> None:
        from content_store.application.use_cases.process_article import _build_stored_payload

        payload = _build_stored_payload(self._make_doc(), self._make_article(_EXTERNAL_ID))
        assert payload["external_id"] == _EXTERNAL_ID

    def test_stored_payload_external_id_none_for_normal_article(self) -> None:
        from content_store.application.use_cases.process_article import _build_stored_payload

        payload = _build_stored_payload(self._make_doc(), self._make_article(None))
        assert payload["external_id"] is None
