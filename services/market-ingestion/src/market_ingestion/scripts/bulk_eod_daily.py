"""Once-daily authoritative daily-OHLCV producer sourced from the EODHD BULK EOD feed.

WHY THIS EXISTS
===============
Alpaca (the intraday 1m bulk source) is priced perfectly for intraday — ~3 API
calls/minute fetch 1-minute bars for EVERY ticker. But Alpaca's free IEX feed is
WRONG for *daily* bars:

* daily ``volume`` is IEX-only — roughly 5% of the true consolidated tape
  (~19-30x understated), and
* ``adjusted_close`` is never stored (Alpaca's ``_normalize_bars`` drops it).

Yet Alpaca's polled 1Day bar was priority 110 = the daily "source of truth", so
~9.9k Alpaca-won days served wrong volume + a mixed adjusted/raw close.

FIX (2026-07-16): keep Alpaca for intraday 1m (unchanged) and source DAILY bars
from EODHD's BULK end-of-day endpoint instead:

    GET /eod-bulk-last-day/{EXCHANGE}?api_token=…&fmt=json

**ONE call returns EVERY symbol on the exchange** (US = ~33.6k records verified
live 2026-07-16) with the CORRECT consolidated ``volume`` + ``adjusted_close`` +
raw ``close``. Cost is a flat **100 credits per exchange per day** — ~200x cheaper
than per-minute per-ticker polling and cheaper than a per-ticker /eod sweep of any
exchange with >100 covered symbols. This script runs once daily (a K8s CronJob),
makes 1 bulk call per configured EQUITY/INDEX exchange, and funnels the matching
bars for our COVERED universe through the *exact same* produce pipeline as the live
worker, stamped with the authoritative ``eodhd_bulk`` source.

DEDUP / PRIORITY COORDINATION (with ``fix/ohlcv-dup-bars``)
==========================================================
market-data (S3) resolves ``source = "eodhd_bulk"`` to ``provider_priority = 120``
— ABOVE Alpaca's IEX daily (110). The upsert guard
``WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority`` therefore lets
this bar overwrite the Alpaca daily bar. This REQUIRES the ``fix/ohlcv-dup-bars``
UTC-midnight ``bar_date`` normalization so the eodhd_bulk and Alpaca daily bars
share the same ``(instrument_id, timeframe, bar_date)`` conflict key; without it
the two rows keep distinct per-provider timestamps and never collide. The dedup
migration 045 keeps the highest ``provider_priority`` per day, so eodhd_bulk (120)
is the retained winner once its rows exist.

CRYPTO / NON-EQUITY EXCHANGES
=============================
``--exchanges`` defaults to ``US`` (the only exchange the Alpaca-daily bug
affects). Bulk EOD covers equities + indices; crypto (``CC``, 24/7) is NOT served
by this endpoint and STAYS on Alpaca. Operators can add index/foreign equity
exchanges (``INDX``, ``SHG``, …) — each is one extra 100-credit call/day. Symbols
we do not cover are ignored (the script never creates instruments outside the
polling universe).

INVOCATION (run IN-CLUSTER as a K8s CronJob — a detached ``kubectl exec`` dies on
pod-roll)::

    # dry-run: print the plan + credit estimate, fetch nothing
    python -m market_ingestion.scripts.bulk_eod_daily --exchanges US --dry-run

    # real once-daily run (safe to re-run; downstream upsert is idempotent)
    python -m market_ingestion.scripts.bulk_eod_daily --exchanges US

    # a specific historical date (used by the corrective backfill driver)
    python -m market_ingestion.scripts.bulk_eod_daily --exchanges US --date 2026-07-14
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import common.time
from market_ingestion.application.ports.adapters import ProviderFetchResult
from market_ingestion.config import Settings
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.freshness import EODHD_CREDIT_COST
from market_ingestion.domain.value_objects import DateRange, Timeframe
from messaging.eodhd_quota.quota_service import EodhdQuotaService  # type: ignore[import-untyped]
from messaging.pg.advisory_lock import pg_advisory_lock  # type: ignore[import-untyped]
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.domain.entities.polling_policy import PollingPolicy

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Constants ────────────────────────────────────────────────────────────────
_DAILY_TIMEFRAME = "1d"
_BULK_CREDITS_PER_EXCHANGE = EODHD_CREDIT_COST.get("bulk_eod", 100)
_DEFAULT_EXCHANGES = "US"
_DEFAULT_MAX_CREDITS_PER_RUN = 5_000
_DEFAULT_DAILY_HEADROOM = 5_000

# Advisory lock — distinct from the /eod backfill lock so the two never collide.
BULK_EOD_LOCK = "s2:bulk_eod_daily"
_SERVICE_NAME = "market-ingestion-bulk-eod-daily"


# ────────────────────────── pure, unit-testable helpers ──────────────────────


def parse_exchanges(raw: str) -> list[str]:
    """Parse the ``--exchanges`` CSV into a de-duplicated, upper-cased list."""
    seen: set[str] = set()
    out: list[str] = []
    for token in raw.split(","):
        code = token.strip().upper()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def covered_symbols_by_exchange(policies: list[PollingPolicy]) -> dict[str, list[str]]:
    """Group the enabled OHLCV polling universe into ``{exchange: [symbol, …]}``.

    Only enabled OHLCV policies naming a concrete symbol are kept (wildcard
    ``symbol=None`` policies carry no instrument). Symbols are de-duplicated and
    sorted per exchange so the walk is deterministic.
    """
    grouped: dict[str, set[str]] = {}
    for policy in policies:
        if policy.dataset_type != DatasetType.OHLCV:
            continue
        if not getattr(policy, "is_enabled", True):
            continue
        symbol = policy.symbol
        if not symbol:
            continue
        exchange = (policy.exchange or "").upper()
        grouped.setdefault(exchange, set()).add(symbol)
    return {exchange: sorted(symbols) for exchange, symbols in grouped.items()}


def index_bulk_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index a bulk-EOD response list by its ``code`` field (upper-cased)."""
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        code = str(record.get("code", "")).upper()
        if code:
            index[code] = record
    return index


