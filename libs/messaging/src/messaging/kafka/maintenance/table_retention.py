"""Generic age-based retention pruning for unbounded append/log tables.

Context (2026-07-18 Postgres disk-full outage)
----------------------------------------------
Several tables in the platform grow monotonically because rows are appended
but never removed:

* ``content_ingestion_db.outbox_events`` — the outbox dispatcher marks rows
  ``status='delivered'`` after publishing to Kafka but NEVER prunes them. The
  claimable partial index (``ix_outbox_claimable``) only covers
  ``pending``/``processing`` rows, so delivered rows are invisible to the
  dispatcher and pile up forever (reached 7.2 GB / 4.3M rows).
* ``content_ingestion_db.prediction_market_fetch_log`` — one dedup row per
  Polymarket snapshot, appended every poll cycle (3.8M rows / 1.1 GB).
* ``market_data_db.ingestion_events`` — one idempotency row per processed
  Kafka event (~1 GB).

Without retention the DB refills within ~1-2 weeks. This module provides a
single reusable, batched, per-batch-committing pruner that each owning
service wires into its already-running dispatcher process.

Design
------
* **Batched DELETE with per-batch commit.** The recovery had to delete in
  100-150k chunks because a single giant ``DELETE`` spikes WAL and holds a
  long transaction. We DELETE at most ``batch_size`` rows per transaction and
  commit after every batch (autocommit-per-batch semantics), so WAL stays
  flat and the pruner can be cancelled cleanly mid-run.
* **Non-blocking against writers.** On PostgreSQL the row-selection subquery
  uses ``FOR UPDATE SKIP LOCKED`` so the live producer/consumer INSERT is
  never blocked and two concurrent pruners cannot fight over the same rows.
  (SQLite — used in unit tests — does not support row locking, so the clause
  is omitted there; correctness of the WHERE filter is unaffected.)
* **DELETE ... WHERE pk IN (SELECT ... LIMIT n).** PostgreSQL ``DELETE`` does
  not accept ``LIMIT`` directly, so we use the canonical subselect pattern.
* **Optional status filter.** For the outbox, we MUST only delete
  ``status='delivered'`` rows — never ``pending``/``processing``/``failed``/
  ``dead_letter`` rows (those still need to be dispatched or triaged). The
  ``status_column``/``status_value`` pair adds ``AND <col> = <val>`` to the
  filter so the pruner physically cannot touch undelivered rows.

Safety
------
The retention window MUST be comfortably longer than any window in which a
row is still operationally needed:

* Outbox delivered rows: kept a short window (default 1h) purely for
  idempotency/audit after Kafka delivery — the Kafka topic itself is the
  durable record.
* Idempotency/dedup logs: kept long enough (default 14 days) to cover any
  plausible consumer offset rewind or re-poll window.
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

import common.time
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

# SQL identifiers (table/column names) cannot be passed as bind parameters, so
# they are interpolated into the statement text. Every identifier used here is
# a hard-coded constant from our own models (never user input), but we still
# validate against a strict allow-list regex as defence-in-depth so this helper
# can never become an injection vector if a future caller passes a dynamic name.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str, *, kind: str) -> str:
    """Return *name* if it is a safe SQL identifier, else raise ``ValueError``."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"unsafe {kind} identifier: {name!r}")
    return name


@dataclasses.dataclass(frozen=True)
class RetentionPolicy:
    """Declarative description of what to prune from a single table.

    Args:
        table: Table name to prune.
        pk_column: Primary-key column used by the ``IN (SELECT ... )`` subquery.
        age_column: Timestamp column compared against the cutoff. Rows whose
            ``age_column < now() - retention`` are eligible for deletion.
        retention: How long a row is kept after ``age_column``. Rows older than
            this are pruned.
        status_column: Optional column for an additional equality filter
            (e.g. ``"status"`` for the outbox). ``None`` disables the filter.
        status_value: Required value when ``status_column`` is set
            (e.g. ``"delivered"``). Rows whose status differs are NEVER touched.
    """

    table: str
    pk_column: str
    age_column: str
    retention: timedelta
    status_column: str | None = None
    status_value: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.table, kind="table")
        _validate_identifier(self.pk_column, kind="pk_column")
        _validate_identifier(self.age_column, kind="age_column")
        if self.status_column is not None:
            _validate_identifier(self.status_column, kind="status_column")
            if self.status_value is None:
                raise ValueError("status_value is required when status_column is set")
        if self.retention <= timedelta(0):
            raise ValueError("retention must be a positive timedelta")


