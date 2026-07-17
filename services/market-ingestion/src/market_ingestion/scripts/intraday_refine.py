"""Once-daily POST-CLOSE 1-minute intraday refinement sourced from EODHD.

WHY THIS EXISTS
===============
Alpaca's free intraday 1m feed (the base timeframe from which market-data derives
5m/15m/30m/1h/4h by volume-sum) is **IEX-only** — roughly **2-5% of the
consolidated tape**. So every intraday bar's absolute volume is ~20x understated,
which is wrong on the 1D/5D instrument-chart volume histogram. The operator chose
this correction over Alpaca-SIP ($99/mo) and over fabricated volume scaling
(dishonest + breaks on the live session) — see
``docs/audits/2026-07-16-consolidated-volume-timeframes.md``.

FIX (2026-07-16): keep Alpaca as the LIVE intra-session 1m source (unchanged), and
run a once-daily CronJob AFTER the US cash close that fetches EODHD's per-ticker 1m
intraday feed for the CLOSED trading day::

    GET /intraday/{SYMBOL}?interval=1m&from=<day 00:00 UTC>&to=<day+1 00:00 UTC>

EODHD 1m volume is the CORRECT consolidated CTA/UTP tape (finalized 2-3h after
close — hence post-close), and its ``datetime`` field is UTC bar-START on the exact
minute, which ALIGNS minute-for-minute with Alpaca's 1m ``bar_date`` convention
(verified live 2026-07-16: Alpaca 1m bars land on ``:00`` seconds, UTC). The bars
are funnelled through the EXACT same produce pipeline as the live worker, stamped
with the authoritative ``eodhd_intraday`` source.

SUPERSEDING / PRIORITY (with market-data S3)
============================================
market-data resolves ``source = "eodhd_intraday"`` to ``provider_priority = 115`` —
ABOVE Alpaca's live IEX 1m (110) and the ``derived`` tag (110), BELOW ``eodhd_bulk``
daily (120). The 1m upsert guard
``WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority`` therefore lets
this bar REPLACE the Alpaca IEX 1m bar on the SAME ``(instrument_id, "1m",
bar_date)`` conflict key — because the minute timestamps ALIGN, they collide
instead of duplicating. A late Alpaca correction (110) can no longer clobber the
refined bar (110 >= 115 is false), so the refinement is durable.

RE-DERIVATION (no double-count)
===============================
Producing the refined 1m bars publishes ``market.dataset.fetched`` — the EXISTING
``intraday_resampling_consumer`` (filters dataset_type=ohlcv, timeframe=1m) picks it
up and re-derives 5m/15m/30m/1h/4h via ``ResampledOHLCVUseCase.execute_batch``. That
path range-fetches the day's 1m bars from the DB and merges the message batch keyed
by ``bar_date`` (batch wins) — since the EODHD bar SUPERSEDED the Alpaca bar at the
same minute, there is exactly ONE 1m bar per minute, so the volume-sum cannot
double-count regardless of consumer ordering. The derived bars are upserted via the
unconditional ``bulk_upsert_derived`` path, so they overwrite the stale IEX-derived
bars with the corrected volume.

LIVE SESSION UNAFFECTED
=======================
Only a fully-CLOSED day is refined (default = today's UTC date, run post-close;
weekends are skipped). Alpaca keeps writing new-minute 1m bars for the CURRENT
session at priority 110 — those are distinct ``bar_date`` keys and never collide
with a prior day's refined bars.

SCOPE / BUDGET
==============
US equities only (``--exchanges US``). Crypto (24/7) stays on Alpaca — EODHD
intraday does not serve it. Per-ticker: 5 credits/symbol (``EODHD_INTRADAY_COST``).
530 covered US equities ⇒ **~2,650 credits/sweep** — alongside the daily bulk EOD
(~100-543) + the existing firehose (~1.1k) this is well under the 100k/day EODHD cap
(≈4.3k/day total). Resumable (a Valkey per-day ``done`` set survives pod-roll),
advisory-locked, dry-runnable, and bounded by ``--max-credits`` + ``--daily-headroom``.

COORDINATION / DEPLOY ORDER
===========================
SEPARATE deploy unit. The daily ``feat/eodhd-bulk-eod`` + ``fix/ohlcv-dup-bars`` fix
ships FIRST (they own the EODHD adapter, the ``eodhd_bulk`` daily source, and the
daily bar_date normalization). This branch adds ONLY the ``eodhd_intraday`` source
(115) + this script + its CronJob. The 1m superseding does NOT depend on the
dup-bars daily-midnight normalization — intraday ``bar_date`` already keeps its full
timestamp on both branches; alignment is inherent to the UTC-minute convention.

INVOCATION (run IN-CLUSTER as a K8s CronJob — a detached ``kubectl exec`` dies on
pod-roll)::

    # dry-run: print the plan + credit estimate, fetch nothing
    python -m market_ingestion.scripts.intraday_refine --exchanges US --dry-run

    # real once-daily run (safe to re-run; resumes from the Valkey done-set)
    python -m market_ingestion.scripts.intraday_refine --exchanges US

    # a specific historical trading day (backfill / re-refine)
    python -m market_ingestion.scripts.intraday_refine --exchanges US --date 2026-07-15
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import common.time
from market_ingestion.config import Settings
from market_ingestion.domain.enums import Provider
from market_ingestion.domain.freshness import EODHD_INTRADAY_COST
from market_ingestion.domain.value_objects import DateRange, Timeframe
from market_ingestion.scripts.bulk_eod_daily import (
    covered_symbols_by_exchange,
    parse_exchanges,
)
from messaging.eodhd_quota.quota_service import EodhdQuotaService  # type: ignore[import-untyped]
from messaging.pg.advisory_lock import pg_advisory_lock  # type: ignore[import-untyped]
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.application.ports.adapters import ProviderFetchResult
    from market_ingestion.domain.entities.polling_policy import PollingPolicy

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Constants ────────────────────────────────────────────────────────────────
_INTRADAY_TIMEFRAME = "1m"
# 5 credits per /intraday request, regardless of interval (EODHD_INTRADAY_COST).
_CREDITS_PER_SYMBOL = EODHD_INTRADAY_COST
_DEFAULT_EXCHANGES = "US"
# ~2,650 credits for 530 US equities; 10k cap leaves comfortable headroom.
_DEFAULT_MAX_CREDITS_PER_RUN = 10_000
_DEFAULT_DAILY_HEADROOM = 5_000
# Valkey key that self-cleans; the per-day "done" set makes the sweep resumable.
_DONE_SET_TTL_SECONDS = 3 * 24 * 60 * 60  # 3 days

# Advisory lock — distinct from the bulk-EOD + /eod backfill locks so none collide.
INTRADAY_REFINE_LOCK = "s2:intraday_refine"
_SERVICE_NAME = "market-ingestion-intraday-refine"


# ────────────────────────── pure, unit-testable helpers ──────────────────────


def resolve_target_day(date_arg: str | None) -> datetime:
    """Resolve the trading day to refine, as a UTC-midnight ``datetime``.

    ``date_arg`` is an optional ``YYYY-MM-DD``. When absent the default is the
    CURRENT UTC date — the CronJob runs post-close (after ~23:00 UTC, once EODHD
    has settled the consolidated tape), so "today UTC" is the day that just closed.

    Raises:
        ValueError: if *date_arg* is present but not ``YYYY-MM-DD``.
    """
    if date_arg:
        return datetime.strptime(date_arg.strip()[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    now = common.time.utc_now()
    return datetime(now.year, now.month, now.day, tzinfo=UTC)


def is_weekend(day: datetime) -> bool:
    """True if *day* is Saturday or Sunday (no US equity session — nothing to refine)."""
    return day.weekday() >= 5  # Mon=0 … Sat=5, Sun=6


def day_unix_window(day: datetime) -> tuple[int, int]:
    """Return ``(from_ts, to_ts)`` Unix seconds bracketing the UTC calendar day.

    ``[day 00:00 UTC, day+1 00:00 UTC)`` covers the full US session in UTC
    (pre-market ~08:00, regular 13:30-20:00, after-hours to ~00:00 next day). EODHD
    ``from``/``to`` are Unix UTC seconds. Any minute we fetch supersedes the
    matching Alpaca minute; any we miss keeps the Alpaca bar (honest, not fabricated).
    """
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def day_date_range(day: datetime) -> DateRange:
    """Single-day ``[midnight, midnight+1d)`` range used as task/fetch metadata."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return DateRange(start=start, end=start + timedelta(days=1))


