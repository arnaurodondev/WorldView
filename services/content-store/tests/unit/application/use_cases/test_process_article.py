"""Unit tests for ProcessArticleUseCase."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from content_store.application.use_cases.process_article import (
    ProcessArticleUseCase,
    RawArticleEvent,
    _build_stored_payload,
    _extract_prose_payload,
    _guess_content_type,
)
from content_store.domain.entities import CanonicalDocument, DeduplicationDecision
from content_store.domain.enums import DedupOutcome, DocumentStatus
from content_store.domain.errors import BronzeObjectNotFoundError

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


def _make_silver_storage() -> AsyncMock:
    """Create a default silver_storage mock that returns a valid key string."""
    mock = AsyncMock()
    mock.put_canonical.return_value = "content-store/canonical/test/body.json"
    return mock


def _make_use_case(
    *,
    document_repo: AsyncMock | None = None,
    dedup_repo: AsyncMock | None = None,
    minhash_repo: AsyncMock | None = None,
    outbox_repo: AsyncMock | None = None,
    bronze_store: AsyncMock | None = None,
    silver_storage: AsyncMock | None = None,
    lsh_client: AsyncMock | None = None,
) -> ProcessArticleUseCase:
    return ProcessArticleUseCase(
        document_repo=document_repo or AsyncMock(),
        dedup_repo=dedup_repo or AsyncMock(),
        minhash_repo=minhash_repo or AsyncMock(),
        outbox_repo=outbox_repo or AsyncMock(),
        bronze_store=bronze_store or AsyncMock(),
        bronze_bucket="worldview-bronze",
        silver_storage=silver_storage or _make_silver_storage(),
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

        uc = _make_use_case(dedup_repo=dedup_repo, bronze_store=store)
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

        uc = _make_use_case(dedup_repo=dedup_repo, bronze_store=store)
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
        silver_storage = AsyncMock()
        silver_storage.put_canonical.return_value = "content-store/canonical/xyz/body.json"

        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(
            outcome=DedupOutcome.UNIQUE,
            stage="stage_c",
        )

        uc = _make_use_case(
            dedup_repo=dedup_repo,
            document_repo=document_repo,
            minhash_repo=minhash_repo,
            outbox_repo=outbox_repo,
            bronze_store=store,
            silver_storage=silver_storage,
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
        silver_storage.put_canonical.assert_called_once()

        # Verify outbox payload
        call_kwargs = outbox_repo.append.call_args
        assert call_kwargs.kwargs["event_type"] == "content.article.stored.v1"
        assert call_kwargs.kwargs["topic"] == "content.article.stored.v1"
        assert call_kwargs.kwargs["aggregate_type"] == "document"

    async def test_eodhd_json_payload_stores_inner_prose_not_envelope(self) -> None:
        """BUG #34 — eodhd JSON payload → silver body is the inner prose, not the JSON."""
        prose = "Apple reported record quarterly revenue and raised guidance for the year."
        store = AsyncMock()
        # content-ingestion stores the EODHD dict as json.dumps(article); bronze is
        # the unwrapped payload (no raw_b64 envelope here — passthrough path).
        store.get_bytes.return_value = json.dumps(
            {"title": "Apple beats earnings", "content": prose, "date": "2026-03-01"}
        ).encode("utf-8")

        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None  # No existing hashes
        minhash_repo = AsyncMock()
        minhash_repo.get_signature_by_doc_id.return_value = None
        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c")
        silver_storage = _make_silver_storage()

        uc = _make_use_case(
            bronze_store=store,
            dedup_repo=dedup_repo,
            minhash_repo=minhash_repo,
            silver_storage=silver_storage,
            lsh_client=lsh_client,
        )
        await uc.execute(_make_article(source_type="eodhd"))

        # The cleaned text handed to silver must be the inner prose, NOT the JSON envelope.
        cleaned_text = silver_storage.put_canonical.call_args.args[1]
        assert cleaned_text == prose
        assert "{" not in cleaned_text
        assert "symbols" not in cleaned_text

    async def test_newsapi_json_payload_stores_content_prose(self) -> None:
        """BUG #34 — newsapi JSON payload → silver body is the inner ``content`` prose."""
        prose = "Stocks climbed across the board on Friday as inflation data cooled."
        store = AsyncMock()
        store.get_bytes.return_value = json.dumps(
            {"title": "Markets rally", "description": "blurb", "content": prose}
        ).encode("utf-8")

        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None  # No existing hashes
        minhash_repo = AsyncMock()
        minhash_repo.get_signature_by_doc_id.return_value = None
        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c")
        silver_storage = _make_silver_storage()

        uc = _make_use_case(
            bronze_store=store,
            dedup_repo=dedup_repo,
            minhash_repo=minhash_repo,
            silver_storage=silver_storage,
            lsh_client=lsh_client,
        )
        await uc.execute(_make_article(source_type="newsapi"))

        cleaned_text = silver_storage.put_canonical.call_args.args[1]
        assert cleaned_text == prose

    async def test_genuine_html_still_cleans_normally(self) -> None:
        """A genuine-HTML source is unaffected: tags stripped, no JSON-recovery path."""
        store = AsyncMock()
        store.get_bytes.return_value = (
            b"<html><body><p>Tesla shares jumped after the delivery numbers"
            b" exceeded analyst expectations for the quarter.</p></body></html>"
        )

        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None  # No existing hashes
        minhash_repo = AsyncMock()
        minhash_repo.get_signature_by_doc_id.return_value = None
        lsh_client = AsyncMock()
        lsh_client.query.return_value = DeduplicationDecision(outcome=DedupOutcome.UNIQUE, stage="stage_c")
        silver_storage = _make_silver_storage()

        uc = _make_use_case(
            bronze_store=store,
            dedup_repo=dedup_repo,
            minhash_repo=minhash_repo,
            silver_storage=silver_storage,
            lsh_client=lsh_client,
        )
        await uc.execute(_make_article(source_type="eodhd"))

        cleaned_text = silver_storage.put_canonical.call_args.args[1]
        assert "Tesla shares jumped" in cleaned_text
        assert "<p>" not in cleaned_text

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
            bronze_store=store,
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

        uc = _make_use_case(dedup_repo=dedup_repo, bronze_store=store, lsh_client=lsh_client)
        summary = await uc.execute(_make_article())

        assert summary.suppressed is True
        assert summary.decision.outcome == DedupOutcome.SAME_SOURCE_DUPLICATE

    async def test_unique_article_returns_signature_for_post_commit_lsh(self) -> None:
        """execute() returns signature data so the consumer can index in LSH post-commit (CR-3).

        Note: execute() does NOT call lsh.index() directly — that is the consumer's
        responsibility after session.commit(). This test verifies the use case returns
        the signature in ProcessingSummary so the consumer can act on it.
        """
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

        uc = _make_use_case(dedup_repo=dedup_repo, bronze_store=store, lsh_client=lsh_client)
        summary = await uc.execute(_make_article())

        assert summary.suppressed is False
        assert summary.doc_id is not None
        # Signature must be returned for consumer to index post-commit
        assert summary.signature is not None
        # execute() must NOT call lsh.index() directly — consumer's job
        lsh_client.index.assert_not_called()

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
            bronze_store=store,
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

    async def test_bronze_object_missing_raises_domain_error(self) -> None:
        """F-DP2-05 (PLAN-deep-qa-iter2): missing bronze key → BronzeObjectNotFoundError.

        When the storage adapter raises ObjectNotFoundError (or NoSuchKey /
        FileNotFoundError), the use case must translate to the domain-level
        BronzeObjectNotFoundError so the consumer can skip the message
        gracefully instead of producing an unhandled traceback.
        """

        # Stub bronze store that raises a class named ObjectNotFoundError
        # (we simulate without importing libs/storage to keep the domain test isolated).
        class FakeObjectNotFoundError(Exception):
            """Mimics storage.exceptions.ObjectNotFoundError by name match."""

        # Rename the class to match what the use case pattern-matches on.
        FakeObjectNotFoundError.__name__ = "ObjectNotFoundError"

        store = AsyncMock()
        store.get_bytes.side_effect = FakeObjectNotFoundError("key gone")

        uc = _make_use_case(bronze_store=store)

        with pytest.raises(BronzeObjectNotFoundError):
            await uc.execute(_make_article(), prefetched_bytes=None)

    async def test_bronze_other_error_propagates(self) -> None:
        """Non-NotFound storage errors must still propagate (e.g. permission, server)."""
        store = AsyncMock()
        store.get_bytes.side_effect = RuntimeError("connection refused")

        uc = _make_use_case(bronze_store=store)

        # RuntimeError is not in the {ObjectNotFoundError, NoSuchKey, FileNotFoundError}
        # whitelist → re-raised as-is, not converted to BronzeObjectNotFoundError.
        with pytest.raises(RuntimeError, match="connection refused"):
            await uc.execute(_make_article(), prefetched_bytes=None)


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


