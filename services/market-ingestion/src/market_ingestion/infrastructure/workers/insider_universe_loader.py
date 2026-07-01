"""InsiderUniverseLoader — expand insider-transactions polling universe via S3 internal API.

PLAN-0089 Wave L-4b (T-WL4B-04); reliability fixes 2026-06-18.

WHY THIS LOADER EXISTS:
  The initial-seeds migration (``0002_initial_seeds.py``) inserts only
  three insider-transactions polling policies (AAPL/TSLA/AMZN). Audit
  §7 (PLAN-0089 Wave L-4b) calls for dynamic universe expansion to the
  full OHLCV-covered set so the L-4b screener column has signal across
  the live universe — not just the 3 mega-caps in the seed.

  Direct cross-service DB reads would violate R9, so this module calls
  ``GET /internal/v1/instruments/ohlcv-covered`` (new in market-data
  Wave L-4b) and writes the resulting policy rows into ``polling_policies``.

BUGS FIXED 2026-06-18 (audit docs/audits/2026-06-16-prd0089-l4b-insider-universe.md):
  * The INSERT targeted a table named ``sched_policies`` which DOES NOT
    EXIST (``to_regclass('sched_policies')`` is NULL); the real table is
    ``polling_policies`` (see ``polling_policy.py`` ``__tablename__``).
    Any operator who ran the loader hit ``UndefinedTableError``, so it had
    never run successfully against this schema.
  * The INSERT wrote ``enabled=FALSE``, which means even with the table-name
    fixed no polling would ever happen — a second manual "enable" step was
    silently required. Intent is for the loaded policies to poll, so this
    now writes ``enabled=TRUE``. (BP candidate: loader/worker raw SQL that
    references a renamed table + ships rows disabled, never exercised in CI.)

BUDGET REALITY (corrected 2026-06-18):
  The original docstring's "~3000 tickers → ~13k credits/month weekly" is
  STALE. The actual OHLCV-covered universe in this environment is ~654
  instruments → ~2,830 credits/month at weekly cadence (1 credit/call).
  EODHD ``/insider-transactions`` = 1 credit/call. Weekly captures Form 4
  filings (which land within 2 business days) with acceptable lag. The seed
  migration's ``86400`` (daily) interval is too aggressive for the universe;
  this loader uses ``604800`` (weekly) instead.

GATED SCHEDULING (Option C from the audit):
  The loader is wrapped by a scheduled loop in ``SchedulerProcess`` that
  runs weekly. It is gated behind ``INSIDER_UNIVERSE_REFRESH_ENABLED`` which
  DEFAULTS TO OFF so that merging this change does NOT silently start
  spending EODHD credits — the spend decision stays the operator's via the
  flag. It remains invokable manually via
  ``python -m market_ingestion.infrastructure.workers.insider_universe_loader``.

R9 honoured (REST not DB); R6/R7 — UUIDv7 + UTC; R10 structlog.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from market_ingestion.infrastructure.db.session import _build_factories
from observability.internal_jwt import mint_internal_jwt  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from market_ingestion.config import Settings

logger = get_logger(__name__)


# Weekly polling — matches the budget envelope in the module docstring.
_INSIDER_POLL_INTERVAL_SEC = 604800
# Page size for the universe walk; market-data clamps to [1, 5000].
_PAGE_SIZE = 1000
# Seconds in a day — used to convert the day-of-week/hour schedule.
_SECONDS_PER_DAY = 86400


def _sign_internal_jwt(settings: Settings) -> str:
    """Sign a short-lived internal JWT, mirroring FundamentalsRefreshWorker.

    DEF-002: delegates to the shared ``mint_internal_jwt`` helper so the token
    always carries ``aud="worldview-internal"`` + a unique ``jti`` (required by
    ``InternalJWTMiddleware`` once real verification is enabled).
    """
    raw_key = getattr(settings, "internal_jwt_private_key", "")
    if hasattr(raw_key, "get_secret_value"):
        raw_key = raw_key.get_secret_value()
    return str(
        mint_internal_jwt(
            sub="system:insider-universe-loader",
            ttl_seconds=300,
            private_key_pem=raw_key or "",
            dev_hs256_secret="dev-skip-verification-key-for-kg-structured-enrichment",  # noqa: S106 — documented dev-only skip_verification key, not a real secret
        )
    )


async def fetch_ohlcv_covered_symbols(
    *,
    settings: Settings,
) -> list[dict[str, str]]:
    """Page through GET /internal/v1/instruments/ohlcv-covered.

    Returns a list of dicts with keys ``symbol``, ``exchange`` — the
    minimum needed to construct an insider-transactions policy row.

    Returns ``[]`` on any failure (network/timeout/non-2xx). The seed
    universe stays the source of truth in that case so the loader is
    safe to call defensively.
    """
    base_url = str(getattr(settings, "market_data_url", "http://market-data:8003")).rstrip("/")
    url = f"{base_url}/internal/v1/instruments/ohlcv-covered"
    try:
        token = _sign_internal_jwt(settings)
    except Exception:
        logger.exception("insider_universe_jwt_sign_failed")
        return []
    headers = {"X-Internal-JWT": token} if token else {}

    out: list[dict[str, str]] = []
    offset = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            while True:
                resp = await client.get(
                    url,
                    params={"limit": _PAGE_SIZE, "offset": offset},
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "insider_universe_endpoint_non_2xx",
                        status_code=resp.status_code,
                        offset=offset,
                    )
                    return out
                payload = resp.json()
                results = payload.get("results") or []
                if not results:
                    break
                out.extend(
                    {
                        "symbol": str(r["symbol"]).strip().upper(),
                        "exchange": str(r.get("exchange") or "US").strip().upper(),
                    }
                    for r in results
                    if r.get("symbol")
                )
                total = int(payload.get("total") or 0)
                offset += len(results)
                if offset >= total:
                    break
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logger.exception("insider_universe_endpoint_error", url=url)
        return out
    logger.info("insider_universe_fetched", count=len(out))
    return out


async def upsert_insider_policies(
    *,
    session: AsyncSession,
    symbols: list[dict[str, str]],
) -> int:
    """Insert one ENABLED ``polling_policies`` row per (symbol, exchange) tuple.

    Writes ENABLED weekly insider-transactions policies so the scheduler
    actually picks them up. Returns the number of rows newly inserted (skips
    are not counted).

    Idempotency: ``polling_policies`` has NO unique constraint on the natural
    key — only the non-unique ``ix_polling_policies_matching`` index — so a raw
    ``ON CONFLICT (provider, dataset_type, ...)`` clause would raise at runtime
    (it requires a unique index). Instead we SELECT-then-skip per symbol on the
    natural-key 6-tuple, NULL-safe via ``IS NOT DISTINCT FROM`` (``timeframe``
    and ``dataset_variant`` are NULL here). This mirrors migration 0022's
    idempotency contract and never flips an operator's manual ``enabled`` change
    on an existing row.

    Columns omitted from the INSERT (``market_hours_only``, ``tier``,
    ``post_market_only``, ``backfill_*``) all have NOT NULL server defaults
    in the schema (migrations 0003 / 0008), so the row is well-formed.
    """
    from sqlalchemy import text

    if not symbols:
        return 0

    exists_sql = text(
        """
        SELECT 1 FROM polling_policies
        WHERE provider = 'eodhd'
          AND dataset_type = 'insider_transactions'
          AND symbol = :symbol
          AND exchange = :exchange
          AND timeframe IS NOT DISTINCT FROM NULL
          AND dataset_variant IS NOT DISTINCT FROM NULL
        LIMIT 1
        """
    )
    insert_sql = text(
        """
        INSERT INTO polling_policies (
            id, provider, dataset_type, dataset_variant, symbol, exchange,
            timeframe, base_interval_sec, min_interval_sec, jitter_sec,
            adaptive_enabled, adaptive_k, adaptive_half_life_sec,
            priority, enabled, backfill_enabled,
            created_at, updated_at
        ) VALUES (
            :id, 'eodhd', 'insider_transactions', NULL, :symbol, :exchange,
            NULL, :interval, GREATEST(60, :interval / 10), 10,
            FALSE, 1.0, 3600,
            0, TRUE, FALSE,
            :now, :now
        )
        """
    )
    now = common.time.utc_now()
    inserted = 0
    for row in symbols:
        params = {"symbol": row["symbol"], "exchange": row["exchange"]}
        already = (await session.execute(exists_sql, params)).first()
        if already is not None:
            continue
        await session.execute(
            insert_sql,
            {
                # 26-char ULID — the ``id`` column is String(26) and every live
                # policy row uses a ULID (migration 0022 / sync worker). A 36-char
                # UUIDv7 string would overflow the column.
                "id": common.ids.new_ulid(),
                "interval": _INSIDER_POLL_INTERVAL_SEC,
                "now": now,
                **params,
            },
        )
        inserted += 1
    return inserted


async def run_insider_universe_load(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Fetch the OHLCV-covered universe and UPSERT enabled insider policies.

    One full pass: page the market-data endpoint, then write the rows in a
    single committed transaction. Returns the number of rows newly inserted.
    Safe to call repeatedly (the upsert skips existing natural keys).

    ``session_factory`` is injectable for tests; production builds the write
    factory from settings.
    """
    if session_factory is None:
        write_factory, _read_factory = _build_factories(settings)
    else:
        write_factory = session_factory

    symbols = await fetch_ohlcv_covered_symbols(settings=settings)
    if not symbols:
        logger.warning("insider_universe_load_no_symbols")
        return 0

    async with write_factory() as session:
        inserted = await upsert_insider_policies(session=session, symbols=symbols)
        await session.commit()
    logger.info("insider_universe_load_done", inserted=inserted, fetched=len(symbols))
    return inserted


