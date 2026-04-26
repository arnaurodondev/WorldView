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
from uuid import UUID

import common.ids
import common.time as ct
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

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
    title: str | None = None,
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
        "title": title,
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
        batch_size: int = 25,
    ) -> None:
        self._adapter = adapter
        self._bronze = bronze
        self._fetch_log = fetch_log_repo
        self._outbox = outbox_repo
        self._commit_fn = commit_fn
        self._rollback_fn = rollback_fn
        self._batch_size = batch_size

    async def execute(
        self,
        source: Source,
        *,
        is_backfill: bool = False,
        from_date: str = "",
        prefetched_results: list[FetchResult] | None = None,
    ) -> FetchSummary:
        """Run one fetch cycle for *source* and return a summary.

        Args:
            source: Polling source configuration.
            is_backfill: Whether this is a backfill run.
            from_date: Optional watermark date override for incremental polling.
            prefetched_results: Pre-fetched results (skip adapter.fetch if provided).
                Used when fetch happens outside the advisory lock.
        """
        start = time.monotonic()
        fetched = 0
        skipped = 0
        failed = 0
        errors: list[str] = []
        pending_in_batch = 0
        pending_minio_keys: list[str] = []  # track keys written since last commit

        # 1. Fetch from external API (or use pre-fetched results)
        if prefetched_results is not None:
            results: list[FetchResult] = prefetched_results
        else:
            try:
                results = await self._adapter.fetch(source, is_backfill=is_backfill, from_date=from_date)
            except Exception as exc:
                duration = time.monotonic() - start
                logger.error("fetch_failed", source=source.name, error=str(exc))
                return FetchSummary(
                    source_name=source.name,
                    failed=1,
                    duration_seconds=round(duration, 3),
                    errors=[str(exc)],
                )

        # 2. Process each result with batch commits
        seen_url_hashes: set[str] = set()  # intra-batch dedup (prevents UNIQUE violation on batched commits)
        for result in results:
            try:
                # 2a. Dedup check (DB + intra-batch)
                if await self._fetch_log.exists_by_url_hash(result.url_hash):
                    skipped += 1
                    continue
                if result.url_hash in seen_url_hashes:
                    skipped += 1
                    continue
                seen_url_hashes.add(result.url_hash)

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
                pending_minio_keys.append(minio_key)  # track for GC on rollback

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
                    doc_id=common.ids.new_uuid7(),
                    source_type=str(source.source_type),
                    source_url=result.url,
                    minio_bronze_key=minio_key,
                    raw_bytes=result.raw_bytes,
                    fetch_id=fetch_log_id,
                    published_at=ct.to_iso8601(result.published_at) if result.published_at else None,
                    is_backfill=result.is_backfill,
                    title=result.title,
                )

                await self._outbox.append(
                    aggregate_type="article",
                    aggregate_id=result.source_id,
                    event_type="content.article.raw.v1",
                    topic="content.article.raw.v1",
                    payload=payload,
                )

                fetched += 1
                pending_in_batch += 1

                # Batch commit: flush every batch_size articles
                if pending_in_batch >= self._batch_size:
                    await self._commit_fn()
                    pending_minio_keys = []  # committed — no longer orphaned
                    pending_in_batch = 0

            except Exception as exc:
                # Rollback to restore session state so subsequent articles can still process
                if self._rollback_fn:
                    try:
                        await self._rollback_fn()
                    except Exception:
                        logger.debug("rollback_failed_after_article_error", url_hash=result.url_hash)
                # GC: delete all MinIO objects that were written in this uncommitted batch
                for _key in pending_minio_keys:
                    try:
                        await self._bronze.delete_object(_key)
                    except Exception:
                        logger.warning("minio_gc_delete_failed", key=_key)
                pending_minio_keys = []
                pending_in_batch = 0  # batch lost on rollback
                failed += 1
                errors.append(f"{result.url_hash}: {exc}")
                logger.error("article_write_failed", url_hash=result.url_hash, error=str(exc))

        # Commit final partial batch
        if pending_in_batch > 0:
            try:
                await self._commit_fn()
                pending_minio_keys = []  # committed — no longer orphaned
            except Exception as exc:
                if self._rollback_fn:
                    try:
                        await self._rollback_fn()
                    except Exception:
                        logger.debug("rollback_failed_after_final_batch")
                # GC: delete all MinIO objects in the uncommitted final batch
                for _key in pending_minio_keys:
                    try:
                        await self._bronze.delete_object(_key)
                    except Exception:
                        logger.warning("minio_gc_delete_failed", key=_key)
                failed += pending_in_batch
                fetched -= pending_in_batch
                errors.append(f"final_batch: {exc}")
                logger.error("final_batch_commit_failed", error=str(exc))

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
