"""Multi-year historical backfill of **daily (1d) OHLCV** from the **Alpaca** feed.

WHY THIS EXISTS
===============
Prod review 2026-07-16 found that daily (``1d``) bars in ``market_data_db
.ohlcv_bars`` come exclusively from ``yahoo_finance`` (``provider_priority`` 80)
and ``eodhd`` (60) — there are **zero Alpaca daily bars** — even though the
platform's intended final topology (PLAN-0036) makes **Alpaca the single deep
source for daily AND intraday**. Two things block Alpaca daily today:

1. The deployed routing cache still carries the stale intermediate value
   ``MARKET_INGESTION_ROUTING_OHLCV_EOD = "yahoo_finance:100,eodhd:80"`` (the
   repo default is ``alpaca:100,eodhd:80``), so every scheduled ``1d`` task —
   even ones enqueued from an ``alpaca`` polling policy — is routed to Yahoo as
   the primary provider. Alpaca is never asked for daily bars. Fixing that is a
   **config/deploy** action (flip the env var), not a code change.

2. The historical daily archive is never pulled by the live incremental
   scheduler (one bar/tick/policy). The sibling EODHD backfill
   (``backfill_daily_ohlcv``) *can* fill history, but its bars land at
   ``provider_priority`` 60 and therefore **cannot overwrite** the incumbent
   Yahoo (80) rows — so the archive stays Yahoo/EODHD-sourced.

This backfill closes the gap the right way: it pulls the deep daily archive
**directly from Alpaca**, so the produced bars carry ``source = 'alpaca'`` →
``provider_priority = 110`` in market-data (S3). 110 outranks both Yahoo (80) and
EODHD (60), so a re-run **supersedes** every existing daily bar for the covered
symbols on the standard ``bulk_upsert_with_priority`` guard — no manual delete of
the legacy rows is needed. Alpaca's free/IEX feed serves split/dividend-adjusted
daily bars back to ~2020-07-27 (~6 years); the default horizon matches that.

COVERAGE (IMPORTANT)
====================
Alpaca only covers **US-listed equities/ETFs and crypto** (our ``US`` and ``CC``
exchanges). It does **NOT** cover indices (``INDX``), forex (``FOREX``), or
non-US venues (e.g. ``SHG``). Those instruments are filtered out here and remain
on the EODHD/Yahoo daily path — flipping the routing env var does not affect them
because Alpaca returns zero bars for them (zero-bar failover keeps EODHD).

DESIGN GUARANTEES (mirrors ``backfill_daily_ohlcv``)
====================================================
* **Idempotent** — downstream upsert keys on ``(instrument_id, timeframe,
  bar_date)`` with a ``provider_priority >=`` guard; the synthetic task INSERTs
  ``ON CONFLICT (provider, dedupe_key) DO NOTHING``. Re-running any symbol is a
  no-op; a crash mid-run re-processes only the un-checkpointed tail.
* **Resumable** — a Valkey cursor (``s2:v1:alpaca_ohlcv_backfill:cursor``,
  SEPARATE from the EODHD backfill's cursor) records the sort-key of the last
  completed instrument. ``--resume`` continues past it so a daily CronJob drains
  the whole universe across many runs.
* **No credit budget** — Alpaca's free tier bills **zero** per request and
  imposes no monthly credit cap, so (unlike the EODHD backfill) there is no
  ``EodhdQuotaService`` gate. A per-run instrument cap (``--max-symbols``) and an
  inter-symbol sleep are the only throttles, both to be gentle on the HTTP rate
  limit (~200 req/min on the free plan; one symbol = one request here).
* **Loud + dry-runnable** — structured logging throughout; ``--dry-run`` prints
  the instrument plan and fetches nothing.
* **Single-flight** — a Postgres advisory lock prevents two concurrent backfill
  runs from colliding (correctness rests on the upsert keys; the lock only avoids
  wasted duplicate work).

INVOCATION (run IN-CLUSTER as a K8s Job — a detached ``kubectl exec`` dies on
pod-roll)::

    # dry-run: print the Alpaca-eligible instrument plan, fetch nothing
    python -m market_ingestion.scripts.backfill_alpaca_daily_ohlcv --years 6 --dry-run

    # real backfill, resumable (safe to re-run daily as a CronJob)
    python -m market_ingestion.scripts.backfill_alpaca_daily_ohlcv --years 6 --resume

    # explicit window + custom per-run symbol cap
    python -m market_ingestion.scripts.backfill_alpaca_daily_ohlcv \
        --from 2020-07-27 --to 2026-07-16 --max-symbols 200 --resume
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import common.time
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.value_objects import DateRange, Timeframe
from messaging.pg.advisory_lock import pg_advisory_lock  # type: ignore[import-untyped]
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.config import Settings
    from market_ingestion.domain.entities.polling_policy import PollingPolicy

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Constants ────────────────────────────────────────────────────────────────
_DAILY_TIMEFRAME = "1d"

# Alpaca free/IEX serves adjusted daily bars back to ~2020-07-27 (~6y). Default
# the horizon to 6 years so a no-arg run pulls the full available archive.
_DEFAULT_YEARS = 6
# Per-run symbol cap (Alpaca is free, so this only bounds wall-clock / rate use).
_DEFAULT_MAX_SYMBOLS = 10_000
_DEFAULT_BATCH_DELAY_SECONDS = 0.2

# Exchanges Alpaca covers. US equities/ETFs live on ``US``; house-format crypto
# (``BTC-USD``) lives on ``CC``. Everything else (INDX/FOREX/SHG/…) is Alpaca-
# ineligible and filtered out so we never spend a request on a guaranteed zero.
_ALPACA_EXCHANGES: frozenset[str] = frozenset({"US", "CC"})

# Valkey keys — DISTINCT from the EODHD backfill's ``s2:v1:ohlcv_backfill:*`` so
# the two backfills never share a cursor / done marker.
CURSOR_KEY = "s2:v1:alpaca_ohlcv_backfill:cursor"
DONE_KEY = "s2:v1:alpaca_ohlcv_backfill:done"

# Distinct advisory lock so an Alpaca backfill run never collides with itself.
BACKFILL_LOCK = "s2:alpaca_ohlcv_backfill"

_SERVICE_NAME = "market-ingestion-alpaca-ohlcv-backfill"


# ────────────────────────── pure, unit-testable helpers ──────────────────────


def resolve_horizon(
    *,
    years: int | None,
    from_date: str | None,
    to_date: str | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve the ``[from, to]`` UTC-aware datetime window.

    ``--from``/``--to`` (YYYY-MM-DD) override ``--years``. ``to`` defaults to now
    (UTC); ``from`` defaults to ``to - years*365d``. The returned datetimes are
    tz-aware and satisfy ``from < to`` (required by ``DateRange``).

    Raises:
        ValueError: if the resolved window is empty (from >= to).
    """
    current = now or common.time.utc_now()
    to_dt = _parse_day(to_date) if to_date else current
    if from_date:
        from_dt = _parse_day(from_date)
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


