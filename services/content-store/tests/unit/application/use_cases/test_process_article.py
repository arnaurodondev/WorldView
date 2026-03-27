"""Unit tests for ProcessArticleUseCase."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from content_store.application.use_cases.process_article import (
    ProcessArticleUseCase,
    RawArticleEvent,
    _build_stored_payload,
    _guess_content_type,
)
from content_store.domain.entities import CanonicalDocument, DeduplicationDecision
from content_store.domain.enums import DedupOutcome, DocumentStatus

pytestmark = pytest.mark.unit


def _make_article(**overrides: object) -> RawArticleEvent:
    defaults = {
        "event_id": "evt-001",
        "doc_id": "doc-001",
        "source_type": "eodhd",
        "source_url": "https://example.com/article",
        "minio_bronze_key": "content-ingestion/eodhd/abc123/raw/v1.json",
        "content_hash": "deadbeef" * 8,
        "title": "Test Article",
        "published_at": "2026-03-01T12:00:00Z",
        "is_backfill": False,
    }
    defaults.update(overrides)
    return RawArticleEvent(**defaults)  # type: ignore[arg-type]


def _make_use_case(
    *,
    session: AsyncMock | None = None,
    document_repo: AsyncMock | None = None,
    dedup_repo: AsyncMock | None = None,
    minhash_repo: AsyncMock | None = None,
    outbox_repo: AsyncMock | None = None,
    object_store: AsyncMock | None = None,
    lsh_client: AsyncMock | None = None,
) -> ProcessArticleUseCase:
    return ProcessArticleUseCase(
        session=session or AsyncMock(),
        document_repo=document_repo or AsyncMock(),
        dedup_repo=dedup_repo or AsyncMock(),
        minhash_repo=minhash_repo or AsyncMock(),
        outbox_repo=outbox_repo or AsyncMock(),
        object_store=object_store or AsyncMock(),
        bronze_bucket="worldview-bronze",
        silver_bucket="worldview-silver",
        lsh_client=lsh_client or AsyncMock(),
    )


class TestProcessArticleUseCase:
    async def test_stage_a_duplicate_suppressed(self) -> None:
        """Stage A hit → suppressed, no DB writes."""
        dedup_repo = AsyncMock()
        existing_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        dedup_repo.check_exists.return_value = existing_id

        store = AsyncMock()
        store.get_bytes.return_value = b"<html><body>Hello</body></html>"

        uc = _make_use_case(dedup_repo=dedup_repo, object_store=store)
        article = _make_article()
        summary = await uc.execute(article)

        assert summary.suppressed is True
        assert summary.decision.outcome == DedupOutcome.DUPLICATE_EXACT
        assert summary.doc_id is None

    async def test_stage_b_duplicate_suppressed(self) -> None:
        """Stage B hit → suppressed, no DB writes."""
        dedup_repo = AsyncMock()
        existing_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        # Stage A: no match
        dedup_repo.check_exists.side_effect = [None, existing_id]

        store = AsyncMock()
        store.get_bytes.return_value = b"<html><body>Hello World</body></html>"

        uc = _make_use_case(dedup_repo=dedup_repo, object_store=store)
        summary = await uc.execute(_make_article())

        assert summary.suppressed is True
        assert summary.decision.outcome == DedupOutcome.DUPLICATE_NORMALIZED

    async def test_unique_article_stored(self) -> None:
        """Unique article → stored in silver + DB + outbox."""
        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None  # No existing hashes

        store = AsyncMock()
        store.get_bytes.return_value = (
            b"<html><body>Apple stock price rose significantly"
            b" after quarterly earnings report was released today</body></html>"
        )
        store.put_bytes.return_value = None

        document_repo = AsyncMock()
        minhash_repo = AsyncMock()
        minhash_repo.get_signature_by_doc_id.return_value = None
        outbox_repo = AsyncMock()
        session = AsyncMock()

        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(
            outcome=DedupOutcome.UNIQUE,
            stage="stage_c",
        )

        uc = _make_use_case(
            session=session,
            dedup_repo=dedup_repo,
            document_repo=document_repo,
            minhash_repo=minhash_repo,
            outbox_repo=outbox_repo,
            object_store=store,
            lsh_client=lsh_client,
        )
        summary = await uc.execute(_make_article())

        assert summary.suppressed is False
        assert summary.decision.outcome == DedupOutcome.UNIQUE
        assert summary.doc_id is not None

        # Verify DB writes happened
        document_repo.create.assert_called_once()
        dedup_repo.insert_pair.assert_called_once()
        minhash_repo.create_signature.assert_called_once()
        outbox_repo.append.assert_called_once()
        session.flush.assert_called_once()

        # Verify outbox payload
        call_kwargs = outbox_repo.append.call_args
        assert call_kwargs.kwargs["event_type"] == "content.article.stored.v1"
        assert call_kwargs.kwargs["topic"] == "content.article.stored.v1"
        assert call_kwargs.kwargs["aggregate_type"] == "document"

    async def test_corroborating_article_stored(self) -> None:
        """Corroborating article → stored with link to primary."""
        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None

        store = AsyncMock()
        store.get_bytes.return_value = (
            b"<html><body>Apple stock price rose significantly"
            b" after quarterly earnings report was released today</body></html>"
        )
        store.put_bytes.return_value = None

        matched_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(
            outcome=DedupOutcome.CORROBORATING,
            jaccard_score=0.85,
            matched_doc_id=matched_id,
            stage="stage_c",
        )

        document_repo = AsyncMock()
        uc = _make_use_case(
            dedup_repo=dedup_repo,
            document_repo=document_repo,
            object_store=store,
            lsh_client=lsh_client,
        )
        summary = await uc.execute(_make_article())

        assert summary.suppressed is False
        assert summary.decision.outcome == DedupOutcome.CORROBORATING

        # Verify corroborates_doc_id was set
        doc_arg = document_repo.create.call_args.args[0]
        assert doc_arg.corroborates_doc_id == matched_id

    async def test_same_source_duplicate_suppressed(self) -> None:
        """Same source duplicate → suppressed."""
        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None

        store = AsyncMock()
        store.get_bytes.return_value = (
            b"<html><body>Apple stock price rose significantly"
            b" after quarterly earnings report was released today</body></html>"
        )

        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(
            outcome=DedupOutcome.SAME_SOURCE_DUPLICATE,
            jaccard_score=0.95,
            matched_doc_id=UUID("01234567-89ab-cdef-0123-456789abcdef"),
            stage="stage_c",
        )

        uc = _make_use_case(dedup_repo=dedup_repo, object_store=store, lsh_client=lsh_client)
        summary = await uc.execute(_make_article())

        assert summary.suppressed is True
        assert summary.decision.outcome == DedupOutcome.SAME_SOURCE_DUPLICATE

    async def test_lsh_index_failure_does_not_break_pipeline(self) -> None:
        """LSH index failure is best-effort — pipeline continues."""
        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None

        store = AsyncMock()
        store.get_bytes.return_value = (
            b"<html><body>Apple stock price rose significantly"
            b" after quarterly earnings report was released today</body></html>"
        )
        store.put_bytes.return_value = None

        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(
            outcome=DedupOutcome.UNIQUE,
            stage="stage_c",
        )
        lsh_client.index.side_effect = RuntimeError("Valkey down")

        uc = _make_use_case(dedup_repo=dedup_repo, object_store=store, lsh_client=lsh_client)
        # Should not raise
        summary = await uc.execute(_make_article())
        assert summary.suppressed is False
        assert summary.doc_id is not None

    async def test_no_kafka_publish_in_use_case(self) -> None:
        """Verify the use case NEVER publishes to Kafka directly."""
        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None

        store = AsyncMock()
        store.get_bytes.return_value = (
            b"<html><body>Apple stock price rose significantly"
            b" after quarterly earnings report was released today</body></html>"
        )
        store.put_bytes.return_value = None

        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(
            outcome=DedupOutcome.UNIQUE,
            stage="stage_c",
        )

        outbox_repo = AsyncMock()
        uc = _make_use_case(
            dedup_repo=dedup_repo,
            object_store=store,
            lsh_client=lsh_client,
            outbox_repo=outbox_repo,
        )
        await uc.execute(_make_article())

        # Outbox append was called (outbox pattern)
        outbox_repo.append.assert_called_once()
        # Payload matches schema
        payload = outbox_repo.append.call_args.kwargs["payload"]
        assert "doc_id" in payload
        assert "content_hash" in payload
        assert "minio_silver_key" in payload


class TestGuessContentType:
    def test_eodhd_html(self) -> None:
        assert _guess_content_type("eodhd") == "html"

    def test_newsapi_html(self) -> None:
        assert _guess_content_type("newsapi") == "html"

    def test_finnhub_json(self) -> None:
        assert _guess_content_type("finnhub") == "json"

    def test_manual_text(self) -> None:
        assert _guess_content_type("manual") == "text"

    def test_unknown_defaults_html(self) -> None:
        assert _guess_content_type("unknown") == "html"


class TestPublishedAtParsing:
    """Edge case tests for published_at parsing in execute() (T-R2-3-03)."""

    async def test_invalid_date_results_in_none(self) -> None:
        """published_at='invalid-date' → doc.published_at is None."""
        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None

        store = AsyncMock()
        store.get_bytes.return_value = (
            b"<html><body>Apple stock price rose significantly"
            b" after quarterly earnings report was released today</body></html>"
        )
        store.put_bytes.return_value = None

        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(
            outcome=DedupOutcome.UNIQUE,
            stage="stage_c",
        )

        document_repo = AsyncMock()
        uc = _make_use_case(
            dedup_repo=dedup_repo,
            document_repo=document_repo,
            object_store=store,
            lsh_client=lsh_client,
        )
        summary = await uc.execute(_make_article(published_at="invalid-date"))

        assert summary.suppressed is False
        doc_arg = document_repo.create.call_args.args[0]
        assert doc_arg.published_at is None

    async def test_valid_iso_date_parses_correctly(self) -> None:
        """published_at='2026-03-27T10:00:00Z' → parses to datetime with UTC tz."""
        from datetime import UTC, datetime

        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None

        store = AsyncMock()
        store.get_bytes.return_value = (
            b"<html><body>Apple stock price rose significantly"
            b" after quarterly earnings report was released today</body></html>"
        )
        store.put_bytes.return_value = None

        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(
            outcome=DedupOutcome.UNIQUE,
            stage="stage_c",
        )

        document_repo = AsyncMock()
        uc = _make_use_case(
            dedup_repo=dedup_repo,
            document_repo=document_repo,
            object_store=store,
            lsh_client=lsh_client,
        )
        summary = await uc.execute(_make_article(published_at="2026-03-27T10:00:00Z"))

        assert summary.suppressed is False
        doc_arg = document_repo.create.call_args.args[0]
        assert doc_arg.published_at is not None
        assert doc_arg.published_at.tzinfo is not None
        assert doc_arg.published_at == datetime(2026, 3, 27, 10, 0, 0, tzinfo=UTC)

    async def test_none_published_at_results_in_none(self) -> None:
        """published_at=None → doc.published_at is None."""
        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None

        store = AsyncMock()
        store.get_bytes.return_value = (
            b"<html><body>Apple stock price rose significantly"
            b" after quarterly earnings report was released today</body></html>"
        )
        store.put_bytes.return_value = None

        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(
            outcome=DedupOutcome.UNIQUE,
            stage="stage_c",
        )

        document_repo = AsyncMock()
        uc = _make_use_case(
            dedup_repo=dedup_repo,
            document_repo=document_repo,
            object_store=store,
            lsh_client=lsh_client,
        )
        summary = await uc.execute(_make_article(published_at=None))

        assert summary.suppressed is False
        doc_arg = document_repo.create.call_args.args[0]
        assert doc_arg.published_at is None


class TestBuildStoredPayload:
    def test_payload_has_required_fields(self) -> None:
        doc = CanonicalDocument(
            source_type="eodhd",
            content_hash="abc123",
            normalized_hash="def456",
            status=DocumentStatus.STORED,
            dedup_result=DedupOutcome.UNIQUE,
            minio_silver_key="content-store/canonical/xyz/body.json",
        )
        article = _make_article()
        payload = _build_stored_payload(doc, article)

        assert payload["event_type"] == "content.article.stored"
        assert payload["schema_version"] == 1
        assert payload["doc_id"] == str(doc.id)
        assert payload["content_hash"] == "abc123"
        assert payload["normalized_hash"] == "def456"
        assert payload["dedup_result"] == DedupOutcome.UNIQUE
        assert payload["source_type"] == "eodhd"
        assert payload["minio_silver_key"] == "content-store/canonical/xyz/body.json"
        assert "event_id" in payload
        assert "occurred_at" in payload
