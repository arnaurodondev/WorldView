"""Nightly intelligence rollup sync use case.

PLAN-0089 Wave L-5b (T-WL5B-03).

WHAT THIS DOES:
  Cursor-paginates over all instruments and for each batch fires parallel
  HTTP calls to 4 upstream services:
    - S6 (content-store) → news_count_7d, llm_relevance_7d_max,
                           display_relevance_7d_weighted
    - S7 (knowledge-graph) → recent_contradiction_count
    - S10 (alert)          → has_active_alert
    - S8  (rag-chat)       → has_ai_brief

  Results are UPSERTed into ``instrument_fundamentals_snapshot`` with an
  ``intelligence_rollup_synced_at`` timestamp.

  Instruments whose ``intelligence_rollup_synced_at`` is within
  ``skip_if_fresh_within_hours`` (default 18) are skipped cheaply.

FAILURE SEMANTICS (keep-last-known):
  If an upstream endpoint fails for a given instrument, the existing snapshot
  column values are kept (NOT overwritten with NULL).  Only the fields from
  successful calls are updated on that run.  The next nightly run will retry.

ARCHITECTURE:
  - R25: this file is a pure application-layer use case; infrastructure
    dependencies (DB session factory, HTTP clients) are injected.
  - R27: instrument pagination queries use a read-only session; UPSERTs use
    the write session factory.
  - R12: structlog only (never stdlib logging).
  - R11: all timestamps via ``common.time.utc_now()``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text

import common.time  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    # R25: depend on application-layer ports, not the concrete infra clients.
    from market_data.application.ports.intelligence_clients import (
        S6NewsRollupClientPort,
        S7IntelligenceClientPort,
        S8BriefClientPort,
        S10AlertClientPort,
    )

logger = structlog.get_logger(__name__)


# ── Options / summary dataclasses ─────────────────────────────────────────────


@dataclass
class SyncIntelligenceRollupOptions:
    """Tuning knobs for one sync run.

    ``batch_size``: how many instrument rows to fetch per SQL cursor page.
    ``concurrency``: number of instruments processed in parallel within
                     each batch (limits simultaneous upstream HTTP calls).
    ``skip_if_fresh_within_hours``: skip instruments whose last sync was
                                    within this many hours (default 18 h).
    """

    batch_size: int = 100
    concurrency: int = 4
    skip_if_fresh_within_hours: int = 18


@dataclass
class SyncIntelligenceRollupSummary:
    """Aggregate statistics from one complete sync run."""

    instruments_processed: int = 0
    instruments_skipped_fresh: int = 0
    s6_success: int = 0
    s6_failure: int = 0
    s7_success: int = 0
    s7_failure: int = 0
    s10_success: int = 0
    s10_failure: int = 0
    s8_success: int = 0
    s8_failure: int = 0
    # Runtime in seconds — populated by the caller after execution.
    runtime_seconds: float = 0.0
    # Field counts: how many instruments had each column updated this run.
    updated_news_count_7d: int = 0
    updated_llm_relevance_7d_max: int = 0
    updated_display_relevance_7d_weighted: int = 0
    updated_recent_contradiction_count: int = 0
    updated_has_active_alert: int = 0
    updated_has_ai_brief: int = 0
    # Flat list of instrument IDs that failed all 4 upstream calls (for alert).
    all_failed: list[str] = field(default_factory=list)


# ── Main use case ─────────────────────────────────────────────────────────────


class SyncIntelligenceRollupUseCase:
    """Pull 6 intelligence fields from 4 services and materialise into snapshot.

    Usage::

        uc = SyncIntelligenceRollupUseCase(
            write_factory=...,
            s6_client=...,
            s7_client=...,
            s10_client=...,
            s8_client=...,
        )
        summary = await uc.execute()
    """

    def __init__(
        self,
        write_factory: async_sessionmaker,
        s6_client: S6NewsRollupClientPort,
        s7_client: S7IntelligenceClientPort,
        s10_client: S10AlertClientPort,
        s8_client: S8BriefClientPort,
    ) -> None:
        self._write_factory = write_factory
        self._s6 = s6_client
        self._s7 = s7_client
        self._s10 = s10_client
        self._s8 = s8_client

    async def execute(
        self,
        options: SyncIntelligenceRollupOptions | None = None,
    ) -> SyncIntelligenceRollupSummary:
        """Run the full sync; return a summary."""
        if options is None:
            options = SyncIntelligenceRollupOptions()

        import time as _time

        start = _time.monotonic()
        summary = SyncIntelligenceRollupSummary()
        fresh_cutoff = common.time.utc_now() - timedelta(hours=options.skip_if_fresh_within_hours)

        # Paginate all instrument IDs from the write DB.  We read from the
        # write DB here (not the replica) because we immediately UPSERT back;
        # replica lag could cause us to re-process freshly synced instruments.
        offset = 0
        while True:
            async with self._write_factory() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT i.id,
                               s.intelligence_rollup_synced_at,
                               s.news_count_7d,
                               s.llm_relevance_7d_max,
                               s.display_relevance_7d_weighted,
                               s.recent_contradiction_count,
                               s.has_active_alert,
                               s.has_ai_brief
                        FROM instruments i
                        LEFT JOIN instrument_fundamentals_snapshot s
                               ON s.instrument_id = i.id
                        ORDER BY i.id
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    {"limit": options.batch_size, "offset": offset},
                )
                rows = result.all()

            if not rows:
                break

            # Process this batch with bounded concurrency.
            # WHY partial/default-arg: avoids B023 (function definition does not
            # bind loop variable) — semaphore and self are captured via default args
            # so each coroutine holds a stable reference.
            semaphore = asyncio.Semaphore(options.concurrency)

            async def _process_one(
                row: object,
                _sem: asyncio.Semaphore = semaphore,
            ) -> None:
                async with _sem:
                    await self._process_instrument(row, fresh_cutoff, options, summary)

            await asyncio.gather(*[_process_one(r) for r in rows])
            offset += len(rows)

            if len(rows) < options.batch_size:
                break  # last (partial) page — done

        summary.runtime_seconds = round(_time.monotonic() - start, 2)
        return summary

    async def _process_instrument(
        self,
        row: object,
        fresh_cutoff: object,
        options: SyncIntelligenceRollupOptions,
        summary: SyncIntelligenceRollupSummary,
    ) -> None:
        """Process a single instrument row: skip-guard, fetch upstream, upsert."""
        from datetime import datetime

        instrument_id: str = str(row.id)  # type: ignore[attr-defined]
        synced_at = row.intelligence_rollup_synced_at  # type: ignore[attr-defined]

        # Skip instruments that were recently synced to avoid redundant work
        # on mid-day re-runs or container restarts (skip-guard).
        if synced_at is not None and isinstance(synced_at, datetime):
            assert isinstance(fresh_cutoff, datetime)
            if synced_at > fresh_cutoff:
                summary.instruments_skipped_fresh += 1
                return

        summary.instruments_processed += 1

        # Fetch all 4 upstream endpoints in parallel — bounded by concurrency
        # semaphore at the caller (``_process_one``).  A single instrument
        # should not block the batch for longer than 2 x 10 s = 20 s.
        s6_result, s7_result, s10_result, s8_result = await asyncio.gather(
            self._s6.get_news_rollup(instrument_id),
            self._s7.get_intelligence_rollup(instrument_id),
            self._s10.get_active_alert_flag(instrument_id),
            self._s8.get_ai_brief_flag(instrument_id),
            return_exceptions=False,
        )

        # Track success/failure counters.
        if s6_result is not None:
            summary.s6_success += 1
        else:
            summary.s6_failure += 1
            logger.warning("intelligence_rollup_s6_failure", instrument_id=instrument_id)

        if s7_result is not None:
            summary.s7_success += 1
        else:
            summary.s7_failure += 1
            logger.warning("intelligence_rollup_s7_failure", instrument_id=instrument_id)

        if s10_result is not None:
            summary.s10_success += 1
        else:
            summary.s10_failure += 1
            logger.warning("intelligence_rollup_s10_failure", instrument_id=instrument_id)

        if s8_result is not None:
            summary.s8_success += 1
        else:
            summary.s8_failure += 1
            logger.warning("intelligence_rollup_s8_failure", instrument_id=instrument_id)

        # If every upstream call failed, note the instrument and bail out —
        # no point writing a row that only updates the timestamp.
        if s6_result is None and s7_result is None and s10_result is None and s8_result is None:
            summary.all_failed.append(instrument_id)
            return

        # Build the SET clause dynamically: only set columns for which we have
        # a fresh value.  Keep-last-known: columns for which the upstream call
        # failed are not included in the SET clause, so Postgres will retain
        # the current column value on the ON CONFLICT path.
        set_parts: list[str] = []
        params: dict[str, object] = {"instrument_id": instrument_id}

        if s6_result is not None:
            set_parts += [
                "news_count_7d = :news_count_7d",
                "llm_relevance_7d_max = :llm_relevance_7d_max",
                "display_relevance_7d_weighted = :display_relevance_7d_weighted",
            ]
            params["news_count_7d"] = s6_result.news_count_7d
            params["llm_relevance_7d_max"] = s6_result.llm_relevance_7d_max
            params["display_relevance_7d_weighted"] = s6_result.display_relevance_7d_weighted
            summary.updated_news_count_7d += 1
            summary.updated_llm_relevance_7d_max += 1 if s6_result.llm_relevance_7d_max is not None else 0
            if s6_result.display_relevance_7d_weighted is not None:
                summary.updated_display_relevance_7d_weighted += 1

        if s7_result is not None:
            set_parts.append("recent_contradiction_count = :recent_contradiction_count")
            params["recent_contradiction_count"] = s7_result.recent_contradiction_count
            summary.updated_recent_contradiction_count += 1

        if s10_result is not None:
            set_parts.append("has_active_alert = :has_active_alert")
            params["has_active_alert"] = s10_result.has_active_alert
            summary.updated_has_active_alert += 1

        if s8_result is not None:
            set_parts.append("has_ai_brief = :has_ai_brief")
            params["has_ai_brief"] = s8_result.has_ai_brief
            summary.updated_has_ai_brief += 1

        # Always update the sync timestamp so the skip-guard works correctly
        # even when some columns were skipped (partial update).
        set_parts.append("intelligence_rollup_synced_at = :synced_at")
        set_parts.append("updated_at = :synced_at")
        params["synced_at"] = common.time.utc_now()

        set_clause = ", ".join(set_parts)

        # Build the INSERT column list from params (minus instrument_id).
        # We always include instrument_id + synced_at + updated_at; the rest
        # are conditional.
        insert_cols: list[str] = ["instrument_id"]
        insert_vals: list[str] = [":instrument_id"]
        for col in (
            "news_count_7d",
            "llm_relevance_7d_max",
            "display_relevance_7d_weighted",
            "recent_contradiction_count",
            "has_active_alert",
            "has_ai_brief",
        ):
            if col in params:
                insert_cols.append(col)
                insert_vals.append(f":{col}")
        insert_cols += ["intelligence_rollup_synced_at", "updated_at"]
        insert_vals += [":synced_at", ":synced_at"]

        # NOTE: insert_cols / insert_vals / set_clause are built from a
        # hardcoded column-name whitelist above. No user input flows into
        # this string — all actual data is bound via SQLAlchemy :params.
        cols_clause = ", ".join(insert_cols)
        vals_clause = ", ".join(insert_vals)
        raw_sql = (
            f"INSERT INTO instrument_fundamentals_snapshot ({cols_clause}) "  # noqa: S608
            f"VALUES ({vals_clause}) "
            f"ON CONFLICT (instrument_id) DO UPDATE SET {set_clause}"
        )
        sql = text(raw_sql)

        async with self._write_factory() as session:
            await session.execute(sql, params)
            await session.commit()
