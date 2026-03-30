"""SubmitContentUseCase — accept a raw document from S9 webhook or manual submission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import common.ids  # type: ignore[import-untyped]
import common.time as ct  # type: ignore[import-untyped]
from content_ingestion.application.use_cases.fetch_and_write import build_raw_article_payload
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from content_ingestion.application.ports.repositories import BronzeStoragePort
    from content_ingestion.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)


@dataclass(frozen=True)
class SubmitResult:
    """DTO for the submit response."""

    doc_id: UUID
    status: str


class SubmitContentUseCase:
    """Accept a raw document submission.

    Performs dedup check, writes to bronze storage, inserts fetch log
    and outbox entries atomically.
    """

    def __init__(self, uow: UnitOfWork, bronze: BronzeStoragePort) -> None:
        self._uow = uow
        self._bronze = bronze

    async def execute(
        self,
        *,
        url: str,
        url_hash: str,
        raw_bytes: bytes,
        source_type: str,
        published_at: datetime | None = None,
    ) -> SubmitResult:
        """Submit a document. Returns status='duplicate' if already ingested."""
        doc_id = common.ids.new_uuid7()
        now = ct.utc_now()

        async with self._uow:
            # Dedup check BEFORE MinIO write to avoid orphaned objects
            if await self._uow.fetch_logs.exists_by_url_hash(url_hash):
                return SubmitResult(doc_id=doc_id, status="duplicate")

            # Write to bronze storage
            minio_key = await self._bronze.put_object(
                source_type=source_type,
                url_hash=url_hash,
                raw_bytes=raw_bytes,
                url=url,
                fetched_at=ct.to_iso8601(now),
                published_at=ct.to_iso8601(published_at) if published_at else None,
                is_backfill=False,
            )

            # Insert fetch log + outbox atomically
            fetch_log_id = common.ids.new_uuid7()
            await self._uow.fetch_logs.create(
                url=url,
                url_hash=url_hash,
                source_id=doc_id,
                http_status=200,
                byte_size=len(raw_bytes),
                fetched_at=now,
                published_at=published_at,
                is_backfill=False,
                row_id=fetch_log_id,
            )

            payload = build_raw_article_payload(
                doc_id=doc_id,
                source_type=source_type,
                source_url=url,
                minio_bronze_key=minio_key,
                raw_bytes=raw_bytes,
                fetch_id=fetch_log_id,
                published_at=ct.to_iso8601(published_at) if published_at else None,
                is_backfill=False,
            )

            await self._uow.outbox.append(
                aggregate_type="article",
                aggregate_id=doc_id,
                event_type="content.article.raw.v1",
                topic="content.article.raw.v1",
                payload=payload,
            )

            await self._uow.commit()

        logger.info("content_submitted", doc_id=str(doc_id))
        return SubmitResult(doc_id=doc_id, status="accepted")
