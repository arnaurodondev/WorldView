"""ProcessArticleUseCase — complete S5 hot path orchestrator.

Pipeline: fetch raw from bronze → clean → Stage A → Stage B → MinHash →
LSH query → (if not suppressed) silver write + atomic DB transaction → LSH index.

NEVER publishes to Kafka directly — uses transactional outbox only.
Dependencies are injected via port ABCs — no infrastructure imports at runtime.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from content_store.application.deduplication.minhash_compute import compute_minhash
from content_store.application.deduplication.stage_a_raw import check_stage_a
from content_store.application.deduplication.stage_b_normalized import check_stage_b
from content_store.application.text_cleaning.cleaner import clean
from content_store.domain.entities import (
    CanonicalDocument,
    DeduplicationDecision,
    MinHashSignature,
)
from content_store.domain.enums import DedupOutcome, DocumentStatus

if TYPE_CHECKING:
    from content_store.application.ports.lsh import LSHClientPort
    from content_store.application.ports.repositories import (
        DedupHashRepositoryPort,
        DocumentRepositoryPort,
        MinHashRepositoryPort,
        OutboxPort,
    )
    from content_store.application.ports.storage import BronzeStoragePort, SilverStoragePort

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class RawArticleEvent:
    """Deserialized content.article.raw.v1 Avro event."""

    event_id: str
    doc_id: str
    source_type: str
    source_url: str | None
    minio_bronze_key: str
    content_hash: str
    title: str | None
    published_at: str | None
    is_backfill: bool


@dataclass(frozen=True)
class ProcessingSummary:
    """Result of processing a single article through the dedup pipeline."""

    article_id: str
    decision: DeduplicationDecision
    doc_id: UUID | None
    suppressed: bool
    signature: list[int] | None = None
    source_type: str | None = None
    minio_silver_key: str | None = None  # set when silver write succeeded; used for GC on commit failure


class ProcessArticleUseCase:
    """Orchestrates the full S5 article processing pipeline.

    Dependencies are injected via port ABCs — no direct infrastructure construction.
    The consumer is responsible for transaction management (commit/rollback).
    """

    def __init__(
        self,
        *,
        document_repo: DocumentRepositoryPort,
        dedup_repo: DedupHashRepositoryPort,
        minhash_repo: MinHashRepositoryPort,
        outbox_repo: OutboxPort,
        bronze_store: BronzeStoragePort,
        bronze_bucket: str,
        silver_storage: SilverStoragePort,
        lsh_client: LSHClientPort,
        output_topic: str = "content.article.stored.v1",
        num_perm: int = 128,
    ) -> None:
        self._document_repo = document_repo
        self._dedup_repo = dedup_repo
        self._minhash_repo = minhash_repo
        self._outbox_repo = outbox_repo
        self._bronze_store = bronze_store
        self._bronze_bucket = bronze_bucket
        self._silver_storage = silver_storage
        self._lsh = lsh_client
        self._output_topic = output_topic
        self._num_perm = num_perm

    async def execute(
        self,
        article: RawArticleEvent,
        prefetched_bytes: bytes | None = None,
    ) -> ProcessingSummary:
        """Process a single raw article through the full dedup pipeline.

        Steps:
        1. Fetch raw bytes from MinIO bronze (skipped if *prefetched_bytes* provided)
        2. Clean text (extract + normalize)
        3. Stage A: exact raw hash check
        4. Stage B: normalized hash check
        5. Compute MinHash signature
        6. Stage C: Valkey LSH near-duplicate query
        7. If not suppressed: write to silver + DB insert + outbox
        8. Return summary (caller is responsible for LSH index post-commit)

        Args:
            article: Deserialized raw article event.
            prefetched_bytes: Raw bytes already fetched from bronze (R24 — pre-fetched
                before the DB session opened).  When ``None``, the use case fetches
                them itself (legacy / test path).

        Returns:
            ProcessingSummary with decision and outcome.
        """
        log = logger.bind(article_id=article.doc_id, source=article.source_type)

        # 1. Fetch raw bytes from bronze (R24: caller should pre-fetch before opening session)
        if prefetched_bytes is not None:
            raw_bytes = prefetched_bytes
        else:
            raw_bytes = await self._bronze_store.get_bytes(self._bronze_bucket, article.minio_bronze_key)
        log.info("bronze_fetched", byte_size=len(raw_bytes))

        # 2. Clean text
        # Unwrap S4 Bronze envelope (JSON with raw_b64) to get actual article bytes
        article_bytes = _unwrap_bronze_envelope(raw_bytes)
        content_type = _guess_content_type(article.source_type)
        cleaned_text = clean(article_bytes, content_type)
        word_count = len(cleaned_text.split()) if cleaned_text else 0

        # 3. Stage A: exact raw hash
        # Use the content_hash from the event (computed by S4 from original bytes).
        # This ensures consistent deduplication across the S4→S5 pipeline boundary,
        # independent of the bronze envelope format.
        raw_hash, stage_a_decision = await check_stage_a(article.content_hash, self._dedup_repo)
        if stage_a_decision is not None:
            log.info("stage_a_duplicate", matched=str(stage_a_decision.matched_doc_id))
            return ProcessingSummary(
                article_id=article.doc_id,
                decision=stage_a_decision,
                doc_id=None,
                suppressed=True,
            )

        # 4. Stage B: normalized hash
        url = article.source_url or ""
        normalized_hash, stage_b_decision = await check_stage_b(url, cleaned_text, self._dedup_repo)
        if stage_b_decision is not None:
            log.info("stage_b_duplicate", matched=str(stage_b_decision.matched_doc_id))
            return ProcessingSummary(
                article_id=article.doc_id,
                decision=stage_b_decision,
                doc_id=None,
                suppressed=True,
            )

        # 5. Compute MinHash
        signature = compute_minhash(cleaned_text, num_perm=self._num_perm)

        # 6. Stage C: LSH near-duplicate query
        async def _fetch_sig(doc_id_str: str) -> list[int] | None:
            from uuid import UUID

            model = await self._minhash_repo.get_signature_by_doc_id(UUID(doc_id_str))
            return list(model.signature) if model else None

        lsh_decision = await self._lsh.query(
            signature=signature,
            source_type=article.source_type,
            source_name=article.source_type,
            fetch_signature=_fetch_sig,
        )

        # Determine final decision
        decision = lsh_decision
        suppressed = decision.is_suppressed

        if suppressed:
            log.info("suppressed", outcome=decision.outcome, jaccard=decision.jaccard_score)
            return ProcessingSummary(
                article_id=article.doc_id,
                decision=decision,
                doc_id=None,
                suppressed=True,
            )

        # 7. Not suppressed — write to silver + atomic DB insert

        # Parse published_at
        published_at = None
        if article.published_at:
            import contextlib
            from datetime import datetime

            with contextlib.suppress(ValueError, TypeError):
                published_at = datetime.fromisoformat(article.published_at).replace(tzinfo=UTC)

        # Build canonical document
        doc_id = common.ids.new_uuid7()
        doc = CanonicalDocument(
            id=doc_id,
            source_type=article.source_type,
            source_url=article.source_url,
            title=article.title,
            published_at=published_at,
            content_hash=raw_hash,
            normalized_hash=normalized_hash,
            status=DocumentStatus.STORED,
            dedup_result=decision.outcome,
            word_count=word_count,
            is_backfill=article.is_backfill,
            corroborates_doc_id=decision.matched_doc_id if decision.outcome == DedupOutcome.CORROBORATING else None,
        )

        # Write to MinIO silver via injected port
        silver_key = await self._silver_storage.put_canonical(doc, cleaned_text)
        doc.minio_silver_key = silver_key

        # DB writes: document + dedup hashes + minhash + outbox
        # (transaction managed by the calling consumer)
        await self._document_repo.create(doc)
        await self._dedup_repo.insert_pair(doc_id, raw_hash, normalized_hash)

        sig_entity = MinHashSignature(
            id=common.ids.new_uuid7(),
            doc_id=doc_id,
            signature=signature,
        )
        await self._minhash_repo.create_signature(sig_entity)

        # Outbox event (NEVER publish Kafka directly)
        await self._outbox_repo.append(
            aggregate_type="document",
            aggregate_id=doc_id,
            event_type="content.article.stored.v1",
            topic=self._output_topic,
            payload=_build_stored_payload(doc, article),
        )

        log.info(
            "article_stored",
            doc_id=str(doc_id),
            decision=decision.outcome,
            word_count=word_count,
            silver_key=silver_key,
        )

        # 8. Return signature data for LSH indexing AFTER DB commit (CR-3)
        #    The consumer is responsible for calling lsh.index() post-commit.
        #    minio_silver_key is included so the consumer can GC on commit failure.
        return ProcessingSummary(
            article_id=article.doc_id,
            decision=decision,
            doc_id=doc_id,
            suppressed=False,
            signature=signature,
            source_type=article.source_type,
            minio_silver_key=silver_key,
        )


def _unwrap_bronze_envelope(raw_bytes: bytes) -> bytes:
    """Extract the actual article bytes from an S4 Bronze envelope.

    S4 content-ingestion wraps raw article bytes in a JSON envelope:
        {"raw_b64": "<base64-encoded article bytes>", "url": ..., ...}

    If raw_bytes is such an envelope, return the decoded article bytes.
    Otherwise return raw_bytes unchanged (passthrough for legacy/direct formats).
    """
    try:
        envelope = json.loads(raw_bytes)
        if isinstance(envelope, dict) and "raw_b64" in envelope:
            return base64.b64decode(envelope["raw_b64"])
    except (json.JSONDecodeError, KeyError, ValueError):
        pass
    return raw_bytes


def _guess_content_type(source_type: str) -> str:
    """Map source type to content type for text extraction."""
    mapping: dict[str, str] = {
        "eodhd": "html",
        "newsapi": "html",
        "sec_edgar": "html",
        "finnhub": "json",
        "manual": "text",
    }
    return mapping.get(source_type, "html")


def _build_stored_payload(doc: CanonicalDocument, article: RawArticleEvent) -> dict:
    """Build the outbox event payload matching content.article.stored.v1 schema."""
    if doc.minio_silver_key is None:
        msg = "minio_silver_key must be set before building stored payload"
        raise ValueError(msg)
    return {
        "event_id": str(common.ids.new_uuid7()),
        "event_type": "content.article.stored",
        "schema_version": 1,
        "occurred_at": common.time.utc_now().isoformat(),
        "doc_id": str(doc.id),
        "content_hash": doc.content_hash,
        "normalized_hash": doc.normalized_hash,
        "dedup_result": doc.dedup_result,
        "minio_silver_key": doc.minio_silver_key,
        "source_type": doc.source_type,
        "title": doc.title,
        "word_count": doc.word_count,
        "published_at": article.published_at,
        "is_backfill": doc.is_backfill,
        "correlation_id": None,
    }