class RetentionCleanupWorker:
    """Batched, per-batch-committing pruner for one :class:`RetentionPolicy`.

    Stateless w.r.t. the DB — a fresh :class:`AsyncSession` is supplied per
    :meth:`run_once` call so the caller owns the engine and pool. Designed to
    be scheduled periodically inside an already-running service process
    (typically the outbox dispatcher) via :func:`run_retention_loop`.

    Args:
        policy: What/how to prune.
        service_name: Identifier for structured logging correlation.
        batch_size: Maximum rows deleted per transaction. Default 10 000 keeps
            the per-transaction WAL/lock footprint small while amortising
            commit overhead on a multi-million-row backlog.
        max_batches: Safety cap on batches per :meth:`run_once` call so a huge
            backlog is drained across several scheduled runs rather than in one
            unbounded burst. ``None`` means "drain until caught up".
        interval_seconds: How often :func:`run_retention_loop` /
            :func:`build_retention_loop_coros` schedule this worker (delay
            between the end of one pass and the start of the next). Each worker
            owns its own cadence so tables with different growth rates can be
            pruned at different frequencies (e.g. a hot outbox every few minutes
            vs a slow dedup log hourly). Default 300s.
        inter_batch_sleep_seconds: Cooperative yield between batches so the
            event loop and DB get breathing room during a large catch-up.
    """

    DEFAULT_BATCH_SIZE = 10_000
    DEFAULT_INTERVAL_SECONDS = 300.0
    INTER_BATCH_SLEEP_SECONDS = 0.1

    def __init__(
        self,
        *,
        policy: RetentionPolicy,
        service_name: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_batches: int | None = None,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        inter_batch_sleep_seconds: float = INTER_BATCH_SLEEP_SECONDS,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0")
        if max_batches is not None and max_batches <= 0:
            raise ValueError("max_batches must be > 0 or None")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        self._policy = policy
        self._service_name = service_name
        self._batch_size = batch_size
        self._max_batches = max_batches
        self._interval_seconds = interval_seconds
        self._inter_batch_sleep = inter_batch_sleep_seconds

    @property
    def policy(self) -> RetentionPolicy:
        """The retention policy this worker enforces (read-only)."""
        return self._policy

    @property
    def interval_seconds(self) -> float:
        """Scheduling cadence for this worker's periodic loop (read-only)."""
        return self._interval_seconds

    def _build_delete_sql(self, *, use_row_locks: bool) -> str:
        """Build the batched DELETE statement text for the active dialect.

        ``FOR UPDATE SKIP LOCKED`` is only emitted for row-locking back-ends
        (PostgreSQL). It makes the delete non-blocking against concurrent
        INSERTs and prevents two pruners from contending on the same rows.
        """
        p = self._policy
        where = f"{p.age_column} < :cutoff"
        if p.status_column is not None:
            where = f"{p.status_column} = :status_value AND {where}"
        lock = " FOR UPDATE SKIP LOCKED" if use_row_locks else ""
        # S608 (SQL injection via string construction) is a false positive here:
        # only :cutoff / :status_value / :batch VALUES are interpolated, and each
        # is a bound parameter. The table/column identifiers come from a
        # RetentionPolicy validated against a strict identifier allow-list in
        # ``_validate_identifier`` (never user input), so this cannot be an
        # injection vector.
        select_ids = f"SELECT {p.pk_column} FROM {p.table} WHERE {where} ORDER BY {p.age_column} LIMIT :batch{lock}"  # noqa: S608
        return f"DELETE FROM {p.table} WHERE {p.pk_column} IN ({select_ids})"  # noqa: S608

    async def run_once(self, session: AsyncSession, *, now: datetime | None = None) -> int:
        """Run a single pruning pass and return the total rows deleted.

        The loop stops as soon as a batch deletes fewer than ``batch_size``
        rows (nothing left to prune, or the remainder is locked by a
        concurrent writer and will be picked up next run) or the
        ``max_batches`` cap is reached.
        """
        p = self._policy
        current = now or common.time.utc_now()
        cutoff = current - p.retention

        # PostgreSQL supports SELECT ... FOR UPDATE SKIP LOCKED; SQLite (tests)
        # does not. Detect via the bound engine dialect so the same worker runs
        # in both environments.
        dialect_name = ""
        bind = session.bind
        if bind is not None:
            dialect_name = getattr(getattr(bind, "dialect", None), "name", "") or ""
        use_row_locks = dialect_name == "postgresql"
        stmt = text(self._build_delete_sql(use_row_locks=use_row_locks))

        params: dict[str, object] = {"cutoff": cutoff, "batch": self._batch_size}
        if p.status_column is not None:
            params["status_value"] = p.status_value

        total_deleted = 0
        batches = 0
        while True:
            result = await session.execute(stmt, params)
            deleted = result.rowcount or 0  # type: ignore[attr-defined]
            total_deleted += deleted
            batches += 1
            # Commit after every batch: each batch is its own short
            # transaction, so WAL never spikes and a cancel mid-run leaves a
            # consistent, already-pruned prefix.
            await session.commit()
            if deleted < self._batch_size:
                break
            if self._max_batches is not None and batches >= self._max_batches:
                logger.info(
                    "table_retention_batch_cap_reached",
                    service=self._service_name,
                    table=p.table,
                    batches=batches,
                    total_deleted=total_deleted,
                )
                break
            await asyncio.sleep(self._inter_batch_sleep)

        logger.info(
            "table_retention_prune_completed",
            service=self._service_name,
            table=p.table,
            status_filter=p.status_value,
            total_deleted=total_deleted,
            batches=batches,
            retention_seconds=int(p.retention.total_seconds()),
            batch_size=self._batch_size,
            cutoff=cutoff.isoformat(),
        )
        return total_deleted


async def run_retention_loop(
    *,
    worker: RetentionCleanupWorker,
    session_factory: async_sessionmaker[AsyncSession],
    interval_seconds: float,
    stop_event: asyncio.Event,
    initial_delay_seconds: float = 0.0,
) -> None:
    """Periodically run *worker* until *stop_event* is set.

    Opens a FRESH session per pass (so a failed pass never leaves a poisoned
    session around) and is fail-open: any error in a single pass is logged and
    the loop continues — a pruning hiccup must never take down the host
    process (e.g. the outbox dispatcher).

    Args:
        worker: The pruner to run each interval.
        session_factory: Async session factory for the target DB.
        interval_seconds: Delay between the END of one pass and the START of
            the next.
        stop_event: Set by the host process on shutdown to end the loop.
        initial_delay_seconds: Optional stagger before the first pass so
            multiple loops sharing a process do not all fire at startup.
    """
    if initial_delay_seconds > 0:
        await _sleep_or_stop(stop_event, initial_delay_seconds)

    while not stop_event.is_set():
        try:
            async with session_factory() as session:
                await worker.run_once(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "table_retention_loop_error",
                table=worker.policy.table,
                error=str(exc),
            )
        await _sleep_or_stop(stop_event, interval_seconds)


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    """Sleep for *seconds* or return early if *stop_event* is set."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        # Timeout is the normal "interval elapsed, no stop requested" path.
        return


def build_retention_loop_coros(
    *,
    workers: list[RetentionCleanupWorker],
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event,
) -> list[Callable[[], Coroutine[Any, Any, None]]]:
    """Return zero-arg coroutine factories, one per worker's retention loop.

    Thin convenience wrapper for host processes that want to
    ``asyncio.create_task(coro())`` one background loop per worker. Each loop
    runs at its worker's own :attr:`RetentionCleanupWorker.interval_seconds`
    cadence, so tables with different growth rates prune at different
    frequencies. Staggers the initial delay so loops sharing a process do not
    all fire at once.
    """
    coros: list[Callable[[], Coroutine[Any, Any, None]]] = []
    for idx, worker in enumerate(workers):

        def _make(worker: RetentionCleanupWorker, delay: float) -> Callable[[], Coroutine[Any, Any, None]]:
            async def _run() -> None:
                await run_retention_loop(
                    worker=worker,
                    session_factory=session_factory,
                    interval_seconds=worker.interval_seconds,
                    stop_event=stop_event,
                    initial_delay_seconds=delay,
                )

            return _run

        coros.append(_make(worker, float(idx * 5)))
    return coros