def _seconds_until_next_run(
    *,
    now: datetime,
    day_of_week: int,
    hour_utc: int,
) -> float:
    """Seconds from ``now`` until the next ``day_of_week`` at ``hour_utc`` (UTC).

    ``day_of_week`` follows ``datetime.weekday()`` (Monday=0 .. Sunday=6).
    Always returns a strictly-positive delay so a tick never busy-loops when
    the worker wakes up exactly on the target boundary.
    """
    day_of_week %= 7
    hour_utc %= 24
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    days_ahead = (day_of_week - now.weekday()) % 7
    target += timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    return (target - now).total_seconds()


class InsiderUniverseRefreshWorker:
    """Weekly scheduled loop that re-runs the insider-universe load.

    Mirrors ``FundamentalsRefreshWorker`` / ``InstrumentPolicySyncWorker``:
    same ``run()`` / ``stop()`` / ``enabled`` contract, same lazy-infra and
    stop-event sleep pattern, so the scheduler can spawn and tear it down
    uniformly.

    GATED OFF BY DEFAULT: ``run()`` is a no-op unless
    ``insider_universe_refresh_enabled`` is truthy. This keeps merging the
    change from silently spending EODHD credits — the operator opts in via
    ``MARKET_INGESTION_INSIDER_UNIVERSE_REFRESH_ENABLED=true``.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._stop_event = asyncio.Event()
        # Test seam for sleep — defaults to asyncio.sleep in production.
        self._sleep: Callable[[float], Awaitable[None]] = sleep_fn or asyncio.sleep

    @property
    def enabled(self) -> bool:
        """True if this worker should run on startup (default OFF)."""
        return bool(getattr(self._settings, "insider_universe_refresh_enabled", False))

    def stop(self) -> None:
        """Signal the worker loop to exit after the current wait."""
        self._stop_event.set()

    async def run(self) -> None:
        """Run the weekly refresh loop until ``stop()`` is fired.

        Returns immediately (no-op) when the kill switch is off — this is the
        load-bearing gate that prevents accidental EODHD spend.
        """
        if not self.enabled:
            logger.info(
                "insider_universe_refresh_disabled",
                hint="set MARKET_INGESTION_INSIDER_UNIVERSE_REFRESH_ENABLED=true to opt in",
            )
            return

        day_of_week = int(getattr(self._settings, "insider_universe_refresh_day_of_week", 6))
        hour_utc = int(getattr(self._settings, "insider_universe_refresh_hour_utc", 5))
        logger.info(
            "insider_universe_refresh_starting",
            day_of_week=day_of_week,
            hour_utc=hour_utc,
        )

        while not self._stop_event.is_set():
            delay = _seconds_until_next_run(
                now=datetime.now(UTC),
                day_of_week=day_of_week,
                hour_utc=hour_utc,
            )
            # Sleep until the scheduled slot OR until stop() fires.
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=delay,
                )
            if self._stop_event.is_set():
                break
            try:
                await run_insider_universe_load(settings=self._settings)
            except asyncio.CancelledError:
                raise
            except Exception:  # — loop must survive any per-run failure
                logger.exception("insider_universe_refresh_run_error")

        logger.info("insider_universe_refresh_stopped")


async def _amain() -> None:
    """Operator entry point: one-shot manual load (ignores the enabled gate)."""
    from market_ingestion.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    inserted = await run_insider_universe_load(settings=settings)
    logger.info("insider_universe_manual_load_complete", inserted=inserted)


if __name__ == "__main__":
    asyncio.run(_amain())