def match_record(index: dict[str, dict[str, Any]], symbol: str) -> dict[str, Any] | None:
    """Find the bulk record for *symbol*, tolerating dot/dash class-share forms.

    EODHD encodes US share classes with a hyphen (``BRK-B``); our house format may
    store either ``BRK.B`` or ``BRK-B``. Try the symbol as-is, then both
    normalisations so a stored-dot symbol still matches a hyphen-coded record.
    """
    upper = symbol.upper()
    for candidate in (upper, upper.replace(".", "-"), upper.replace("-", ".")):
        record = index.get(candidate)
        if record is not None:
            return record
    return None


def record_date_range(record: dict[str, Any]) -> DateRange:
    """Build a single-day ``[midnight, midnight+1d)`` range from a record's date.

    Raises:
        ValueError: if the record has no parseable ``date`` field.
    """
    raw = str(record.get("date", "")).strip()
    if not raw:
        raise ValueError("bulk EOD record has no 'date' field")
    day = datetime.strptime(raw[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    return DateRange(start=day, end=day + timedelta(days=1))


def build_symbol_fetch_result(
    record: dict[str, Any],
    symbol: str,
    exchange: str,
    date_range: DateRange,
) -> ProviderFetchResult:
    """Wrap a single bulk record as a per-symbol ``EODHD_BULK`` OHLCV fetch result.

    ``raw_data`` is a one-element JSON array so the shared canonicalizer's OHLCV
    branch (which expects a list) enriches it with symbol/exchange/source and
    ``CanonicalOHLCVBar.from_dict`` reads ``date``/``open``/…/``adjusted_close``/
    ``volume`` (extra bulk keys like ``code``/``prev_close`` are ignored).
    """
    return ProviderFetchResult(
        provider=Provider.EODHD_BULK,
        dataset_type=DatasetType.OHLCV,
        symbol=symbol,
        raw_data=json.dumps([record]).encode(),
        content_type="application/json",
        fetched_at=common.time.utc_now(),
        duration_ms=0,
        range_start=date_range.start,
        range_end=date_range.end,
        provider_metadata={"exchange": exchange, "date": record.get("date")},
        bars_returned=1,
    )


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

    def record_exchange(self) -> int:
        self.spent += _BULK_CREDITS_PER_EXCHANGE
        return _BULK_CREDITS_PER_EXCHANGE


# ─────────────────────────────── runner ──────────────────────────────────────


def _parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Once-daily authoritative daily OHLCV from the EODHD BULK EOD feed.")
    parser.add_argument(
        "--exchanges",
        default=_DEFAULT_EXCHANGES,
        help=f"CSV of EODHD exchange codes to pull (default: {_DEFAULT_EXCHANGES!r}). Crypto (CC) stays on Alpaca.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Specific trading day YYYY-MM-DD (default: the exchange's most recent close).",
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
    parser.add_argument("--dry-run", action="store_true", help="Print the plan + estimate; fetch nothing.")
    return parser.parse_args(argv)


async def _list_policies(uow_factory: Any) -> list[PollingPolicy]:
    async with uow_factory() as uow:
        try:
            policies = await uow.policies.list_enabled()
        finally:
            await uow.rollback()
    return list(policies)


async def run_bulk_eod(settings: Settings, args: argparse.Namespace) -> int:
    """Execute the bulk-EOD daily producer. Returns the number of symbols produced."""
    from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer
    from market_ingestion.infrastructure.adapters.object_store import S3ObjectStoreAdapter
    from market_ingestion.infrastructure.adapters.providers import build_provider_registry
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    exchanges = parse_exchanges(args.exchanges)
    write_factory, read_factory = _build_factories(settings)

    def _uow() -> SqlaUnitOfWork:
        return SqlaUnitOfWork(write_factory, read_factory)

    policies = await _list_policies(_uow)
    universe = covered_symbols_by_exchange(policies)

    plan = {exch: len(universe.get(exch, [])) for exch in exchanges}
    logger.info(
        "bulk_eod_plan",
        exchanges=exchanges,
        date=args.date or "latest",
        covered_by_exchange=plan,
        estimated_credits=len(exchanges) * _BULK_CREDITS_PER_EXCHANGE,
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

    produced = 0
    unmatched = 0

    async with write_factory() as lock_session, pg_advisory_lock(lock_session, BULK_EOD_LOCK) as acquired:
        if not acquired:
            logger.warning("bulk_eod_lock_busy")
            await valkey.close()
            await _aclose_registry(registry)
            return 0

        for exchange in exchanges:
            symbols = universe.get(exchange, [])
            if not symbols:
                logger.info("bulk_eod_exchange_no_universe", exchange=exchange)
                continue

            estimate = _BULK_CREDITS_PER_EXCHANGE
            if budget.run_budget_exhausted(estimate):
                logger.info("bulk_eod_run_budget_reached", spent=budget.spent, max_credits=budget.max_credits)
                break
            daily_used = await quota_service.get_daily_credits_used()
            if budget.daily_budget_exhausted(daily_used, estimate):
                logger.info(
                    "bulk_eod_daily_budget_reached",
                    daily_used=daily_used,
                    daily_cap=budget.daily_cap,
                    headroom=budget.daily_headroom,
                )
                break

            # ── ONE bulk call for the whole exchange (100 credits) ────────────
            try:
                bulk_result = await eodhd_adapter.fetch_bulk_eod(exchange=exchange, date=args.date)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.warning("bulk_eod_fetch_failed", exchange=exchange, error=str(exc))
                continue

            budget.record_exchange()
            # We bypass the pipeline's Step-0 quota gate, so record the spend
            # against the SHARED per-UTC-day counter ourselves.
            await quota_service.record_usage(
                service=_SERVICE_NAME, cost=_BULK_CREDITS_PER_EXCHANGE, symbol=f"BULK.{exchange}"
            )

            try:
                records = json.loads(bulk_result.raw_data.decode())
            except Exception as exc:
                logger.warning("bulk_eod_parse_failed", exchange=exchange, error=str(exc))
                continue
            index = index_bulk_records(records if isinstance(records, list) else [])
            logger.info("bulk_eod_fetched", exchange=exchange, records=len(index), covered=len(symbols))

            for symbol in symbols:
                record = match_record(index, symbol)
                if record is None:
                    unmatched += 1
                    continue
                try:
                    date_range = record_date_range(record)
                except ValueError:
                    unmatched += 1
                    continue

                fetch_result = build_symbol_fetch_result(record, symbol, exchange, date_range)
                task = IngestionTask.create_ohlcv_task(
                    provider=Provider.EODHD_BULK,
                    symbol=symbol,
                    timeframe=Timeframe(_DAILY_TIMEFRAME),
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
                    logger.warning("bulk_eod_produce_failed", symbol=symbol, exchange=exchange, error=str(exc))
                    continue
                produced += 1

            logger.info("bulk_eod_exchange_done", exchange=exchange, produced=produced, unmatched=unmatched)

    await _aclose_registry(registry)
    await valkey.close()
    logger.info(
        "bulk_eod_run_summary",
        produced=produced,
        unmatched=unmatched,
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
        logger.warning("bulk_eod_registry_aclose_failed", error=str(exc))


def main(argv: list[str] | None = None) -> None:
    """CLI entry point (``python -m market_ingestion.scripts.bulk_eod_daily``)."""
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=_SERVICE_NAME,
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    args = _parse_cli(argv)
    produced = asyncio.run(run_bulk_eod(settings, args))
    logger.info("bulk_eod_exit", produced=produced)


if __name__ == "__main__":
    main()
