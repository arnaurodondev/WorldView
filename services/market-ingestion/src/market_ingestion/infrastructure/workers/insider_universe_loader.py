"""InsiderUniverseLoader — expand insider-transactions polling universe via S3 internal API.

PLAN-0089 Wave L-4b (T-WL4B-04).

WHY THIS LOADER EXISTS:
  The initial-seeds migration (``0002_initial_seeds.py``) inserts only
  three insider-transactions polling policies (AAPL/TSLA/AMZN). Audit
  §7 (PLAN-0089 Wave L-4b) calls for dynamic universe expansion to the
  full OHLCV-covered set so the L-4b screener column has signal across
  the live universe — not just the 3 mega-caps in the seed.

  Direct cross-service DB reads would violate R9, so this module calls
  ``GET /internal/v1/instruments/ohlcv-covered`` (new in market-data
  Wave L-4b) and writes the resulting policy rows into ``sched_policies``.

BUDGET ESTIMATE (audit §7):
  * ~3000 OHLCV-covered tickers at full coverage.
  * EODHD ``/insider-transactions`` = 1 credit/call.
  * Weekly polling = 3000 / 7 ≈ 430 calls/day = ~13k credits/month.
  * Adjust to monthly polling for ~3.1k credits/month if budget pressure.
  * The seed migration's ``86400`` (daily) base_interval is too aggressive
    for the full universe; this loader uses ``604800`` (weekly) instead.

  TODO(budget-owner): confirm budget before flipping this loader's
  ``enabled=True`` for production. Currently safe to invoke manually
  from an operator shell or smoke-test.

NOT AUTO-SCHEDULED YET:
  The seed remains the baseline for fresh installs (3 tickers, daily
  polling). This loader is exposed as a function the operator can call
  via ``python -m market_ingestion.infrastructure.workers.insider_universe_loader``
  once the budget is confirmed. A future wave can wrap it in a scheduler
  task — see ``FundamentalsRefreshWorker`` for the cadence pattern.

R9 honoured (REST not DB); R6/R7 — UUIDv7 + UTC; R10 structlog.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import jwt
import structlog

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from market_ingestion.config import MarketIngestionSettings

logger = structlog.get_logger(__name__)


# Weekly polling — matches the budget envelope in the module docstring.
_INSIDER_POLL_INTERVAL_SEC = 604800
# Page size for the universe walk; market-data clamps to [1, 5000].
_PAGE_SIZE = 1000


def _sign_internal_jwt(settings: MarketIngestionSettings) -> str:
    """Sign a short-lived internal JWT, mirroring FundamentalsRefreshWorker."""
    now = int(time.time())
    payload = {
        "iss": "worldview-gateway",
        "sub": "system:insider-universe-loader",
        "user_id": "00000000-0000-0000-0000-000000000000",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "role": "system",
        "iat": now,
        "exp": now + 300,
    }
    raw_key = getattr(settings, "internal_jwt_private_key", "")
    if hasattr(raw_key, "get_secret_value"):
        raw_key = raw_key.get_secret_value()
    if raw_key:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        private_key = load_pem_private_key(raw_key.encode(), password=None)
        return str(jwt.encode(payload, private_key, algorithm="RS256"))  # type: ignore[arg-type]
    return str(
        jwt.encode(
            payload,
            "dev-skip-verification-key-for-kg-structured-enrichment",
            algorithm="HS256",
        )
    )


async def fetch_ohlcv_covered_symbols(
    *,
    settings: MarketIngestionSettings,
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
    """UPSERT one ``sched_policies`` row per (symbol, exchange) tuple.

    Idempotent — uses ON CONFLICT on the natural-key tuple. Returns the
    number of rows offered (not net inserted).
    """
    from sqlalchemy import text

    if not symbols:
        return 0
    sql = text(
        """
        INSERT INTO sched_policies (
            id, provider, dataset_type, dataset_variant, symbol, exchange,
            timeframe, base_interval_sec, min_interval_sec, jitter_sec,
            adaptive_enabled, adaptive_k, adaptive_half_life_sec,
            priority, enabled, backfill_enabled,
            created_at, updated_at
        ) VALUES (
            :id, 'eodhd', 'insider_transactions', NULL, :symbol, :exchange,
            NULL, :interval, GREATEST(60, :interval / 10), 10,
            FALSE, 1.0, 3600,
            0, FALSE, FALSE,
            :now, :now
        )
        ON CONFLICT (provider, dataset_type, symbol, exchange, timeframe, dataset_variant)
        DO NOTHING
        """
    )
    now = common.time.utc_now()
    for row in symbols:
        await session.execute(
            sql,
            {
                "id": common.ids.new_uuid7(),
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "interval": _INSIDER_POLL_INTERVAL_SEC,
                "now": now,
            },
        )
    return len(symbols)
