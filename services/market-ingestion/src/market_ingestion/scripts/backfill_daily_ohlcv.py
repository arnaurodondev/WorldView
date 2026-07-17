"""Multi-year historical backfill of **daily (1d) OHLCV** from the EODHD EOD feed.

WHY THIS EXISTS
===============
Prod review 2026-07-15 (D2 / F1) found ``market_data_db.ohlcv_bars`` holds only
~1 daily bar per instrument (86 bars / 86 instruments) — there is effectively
**no daily price history**. Every close-on-close surface therefore returns
"200 with null": instrument returns (1D…5Y), price-levels (52w hi/lo, MA50/200,
S/R), intraday-stats (prev_close, volume_vs_30d), market top-movers / heatmap
sector change_pct, sparklines, portfolio TWR / risk / value-history. Intraday
(1m/5m) is healthy; only the **daily history is missing**.

The live scheduler only enqueues a *single* incremental daily task per policy
per tick, and EOD daily is routed to Yahoo as primary — so the deep historical
archive never gets pulled. This standalone backfill fills that gap by walking
every enabled OHLCV instrument and pulling **2 years** of daily bars directly
from the EODHD ``/eod`` endpoint (the task mandates EODHD as the source), then
funnelling them through the *exact same* produce pipeline as the live worker:
persist a synthetic ``IngestionTask`` → ``ExecuteTaskUseCase
.execute_with_prefetched_result`` (bronze → canonicalize → canonical → outbox
``MarketDatasetFetched``) → dispatcher → market-data ``OHLCVConsumer`` upsert.

DESIGN GUARANTEES (mirrors content-ingestion ``backfill_general_news.py``)
=========================================================================
* **Idempotent** — downstream upsert keys on ``(instrument_id, timeframe,
  bar_date)`` with a ``provider_priority >=`` guard (``ohlcv_repo
  .bulk_upsert_with_priority``), and the synthetic task INSERTs
  ``ON CONFLICT (provider, dedupe_key) DO NOTHING``. Re-running any symbol is a
  no-op; a crash mid-run re-processes only the un-checkpointed tail.
* **Resumable** — a Valkey cursor (``s2:v1:ohlcv_backfill:cursor``) records the
  sort-key of the last completed instrument. ``--resume`` continues past it, so
  a daily CronJob drains the whole universe across many days.
* **Budget-capped** — a per-invocation credit cap (``--max-credits``) plus the
  SHARED per-UTC-day EODHD headroom guard (``eodhd_daily_quota -
  --daily-headroom``, read from the same Valkey counter the live firehose
  shares). One EOD request = **1 credit** (``EODHD_CREDIT_COST["ohlcv"]``), and
  a single request returns the whole date range, so credits ≈ number of
  instruments — it can never blow the 100k/day account cap.
* **Loud + dry-runnable** — structured logging throughout; ``--dry-run`` prints
  the instrument plan + credit estimate and fetches nothing.
* **Single-flight** — a Postgres advisory lock prevents two concurrent backfill
  runs from colliding (correctness is guaranteed by the upsert keys, not the
  lock; the lock only avoids wasted duplicate work).

INVOCATION (run IN-CLUSTER as a K8s Job — a detached ``kubectl exec`` dies on
pod-roll; see ``infra/k8s/backfill-daily-ohlcv-job.yaml``)::

    # dry-run: print the instrument plan + credit estimate, fetch nothing
    python -m market_ingestion.scripts.backfill_daily_ohlcv --years 2 --dry-run

    # real backfill, resumable (safe to re-run daily as a CronJob)
    python -m market_ingestion.scripts.backfill_daily_ohlcv --years 2 --resume

    # explicit window + custom per-run budget
    python -m market_ingestion.scripts.backfill_daily_ohlcv \
        --from 2024-01-01 --to 2024-12-31 --max-credits 800 --resume

CREDIT / TIME ESTIMATE
======================
EOD is **1 credit/request** and one request returns the full [from,to] range,
so a 2-year backfill costs **~1 credit per instrument**. For ~550 instruments
that is **~550 credits total** (plus a few retries) — well under a single day's
100k budget. Wall-clock is dominated by HTTP latency + the inter-symbol delay.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import common.time
from market_ingestion.config import Settings
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.value_objects import DateRange, Timeframe
from messaging.eodhd_quota.quota_service import EodhdQuotaService  # type: ignore[import-untyped]
from messaging.pg.advisory_lock import pg_advisory_lock  # type: ignore[import-untyped]
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.domain.entities.polling_policy import PollingPolicy

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Constants ────────────────────────────────────────────────────────────────
# EOD daily OHLCV: EODHD ``/eod`` returns the whole [from,to] range in ONE
# request and costs exactly 1 credit (``EODHD_CREDIT_COST["ohlcv"]``).
_CREDITS_PER_SYMBOL = 1
_DAILY_TIMEFRAME = "1d"

# Backfill tuning defaults. These are NOT in market-ingestion Settings (unlike
# content-ingestion's backfill_*), so they live here + are CLI-overridable. The
# daily hard cap itself comes from ``settings.eodhd_daily_quota``.
_DEFAULT_YEARS = 2
_DEFAULT_MAX_CREDITS_PER_RUN = 5_000
_DEFAULT_DAILY_HEADROOM = 5_000
_DEFAULT_BATCH_DELAY_SECONDS = 0.2

# Valkey keys — SEPARATE from any live scheduler/watermark state so the backfill
# cursor never interferes with incremental polling.
CURSOR_KEY = "s2:v1:ohlcv_backfill:cursor"
DONE_KEY = "s2:v1:ohlcv_backfill:done"

# Distinct advisory lock so two backfill runs never collide. The live firehose
# uses its own locks; correctness here rests on the OHLCV upsert keys, not this.
BACKFILL_LOCK = "s2:ohlcv_backfill"

_SERVICE_NAME = "market-ingestion-ohlcv-backfill"


# ────────────────────────── pure, unit-testable helpers ──────────────────────


def resolve_horizon(
    *,
    years: int | None,
    from_date: str | None,
    to_date: str | None,
    days: int | None = None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve the ``[from, to]`` UTC-aware datetime window.

    Precedence for the start bound: an explicit ``--from`` (YYYY-MM-DD) wins;
    else ``--days N`` (a short TRAILING window ending at ``to`` — used by the
    once-daily authoritative CronJob to re-fetch just the recent close(s) per
    ticker); else ``--years`` (deep backfill). ``to`` defaults to now (UTC).
    The returned datetimes are tz-aware and satisfy ``from < to`` (required by
    ``DateRange``).

    Raises:
        ValueError: if the resolved window is empty (from >= to).
    """
    current = now or common.time.utc_now()
    to_dt = _parse_day(to_date) if to_date else current
    if from_date:
        from_dt = _parse_day(from_date)
    elif days is not None:
        from_dt = to_dt - timedelta(days=max(1, days))
    else:
        horizon_years = years if years is not None else _DEFAULT_YEARS
        from_dt = to_dt - timedelta(days=max(1, horizon_years) * 365)
    if from_dt >= to_dt:
        msg = f"backfill window is empty: from={from_dt.isoformat()} >= to={to_dt.isoformat()}"
        raise ValueError(msg)
    return from_dt, to_dt


