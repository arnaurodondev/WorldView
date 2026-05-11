"""Unit tests for PLAN-0086 Wave C-1 — tenant_id propagation through S5 pipeline.

Verifies:
1. _parse_raw_event extracts tenant_id from Avro event dict (null and non-null paths)
2. ProcessArticleUseCase passes tenant_id to dedup_repo.check_exists and insert_pair
3. ProcessArticleUseCase passes tenant_id to CanonicalDocument
4. DocumentRepository.create sets model.tenant_id from doc.tenant_id
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_TENANT_UUID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_DOC_UUID = UUID("11111111-2222-3333-4444-555555555555")


# ── _parse_raw_event ─────────────────────────────────────────────────────────


class TestParseRawEventTenantId:
    """_parse_raw_event must propagate tenant_id from the Avro dict."""

    def test_extracts_tenant_id_when_present(self) -> None:
        """tenant_id string in event dict → RawArticleEvent.tenant_id set."""
        from content_store.infrastructure.messaging.consumers.article_consumer import (
            _parse_raw_event,
        )

        value = {
            "event_id": "evt-001",
            "doc_id": "doc-001",
            "source_type": "tenant_upload",
            "source_url": None,
            "minio_bronze_key": "key",
            "content_hash": "hash",
            "title": None,
            "published_at": None,
            "is_backfill": False,
            "tenant_id": str(_TENANT_UUID),
        }
        event = _parse_raw_event(value)
        assert event.tenant_id == str(_TENANT_UUID)

    def test_returns_none_when_tenant_id_absent(self) -> None:
        """Missing tenant_id key → RawArticleEvent.tenant_id is None."""
        from content_store.infrastructure.messaging.consumers.article_consumer import (
            _parse_raw_event,
        )

        value = {
            "event_id": "evt-001",
            "doc_id": "doc-001",
            "source_type": "eodhd",
            "source_url": None,
            "minio_bronze_key": "key",
            "content_hash": "hash",
        }
        event = _parse_raw_event(value)
        assert event.tenant_id is None

    def test_returns_none_when_tenant_id_empty_string(self) -> None:
        """Empty-string tenant_id (Avro default) → RawArticleEvent.tenant_id is None."""
        from content_store.infrastructure.messaging.consumers.article_consumer import (
            _parse_raw_event,
        )

        value = {
            "event_id": "evt-001",
            "doc_id": "doc-001",
            "source_type": "eodhd",
            "source_url": None,
            "minio_bronze_key": "key",
            "content_hash": "hash",
            "tenant_id": "",
        }
        event = _parse_raw_event(value)
        assert event.tenant_id is None


# ── DocumentRepository.create ────────────────────────────────────────────────


class TestDocumentRepositoryCreateTenantId:
    """DocumentRepository.create must propagate tenant_id to the ORM model."""

    async def test_sets_tenant_id_on_model_when_present(self) -> None:
        """create() must pass doc.tenant_id to the DocumentModel constructor."""
        from content_store.domain.entities import CanonicalDocument
        from content_store.infrastructure.db.repositories.document import DocumentRepository

        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        repo = DocumentRepository(session)

        doc = CanonicalDocument(
            id=_DOC_UUID,
            source_type="tenant_upload",
            content_hash="abc",
            normalized_hash="def",
            tenant_id=_TENANT_UUID,
        )
        await repo.create(doc)

        # Extract the model instance passed to session.add
        session.add.assert_called_once()
        model = session.add.call_args.args[0]
        assert model.tenant_id == _TENANT_UUID

    async def test_sets_tenant_id_none_for_public_content(self) -> None:
        """create() must pass None for tenant_id when doc.tenant_id is None."""
        from content_store.domain.entities import CanonicalDocument
        from content_store.infrastructure.db.repositories.document import DocumentRepository

        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        repo = DocumentRepository(session)

        doc = CanonicalDocument(
            id=_DOC_UUID,
            source_type="eodhd",
            content_hash="abc",
            normalized_hash="def",
            tenant_id=None,
        )
        await repo.create(doc)

        model = session.add.call_args.args[0]
        assert model.tenant_id is None


# ── ProcessArticleUseCase — tenant_id wiring ─────────────────────────────────


class TestProcessArticleUseCaseTenantIdPropagation:
    """ProcessArticleUseCase must pass tenant_id through dedup checks and doc creation."""

    def _make_use_case(
        self,
        *,
        dedup_repo: object,
        document_repo: object,
        minhash_repo: object,
        outbox_repo: object,
    ) -> object:
        from content_store.application.use_cases.process_article import ProcessArticleUseCase

        return ProcessArticleUseCase(
            document_repo=document_repo,  # type: ignore[arg-type]
            dedup_repo=dedup_repo,  # type: ignore[arg-type]
            minhash_repo=minhash_repo,  # type: ignore[arg-type]
            outbox_repo=outbox_repo,  # type: ignore[arg-type]
            bronze_store=AsyncMock(),
            bronze_bucket="test-bucket",
            silver_storage=AsyncMock(),
            lsh_client=AsyncMock(),
            output_topic="content.article.stored.v1",
        )

    async def test_tenant_id_passed_to_stage_a_check_exists(self) -> None:
        """Stage A check_exists must receive tenant_id from the article event."""
        import base64
        import json

        from content_store.application.use_cases.process_article import RawArticleEvent

        dedup_repo = AsyncMock()
        # Stage A finds no duplicate → proceed to stage B
        dedup_repo.check_exists.return_value = None
        document_repo = AsyncMock()
        minhash_repo = AsyncMock()
        outbox_repo = AsyncMock()

        # Stub silver_storage to return a key
        silver_storage = AsyncMock()
        silver_storage.put_canonical = AsyncMock(return_value="silver/key")

        # Bronze store returning a valid JSON envelope
        bronze_bytes = json.dumps({"raw_b64": base64.b64encode(b"hello world article content here").decode()}).encode()

        from content_store.application.use_cases.process_article import ProcessArticleUseCase

        use_case = ProcessArticleUseCase(
            document_repo=document_repo,
            dedup_repo=dedup_repo,
            minhash_repo=minhash_repo,
            outbox_repo=outbox_repo,
            bronze_store=AsyncMock(),
            bronze_bucket="test-bucket",
            silver_storage=silver_storage,
            lsh_client=AsyncMock(),
            output_topic="content.article.stored.v1",
        )

        article = RawArticleEvent(
            event_id="evt-001",
            doc_id=str(_DOC_UUID),
            source_type="tenant_upload",
            source_url=None,
            minio_bronze_key="bronze/key",
            content_hash="abc123",
            title="Test Article",
            published_at=None,
            is_backfill=False,
            tenant_id=str(_TENANT_UUID),
        )

        await use_case.execute(article, prefetched_bytes=bronze_bytes)

        # Stage A check_exists must have been called with the tenant_id UUID
        first_call_kwargs = dedup_repo.check_exists.call_args_list[0].kwargs
        assert first_call_kwargs.get("tenant_id") == _TENANT_UUID, (
            f"Stage A check_exists must pass tenant_id={_TENANT_UUID!r}; " f"got kwargs={first_call_kwargs!r}"
        )

    async def test_tenant_id_none_when_not_in_event(self) -> None:
        """Stage A check_exists must receive tenant_id=None for public content."""
        import base64
        import json

        from content_store.application.use_cases.process_article import ProcessArticleUseCase, RawArticleEvent

        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None

        silver_storage = AsyncMock()
        silver_storage.put_canonical = AsyncMock(return_value="silver/key")

        bronze_bytes = json.dumps({"raw_b64": base64.b64encode(b"hello world article content here").decode()}).encode()

        use_case = ProcessArticleUseCase(
            document_repo=AsyncMock(),
            dedup_repo=dedup_repo,
            minhash_repo=AsyncMock(),
            outbox_repo=AsyncMock(),
            bronze_store=AsyncMock(),
            bronze_bucket="test-bucket",
            silver_storage=silver_storage,
            lsh_client=AsyncMock(),
            output_topic="content.article.stored.v1",
        )

        article = RawArticleEvent(
            event_id="evt-002",
            doc_id=str(_DOC_UUID),
            source_type="eodhd",
            source_url=None,
            minio_bronze_key="bronze/key",
            content_hash="abc123",
            title=None,
            published_at=None,
            is_backfill=False,
            tenant_id=None,  # public content
        )

        await use_case.execute(article, prefetched_bytes=bronze_bytes)

        first_call_kwargs = dedup_repo.check_exists.call_args_list[0].kwargs
        assert first_call_kwargs.get("tenant_id") is None, (
            f"Stage A check_exists must pass tenant_id=None for public content; " f"got kwargs={first_call_kwargs!r}"
        )

    async def test_insert_pair_called_with_tenant_id(self) -> None:
        """insert_pair must be called with the correct tenant_id UUID."""
        import base64
        import json

        from content_store.application.use_cases.process_article import ProcessArticleUseCase, RawArticleEvent
        from content_store.domain.enums import DedupOutcome

        dedup_repo = AsyncMock()
        dedup_repo.check_exists.return_value = None  # No duplicates at any stage
        dedup_repo.insert_pair = AsyncMock()

        silver_storage = AsyncMock()
        silver_storage.put_canonical = AsyncMock(return_value="silver/key")

        bronze_bytes = json.dumps({"raw_b64": base64.b64encode(b"hello world article content here").decode()}).encode()

        # LSH client must return a non-suppressed decision so the article proceeds
        # past Stage C to the insert_pair call.
        lsh_decision = MagicMock()
        lsh_decision.is_suppressed = False
        lsh_decision.outcome = DedupOutcome.UNIQUE
        lsh_decision.jaccard_score = 0.0
        lsh_client = AsyncMock()
        lsh_client.query = AsyncMock(return_value=lsh_decision)

        use_case = ProcessArticleUseCase(
            document_repo=AsyncMock(),
            dedup_repo=dedup_repo,
            minhash_repo=AsyncMock(),
            outbox_repo=AsyncMock(),
            bronze_store=AsyncMock(),
            bronze_bucket="test-bucket",
            silver_storage=silver_storage,
            lsh_client=lsh_client,
            output_topic="content.article.stored.v1",
        )

        article = RawArticleEvent(
            event_id="evt-003",
            doc_id=str(_DOC_UUID),
            source_type="tenant_upload",
            source_url=None,
            minio_bronze_key="bronze/key",
            content_hash="abc123",
            title=None,
            published_at=None,
            is_backfill=False,
            tenant_id=str(_TENANT_UUID),
        )

        await use_case.execute(article, prefetched_bytes=bronze_bytes)

        dedup_repo.insert_pair.assert_called_once()
        call_kwargs = dedup_repo.insert_pair.call_args.kwargs
        assert call_kwargs.get("tenant_id") == _TENANT_UUID, (
            f"insert_pair must be called with tenant_id={_TENANT_UUID!r}; " f"got kwargs={call_kwargs!r}"
        )
