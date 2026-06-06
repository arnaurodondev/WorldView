"""InstrumentPolicySyncWorker — PLAN-0106 Wave D-1.

WHY THIS WORKER EXISTS
======================
The S&P 500 expansion migration (0014) adds fundamentals + OHLCV EOD policies
for ~440 new symbols, but Alpaca 1m intraday policies must be inserted
**dynamically** as new instruments are registered in the market-data service.
A static migration cannot cover instruments that are registered after the
migration runs (e.g. newly-listed equities, index additions mid-year).

This worker solves that by periodically querying the market-data service for
all US and CC instruments, then inserting Alpaca 1m polling policies for any
symbol that doesn't already have one.  It is the live equivalent of migration
0011 — that migration seeded the original 50 symbols; this worker keeps the
universe current.

Design decisions
----------------
- Modelled after ``FundamentalsRefreshWorker`` (same run/stop/enabled pattern,
  same JWT-signing logic, same infra lazy-init pattern).
- Uses direct SQL INSERT ON CONFLICT DO NOTHING via the write factory session
  — same pattern as migrations 0011 and 0014.
- INDX and FOREX exchanges are skipped; Alpaca does not provide them.
- Runs every 6 hours by default (``instrument_policy_sync_interval_hours``).
- Gated by ``instrument_policy_sync_enabled`` (default True).

Metrics
-------
- ``instrument_policy_sync_created_total{exchange, symbol}`` — incremented
  once per newly-created policy.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from contextlib import suppress
from typing import TYPE_CHECKING

import httpx
import jwt
import prometheus_client as prom

from market_ingestion.infrastructure.db.session import _build_factories
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from market_ingestion.config import Settings

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Prometheus metric — module-level singleton to survive re-imports
# ---------------------------------------------------------------------------
instrument_policy_sync_created_total: prom.Counter = prom.Counter(
    "instrument_policy_sync_created_total",
    "Total Alpaca 1m policies created by InstrumentPolicySyncWorker.",
    labelnames=["exchange", "symbol"],
)

# Exchanges to skip — Alpaca does not provide data for indices or forex.
_SKIP_EXCHANGES: frozenset[str] = frozenset(["INDX", "FOREX"])


def _ulid_from_seed(seed: str) -> str:
    """Deterministic 26-char ULID-like ID from a seed string.

    Copied verbatim from migration 0011 so policy IDs are stable across
    runs regardless of which path (migration or this worker) creates them.
    """
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"01HX{h[:22].upper()}"


class InstrumentPolicySyncWorker:
    """Long-running worker that syncs Alpaca 1m policies to the instrument universe.

    Each tick:
    1. Fetches all instruments for US and CC exchanges from market-data.
    2. For each instrument, checks whether an Alpaca 1m policy already exists.
    3. If not, inserts one with ``ON CONFLICT (id) DO NOTHING``.
    4. Increments the Prometheus counter for each newly-created policy.

    Args:
        settings: Service configuration.  The worker reads:
            - ``instrument_policy_sync_enabled`` (bool, default True) — kill switch.
            - ``instrument_policy_sync_interval_hours`` (float, default 6.0).
            - ``market_data_url`` (str) — base URL for market-data service.
            - ``internal_jwt_private_key`` (SecretStr) — RS256 key for JWT signing.
        sleep_fn: Override for ``asyncio.sleep`` — present so unit tests can
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
        # Built lazily in run() so disabled-flag tests don't touch infra.
        self._write_factory: async_sessionmaker[AsyncSession] | None = None
        self._read_factory: async_sessionmaker[AsyncSession] | None = None
        # Test seam for sleep — defaults to asyncio.sleep in production.
        self._sleep: Callable[[float], Awaitable[None]] = sleep_fn or asyncio.sleep

    @property
    def enabled(self) -> bool:
        """True if this worker should run on startup."""
        return bool(getattr(self._settings, "instrument_policy_sync_enabled", True))

    def stop(self) -> None:
        """Signal the worker loop to exit after the current iteration."""
        self._stop_event.set()

    # ------------------------------------------------------------------ loop

    async def run(self) -> None:
        """Run the sync loop until ``stop()`` is fired.

        Returns immediately (no-op) when the kill switch is off.
        """
        if not self.enabled:
            logger.info(
                "instrument_policy_sync_worker_disabled",
                hint="set INSTRUMENT_POLICY_SYNC_ENABLED=false to opt out",
            )
            return

        interval_hours = float(getattr(self._settings, "instrument_policy_sync_interval_hours", 6.0))
        interval_seconds = max(60.0, interval_hours * 3600.0)
        logger.info(
            "instrument_policy_sync_worker_starting",
            interval_hours=interval_hours,
        )

        # Build infra lazily — disabled-flag callers never reach here.
        self._write_factory, self._read_factory = _build_factories(self._settings)

        while not self._stop_event.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # — loop must survive any per-tick failure
                logger.exception("instrument_policy_sync_tick_error")

            # Sleep until the next tick OR until stop() (mirrors SchedulerProcess).
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=interval_seconds,
                )

        logger.info("instrument_policy_sync_worker_stopped")

    # ---------------------------------------------------------------- tick

    async def _tick(self) -> None:
        """Sync Alpaca 1m policies for US and CC instruments in one round."""
        created_count = 0

        for exchange in ("US", "CC"):
            if self._stop_event.is_set():
                break
            instruments = await self._fetch_instruments(exchange)
            for instrument in instruments:
                symbol: str = str(instrument.get("symbol", "")).strip().upper()
                if not symbol:
                    continue
                if self._stop_event.is_set():
                    break
                created = await self._ensure_alpaca_policy(symbol, exchange)
                if created:
                    created_count += 1
                    instrument_policy_sync_created_total.labels(
                        exchange=exchange,
                        symbol=symbol,
                    ).inc()
                    logger.info(
                        "instrument_policy_created",
                        symbol=symbol,
                        exchange=exchange,
                        provider="alpaca",
                        dataset_type="ohlcv",
                        timeframe="1m",
                    )

        logger.info(
            "instrument_policy_sync_tick_done",
            created=created_count,
        )

    async def _ensure_alpaca_policy(self, symbol: str, exchange: str) -> bool:
        """Insert an Alpaca 1m policy if one does not already exist.

        Returns True when a new row was inserted (policy did not exist before),
        False when the row already existed (ON CONFLICT — no-op).

        Uses raw SQL via the write factory so we can use ON CONFLICT DO NOTHING
        without loading the full ORM machinery in the async context.
        """
        assert self._write_factory is not None

        policy_id = _ulid_from_seed(f"alpaca:ohlcv:{symbol}:{exchange}:1m:")
        market_hours_only = exchange == "US"  # crypto (CC) trades 24/7

        insert_sql = """
            INSERT INTO polling_policies (
                id, provider, dataset_type, dataset_variant,
                symbol, exchange, timeframe,
                base_interval_sec, min_interval_sec, jitter_sec,
                adaptive_enabled, adaptive_k, adaptive_half_life_sec,
                priority, enabled, backfill_enabled,
                backfill_start_date, backfill_chunk_days,
                market_hours_only, tier, post_market_only,
                created_at, updated_at
            ) VALUES (
                :id, 'alpaca', 'ohlcv', NULL,
                :symbol, :exchange, '1m',
                60, 60, 5,
                false, 1.0, 3600,
                20, true, false,
                NULL, NULL,
                :market_hours_only, 1, false,
                NOW(), NOW()
            )
            ON CONFLICT (id) DO NOTHING
        """

        # Use a fresh session from the write factory for each INSERT to avoid
        # long-lived transactions that accumulate lock pressure across a full
        # tick. The INSERT is idempotent so retrying on transient failure is
        # safe; we let the outer tick-level exception handler cover that.
        async with self._write_factory() as session:
            import sqlalchemy as sa

            result = await session.execute(
                sa.text(insert_sql),
                {
                    "id": policy_id,
                    "symbol": symbol,
                    "exchange": exchange,
                    "market_hours_only": market_hours_only,
                },
            )
            await session.commit()
            # rowcount == 1 means the INSERT succeeded; 0 means ON CONFLICT.
            return bool(result.rowcount == 1)  # type: ignore[union-attr,attr-defined]

    # ----------------------------------------------------------- market-data call

    async def _fetch_instruments(self, exchange: str) -> list[dict]:
        """Fetch all instruments for *exchange* from the market-data service.

        Returns a list of dicts with at least ``{"symbol": str, "exchange": str}``.
        Returns an empty list on any failure (network error, non-2xx, bad JSON)
        so the caller's loop continues without crashing.

        Skips INDX and FOREX exchanges silently — Alpaca does not cover them.
        """
        if exchange in _SKIP_EXCHANGES:
            return []

        base_url = str(getattr(self._settings, "market_data_url", "http://market-data:8003")).rstrip("/")
        url = f"{base_url}/internal/v1/instruments"

        try:
            token = self._sign_internal_jwt()
        except Exception:
            logger.exception("instrument_policy_sync_jwt_sign_failed")
            return []

        headers: dict[str, str] = {}
        if token:
            headers["X-Internal-JWT"] = token

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.get(url, params={"exchange": exchange}, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    "instrument_policy_sync_fetch_non_2xx",
                    exchange=exchange,
                    status_code=resp.status_code,
                    url=url,
                )
                return []
            payload = resp.json()
            # Accept both {"results": [...]} envelope and bare list.
            if isinstance(payload, list):
                return payload
            return list(payload.get("results") or payload.get("items") or [])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.exception("instrument_policy_sync_fetch_error", exchange=exchange, url=url)
            return []

    def _sign_internal_jwt(self) -> str:
        """Sign a short-lived internal JWT for the market-data call.

        Mirrors ``FundamentalsRefreshWorker._sign_internal_jwt`` exactly —
        same issuer/sub/claims pattern so market-data's InternalJWTMiddleware
        accepts the request.
        """
        now = int(time.time())
        payload = {
            "iss": "worldview-gateway",
            "sub": "system:instrument-policy-sync-worker",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "role": "system",
            "iat": now,
            "exp": now + 300,
        }
        # SecretStr-or-str compatibility — settings expose either form.
        raw_key = getattr(self._settings, "internal_jwt_private_key", "")
        if hasattr(raw_key, "get_secret_value"):
            raw_key = raw_key.get_secret_value()
        if raw_key:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key

            private_key = load_pem_private_key(raw_key.encode(), password=None)
            return str(
                jwt.encode(payload, private_key, algorithm="RS256")  # type: ignore[arg-type]
            )
        # Dev fallback — HS256 with the shared dev key (same as FundamentalsRefreshWorker).
        return str(
            jwt.encode(
                payload,
                "dev-skip-verification-key-for-kg-structured-enrichment",
                algorithm="HS256",
            )
        )