def _parse_day(day: str) -> datetime:
    """Parse a ``YYYY-MM-DD`` string into a UTC-aware midnight datetime."""
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)


def resolve_produced_provider(authoritative: bool) -> Provider:
    """Pick the ``source`` label for the produced bars.

    ``--authoritative`` stamps ``eodhd_bulk`` (market-data priority 120) so the
    fetched EODHD /eod bars OVERWRITE Alpaca's IEX daily bars (110) — used to
    correct the ~9.9k Alpaca-won rows. The default keeps the deep-history label
    ``eodhd`` (60), which coexists as failover and never clobbers Alpaca.
    """
    return Provider.EODHD_BULK if authoritative else Provider.EODHD


def symbol_sort_key(symbol: str, exchange: str | None) -> str:
    """Stable, comparable cursor key for one instrument.

    ``exchange`` is normalised to '' when absent so the key is deterministic;
    the walk proceeds in ascending ``symbol|exchange`` order, and the resume
    cursor stores the last COMPLETED key.
    """
    return f"{symbol}|{exchange or ''}"


def dedupe_ohlcv_instruments(policies: list[PollingPolicy]) -> list[tuple[str, str | None]]:
    """Extract the unique, sorted OHLCV instrument universe from polling policies.

    Keeps only enabled OHLCV policies that name a concrete symbol (wildcard
    ``symbol=None`` policies carry no instrument), de-duplicates on
    ``(symbol, exchange)``, and returns them sorted by :func:`symbol_sort_key`
    so the resume cursor is monotonic.
    """
    seen: set[str] = set()
    out: list[tuple[str, str | None]] = []
    for policy in policies:
        if policy.dataset_type != DatasetType.OHLCV:
            continue
        if not getattr(policy, "is_enabled", True):
            continue
        symbol = policy.symbol
        if not symbol:
            continue
        key = symbol_sort_key(symbol, policy.exchange)
        if key in seen:
            continue
        seen.add(key)
        out.append((symbol, policy.exchange))
    out.sort(key=lambda pair: symbol_sort_key(pair[0], pair[1]))
    return out


