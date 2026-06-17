"""Poll daily (1d) OHLCV from Alpaca; disable redundant EODHD 1d polling.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-16

Rationale (PLAN-0036 final OHLCV-sourcing topology)
---------------------------------------------------
Daily (``1d``) OHLCV bars are now POLLED DIRECTLY from Alpaca (``timeframe=1Day``)
as the deep-history daily source. Alpaca's free/IEX feed serves ~6 years of
split/dividend-adjusted daily bars (~1480 sessions back to mid-2020 in practice;
validated live for AAPL/NVDA/MSFT — closes match EODHD/Yahoo within 0.04%; IEX
volume is understated to ~3% of consolidated, acceptable for charting).

This gives every timeframe family exactly ONE source (no cross-source seam):
  - Alpaca 1m   → derive 5m/15m/30m/1h/4h  (market-data resampler)
  - Alpaca 1Day → 1d (polled here)         → derive 1w/1mo on-read (market-data)
EODHD remains a routing failover ONLY (``routing_ohlcv_eod = alpaca:100,eodhd:80``),
never a polling source. Yahoo Finance is dropped from OHLCV routing entirely.

What this migration does (idempotent, data-only — R5)
-----------------------------------------------------
1. Inserts an ``alpaca / ohlcv / 1d`` polling policy for EVERY symbol that has an
   enabled ``alpaca / ohlcv / 1m`` policy, copying its ``symbol``/``exchange``/
   ``market_hours_only``/``tier`` so coverage is identical. The daily policy uses
   an EOD-friendly cadence (``base_interval_sec = 21600`` = 6h) since a daily bar
   only changes once per session — polling every minute would burn requests for
   no new data. ``priority = 30`` (above the legacy 1m=20) so the scheduler keeps
   it active; execution-time PROVIDER routing is governed by the routing cache,
   not this policy row. ``ON CONFLICT (id) DO NOTHING`` → safe to re-run.

2. Disables the 554 enabled ``eodhd / ohlcv / 1d`` polling policies. EODHD daily
   is now failover-only (reached via routing when an Alpaca 1d fetch returns zero
   bars), so a standing EODHD daily POLL is pure redundant credit burn.

Note: this REVERSES the prior turn's Yahoo revival for daily — that's intended.
There are no ``yahoo_finance`` OHLCV polling policies to disable (the revival was
routing-only), so none are touched here.

Idempotent + reversible
------------------------
Re-running is a no-op (ON CONFLICT for inserts; the UPDATE matches already-disabled
rows with an identical SET). Downgrade deletes the inserted Alpaca 1d policies and
re-enables the EODHD 1d policies, restoring prior behaviour.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

# EOD-friendly cadence for daily bars (6h). A 1d bar only closes once per session.
_DAILY_INTERVAL_SEC = 21600
# Priority above the legacy 1m policies so the scheduler keeps daily active.
_DAILY_PRIORITY = 30


def _ulid_from_seed(seed: str) -> str:
    """Deterministic 26-char ULID-like ID from a seed string (matches 0011)."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"01HX{h[:22].upper()}"


def upgrade() -> None:
    now = datetime.now(tz=UTC)
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Insert an Alpaca 1d policy for every Alpaca 1m policy.
    #
    #    Driven entirely by the existing rows so the daily coverage tracks the
    #    1m universe exactly (690 symbols today; future 1m additions get a daily
    #    sibling the next time this migration class of logic runs / via seeds).
    #    The deterministic ULID seed mirrors 0011 but with the 1d timeframe so a
    #    re-run is a no-op and downgrade can target the exact rows.
    # ------------------------------------------------------------------
    rows = conn.execute(
        sa.text(
            "SELECT symbol, exchange, tier "
            "FROM polling_policies "
            "WHERE provider = 'alpaca' AND dataset_type = 'ohlcv' AND timeframe = '1m'"
        )
    ).fetchall()

    for symbol, exchange, tier in rows:
        policy = {
            "id": _ulid_from_seed(f"alpaca:ohlcv:{symbol}:{exchange}:1d:"),
            "provider": "alpaca",
            "dataset_type": "ohlcv",
            "dataset_variant": None,
            "symbol": symbol,
            "exchange": exchange,
            "timeframe": "1d",
            "base_interval_sec": _DAILY_INTERVAL_SEC,
            "min_interval_sec": _DAILY_INTERVAL_SEC,
            "jitter_sec": 60,
            "adaptive_enabled": False,
            "adaptive_k": 1.0,
            "adaptive_half_life_sec": 3600,
            "priority": _DAILY_PRIORITY,
            "enabled": True,
            "backfill_enabled": False,
            "backfill_start_date": None,
            "backfill_chunk_days": None,
            # Daily bars are NOT market-hours-gated: the final daily bar settles at
            # /after the close, so a market-hours-only poll would systematically miss
            # the just-closed session. The 6h cadence means at most a handful of polls
            # per day regardless. (Differs from the 1m policy, which IS market-hours
            # gated to avoid polling an idle intraday tape.)
            "market_hours_only": False,
            "tier": tier,
            "post_market_only": False,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            sa.text(
                """
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
                    :id, :provider, :dataset_type, :dataset_variant,
                    :symbol, :exchange, :timeframe,
                    :base_interval_sec, :min_interval_sec, :jitter_sec,
                    :adaptive_enabled, :adaptive_k, :adaptive_half_life_sec,
                    :priority, :enabled, :backfill_enabled,
                    :backfill_start_date, :backfill_chunk_days,
                    :market_hours_only, :tier, :post_market_only,
                    :created_at, :updated_at
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            policy,
        )

    # ------------------------------------------------------------------
    # 2. Disable redundant EODHD 1d polling — EODHD is failover-only now.
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = false, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'ohlcv' "
            "AND timeframe = '1d' AND enabled = true"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove the Alpaca 1d policies inserted above (by deterministic id).
    alpaca_1d_ids = [
        _ulid_from_seed(f"alpaca:ohlcv:{symbol}:{exchange}:1d:")
        for symbol, exchange in conn.execute(
            sa.text(
                "SELECT symbol, exchange FROM polling_policies "
                "WHERE provider = 'alpaca' AND dataset_type = 'ohlcv' AND timeframe = '1m'"
            )
        ).fetchall()
    ]
    if alpaca_1d_ids:
        conn.execute(
            sa.text("DELETE FROM polling_policies WHERE id = ANY(:ids)").bindparams(
                sa.bindparam("ids", value=alpaca_1d_ids, type_=sa.ARRAY(sa.String))
            )
        )

    # Re-enable the EODHD 1d polling policies.
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = true, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'ohlcv' "
            "AND timeframe = '1d' AND enabled = false"
        )
    )