class TestExtractProsePayload:
    """BUG #34 — recover inner prose from a raw-news JSON payload."""

    def test_eodhd_content_field(self) -> None:
        # EODHD adapter emits ``json.dumps(article)`` with prose under ``content``.
        payload = json.dumps(
            {
                "title": "Apple beats earnings",
                "content": "Apple reported record quarterly revenue today.",
                "date": "2026-03-01",
                "symbols": ["AAPL.US"],
            }
        ).encode("utf-8")
        assert _extract_prose_payload(payload) == "Apple reported record quarterly revenue today."

    def test_newsapi_content_field(self) -> None:
        payload = json.dumps(
            {
                "title": "Markets rally",
                "description": "Short blurb.",
                "content": "Stocks climbed across the board on Friday.",
                "url": "https://example.com/x",
            }
        ).encode("utf-8")
        # ``content`` outranks ``description`` in the priority order.
        assert _extract_prose_payload(payload) == "Stocks climbed across the board on Friday."

    def test_newsapi_description_fallback(self) -> None:
        payload = json.dumps({"title": "T", "description": "Only a description here."}).encode("utf-8")
        assert _extract_prose_payload(payload) == "Only a description here."

    def test_summary_field_yahoo_seed(self) -> None:
        payload = json.dumps({"summary": "Yahoo-style summary prose."}).encode("utf-8")
        assert _extract_prose_payload(payload) == "Yahoo-style summary prose."

    def test_genuine_html_returns_none(self) -> None:
        # Real HTML must fall through to the classify+clean path unchanged.
        assert _extract_prose_payload(b"<html><body><p>Hello</p></body></html>") is None

    def test_json_array_returns_none(self) -> None:
        assert _extract_prose_payload(b'["a", "b"]') is None

    def test_dict_without_prose_field_returns_none(self) -> None:
        # No recognised prose field → fall through (don't drop content silently).
        assert _extract_prose_payload(b'{"title": "T", "date": "2026-03-01"}') is None

    def test_does_not_match_own_silver_body_envelope(self) -> None:
        # content-store's OWN silver envelope uses a top-level ``body`` key — it must
        # NOT be treated as a raw news payload (no ``content``/``summary``/etc.).
        payload = json.dumps({"body": "already-cleaned prose", "source_type": "eodhd"}).encode("utf-8")
        assert _extract_prose_payload(payload) is None


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
            bronze_store=store,
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
            bronze_store=store,
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
            bronze_store=store,
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
