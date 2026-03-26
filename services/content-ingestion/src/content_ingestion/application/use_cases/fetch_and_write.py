"""Fetch-and-write use-case — orchestrates adapter → MinIO → DB (outbox).

This is the hot-path for S4:

1. Call ``adapter.fetch(source)`` to retrieve new articles.
2. For each :class:`FetchResult`:
   a. Skip if ``url_hash`` already in ``article_fetch_log`` (idempotent).
   b. Write raw payload to MinIO bronze tier.
   c. In a **single DB transaction**: INSERT ``article_fetch_log`` +
      INSERT ``outbox_events``.
3. NEVER publish directly to Kafka — outbox dispatcher handles that.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import common.time as ct
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.domain.entities import FetchResult, Source
    from content_ingestion.infrastructure.adapters.base import SourceAdapter
    from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
    from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
    from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class FetchSummary:
    """Summary of a single fetch-and-write cycle."""

    source_name: str
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class FetchAndWriteUseCase:
    """Orchestrate adapter.fetch → MinIO bronze → atomic DB transaction.

    Args:
        adapter: Source-specific adapter.
        bronze: MinIO bronze-tier adapter.
        fetch_log_repo: Repository for url-hash dedup + fetch logging.
        outbox_repo: Repository for transactional outbox events.
        commit_fn: ``async () -> None`` callable to commit the DB session.
    """

    def __init__(
        self,
        adapter: SourceAdapter,
        bronze: MinioBronzeAdapter,
        fetch_log_repo: FetchLogRepository,
        outbox_repo: OutboxRepository,
        commit_fn: object,
    ) -> None:
        self._adapter = adapter
        self._bronze = bronze
        self._fetch_log = fetch_log_repo
        self._outbox = outbox_repo
        self._commit_fn = commit_fn

    async def execute(self, source: Source, *, is_backfill: bool = False) -> FetchSummary:
        """Run one fetch cycle for *source* and return a summary."""
        start = time.monotonic()
        fetched = 0
        skipped = 0
        failed = 0
        errors: list[str] = []

        # 1. Fetch from external API
        try:
            results: list[FetchResult] = await self._adapter.fetch(source, is_backfill=is_backfill)
        except Exception as exc:
            duration = time.monotonic() - start
            logger.error("fetch_failed", source=source.name, error=str(exc))
            return FetchSummary(
                source_name=source.name,
                failed=1,
                duration_seconds=round(duration, 3),
                errors=[str(exc)],
            )

        # 2. Process each result
        for result in results:
            try:
                # 2a. Dedup check
                if await self._fetch_log.exists_by_url_hash(result.url_hash):
                    skipped += 1
                    continue

                # 2b. Write to MinIO bronze
                minio_key = await self._bronze.put_object(
                    source_type=str(source.source_type),
                    url_hash=result.url_hash,
                    raw_bytes=result.raw_bytes,
                    url=result.url,
                    fetched_at=ct.to_iso8601(result.fetched_at),
                    published_at=ct.to_iso8601(result.published_at) if result.published_at else None,
                    is_backfill=result.is_backfill,
                )

                # 2c. Atomic DB transaction: fetch_log + outbox
                await self._fetch_log.create(
                    url=result.url,
                    url_hash=result.url_hash,
                    source_id=result.source_id,
                    http_status=result.http_status,
                    byte_size=len(result.raw_bytes),
                    fetched_at=result.fetched_at,
                    published_at=result.published_at,
                    is_backfill=result.is_backfill,
                )

                await self._outbox.append(
                    aggregate_type="article",
                    aggregate_id=result.source_id,
                    event_type="content.article.raw.v1",
                    topic="content.article.raw.v1",
                    payload={
                        "doc_id": str(result.source_id),
                        "source_type": str(source.source_type),
                        "url": result.url,
                        "url_hash": result.url_hash,
                        "minio_key": minio_key,
                        "fetched_at": ct.to_iso8601(result.fetched_at),
                        "byte_size": len(result.raw_bytes),
                        "published_at": ct.to_iso8601(result.published_at) if result.published_at else None,
                        "is_backfill": result.is_backfill,
                    },
                )

                await self._commit_fn()  # type: ignore[operator]
                fetched += 1

            except Exception as exc:
                failed += 1
                errors.append(f"{result.url_hash}: {exc}")
                logger.error("article_write_failed", url_hash=result.url_hash, error=str(exc))

        duration = time.monotonic() - start
        logger.info(
            "fetch_cycle_complete",
            source=source.name,
            fetched=fetched,
            skipped=skipped,
            failed=failed,
            duration_seconds=round(duration, 3),
        )
        return FetchSummary(
            source_name=source.name,
            fetched=fetched,
            skipped=skipped,
            failed=failed,
            duration_seconds=round(duration, 3),
            errors=errors,
        )