def stamp_intraday_source(result: ProviderFetchResult) -> ProviderFetchResult:
    """Re-stamp an EODHD ``/intraday`` fetch result with the ``eodhd_intraday`` source.

    The adapter's ``fetch_intraday`` returns ``provider=Provider.EODHD``; the
    canonicalizer stamps each bar's ``source`` (and the ``market.dataset.fetched``
    event's ``provider``) from ``fetch_result.provider.value``. Overriding it to
    :data:`Provider.EODHD_INTRADAY` is what makes market-data resolve priority 115
    and supersede the Alpaca IEX 1m bar. Pure — returns a new result.
    """
    return dataclasses.replace(result, provider=Provider.EODHD_INTRADAY)


def done_set_key(day: datetime) -> str:
    """Valkey key of the per-day resume set of already-refined symbols."""
    return f"s2:v1:intraday_refine:{day.date().isoformat()}:done"


@dataclass
class RunBudget:
    """Tracks per-invocation credit spend and enforces both budget ceilings."""

    max_credits: int
    daily_cap: int
    daily_headroom: int
    spent: int = 0

    def run_budget_exhausted(self, next_estimate: int) -> bool:
        return self.spent + next_estimate > self.max_credits

    def daily_budget_exhausted(self, daily_used: int, next_estimate: int) -> bool:
        return daily_used + next_estimate > self.daily_cap - self.daily_headroom

    def record_symbol(self) -> int:
        self.spent += _CREDITS_PER_SYMBOL
        return _CREDITS_PER_SYMBOL


