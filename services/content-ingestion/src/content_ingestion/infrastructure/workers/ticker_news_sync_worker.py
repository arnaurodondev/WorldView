"""TickerNewsSymbolSyncWorker — PLAN-0106 Wave C-2.

WHY THIS WORKER EXISTS
======================
The EODHDTickerNewsAdapter (Wave C-1) fetches news for a single equity ticker
given a Source row with ``{"symbol": "AAPL", "exchange": "US"}`` in its config.
The problem: those Source rows don't exist on a fresh deploy — the operator
would have to create them manually for every ticker they care about.

This worker solves that by:
  1. Calling ``GET /internal/v1/instruments?exchange=US`` on the market-data
     service (S3) every 6 hours to get the current list of US equity instruments.
  2. For each instrument, calling ``CreateSourceUseCase`` to upsert an
     ``eodhd_ticker_news`` Source row.  The ``uq_sources_dedup`` constraint
     (migration 0006) makes this fully idempotent — re-running for an
     already-existing ticker is a silent no-op.

The pattern mirrors ``FundamentalsRefreshWorker`` in market-ingestion (PLAN-0099
W2-T02): a long-running loop, gated by a kill-switch, sleeping between ticks,
respecting SIGTERM via an Event + ``stop()`` method.

Auth: signs a short-lived RS256 internal JWT using the same private key S9
issues — same pattern as FundamentalsRefreshWorker._sign_internal_jwt().
Falls back to HS256 dev token when no key is configured.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from typing import TYPE_CHECKING

import httpx
import jwt

from content_ingestion.application.use_cases.create_source import CreateSourceUseCase
from content_ingestion.infrastructure.db.session import _build_factories
from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from content_ingestion.config import Settings

logger = get_logger(__name__)  # type: ignore[no-any-return]


class TickerNewsSymbolSyncWorker:
    """Long-running worker that auto-creates eodhd_ticker_news Source rows.

    On each tick it fetches the list of US equity instruments from market-data
    and upserts one ``eodhd_ticker_news`` Source per ticker.  The scheduler
    will then automatically pick up new rows on its next tick.

    Args:
        settings: Service configuration.  The worker reads:
            - ``ticker_news_sync_enabled`` (bool, default True) — kill switch.
            - ``ticker_news_sync_interval_hours`` (float, default 6.0).
            - ``market_data_url`` (str, default "http://market-data:8003").
            - ``internal_jwt_private_key`` (SecretStr, default empty).
        sleep_fn: Override for ``asyncio.sleep`` — injected in unit tests to
            avoid wall-clock waits.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._stop_event = asyncio.Event()
        # DB factories are built lazily in run() so that disabled-flag tests
        # never hit the DB factory constructor (mirrors FundamentalsRefreshWorker).
        self._write_factory: async_sessionmaker[AsyncSession] | None = None
        self._read_factory: async_sessionmaker[AsyncSession] | None = None
        self._sleep: Callable[[float], Awaitable[None]] = sleep_fn or asyncio.sleep

    @property
    def enabled(self) -> bool:
        """True if this worker should run on startup."""
        return bool(getattr(self._settings, "ticker_news_sync_enabled", True))

    def stop(self) -> None:
        """Signal the worker loop to exit after the current iteration."""
        self._stop_event.set()

    # ------------------------------------------------------------------ loop

    async def run(self) -> None:
        """Run the sync loop until ``stop()`` is fired.

        No-op when the kill switch is off (``ticker_news_sync_enabled=false``).
        Returns immediately in that case — same contract as FundamentalsRefreshWorker.
        """
        if not self.enabled:
            logger.info(
                "ticker_news_sync_worker_disabled",
                hint="set CONTENT_INGESTION_TICKER_NEWS_SYNC_ENABLED=true to enable",
            )
            return

        interval_hours = float(getattr(self._settings, "ticker_news_sync_interval_hours", 6.0))
        # Clamp to at least 60 seconds so a misconfigured interval_hours=0 does
        # not spin-loop against the DB and market-data HTTP endpoint.
        interval_seconds = max(60.0, interval_hours * 3600.0)

        logger.info(
            "ticker_news_sync_worker_starting",
            interval_hours=interval_hours,
        )

        # Build DB factories now — disabled callers above this line never reach here.
        _, _, self._write_factory, self._read_factory = _build_factories(self._settings)

        while not self._stop_event.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Loop must survive any per-tick failure so one bad market-data
                # response doesn't kill the sync for the whole interval.
                logger.exception("ticker_news_sync_tick_error")

            # Sleep until next tick OR until stop().  The shield+wait_for idiom
            # mirrors SchedulerProcess.run() so SIGTERM is honoured promptly.
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=interval_seconds,
                )

        logger.info("ticker_news_sync_worker_stopped")

    # ----------------------------------------------------------------- tick

    async def _tick(self) -> None:
        """Fetch the instrument universe and upsert one Source per ticker."""
        instruments = await self._fetch_us_instruments()
        if not instruments:
            logger.warning(
                "ticker_news_sync_no_instruments",
                hint="market-data returned empty list; skipping tick",
            )
            return

        logger.info("ticker_news_sync_tick_start", instrument_count=len(instruments))
        created_count = 0
        skipped_count = 0

        for inst in instruments:
            if self._stop_event.is_set():
                break

            symbol: str = str(inst.get("symbol", "")).strip().upper()
            exchange: str = str(inst.get("exchange", "US")).strip().upper()

            if not symbol:
                continue

            source_name = f"eodhd-ticker-news-{symbol.lower()}-{exchange.lower()}"

            try:
                assert self._write_factory is not None
                assert self._read_factory is not None
                uow = SqlaUnitOfWork(self._write_factory, self._read_factory)
                use_case = CreateSourceUseCase(uow=uow)
                result = await use_case.execute(
                    name=source_name,
                    source_type="eodhd_ticker_news",
                    config={"symbol": symbol, "exchange": exchange},
                    enabled=True,
                )
                if result.was_created:
                    created_count += 1
                    logger.info(
                        "ticker_news_source_created",
                        symbol=symbol,
                        exchange=exchange,
                        source_id=str(result.id),
                    )
                else:
                    skipped_count += 1
            except Exception:
                # One failing ticker must not abort the loop — log and continue.
                logger.exception(
                    "ticker_news_source_upsert_error",
                    symbol=symbol,
                    exchange=exchange,
                )

        logger.info(
            "ticker_news_sync_tick_complete",
            created=created_count,
            already_existed=skipped_count,
        )

    # ------------------------------------------------------------- helpers

    async def _fetch_us_instruments(self) -> list[dict]:  # type: ignore[type-arg]
        """Call ``GET /internal/v1/instruments?exchange=US`` on market-data.

        Returns the list of instrument dicts on success, or an empty list on
        ANY failure (network error, non-2xx, malformed JSON).  Empty-on-failure
        is the same contract as FundamentalsRefreshWorker._fetch_top_n_symbols.

        Auth: signs a short-lived internal JWT — same pattern as S2 worker.
        BP-235 guard: explicit ``httpx.Timeout`` on every external call.
        """
        base_url = str(getattr(self._settings, "market_data_url", "http://market-data:8003")).rstrip("/")
        url = f"{base_url}/internal/v1/instruments"

        try:
            token = self._sign_internal_jwt()
        except Exception:
            logger.exception("ticker_news_sync_jwt_sign_failed")
            return []

        headers: dict[str, str] = {}
        if token:
            headers["X-Internal-JWT"] = token

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.get(url, params={"exchange": "US"}, headers=headers)

            if resp.status_code != 200:
                logger.warning(
                    "ticker_news_sync_market_data_non_2xx",
                    status_code=resp.status_code,
                    url=url,
                )
                return []

            payload = resp.json()
            # market-data /internal/v1/instruments may return a list directly
            # or a ``{"results": [...], "total": N}`` envelope — handle both.
            if isinstance(payload, list):
                return payload
            results = payload.get("results") or payload.get("items") or []
            return list(results)

        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.exception("ticker_news_sync_market_data_error", url=url)
            return []

    def _sign_internal_jwt(self) -> str:
        """Sign a short-lived RS256 internal JWT for the market-data call.

        Returns an HS256 dev token when no RS256 private key is configured
        (dev / CI environments).  Production deployments MUST inject the same
        RS256 private key that S9 uses so market-data's ``InternalJWTMiddleware``
        accepts the request.

        Mirrors ``FundamentalsRefreshWorker._sign_internal_jwt`` exactly.
        """
        now = int(time.time())
        payload = {
            "iss": "worldview-gateway",
            "sub": "system:ticker-news-sync-worker",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "role": "system",
            "iat": now,
            "exp": now + 300,  # 5-minute TTL — same as FundamentalsRefreshWorker
        }

        raw_key = getattr(self._settings, "internal_jwt_private_key", "")
        if hasattr(raw_key, "get_secret_value"):
            raw_key = raw_key.get_secret_value()

        if raw_key:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key

            private_key = load_pem_private_key(raw_key.encode(), password=None)
            return str(jwt.encode(payload, private_key, algorithm="RS256"))  # type: ignore[arg-type]

        # Dev fallback — same shared secret as the KG signer and S2 worker so
        # behaviour is consistent across all worker → market-data calls in dev.
        return str(
            jwt.encode(
                payload,
                "dev-skip-verification-key-for-kg-structured-enrichment",
                algorithm="HS256",
            )
        )
