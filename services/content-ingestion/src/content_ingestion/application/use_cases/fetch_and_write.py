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

import hashlib
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import common.ids
import common.time as ct
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from uuid import UUID

    from content_ingestion.application.ports import BronzeStoragePort, FetchLogPort, OutboxPort, SourceAdapterPort
    from content_ingestion.domain.entities import FetchResult, Source

logger = get_logger(__name__)  # type: ignore[no-any-return]


def build_raw_article_payload(
    *,
    doc_id: UUID,
    source_type: str,
    source_url: str | None,
    minio_bronze_key: str,
    raw_bytes: bytes,
    fetch_id: UUID,
    published_at: str | None,
    is_backfill: bool,
) -> dict[str, Any]:
    """Build outbox payload matching ``content.article.raw.v1`` Avro schema exactly."""
    return {
        "event_id": str(common.ids.new_uuid7()),
        "event_type": "content.article.raw",
        "schema_version": 1,
        "occurred_at": ct.to_iso8601(ct.utc_now()),
        "doc_id": str(doc_id),
        "source_type": source_type,
        "source_url": source_url,
        "minio_bronze_key": minio_bronze_key,
        "content_hash": hashlib.sha256(raw_bytes).hexdigest(),
        "fetch_id": str(fetch_id),
        "title": None,
        "published_at": published_at,
        "is_backfill": is_backfill,
        "correlation_id": None,
    }


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
        commit_fn: Async callable to commit the DB session.
        rollback_fn: Async callable to rollback the DB session on error.
    """

    def __init__(
        self,
        adapter: SourceAdapterPort,
        bronze: BronzeStoragePort,
        fetch_log_repo: FetchLogPort,
        outbox_repo: OutboxPort,
        commit_fn: Callable[[], Coroutine[Any, Any, None]],
        rollback_fn: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._adapter = adapter
        self._bronze = bronze
        self._fetch_log = fetch_log_repo
        self._outbox = outbox_repo
        self._commit_fn = commit_fn
        self._rollback_fn = rollback_fn

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
                fetch_log_id = common.ids.new_uuid7()
                await self._fetch_log.create(
                    url=result.url,
                    url_hash=result.url_hash,
                    source_id=result.source_id,
                    http_status=result.http_status,
                    byte_size=len(result.raw_bytes),
                    fetched_at=result.fetched_at,
                    published_at=result.published_at,
                    is_backfill=result.is_backfill,
                    row_id=fetch_log_id,
                )

                payload = build_raw_article_payload(
                    doc_id=result.source_id,
                    source_type=str(source.source_type),
                    source_url=result.url,
                    minio_bronze_key=minio_key,
                    raw_bytes=result.raw_bytes,
                    fetch_id=fetch_log_id,
                    published_at=ct.to_iso8601(result.published_at) if result.published_at else None,
                    is_backfill=result.is_backfill,
                )

                await self._outbox.append(
                    aggregate_type="article",
                    aggregate_id=result.source_id,
                    event_type="content.article.raw.v1",
                    topic="content.article.raw.v1",
                    payload=payload,
                )

                await self._commit_fn()
                fetched += 1

            except Exception as exc:
                # Rollback to restore session state so subsequent articles can still process
                if self._rollback_fn:
                    try:
                        await self._rollback_fn()
                    except Exception:
                        logger.debug("rollback_failed_after_article_error", url_hash=result.url_hash)
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