# ─────────────────────────────── runner ──────────────────────────────────────


def _parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Once-daily post-close EODHD 1m intraday refinement (consolidated volume)."
    )
    parser.add_argument(
        "--exchanges",
        default=_DEFAULT_EXCHANGES,
        help=f"CSV of EODHD exchange codes to refine (default: {_DEFAULT_EXCHANGES!r}). Crypto (CC) stays on Alpaca.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Specific trading day YYYY-MM-DD (default: today UTC — the day that just closed).",
    )
    parser.add_argument(
        "--max-credits",
        type=int,
        default=_DEFAULT_MAX_CREDITS_PER_RUN,
        help=f"Per-run credit cap (default: {_DEFAULT_MAX_CREDITS_PER_RUN}).",
    )
    parser.add_argument(
        "--daily-headroom",
        type=int,
        default=_DEFAULT_DAILY_HEADROOM,
        help=f"Credits reserved for the live firehose (default: {_DEFAULT_DAILY_HEADROOM}).",
    )
    parser.add_argument(
        "--allow-weekend",
        action="store_true",
        help="Refine even when the target day is Sat/Sun (default: skip weekends).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan + estimate; fetch nothing.")
    return parser.parse_args(argv)


async def _list_policies(uow_factory: Any) -> list[PollingPolicy]:
    async with uow_factory() as uow:
        try:
            policies = await uow.policies.list_enabled()
        finally:
            await uow.rollback()
    return list(policies)


