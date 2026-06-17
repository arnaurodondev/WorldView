"""ExecuteContentTaskUseCase — execute one content ingestion task.

Wraps the existing ``FetchAndWriteUseCase`` with task lifecycle management:
mark RUNNING → fetch from external API → write results → mark SUCCEEDED/RETRY/FAILED.

Session optimization (R24): no database session is held during external API
calls.  The pattern is read → release → I/O → acquire → write.

All infrastructure dependencies are injected via the constructor (R25):
repository factories, bronze storage, and adapter builder.  The application
layer has zero imports from ``content_ingestion.infrastructure``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from content_ingestion.application.use_cases.fetch_and_write import FetchAndWriteUseCase, FetchSummary
from content_ingestion.domain.exceptions import ConfigurationError
from messaging.pg.advisory_lock import pg_advisory_lock  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from content_ingestion.application.ports.repositories import (
        AdapterStatePort,
        BronzeStoragePort,
        FetchLogPort,
        OutboxPort,
        TaskPort,
    )
    from content_ingestion.application.ports.source_adapter import SourceAdapterPort
    from content_ingestion.config import Settings
    from content_ingestion.domain.entities import ContentIngestionTask, FetchResult, Source, SourceType

logger = get_logger(__name__)

# Fatal errors that should not be retried
_FATAL_ERRORS = (ConfigurationError, KeyError, ValueError, TypeError)


def _newest_published_at(results: list[FetchResult]) -> Any:
    """Return the maximum ``published_at`` across a fetched batch, or ``None``.

    Used to advance the source watermark to the newest article we actually
    saw (QUOTA-OPT) so the next sweep's ``from`` window stays tight. Articles
    without a parseable ``published_at`` are ignored; when none carry a
    timestamp the caller falls back to wall-clock ``now``.
    """
    timestamps = [r.published_at for r in results if r.published_at is not None]
    return max(timestamps) if timestamps else None


@dataclass
class _FetchOutput:
    """Result of _fetch_from_source — carries all data needed for write phase."""

    results: list[FetchResult]
    adapter: SourceAdapterPort
    source: Source
    watermark_date: str


class ExecuteContentTaskUseCase:
    """Execute one content ingestion task: fetch → MinIO → DB + outbox.

    Reuses ``FetchAndWriteUseCase`` unchanged for the write pipeline;
    this use case adds task lifecycle (RUNNING → SUCCEEDED/RETRY/FAILED)
    and session optimization (no session held during external API calls).

    All infrastructure dependencies are injected via the constructor:

    - **Repository factories** (``adapter_state_factory``, ``fetch_log_factory``,
      ``outbox_factory``): callables that accept a DB session and return
      the corresponding port implementation.
    - **task_factory**: callable that accepts a DB session and returns a
      ``TaskPort``.  Used to update task status *inside* the advisory-lock
      transaction so the status write is atomic with the data write (D-9).
    - **bronze**: pre-built ``BronzeStoragePort`` for MinIO writes.
    - **adapter_builder**: callable that constructs a ``SourceAdapterPort``
      for a given source type + dedup function, encapsulating all client
      and rate-limiter construction in the infrastructure layer.
    """

    def __init__(
        self,
        *,
        write_factory: async_sessionmaker[Any],
        settings: Settings,
        bronze: BronzeStoragePort,
        adapter_state_factory: Callable[[Any], AdapterStatePort],
        fetch_log_factory: Callable[[Any], FetchLogPort],
        outbox_factory: Callable[[Any], OutboxPort],
        adapter_builder: Callable[[SourceType, Callable[[str], Awaitable[bool]]], SourceAdapterPort],
        task_factory: Callable[[Any], TaskPort] | None = None,
    ) -> None:
        self._write_factory = write_factory
        self._settings = settings
        self._bronze = bronze
        self._adapter_state_factory = adapter_state_factory
        self._fetch_log_factory = fetch_log_factory
        self._outbox_factory = outbox_factory
        self._adapter_builder = adapter_builder
        self._task_factory = task_factory

    async def execute(
        self,
        task: ContentIngestionTask,
        task_repo: TaskPort,
    ) -> FetchSummary | None:
        """Execute one task through the full fetch-and-write pipeline.

        Args:
            task: The claimed task to execute.
            task_repo: Task repository for status updates (uses caller's session).

        Returns:
            FetchSummary on success, None on empty results.
        """
        # 1. Mark RUNNING (task was already CLAIMED by the worker).
        #
        # BP-XXX (poisoned-session P0, 2026-06-11): the RUNNING write MUST be
        # committed IMMEDIATELY in its own short-lived session — never left
        # uncommitted on the outer worker session.  The outer session is only
        # committed by the worker AFTER execute() returns, so an uncommitted
        # RUNNING UPDATE holds a row lock on content_ingestion_tasks for the
        # entire fetch.  The D-9 path later updates the SAME row from the
        # advisory-lock session → undetectable self-deadlock (outer session is
        # idle-in-transaction, not waiting, so Postgres can't see the cycle).
        # The 120s worker_task_timeout then cancels the task mid-transaction,
        # poisoning pooled asyncpg connections ("Can't reconnect until invalid
        # transaction is rolled back") for every subsequent task.
        # Mirrors the working pattern in worker._execute_polymarket_task.
        task.start()
        if self._task_factory is not None:
            async with self._write_factory() as running_session:
                try:
                    running_repo = self._task_factory(running_session)
                    await running_repo.update_status(task.id, task.status)
                    await running_session.commit()
                except Exception:
                    await running_session.rollback()
                    raise
        else:
            # Legacy/test path without task_factory: fall back to the caller's
            # session.  Production (worker.py) always injects task_factory.
            await task_repo.update_status(task.id, task.status)

        try:
            return await self._do_fetch_and_write(task, task_repo)
        except _FATAL_ERRORS as exc:
            # Fatal: exhaust attempts immediately
            task.attempt_count = task.max_attempts
            task.fail(str(exc))
            try:
                await task_repo.update_status(task.id, task.status, error_detail=task.error_detail)
            except Exception as db_err:
                logger.error(
                    "task_status_update_failed",
                    task_id=str(task.id),
                    original_error=str(exc),
                    db_error=str(db_err),
                )
                raise db_err from exc
            logger.error("task_fatal_error", task_id=str(task.id), error=str(exc))
            return None
        except Exception as exc:
            # Retryable
            task.fail(str(exc))
            try:
                await task_repo.update_status(task.id, task.status, error_detail=task.error_detail)
            except Exception as db_err:
                logger.error(
                    "task_status_update_failed",
                    task_id=str(task.id),
                    original_error=str(exc),
                    db_error=str(db_err),
                )
                raise db_err from exc
            logger.warning("task_retryable_error", task_id=str(task.id), error=str(exc))
            return None

    async def _do_fetch_and_write(
        self,
        task: ContentIngestionTask,
        task_repo: TaskPort,
    ) -> FetchSummary | None:
        """Inner pipeline: read watermark → fetch → write → update watermark."""
        import common.time as ct_mod

        # 2. Read watermark (separate short session — BP-016: released before I/O).
        #
        # PLAN-0109 / BP-659: wrap the read in ``try/finally: rollback`` so a
        # pooled connection never returns to the pool with state
        # ``idle in transaction (aborted)``.  Without the rollback an asyncpg
        # exception surfaces as "Can't reconnect" on the next acquirer because
        # the implicit transaction stayed open.
        watermark_date = ""
        async with self._write_factory() as ro_session:
            try:
                state_repo = self._adapter_state_factory(ro_session)
                state = await state_repo.get(task.source_id)
                if state and state.last_watermark:
                    watermark_date = state.last_watermark.strftime("%Y-%m-%d")
            finally:
                # Read-only, but rollback is still required to release the
                # implicit transaction and reset the pooled connection.
                await ro_session.rollback()

        # 3. Build adapter and fetch (no session held — R24)
        fetch_output = await self._fetch_from_source(task, watermark_date)

        if not fetch_output.results:
            # PLAN-0109 / T-C-1-02: empty-but-successful poll — advance
            # ``last_run_at`` so dashboards can distinguish a healthy
            # "no news today" cycle from a silently failing worker.
            # ``last_watermark`` is intentionally NOT touched so backfills
            # remain anchored at the most recent article we actually saw.
            async with self._write_factory() as empty_session:
                try:
                    adapter_state_repo = self._adapter_state_factory(empty_session)
                    config_hash = getattr(fetch_output.source, "config_hash", None)
                    await adapter_state_repo.upsert(
                        task.source_id,
                        last_run_at=ct_mod.utc_now(),
                        last_run_config_hash=config_hash,
                    )
                    await empty_session.commit()
                except Exception:
                    await empty_session.rollback()
                    raise
            task.succeed()
            await task_repo.update_status(task.id, task.status)
            return None

        # 4. Write results under advisory lock
        async with (
            self._write_factory() as session,
            pg_advisory_lock(session, f"s4:fetch:{task.source_name}") as acquired,
        ):
            try:
                return await self._write_results_under_lock(
                    session=session,
                    acquired=acquired,
                    task=task,
                    task_repo=task_repo,
                    fetch_output=fetch_output,
                )
            except Exception:
                # Defense in depth (poisoned-session P0): roll back BEFORE
                # ``pg_advisory_lock``'s finally clause runs ``pg_advisory_unlock``.
                # On an aborted transaction the unlock statement would raise
                # ``InFailedSQLTransaction`` — masking the original error — and
                # the session-level advisory lock would leak into the pooled
                # connection, blocking every other worker for this source.
                await session.rollback()
                raise

    async def _write_results_under_lock(
        self,
        *,
        session: Any,
        acquired: bool,
        task: ContentIngestionTask,
        task_repo: TaskPort,
        fetch_output: _FetchOutput,
    ) -> FetchSummary | None:
        """Write fetch results + final task status inside the advisory-lock session.

        Extracted from ``_do_fetch_and_write`` (poisoned-session P0 fix) so the
        caller can roll back the session on ANY failure before the advisory
        lock's unlock statement executes.
        """
        # Defense in depth (poisoned-session P0): bound every lock wait in
        # this transaction.  If a future change re-introduces an uncommitted
        # row lock held by another session of this same worker (the
        # self-deadlock fixed in step 1 of execute()), the UPDATE here fails
        # loudly with ``lock_not_available`` after 10s instead of hanging until
        # the 120s task timeout cancels mid-transaction and poisons the pool.
        # SET LOCAL scopes the setting to the current transaction only, so the
        # pooled connection returns clean after commit/rollback.
        from sqlalchemy import text

        import common.time as ct_mod

        await session.execute(text("SET LOCAL lock_timeout = '10s'"))

        if not acquired:
            # Another worker holds the lock — mark RETRY so the task is
            # re-attempted later (D-003).  We must NOT mark SUCCEEDED because
            # the data write did not happen in *this* worker.
            from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

            if self._task_factory is not None:
                # F-CRIT-004: always use task_factory(session) inside the
                # write_factory session — never the outer task_repo.
                inner_task_repo = self._task_factory(session)
                await inner_task_repo.update_status(task.id, IngestionTaskStatus.RETRY)
                await session.commit()
            else:
                await task_repo.update_status(task.id, IngestionTaskStatus.RETRY)
            task.retry("advisory_lock_held_by_another_worker")
            return None

        fetch_log_repo = self._fetch_log_factory(session)
        outbox_repo = self._outbox_factory(session)
        use_case = FetchAndWriteUseCase(
            adapter=fetch_output.adapter,
            bronze=self._bronze,
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

        # Update watermark after successful writes.
        # PLAN-0055 B-1: also snapshot the live ``sources.config_hash`` so the
        # startup drift detector can flag operator config edits since this run.
        #
        # PLAN-0109 / T-C-1-02: ``last_run_at`` must advance UNCONDITIONALLY
        # on every successful poll — even when ``summary.fetched == 0`` — so
        # operational dashboards (and the polling-staleness alert) can tell
        # a healthy "no news today" run apart from a hung/silent worker.
        # ``last_watermark`` keeps its existing semantics (only advances when
        # we actually persisted new articles) so backfills remain correct.
        adapter_state_repo = self._adapter_state_factory(session)
        now = ct_mod.utc_now()
        config_hash = getattr(fetch_output.source, "config_hash", None)
        if summary.fetched > 0:
            # QUOTA-OPT (2026-06-16): advance the watermark to the NEWEST
            # article's ``published_at`` (not wall-clock ``now``). The next
            # sweep's ``from`` is derived from this value, so anchoring it on
            # the actual newest article keeps the incremental window tight and
            # correct — wall-clock ``now`` could skip articles published
            # between the API's latest item and this write, or (with the
            # adapter's safety overlap) needlessly widen the next window.
            # Fall back to ``now`` only when no article carried a timestamp.
            newest_published = _newest_published_at(fetch_output.results)
            await adapter_state_repo.upsert(
                task.source_id,
                last_watermark=newest_published or now,
                last_run_at=now,
                last_run_config_hash=config_hash,
            )
        else:
            # Empty-but-successful poll: bump ``last_run_at`` only.
            # We deliberately omit ``last_watermark`` so the existing
            # watermark (or NULL) is preserved by the upsert.
            await adapter_state_repo.upsert(
                task.source_id,
                last_run_at=now,
                last_run_config_hash=config_hash,
            )

        # 5. Mark task SUCCEEDED *inside* the advisory-lock transaction (D-9).
        #
        # Write the status to the DB BEFORE mutating the domain object.
        # This way, if session.commit() fails, task.status is still RUNNING
        # and the outer execute() error handler can safely call task.fail().
        # The domain object is only updated AFTER the commit succeeds.
        #
        # Pattern: write-then-commit-then-mutate (not mutate-then-commit).
        from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

        if self._task_factory is not None:
            inner_task_repo = self._task_factory(session)
            await inner_task_repo.update_status(task.id, IngestionTaskStatus.SUCCEEDED)
        else:
            await task_repo.update_status(task.id, IngestionTaskStatus.SUCCEEDED)
        await session.commit()
        # Commit succeeded — safe to mutate domain object in memory
        task.succeed()

        return summary

    async def _fetch_from_source(
        self,
        task: ContentIngestionTask,
        watermark_date: str,
    ) -> _FetchOutput:
        """Build the adapter for this task's source type and fetch articles.

        Adapter construction is delegated to the injected ``adapter_builder``
        callable, keeping infrastructure imports out of the application layer.

        Returns a ``_FetchOutput`` containing all data the write phase needs.
        """
        from content_ingestion.domain.entities import Source

        source = Source(
            id=task.source_id,
            name=task.source_name,
            source_type=task.source_type,
            enabled=True,
            # Use the source config loaded by claim_batch (symbol, from_date, etc.)
            # so adapters like Finnhub can read their required parameters.
            config=task.source_config,
        )

        # Build adapter with dedup check via a short-lived session.
        #
        # PLAN-0109 / BP-659: this session lives across the external HTTP fetch
        # (adapter.fetch) — if the fetch raises and the session exits without an
        # explicit rollback, the asyncpg connection returns to the pool with
        # ``idle in transaction (aborted)`` state and surfaces as "Can't
        # reconnect" on the next acquirer.  Wrap in ``try/finally: rollback`` to
        # reset the connection on every exit path (success or failure).
        async with self._write_factory() as dedup_session:
            try:
                dedup_repo = self._fetch_log_factory(dedup_session)
                adapter = self._adapter_builder(task.source_type, dedup_repo.exists_by_url_hash)

                results = await adapter.fetch(
                    source,
                    is_backfill=task.is_backfill or self._settings.backfill_enabled,
                    from_date=watermark_date,
                )
            finally:
                # Read-only session over network I/O — rollback the implicit
                # transaction so the connection returns clean to the pool.
                await dedup_session.rollback()

        return _FetchOutput(
            results=results,  # type: ignore[arg-type]
            adapter=adapter,
            source=source,
            watermark_date=watermark_date,
        )
