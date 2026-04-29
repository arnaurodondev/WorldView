"""Backfill ``alerts.title`` for legacy rows missing the enrichment column.

PLAN-0049 T-C-3-01.  Migration ``0006_add_alert_enrichment_columns`` added
four nullable VARCHAR columns to ``alerts`` (``title``, ``ticker``,
``entity_name``, ``signal_label``).  ``AlertFanoutUseCase`` populates them
on every newly-fanned-out alert, but rows written before the migration
landed still have ``title IS NULL``.  The frontend's RecentAlerts /
AlarmsPanel widgets then have to fall back to "<SEVERITY> signal" labels
which is exactly what F-D-006 / F-X-201 wanted to eliminate.

What this script does
---------------------
1. Selects alerts where ``title IS NULL`` (idempotent — repeated runs are
   no-ops once everything has been populated).
2. For each row, derives ``signal_label`` and ``title`` from the
   persisted ``payload`` JSON using the **same logic** as
   :mod:`alert.application.use_cases.alert_fanout` so that backfilled
   rows are indistinguishable from natively-enriched ones.
3. Writes the derived values back in batches of 1000 rows per commit.
4. Logs progress every 10 000 rows and a final tally.

Idempotency contract
--------------------
* The selection query filters on ``title IS NULL`` — once a row has a
  non-null title we never touch it again, even if a later iteration of
  the derivation logic would yield a different string.  Operators can
  re-run the script freely after schema changes without churning rows.
* ``UPDATE`` is also guarded by ``WHERE title IS NULL`` so a concurrent
  fan-out write (which sets title) wins; we never clobber live writes.

Connection model
----------------
Uses asyncpg directly via the ``ALERT_DB_URL`` env var (canonical libpq
DSN: ``postgres://user:pass@host:port/dbname``).  Bypasses SQLAlchemy /
the application UoW because:
  * SQLAlchemy adds startup overhead this one-shot doesn't need.
  * UoW expects a fully-wired DI graph; a backfill is operational, not
    request-scoped.
  * We need a single connection with explicit transactions for batch
    commits — asyncpg gives that with zero ceremony.

Usage
-----
::

    export ALERT_DB_URL="postgres://alert:alertpw@localhost:5443/alert_db"
    python services/alert/scripts/backfill_alert_titles.py

Add ``--dry-run`` to count the unbackfilled rows without mutating anything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from alert.application.use_cases.alert_fanout import (
    _compose_alert_title,
    _derive_signal_label,
)
from alert.domain.enums import AlertSeverity, AlertType
from observability import configure_logging, get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Tunables ──────────────────────────────────────────────────────────────────
# Batch size: 1000 rows / commit. Small enough that one bad row does not
# wedge a long transaction; large enough that we don't pay a fsync per row.
_BATCH_SIZE = 1000
# Progress log granularity (rows). 10x the batch size keeps the log signal-
# to-noise ratio sensible on multi-million-row backfills.
_PROGRESS_EVERY = 10_000


def _safe_severity(value: Any) -> AlertSeverity:
    """Coerce a free-form severity string to :class:`AlertSeverity`.

    Falls back to ``MEDIUM`` for unrecognised values — the derivation
    logic in :mod:`alert_fanout` produces ``"<SEVERITY> signal"`` strings
    only on the fallback path, so an unknown severity here just shows up
    as "MEDIUM signal" rather than crashing the backfill.
    """
    if isinstance(value, str):
        try:
            return AlertSeverity(value.lower())
        except ValueError:
            pass
    return AlertSeverity.MEDIUM


def _safe_alert_type(value: Any) -> AlertType:
    """Coerce a free-form alert_type string to :class:`AlertType`.

    Mirrors ``_safe_severity``: any unknown value collapses to ``SIGNAL``
    so the title fallback still produces a sensible humanised string
    ("Signal Alert") rather than raising.
    """
    if isinstance(value, str):
        try:
            return AlertType(value.upper())
        except ValueError:
            pass
    return AlertType.SIGNAL


def _derive_for_row(row: asyncpg.Record) -> tuple[str, str, str | None, str | None]:
    """Return ``(title, signal_label, entity_name, ticker)`` derived from a DB row.

    Mirrors :func:`alert_fanout._derive_signal_label` and
    :func:`alert_fanout._compose_alert_title` exactly so backfilled rows
    are indistinguishable from rows written natively by the consumer.
    """
    payload: dict[str, Any] = row["payload"] or {}
    severity = _safe_severity(row["severity"])
    alert_type = _safe_alert_type(row["alert_type"])

    # Pull (entity_name, ticker) out of payload first — they were
    # injected there by AlertFanoutUseCase before the dedicated columns
    # existed, so legacy rows have them in the JSON blob.
    entity_name_raw = payload.get("entity_name")
    ticker_raw = payload.get("ticker")
    entity_name: str | None = str(entity_name_raw) if entity_name_raw else None
    ticker: str | None = str(ticker_raw) if ticker_raw else None

    # The signal_label-on-payload key only started being written in
    # PLAN-0048 Wave B-1; older rows have nothing there.  Re-derive
    # rather than trust the payload value to keep one source of truth.
    signal_label, is_fallback = _derive_signal_label(payload, severity)

    title = _compose_alert_title(
        signal_label=signal_label,
        entity_name=entity_name,
        ticker=ticker,
        alert_type=alert_type,
        is_signal_label_fallback=is_fallback,
    )
    return title, signal_label, entity_name, ticker


async def _count_null_titles(conn: asyncpg.Connection) -> int:
    """Return the number of rows with ``title IS NULL`` (operational metric)."""
    result = await conn.fetchval("SELECT COUNT(*) FROM alerts WHERE title IS NULL")
    return int(result or 0)


async def _fetch_batch(conn: asyncpg.Connection, batch_size: int) -> list[asyncpg.Record]:
    """Fetch the next batch of rows needing a backfill.

    We re-issue the SELECT on every iteration rather than stream a server-
    side cursor: each batch's UPDATE narrows the WHERE clause population
    so the next SELECT naturally returns fresh rows.  Avoids holding a
    transaction open across the whole job.
    """
    rows = await conn.fetch(
        """
        SELECT alert_id, alert_type, severity, payload
        FROM alerts
        WHERE title IS NULL
        ORDER BY alert_id
        LIMIT $1
        """,
        batch_size,
    )
    return list(rows)


async def _update_batch(
    conn: asyncpg.Connection,
    updates: Iterable[tuple[UUID, str, str, str | None, str | None]],
) -> int:
    """Apply a batch of ``(alert_id, title, signal_label, entity_name, ticker)`` updates.

    Wrapped in a single transaction; each ``UPDATE`` is guarded by
    ``title IS NULL`` so a racing fan-out write that already populated
    the row wins (we never overwrite live data).
    """
    updated = 0
    async with conn.transaction():
        for alert_id, title, signal_label, entity_name, ticker in updates:
            result = await conn.execute(
                """
                UPDATE alerts
                SET title = $2,
                    signal_label = $3,
                    entity_name = COALESCE(entity_name, $4),
                    ticker = COALESCE(ticker, $5)
                WHERE alert_id = $1
                  AND title IS NULL
                """,
                alert_id,
                title,
                signal_label,
                entity_name,
                ticker,
            )
            # asyncpg's execute returns "UPDATE N" — parse trailing int.
            try:
                count = int(result.rsplit(" ", 1)[-1])
            except (ValueError, AttributeError):
                count = 0
            updated += count
    return updated


async def _run(database_url: str, *, dry_run: bool) -> tuple[int, int]:
    """Top-level driver.  Returns ``(rows_seen, rows_updated)``."""
    # asyncpg accepts both ``postgres://`` and ``postgresql://`` DSNs.
    # The application config uses SQLAlchemy's ``postgresql+asyncpg://``
    # form which asyncpg itself rejects — strip the ``+asyncpg`` driver
    # tag if present so operators can paste either DSN flavour.
    cleaned = database_url.replace("postgresql+asyncpg://", "postgresql://")

    # F-QAC-12 fix: tag connection so operators can identify the script in
    # pg_stat_activity / kill it cleanly if it runs away on a huge table.
    # command_timeout=300 means a single statement (the SELECT batch or
    # UPDATE batch) won't hang the script forever on a deadlocked row.
    conn = await asyncpg.connect(
        cleaned,
        server_settings={"application_name": "alert-backfill-titles"},
        command_timeout=300,
    )
    try:
        # F-QAC-01 fix (CRITICAL): asyncpg does NOT auto-decode JSONB by
        # default — it returns the raw text representation as a `str`.
        # Without this codec registration, every row's `payload` would be
        # a string and `payload.get(...)` would raise AttributeError, get
        # swallowed by the per-row try/except, and the script would silently
        # log thousands of `derive_error` lines while updating zero rows.
        # The codec converts JSONB → dict on read and dict → JSONB on write
        # using the std-lib `json` module (no external deps).
        await conn.set_type_codec(
            "jsonb",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )
        initial_null = await _count_null_titles(conn)
        logger.info("backfill_alert_titles.start", rows_with_null_title=initial_null, dry_run=dry_run)

        if dry_run or initial_null == 0:
            return initial_null, 0

        rows_seen = 0
        rows_updated = 0
        # F-QAC-11 fix: track an explicit threshold rather than relying on
        # `rows_seen % _PROGRESS_EVERY < _BATCH_SIZE` which only works when
        # _PROGRESS_EVERY is an exact multiple of _BATCH_SIZE. Self-corrects
        # if either constant is later tuned.
        next_progress_threshold = _PROGRESS_EVERY

        while True:
            batch = await _fetch_batch(conn, _BATCH_SIZE)
            if not batch:
                break

            updates: list[tuple[UUID, str, str, str | None, str | None]] = []
            for row in batch:
                try:
                    title, signal_label, entity_name, ticker = _derive_for_row(row)
                except Exception as exc:
                    # Defensive: never let one malformed payload abort the
                    # whole backfill. Log + skip; operators can grep the
                    # logs for these alert_ids and handle them out-of-band.
                    logger.warning(
                        "backfill_alert_titles.derive_error",
                        alert_id=str(row["alert_id"]),
                        error=str(exc),
                    )
                    continue
                updates.append((row["alert_id"], title, signal_label, entity_name, ticker))

            if updates:
                applied = await _update_batch(conn, updates)
                rows_updated += applied

            rows_seen += len(batch)

            # Progress log every 10k rows (or on the very first batch so
            # operators see *something* quickly on small tables).
            if rows_seen == len(batch) or rows_seen >= next_progress_threshold:
                logger.info(
                    "backfill_alert_titles.progress",
                    rows_seen=rows_seen,
                    rows_updated=rows_updated,
                    rows_remaining=max(0, initial_null - rows_seen),
                )
                # Advance threshold past the current rows_seen — handles the
                # case where one batch jumps over multiple progress windows.
                while next_progress_threshold <= rows_seen:
                    next_progress_threshold += _PROGRESS_EVERY

        logger.info(
            "backfill_alert_titles.complete",
            rows_seen=rows_seen,
            rows_updated=rows_updated,
            initial_null=initial_null,
        )
        return rows_seen, rows_updated
    finally:
        await conn.close()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill alerts.title for legacy rows (PLAN-0049 T-C-3-01).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report row counts without mutating anything.",
    )
    return parser.parse_args(argv)


async def amain(argv: list[str]) -> int:
    args = _parse_args(argv)

    try:
        database_url = os.environ["ALERT_DB_URL"]
    except KeyError:
        # Plain print to stderr — structlog isn't configured yet at this point
        # and the operator needs an unambiguous message.
        sys.stderr.write("ALERT_DB_URL env var is required\n")
        return 2

    configure_logging(service_name="alert-backfill-titles", level="INFO", json=False)

    await _run(database_url, dry_run=args.dry_run)
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain(sys.argv[1:])))


if __name__ == "__main__":
    main()