async def run_intraday_refine(settings: Settings, args: argparse.Namespace) -> int:
    """Execute the post-close intraday refinement. Returns the number of symbols produced."""
    from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer
    from market_ingestion.infrastructure.adapters.object_store import S3ObjectStoreAdapter
    from market_ingestion.infrastructure.adapters.providers import build_provider_registry
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    exchanges = parse_exchanges(args.exchanges)
    target_day = resolve_target_day(args.date)

    if is_weekend(target_day) and not args.allow_weekend:
        logger.info("intraday_refine_skip_weekend", target_day=target_day.date().isoformat())
        return 0

    write_factory, read_factory = _build_factories(settings)

    def _uow() -> SqlaUnitOfWork:
        return SqlaUnitOfWork(write_factory, read_factory)

    policies = await _list_policies(_uow)
    universe = covered_symbols_by_exchange(policies)

    plan = {exch: len(universe.get(exch, [])) for exch in exchanges}
    from_ts, to_ts = day_unix_window(target_day)
    logger.info(
        "intraday_refine_plan",
        exchanges=exchanges,
        target_day=target_day.date().isoformat(),
        covered_by_exchange=plan,
        estimated_credits=sum(plan.values()) * _CREDITS_PER_SYMBOL,
        credits_per_symbol=_CREDITS_PER_SYMBOL,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        return 0

    valkey = create_valkey_client_from_url(settings.valkey_url)
    budget = RunBudget(
        max_credits=args.max_credits,
        daily_cap=int(settings.eodhd_daily_quota),
        daily_headroom=args.daily_headroom,
    )
    quota_service = EodhdQuotaService(
        valkey=valkey,
        hard_limit=int(settings.eodhd_monthly_quota),
        daily_hard_limit=int(settings.eodhd_daily_quota),
    )
    registry = build_provider_registry(settings, http_timeout=getattr(settings, "provider_http_timeout_seconds", 30.0))
    eodhd_adapter = registry.get(Provider.EODHD)
    object_store = _build_object_store(settings, S3ObjectStoreAdapter)
    serializer = DefaultCanonicalSerializer()
    date_range = day_date_range(target_day)
    done_key = done_set_key(target_day)

    produced = 0
    skipped_resumed = 0
    empty_days = 0

    async with write_factory() as lock_session, pg_advisory_lock(lock_session, INTRADAY_REFINE_LOCK) as acquired:
        if not acquired:
            logger.warning("intraday_refine_lock_busy")
            await valkey.close()
            await _aclose_registry(registry)
            return 0

        for exchange in exchanges:
            symbols = universe.get(exchange, [])
            if not symbols:
                logger.info("intraday_refine_exchange_no_universe", exchange=exchange)
                continue

            for symbol in symbols:
                # ── Resume: skip symbols already refined for this day ──────────
                if await valkey.sismember(done_key, symbol):
                    skipped_resumed += 1
                    continue

                estimate = _CREDITS_PER_SYMBOL
                if budget.run_budget_exhausted(estimate):
                    logger.info(
                        "intraday_refine_run_budget_reached", spent=budget.spent, max_credits=budget.max_credits
                    )
                    break
                daily_used = await quota_service.get_daily_credits_used()
                if budget.daily_budget_exhausted(daily_used, estimate):
                    logger.info(
                        "intraday_refine_daily_budget_reached",
                        daily_used=daily_used,
                        daily_cap=budget.daily_cap,
                        headroom=budget.daily_headroom,
                    )
                    break

                # ── ONE per-ticker intraday call (5 credits) ──────────────────
                try:
                    raw_result = await eodhd_adapter.fetch_intraday(  # type: ignore[attr-defined]
                        symbol=symbol,
                        interval=_INTRADAY_TIMEFRAME,
                        from_ts=from_ts,
                        to_ts=to_ts,
                        exchange=exchange,
                    )
                except Exception as exc:
                    logger.warning("intraday_refine_fetch_failed", symbol=symbol, exchange=exchange, error=str(exc))
                    continue

                budget.record_symbol()
                # We bypass the pipeline's Step-0 quota gate, so record the spend
                # against the SHARED per-UTC-day counter ourselves.
                await quota_service.record_usage(service=_SERVICE_NAME, cost=_CREDITS_PER_SYMBOL, symbol=symbol)

                # A holiday / halted symbol returns an empty array — mark done so a
                # resume does not re-spend credits on it.
                if raw_result.bars_returned == 0:
                    empty_days += 1
                    await valkey.sadd(done_key, symbol)
                    continue

                fetch_result = stamp_intraday_source(raw_result)
                task = IngestionTask.create_ohlcv_task(
                    provider=Provider.EODHD_INTRADAY,
                    symbol=symbol,
                    timeframe=Timeframe(_INTRADAY_TIMEFRAME),
                    date_range=date_range,
                    exchange=exchange,
                )
                # Persist the synthetic task (idempotent ON CONFLICT DO NOTHING) so
                # the produce path's task.succeed()/tasks.save() finds its row.
                async with _uow() as enqueue_uow:
                    await enqueue_uow.tasks.add_many([task])
                    await enqueue_uow.commit()

                use_case = ExecuteTaskUseCase(
                    uow=_uow(),
                    provider_registry=registry,
                    object_store=object_store,
                    serializer=serializer,
                    bronze_bucket=getattr(settings, "bronze_bucket", "market-bronze"),
                    canonical_bucket=getattr(settings, "canonical_bucket", "market-canonical"),
                )
                try:
                    await use_case.execute_with_prefetched_result(task, fetch_result)
                except Exception as exc:
                    logger.warning("intraday_refine_produce_failed", symbol=symbol, exchange=exchange, error=str(exc))
                    continue

                await valkey.sadd(done_key, symbol)
                produced += 1

            logger.info(
                "intraday_refine_exchange_done",
                exchange=exchange,
                produced=produced,
                skipped_resumed=skipped_resumed,
                empty_days=empty_days,
            )

    # Let the resume set self-clean a few days after the sweep.
    try:
        await valkey.expire(done_key, _DONE_SET_TTL_SECONDS)
    except Exception as exc:  # pragma: no cover — best-effort TTL
        logger.warning("intraday_refine_done_set_expire_failed", error=str(exc))

    await _aclose_registry(registry)
    await valkey.close()
    logger.info(
        "intraday_refine_run_summary",
        target_day=target_day.date().isoformat(),
        produced=produced,
        skipped_resumed=skipped_resumed,
        empty_days=empty_days,
        credits_spent=budget.spent,
    )
    return produced


def _build_object_store(settings: Settings, adapter_cls: Any) -> Any:
    """Mirror ``WorkerProcess._build_object_store`` for the standalone script."""
    try:
        from storage.s3_adapter import S3ObjectStorage  # type: ignore[import-untyped]
        from storage.settings import StorageSettings  # type: ignore[import-untyped]

        storage = S3ObjectStorage(
            StorageSettings(
                endpoint=settings.storage_endpoint,
                access_key=settings.storage_access_key.get_secret_value(),
                secret_key=settings.storage_secret_key.get_secret_value(),
            )
        )
    except ImportError:
        storage = None
    return adapter_cls(storage=storage, default_bucket=settings.storage_bucket)


async def _aclose_registry(registry: Any) -> None:
    """Close provider adapter HTTP clients if the registry exposes aclose."""
    closer = getattr(registry, "aclose", None)
    if closer is None:
        return
    try:
        await closer()
    except Exception as exc:  # pragma: no cover — best-effort cleanup
        logger.warning("intraday_refine_registry_aclose_failed", error=str(exc))


def main(argv: list[str] | None = None) -> None:
    """CLI entry point (``python -m market_ingestion.scripts.intraday_refine``)."""
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=_SERVICE_NAME,
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    args = _parse_cli(argv)
    produced = asyncio.run(run_intraday_refine(settings, args))
    logger.info("intraday_refine_exit", produced=produced)


if __name__ == "__main__":
    main()