def filter_instruments_by_exchange(
    instruments: list[tuple[str, str | None]],
    exchanges: str | None,
) -> list[tuple[str, str | None]]:
    """Keep only instruments whose exchange is in the ``--exchanges`` allowlist.

    ``exchanges`` is a case-insensitive CSV (e.g. ``"US,INDX,SHG"``); ``None`` or
    empty means NO filter (whole universe). The once-daily authoritative CronJob
    passes an equities+indices allowlist so crypto (``CC``, 24/7) and ``FOREX``
    stay on Alpaca and are never relabelled to the priority-120 ``eodhd_bulk``
    source — they are not affected by the Alpaca IEX daily-volume bug.
    """
    if not exchanges:
        return list(instruments)
    allow = {tok.strip().upper() for tok in exchanges.split(",") if tok.strip()}
    return [(sym, exch) for (sym, exch) in instruments if (exch or "").upper() in allow]


def remaining_instruments(
    instruments: list[tuple[str, str | None]],
    cursor: str | None,
) -> list[tuple[str, str | None]]:
    """Drop instruments already completed on a prior (resumable) run.

    ``cursor`` is the :func:`symbol_sort_key` of the LAST completed instrument.
    Because the walk is ascending, the work still to do is every instrument
    whose key is strictly greater than the cursor.
    """
    if cursor is None:
        return list(instruments)
    return [pair for pair in instruments if symbol_sort_key(pair[0], pair[1]) > cursor]


@dataclass
class RunBudget:
    """Tracks per-invocation credit spend and enforces both budget ceilings."""

    max_credits: int
    daily_cap: int
    daily_headroom: int
    credits_per_symbol: int = _CREDITS_PER_SYMBOL
    spent: int = 0

    def run_budget_exhausted(self, next_estimate: int) -> bool:
        """True when spending ``next_estimate`` more would exceed the run cap."""
        return self.spent + next_estimate > self.max_credits

    def daily_budget_exhausted(self, daily_used: int, next_estimate: int) -> bool:
        """True when the next fetch would breach the shared daily headroom."""
        return daily_used + next_estimate > self.daily_cap - self.daily_headroom

    def record_symbol(self) -> int:
        """Attribute one instrument's credits; returns the credits spent."""
        self.spent += self.credits_per_symbol
        return self.credits_per_symbol


# ─────────────────────────────── runner ──────────────────────────────────────


def _parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill daily (1d) OHLCV from the EODHD EOD feed.")
    parser.add_argument("--years", type=int, default=None, help=f"Horizon in years (default: {_DEFAULT_YEARS}).")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help=(
            "Trailing-window length in days ending at --to (overrides --years, "
            "overridden by --from). Used by the once-daily authoritative CronJob "
            "to re-fetch only the recent close(s) per ticker at ~1 credit each."
        ),
    )
    parser.add_argument(
        "--from", dest="from_date", default=None, help="Start date YYYY-MM-DD (overrides --years/--days)."
    )
    parser.add_argument("--to", dest="to_date", default=None, help="Explicit end date YYYY-MM-DD (default: today UTC).")
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
        "--sleep",
        type=float,
        default=_DEFAULT_BATCH_DELAY_SECONDS,
        help="Seconds slept between instruments (default: %(default)s).",
    )
    parser.add_argument(
        "--exchanges",
        default=None,
        help=(
            "CSV exchange allowlist (e.g. 'US,INDX,SHG'); default = whole universe. "
            "The authoritative daily CronJob sets equities+indices so crypto (CC) "
            "and FOREX stay on Alpaca."
        ),
    )
    parser.add_argument("--resume", action="store_true", help="Resume from the persisted Valkey cursor.")
    parser.add_argument("--dry-run", action="store_true", help="Print the instrument plan + estimate; fetch nothing.")
    parser.add_argument(
        "--authoritative",
        action="store_true",
        help=(
            "Stamp fetched bars as the AUTHORITATIVE daily source ('eodhd_bulk', "
            "provider_priority 120) instead of the deep-history 'eodhd' (60). Use "
            "this to CORRECT the ~9.9k Alpaca-won (110) daily rows whose IEX volume "
            "is understated and whose adjusted_close is NULL — the EODHD /eod range "
            "carries the correct consolidated volume + adjusted_close, and priority "
            "120 >= 110 lets the upsert guard overwrite the Alpaca bar."
        ),
    )
    return parser.parse_args(argv)