def symbol_sort_key(symbol: str, exchange: str | None) -> str:
    """Stable, comparable cursor key for one instrument.

    ``exchange`` is normalised to '' when absent so the key is deterministic; the
    walk proceeds in ascending ``symbol|exchange`` order and the resume cursor
    stores the last COMPLETED key.
    """
    return f"{symbol}|{exchange or ''}"


def is_alpaca_eligible(exchange: str | None) -> bool:
    """True when Alpaca can serve daily bars for an instrument on ``exchange``.

    Alpaca covers US equities/ETFs (``US``) and crypto (``CC``) only; indices
    (``INDX``), forex (``FOREX``) and non-US venues are excluded so the backfill
    never wastes a request on a guaranteed zero-bar response.
    """
    return (exchange or "").upper() in _ALPACA_EXCHANGES


def dedupe_ohlcv_instruments(policies: list[PollingPolicy]) -> list[tuple[str, str | None]]:
    """Extract the unique, sorted, **Alpaca-eligible** OHLCV instrument universe.

    Keeps only enabled OHLCV policies that name a concrete symbol on an
    Alpaca-covered exchange, de-duplicates on ``(symbol, exchange)``, and returns
    them sorted by :func:`symbol_sort_key` so the resume cursor is monotonic.
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
        if not is_alpaca_eligible(policy.exchange):
            continue
        key = symbol_sort_key(symbol, policy.exchange)
        if key in seen:
            continue
        seen.add(key)
        out.append((symbol, policy.exchange))
    out.sort(key=lambda pair: symbol_sort_key(pair[0], pair[1]))
    return out


def remaining_instruments(
    instruments: list[tuple[str, str | None]],
    cursor: str | None,
) -> list[tuple[str, str | None]]:
    """Drop instruments already completed on a prior (resumable) run.

    ``cursor`` is the :func:`symbol_sort_key` of the LAST completed instrument.
    Because the walk is ascending, the work still to do is every instrument whose
    key is strictly greater than the cursor.
    """
    if cursor is None:
        return list(instruments)
    return [pair for pair in instruments if symbol_sort_key(pair[0], pair[1]) > cursor]


# ─────────────────────────────── runner ──────────────────────────────────────


def _parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill daily (1d) OHLCV from the Alpaca bars feed.")
    parser.add_argument("--years", type=int, default=None, help=f"Horizon in years (default: {_DEFAULT_YEARS}).")
    parser.add_argument("--from", dest="from_date", default=None, help="Start date YYYY-MM-DD (overrides --years).")
    parser.add_argument("--to", dest="to_date", default=None, help="Explicit end date YYYY-MM-DD (default: today UTC).")
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=_DEFAULT_MAX_SYMBOLS,
        help=f"Per-run cap on instruments processed (default: {_DEFAULT_MAX_SYMBOLS}).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=_DEFAULT_BATCH_DELAY_SECONDS,
        help="Seconds slept between instruments (default: %(default)s).",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from the persisted Valkey cursor.")
    parser.add_argument("--dry-run", action="store_true", help="Print the instrument plan; fetch nothing.")
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
    """Load the enabled, Alpaca-eligible OHLCV instrument universe from policies."""
    async with uow_factory() as uow:
        try:
            policies = await uow.policies.list_enabled()
        finally:
            # Read-only — never leave a write transaction open.
            await uow.rollback()
    return dedupe_ohlcv_instruments(list(policies))


async def run_backfill(settings: Settings, args: argparse.Namespace) -> int:
    """Execute the Alpaca daily OHLCV backfill. Returns instruments produced."""
    from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.domain.errors import ProviderUnavailable
    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer
    from market_ingestion.infrastructure.adapters.object_store import S3ObjectStoreAdapter
    from market_ingestion.infrastructure.adapters.providers import build_provider_registry
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    from_dt, to_dt = resolve_horizon(years=args.years, from_date=args.from_date, to_date=args.to_date)

    write_factory, read_factory = _build_factories(settings)

    def _uow() -> SqlaUnitOfWork:
        return SqlaUnitOfWork(write_factory, read_factory)

    instruments = await _list_ohlcv_instruments(_uow)
    valkey = create_valkey_client_from_url(settings.valkey_url)
    cursor = await _load_cursor(valkey, resume=args.resume)
    todo = remaining_instruments(instruments, cursor)

    logger.info(
        "alpaca_ohlcv_backfill_plan",
        from_date=from_dt.date().isoformat(),
        to_date=to_dt.date().isoformat(),
        total_instruments=len(instruments),
        remaining_instruments=len(todo),
        resumed_from=cursor,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        logger.info("alpaca_ohlcv_backfill_dry_run", instruments=len(todo))
        await valkey.close()
        return 0

    # Alpaca is free/unlimited — no credit quota gate. The provider registry only
    # registers Alpaca when both keys are configured; a missing key is fatal here
    # (there is no cheaper fallback that would carry the authoritative priority).
    registry = build_provider_registry(settings, http_timeout=getattr(settings, "provider_http_timeout_seconds", 30.0))
    try:
        alpaca_adapter = registry.get(Provider.ALPACA)
    except ProviderUnavailable:
        logger.error("alpaca_ohlcv_backfill_no_adapter", hint="set MARKET_INGESTION_ALPACA_API_KEY/SECRET_KEY")
        await valkey.close()
        await _aclose_registry(registry)
        return 0

    object_store = _build_object_store(settings, S3ObjectStoreAdapter)
    serializer = DefaultCanonicalSerializer()
    date_range = DateRange(start=from_dt, end=to_dt)
    timeframe = Timeframe(_DAILY_TIMEFRAME)

    produced = 0
    skipped_empty = 0
    processed = 0

    # Single-flight guard: hold the advisory lock for the whole run so a second
    # backfill Job cannot double-fetch the same universe.
    async with write_factory() as lock_session, pg_advisory_lock(lock_session, BACKFILL_LOCK) as acquired:
        if not acquired:
            logger.warning("alpaca_ohlcv_backfill_lock_busy")
            await valkey.close()
            await _aclose_registry(registry)
            return 0
        for symbol, exchange in todo:
            if processed >= args.max_symbols:
                logger.info("alpaca_ohlcv_backfill_symbol_cap_reached", processed=processed, cap=args.max_symbols)
                break
            processed += 1

            # ── Fetch the whole window from Alpaca (1 request; adjusted daily) ──
            try:
                fetch_result = await alpaca_adapter.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=_DAILY_TIMEFRAME,
                    start=from_dt,
                    end=to_dt,
                    exchange=exchange,
                )
            except Exception as exc:
                logger.warning(
                    "alpaca_ohlcv_backfill_fetch_failed",
                    symbol=symbol,
                    exchange=exchange or "",
                    error=str(exc),
                )
                # Do NOT checkpoint — a transient fetch error retries next run.
                continue

            if fetch_result.bars_returned == 0:
                # Alpaca has no daily history for this symbol (e.g. listed after
                # the window, or delisted). Checkpoint so --resume skips it.
                skipped_empty += 1
                await valkey.set(CURSOR_KEY, symbol_sort_key(symbol, exchange))
                logger.info("alpaca_ohlcv_backfill_zero_bars", symbol=symbol, exchange=exchange or "")
                if args.sleep > 0:
                    await asyncio.sleep(args.sleep)
                continue

            # ── Produce through the SAME pipeline the live worker uses ──────────
            # provider=ALPACA so the emitted ``source`` → provider_priority 110 in
            # market-data, which outranks the incumbent Yahoo (80) / EODHD (60).
            task = IngestionTask.create_ohlcv_task(
                provider=Provider.ALPACA,
                symbol=symbol,
                timeframe=timeframe,
                date_range=date_range,
                exchange=exchange,
            )
            async with _uow() as enqueue_uow:
                await enqueue_uow.tasks.add_many([task])
                await enqueue_uow.commit()

            # Claim PENDING → RUNNING before the produce path (see the sibling
            # backfill's regression note: ``task.succeed()`` requires RUNNING or
            # the whole Step-5 transaction — incl. the outbox event — rolls back).
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
                    "alpaca_ohlcv_backfill_produce_failed",
                    symbol=symbol,
                    exchange=exchange or "",
                    error=str(exc),
                )
                # Don't checkpoint — retry the produce on the next run.
                continue

            produced += 1
            await valkey.set(CURSOR_KEY, symbol_sort_key(symbol, exchange))
            logger.info(
                "alpaca_ohlcv_backfill_instrument_done",
                symbol=symbol,
                exchange=exchange or "",
                bars=fetch_result.bars_returned,
            )
            if args.sleep > 0:
                await asyncio.sleep(args.sleep)
        else:
            # Loop completed without break → whole universe drained this run.
            await valkey.set(DONE_KEY, common.time.utc_now().date().isoformat())
            logger.info("alpaca_ohlcv_backfill_complete", produced=produced, skipped_empty=skipped_empty)

    await _aclose_registry(registry)
    await valkey.close()
    logger.info(
        "alpaca_ohlcv_backfill_run_summary",
        produced=produced,
        skipped_empty=skipped_empty,
        processed=processed,
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
        logger.warning("alpaca_ohlcv_backfill_registry_aclose_failed", error=str(exc))


def main(argv: list[str] | None = None) -> None:
    """CLI entry point (``python -m market_ingestion.scripts.backfill_alpaca_daily_ohlcv``)."""
    from market_ingestion.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=_SERVICE_NAME,
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    args = _parse_cli(argv)
    produced = asyncio.run(run_backfill(settings, args))
    logger.info("alpaca_ohlcv_backfill_exit", produced=produced)


if __name__ == "__main__":
    main()
