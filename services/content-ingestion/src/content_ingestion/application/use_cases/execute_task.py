"""ExecuteContentTaskUseCase — execute one content ingestion task.

Wraps the existing ``FetchAndWriteUseCase`` with task lifecycle management:
mark RUNNING → fetch from external API → write results → mark SUCCEEDED/RETRY/FAILED.

Session optimization (R24): no database session is held during external API
calls.  The pattern is read → release → I/O → acquire → write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from content_ingestion.application.use_cases.fetch_and_write import FetchAndWriteUseCase, FetchSummary
from content_ingestion.domain.exceptions import AdapterError, ConfigurationError
from content_ingestion.infrastructure.db.repositories.adapter_state import AdapterStateRepository
from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.metrics.prometheus import record_fetch
from content_ingestion.infrastructure.scheduler.scheduler import ADAPTER_REGISTRY
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter
from messaging.pg.advisory_lock import pg_advisory_lock  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from content_ingestion.config import Settings
    from content_ingestion.domain.entities import ContentIngestionTask, FetchResult, Source
    from content_ingestion.infrastructure.adapters.base import SourceAdapter
    from content_ingestion.infrastructure.db.repositories.task import TaskRepository
    from messaging.valkey import ValkeyClient  # type: ignore[import-untyped]
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)

# Fatal errors that should not be retried
_FATAL_ERRORS = (ConfigurationError, KeyError, ValueError, TypeError)


@dataclass
class _FetchOutput:
    """Result of _fetch_from_source — carries all data needed for write phase."""

    results: list[FetchResult]
    adapter: SourceAdapter
    source: Source
    watermark_date: str


class ExecuteContentTaskUseCase:
    """Execute one content ingestion task: fetch → MinIO → DB + outbox.

    Reuses ``FetchAndWriteUseCase`` unchanged for the write pipeline;
    this use case adds task lifecycle (RUNNING → SUCCEEDED/RETRY/FAILED)
    and session optimization (no session held during external API calls).
    """

    def __init__(
        self,
        write_factory: async_sessionmaker[Any],
        http_client: httpx.AsyncClient,
        storage: ObjectStorage,
        valkey: ValkeyClient,
        settings: Settings,
    ) -> None:
        self._write_factory = write_factory
        self._http_client = http_client
        self._storage = storage
        self._valkey = valkey
        self._settings = settings

    async def execute(
        self,
        task: ContentIngestionTask,
        task_repo: TaskRepository,
    ) -> FetchSummary | None:
        """Execute one task through the full fetch-and-write pipeline.

        Args:
            task: The claimed task to execute.
            task_repo: Task repository for status updates (uses caller's session).

        Returns:
            FetchSummary on success, None on empty results.
        """
        # 1. Mark RUNNING (task was already CLAIMED by the worker)
        task.start()
        await task_repo.update_status(task.id, task.status)

        try:
            return await self._do_fetch_and_write(task, task_repo)
        except _FATAL_ERRORS as exc:
            # Fatal: exhaust attempts immediately
            task.attempt_count = task.max_attempts
            task.fail(str(exc))
            await task_repo.update_status(task.id, task.status, error_detail=task.error_detail)
            logger.error("task_fatal_error", task_id=str(task.id), error=str(exc))
            return None
        except Exception as exc:
            # Retryable
            task.fail(str(exc))
            await task_repo.update_status(task.id, task.status, error_detail=task.error_detail)
            logger.warning("task_retryable_error", task_id=str(task.id), error=str(exc))
            return None

    async def _do_fetch_and_write(
        self,
        task: ContentIngestionTask,
        task_repo: TaskRepository,
    ) -> FetchSummary | None:
        """Inner pipeline: read watermark → fetch → write → update watermark."""
        import common.time as ct_mod

        # 2. Read watermark (separate short session — BP-016: released before I/O)
        watermark_date = ""
        async with self._write_factory() as ro_session:
            state_repo = AdapterStateRepository(ro_session)
            state = await state_repo.get(task.source_id)
            if state and state.last_watermark:
                watermark_date = state.last_watermark.strftime("%Y-%m-%d")

        # 3. Build adapter and fetch (no session held — R24)
        fetch_output = await self._fetch_from_source(task, watermark_date)

        if not fetch_output.results:
            task.succeed()
            await task_repo.update_status(task.id, task.status)
            return None

        # 4. Write results under advisory lock
        async with (
            self._write_factory() as session,
            pg_advisory_lock(session, f"s4:fetch:{task.source_name}") as acquired,
        ):
            if not acquired:
                task.succeed()
                await task_repo.update_status(task.id, task.status)
                return None

            fetch_log_repo = FetchLogRepository(session)
            bronze = MinioBronzeAdapter(self._storage)
            outbox_repo = OutboxRepository(session)
            use_case = FetchAndWriteUseCase(
                adapter=fetch_output.adapter,
                bronze=bronze,
                fetch_log_repo=fetch_log_repo,
                outbox_repo=outbox_repo,
                commit_fn=session.commit,
                rollback_fn=session.rollback,
            )

            summary = await use_case.execute(
                fetch_output.source,
                is_backfill=task.is_backfill or self._settings.backfill_enabled,
                from_date=fetch_output.watermark_date,
                prefetched_results=fetch_output.results,
            )

            # Update watermark after successful writes
            if summary.fetched > 0:
                adapter_state_repo = AdapterStateRepository(session)
                now = ct_mod.utc_now()
                await adapter_state_repo.upsert(
                    task.source_id,
                    last_watermark=now,
                    last_run_at=now,
                )
                await session.commit()

        # 5. Mark task SUCCEEDED
        task.succeed()
        await task_repo.update_status(task.id, task.status)

        # Record metrics
        record_fetch(
            task.source_name,
            fetched=summary.fetched,
            skipped=summary.skipped,
            failed=summary.failed,
            duration=summary.duration_seconds,
        )
        return summary

    async def _fetch_from_source(
        self,
        task: ContentIngestionTask,
        watermark_date: str,
    ) -> _FetchOutput:
        """Build the adapter for this task's source type and fetch articles.

        Returns a ``_FetchOutput`` containing all data the write phase needs.
        """
        import common.time as ct_mod
        from content_ingestion.domain.entities import Source
        from content_ingestion.domain.value_objects import TokenBucket
        from content_ingestion.infrastructure.adapters.eodhd.client import EODHDClient
        from content_ingestion.infrastructure.adapters.finnhub.client import FinnhubClient
        from content_ingestion.infrastructure.adapters.newsapi.client import NewsAPIClient
        from content_ingestion.infrastructure.adapters.sec_edgar.client import SECEdgarClient

        now = ct_mod.utc_now()
        settings = self._settings

        # Build Source entity for the adapter
        source = Source(
            id=task.source_id,
            name=task.source_name,
            source_type=task.source_type,
            enabled=True,
            config={},
        )

        adapter_cls = ADAPTER_REGISTRY.get(task.source_type)
        if adapter_cls is None:
            raise AdapterError(f"No adapter registered for source type {task.source_type!r}")

        # Build rate limiter and client
        eodhd_rps = settings.eodhd.rate_limit_per_second
        rate_limiter = TokenBucket(
            capacity=int(eodhd_rps),
            tokens=eodhd_rps,
            refill_rate=eodhd_rps,
            last_refill=now,
        )

        client: object
        source_type_val = task.source_type.value
        if source_type_val == "eodhd":
            client = EODHDClient(
                http_client=self._http_client,
                api_key=settings.eodhd_api_key,
                provider_cfg=settings.eodhd,
            )
        elif source_type_val == "sec_edgar":
            client = SECEdgarClient(
                http_client=self._http_client,
                user_agent=settings.sec_edgar_user_agent,
                provider_cfg=settings.sec_edgar,
            )
        elif source_type_val == "finnhub":
            rate_per_second = settings.finnhub.rate_limit_per_minute / 60.0
            rate_limiter = TokenBucket(
                capacity=settings.finnhub.rate_limit_per_minute,
                tokens=float(settings.finnhub.rate_limit_per_minute),
                refill_rate=rate_per_second,
                last_refill=now,
            )
            client = FinnhubClient(
                http_client=self._http_client,
                api_key=settings.finnhub_api_key,
                provider_cfg=settings.finnhub,
            )
        elif source_type_val == "newsapi":
            client = NewsAPIClient(
                http_client=self._http_client,
                api_key=settings.newsapi_key,
                provider_cfg=settings.newsapi,
                valkey=self._valkey,
                daily_limit=settings.newsapi_daily_limit,
            )
        else:
            raise AdapterError(f"Unknown source type: {source_type_val}")

        # Build adapter with dedup check via a short-lived session
        async with self._write_factory() as dedup_session:
            dedup_repo = FetchLogRepository(dedup_session)

            if source_type_val == "newsapi":
                adapter = adapter_cls(  # type: ignore[call-arg]
                    client=client,
                    exists_fn=dedup_repo.exists_by_url_hash,
                )
            else:
                adapter = adapter_cls(  # type: ignore[call-arg]
                    client=client,
                    rate_limiter=rate_limiter,
                    exists_fn=dedup_repo.exists_by_url_hash,
                )

            results = await adapter.fetch(
                source,
                is_backfill=task.is_backfill or settings.backfill_enabled,
                from_date=watermark_date,
            )

        return _FetchOutput(
            results=results,  # type: ignore[arg-type]
            adapter=adapter,
            source=source,
            watermark_date=watermark_date,
        )