async def _load_cursor(valkey: Any, *, resume: bool) -> str | None:
    """Read the persisted backfill cursor when resuming."""
    if not resume:
        return None
    raw = await valkey.get(CURSOR_KEY)
    if not raw:
        return None
    return str(raw)


async def _list_ohlcv_instruments(uow_factory: Any) -> list[tuple[str, str | None]]:
    """Load the enabled OHLCV instrument universe from polling policies."""
    async with uow_factory() as uow:
        try:
            policies = await uow.policies.list_enabled()
        finally:
            # Read-only — never leave a write transaction open.
            await uow.rollback()
    return dedupe_ohlcv_instruments(list(policies))


async def run_backfill(settings: Settings, args: argparse.Namespace) -> int:
    """Execute the daily OHLCV backfill. Returns the number of instruments produced."""
    from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer
    from market_ingestion.infrastructure.adapters.object_store import S3ObjectStoreAdapter
    from market_ingestion.infrastructure.adapters.providers import build_provider_registry
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    from_dt, to_dt = resolve_horizon(
        years=args.years, from_date=args.from_date, to_date=args.to_date, days=getattr(args, "days", None)
    )

    write_factory, read_factory = _build_factories(settings)

    def _uow() -> SqlaUnitOfWork:
        return SqlaUnitOfWork(write_factory, read_factory)

    instruments = await _list_ohlcv_instruments(_uow)
    instruments = filter_instruments_by_exchange(instruments, getattr(args, "exchanges", None))
    valkey = create_valkey_client_from_url(settings.valkey_url)
    cursor = await _load_cursor(valkey, resume=args.resume)
    todo = remaining_instruments(instruments, cursor)

    logger.info(
        "ohlcv_backfill_plan",
        from_date=from_dt.date().isoformat(),
        to_date=to_dt.date().isoformat(),
        total_instruments=len(instruments),
        remaining_instruments=len(todo),
        resumed_from=cursor,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        logger.info(
            "ohlcv_backfill_dry_run_estimate",
            instruments=len(todo),
            estimated_credits=len(todo) * _CREDITS_PER_SYMBOL,
        )
        await valkey.close()
        return 0

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
    date_range = DateRange(start=from_dt, end=to_dt)
    timeframe = Timeframe(_DAILY_TIMEFRAME)
    # ``--authoritative`` relabels the EODHD /eod bars as the top-priority daily
    # source (``eodhd_bulk``=120) so they OVERWRITE Alpaca's IEX daily bars (110)
    # — used to correct the ~9.9k Alpaca-won rows with wrong volume + null
    # adjusted_close. Default keeps the deep-history label (``eodhd``=60).
    produced_provider = resolve_produced_provider(getattr(args, "authoritative", False))

    produced = 0
    skipped_empty = 0

    # Single-flight guard: hold the advisory lock (on a dedicated session) for the
    # whole run so a second backfill Job cannot double-fetch the same universe.
    async with write_factory() as lock_session, pg_advisory_lock(lock_session, BACKFILL_LOCK) as acquired:
        if not acquired:
            logger.warning("ohlcv_backfill_lock_busy")
            await valkey.close()
            await _aclose_registry(registry)
            return 0
        for symbol, exchange in todo:
            estimate = _CREDITS_PER_SYMBOL
            if budget.run_budget_exhausted(estimate):
                logger.info("ohlcv_backfill_run_budget_reached", spent=budget.spent, max_credits=budget.max_credits)
                break
            daily_used = await quota_service.get_daily_credits_used()
            if budget.daily_budget_exhausted(daily_used, estimate):
                logger.info(
                    "ohlcv_backfill_daily_budget_reached",
                    daily_used=daily_used,
                    daily_cap=budget.daily_cap,
                    headroom=budget.daily_headroom,
                )
                break

            # ── Fetch the whole 2yr window from EODHD (1 request, 1 credit) ──
            try:
                fetch_result = await eodhd_adapter.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=_DAILY_TIMEFRAME,
                    start=from_dt,
                    end=to_dt,
                    exchange=exchange,
                )
            except Exception as exc:
                logger.warning(
                    "ohlcv_backfill_fetch_failed",
                    symbol=symbol,
                    exchange=exchange or "",
                    error=str(exc),
                )
                # Do NOT checkpoint — a transient fetch error should retry on the
                # next run rather than skip this instrument.
                continue

            budget.record_symbol()
            # We bypass the pipeline's Step-0 quota gate, so record the spend
            # against the SHARED per-UTC-day counter ourselves (keeps the
            # firehose's headroom accounting honest).
            await quota_service.record_usage(service=_SERVICE_NAME, cost=_CREDITS_PER_SYMBOL, symbol=symbol)

            if fetch_result.bars_returned == 0:
                # EODHD has no daily history for this symbol — nothing to publish.
                # Checkpoint so --resume skips it next time.
                skipped_empty += 1
                await valkey.set(CURSOR_KEY, symbol_sort_key(symbol, exchange))
                logger.info("ohlcv_backfill_zero_bars", symbol=symbol, exchange=exchange or "")
                if args.sleep > 0:
                    await asyncio.sleep(args.sleep)
                continue

            # Relabel the fetch result's provider so the canonical ``source`` and
            # the outbox event carry ``produced_provider`` (eodhd_bulk when
            # ``--authoritative``); ExecuteTaskUseCase stamps
            # ``fetched_by_provider = fetch_result.provider.value``.
            if produced_provider is not Provider.EODHD:
                fetch_result = replace(fetch_result, provider=produced_provider)

            # ── Produce through the SAME pipeline the live worker uses ──────
            task = IngestionTask.create_ohlcv_task(
                provider=produced_provider,
                symbol=symbol,
                timeframe=timeframe,
                date_range=date_range,
                exchange=exchange,
            )
            # Persist the synthetic task (idempotent: ON CONFLICT DO NOTHING) so
            # the produce path's task.succeed()/tasks.save() finds its row.
            async with _uow() as enqueue_uow:
                await enqueue_uow.tasks.add_many([task])
                await enqueue_uow.commit()

            # ── Transition the synthetic task PENDING → RUNNING ──────────────
            # ``add_many`` persists the task as PENDING. The live worker path only
            # ever hands ``execute_with_prefetched_result`` a task it has already
            # CLAIMED via ``claim_batch`` (status=RUNNING); its terminal
            # ``commit_transaction`` calls ``task.succeed()``, which REQUIRES the
            # task to be RUNNING. Without claiming here the synthetic task stays
            # PENDING, ``succeed()`` raises ``InvalidStateTransition`` AFTER the
            # ``MarketDatasetFetched`` outbox event is staged, and the whole Step-5
            # ``async with uow`` transaction rolls back — so the backfill produced
            # NOTHING downstream while still (a) spending an EODHD credit per
            # symbol and (b) failing to advance the Valkey resume cursor, i.e. an
            # unbounded credit-burning re-run that never makes progress. Claiming
            # in-memory (the DB row keeps its NULL lease, which ``tasks.save``'s
            # ``locked_by IS NULL`` guard still matches) is the fix. Re-runs stay
            # idempotent: the OHLCV upsert is keyed + provider-priority-guarded and
            # ``add_many`` is ``ON CONFLICT DO NOTHING``.
            task.claim(_SERVICE_NAME)

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
                logger.warning(
                    "ohlcv_backfill_produce_failed",
                    symbol=symbol,
                    exchange=exchange or "",
                    error=str(exc),
                )
                # Don't checkpoint — retry the produce on the next run.
                continue

            produced += 1
            await valkey.set(CURSOR_KEY, symbol_sort_key(symbol, exchange))
            logger.info(
                "ohlcv_backfill_instrument_done",
                symbol=symbol,
                exchange=exchange or "",
                bars=fetch_result.bars_returned,
                credits_spent=budget.spent,
            )
            if args.sleep > 0:
                await asyncio.sleep(args.sleep)
        else:
            # Loop completed without break → whole universe drained this run.
            await valkey.set(DONE_KEY, common.time.utc_now().date().isoformat())
            logger.info("ohlcv_backfill_complete", produced=produced, skipped_empty=skipped_empty)

    await _aclose_registry(registry)
    await valkey.close()
    logger.info(
        "ohlcv_backfill_run_summary",
        produced=produced,
        skipped_empty=skipped_empty,
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
        logger.warning("ohlcv_backfill_registry_aclose_failed", error=str(exc))


def main(argv: list[str] | None = None) -> None:
    """CLI entry point (``python -m market_ingestion.scripts.backfill_daily_ohlcv``)."""
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=_SERVICE_NAME,
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    args = _parse_cli(argv)
    produced = asyncio.run(run_backfill(settings, args))
    logger.info("ohlcv_backfill_exit", produced=produced)


if __name__ == "__main__":
    main()
