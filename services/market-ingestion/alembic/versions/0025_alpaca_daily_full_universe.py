"""Seed Alpaca 1d OHLCV policies for the FULL US+CC universe; disable redundant EODHD 1d.

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-16

Rationale (follow-up 2026-07-16 — Alpaca daily policy-seed 86 → 541)
--------------------------------------------------------------------
Migration 0023 seeded ``alpaca / ohlcv / 1d`` policies ONLY for symbols that
already had an *enabled* ``alpaca / ohlcv / 1m`` policy (the ~86 US + 10 CC
top-tier from 0011). It also disabled all ``eodhd / ohlcv / 1d`` polls, because
execution-time routing (``routing.py`` ``_EOD_TIMEFRAMES``) reroutes EVERY 1d
OHLCV task to Alpaca whenever the Alpaca adapter is registered, so a standing
EODHD daily poll is redundant.

Live audit on 2026-07-16 (alembic head 0024) found that intent only half-held:

    provider  tf   enabled  count
    alpaca    1d   true     96      (US 86 + CC 10)   <- explicit Alpaca daily
    alpaca    1m   true     96      (US 86 + CC 10)
    eodhd     1d   true     554     (US 531 + CC 10 + INDX 11 + FOREX 1 + SHG 1)

The 554 ``eodhd / ohlcv / 1d`` rows are enabled again (0023's disable was undone
somewhere along the re-provision path). Because routing reroutes them to Alpaca,
every US+CC symbol that has BOTH an eodhd/1d and an alpaca/1d policy is scheduled
and fetched from Alpaca TWICE per day - pure duplicate ``market.dataset.fetched``
volume feeding the OHLCV consumer (a contributor to consumer lag), while the
other ~445 US symbols reach Alpaca only through their eodhd-labelled 1d policy
(no explicit Alpaca policy at all).

This migration finishes 0023's job for the WHOLE Alpaca-eligible universe:

1. Inserts an ``alpaca / ohlcv / 1d`` policy for every DISTINCT (symbol, exchange)
   that currently has an *enabled* ``eodhd / ohlcv / 1d`` policy on a
   Alpaca-covered exchange (US equities/ETFs + CC crypto). Deterministic ULID
   seed ``alpaca:ohlcv:{symbol}:{exchange}:1d:`` matches 0023, so the ~96 rows
   0023 already created are ``ON CONFLICT (id) DO NOTHING`` no-ops and only the
   ~445 missing US symbols are inserted. Cadence = 86_400 s (once daily, the
   final value set by 0024), priority 30, ``market_hours_only = false`` (the
   daily bar settles at/after the close), tier 2.

2. Disables the redundant ``eodhd / ohlcv / 1d`` polls for US+CC ONLY. The
   ~13 INDX / FOREX / SHG rows are LEFT ENABLED - Alpaca does not cover indices
   or forex, so those must keep polling EODHD/Yahoo (they reach EODHD via the
   zero-bar failover chain; keeping the policy enabled preserves their schedule).

Exchanges skipped (kept on EODHD): ``INDX`` (11), ``FOREX`` (1), ``SHG`` (1).

1-minute (1m) is intentionally NOT expanded here
------------------------------------------------
Expanding ``alpaca / ohlcv / 1m`` from the 96 top-tier symbols to the full ~541
universe is deferred. Per-request Alpaca rate is fine (the worker batches up to
``_BATCH_SIZE`` symbols per multi-bar HTTP call - ~541 due symbols / batch_size
= a few dozen requests/min, well under Alpaca free-IEX ~200 req/min). The real
constraint is Kafka/consumer THROUGHPUT: 1m polls publish one
``market.dataset.fetched`` per symbol EVERY MINUTE during market hours, so a
541-symbol 1m universe is ~9x the current intraday event volume into an
already-lagging OHLCV + intraday-resampling consumer pair on a single cx53 node.
The bounded top-tier 1m set (96 symbols: top-86 US equities/ETFs + 10 crypto,
seeded by 0011) stays as-is; full 1m expansion should follow a consumer-capacity
review, not ride in on this daily-coverage fix.

Idempotent + reversible (R5 - data-only, no DDL)
------------------------------------------------
Re-running upgrade is a no-op: inserts use ``ON CONFLICT (id) DO NOTHING`` and
the disable UPDATE matches already-disabled rows with an identical SET.
Downgrade re-enables the US+CC eodhd/1d rows and deletes ONLY the alpaca/1d rows
this migration added (US+CC symbols that lack an enabled alpaca/1m policy),
leaving 0023's 96 rows intact.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# Once-daily cadence (final value set by 0024) - a 1d bar closes once per session.
_DAILY_INTERVAL_SEC = 86400
# Priority above the legacy 1m policies (=20) so the scheduler keeps daily active.
_DAILY_PRIORITY = 30
# Alpaca does not provide these exchanges - keep them on EODHD/Yahoo.
_SKIP_EXCHANGES = ("INDX", "FOREX", "SHG")


def _ulid_from_seed(seed: str) -> str:
    """Deterministic 26-char ULID-like ID from a seed string (matches 0011/0023)."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"01HX{h[:22].upper()}"


def upgrade() -> None:
    now = datetime.now(tz=UTC)
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Universe = every (symbol, exchange) with an ENABLED eodhd/ohlcv/1d
    #    policy on an Alpaca-covered exchange. This is the declarative source
    #    of the full US+CC symbol set already known to market-ingestion, without
    #    a cross-service call to market-data (not reachable at migration time).
    # ------------------------------------------------------------------
    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT symbol, exchange "
            "FROM polling_policies "
            "WHERE provider = 'eodhd' AND dataset_type = 'ohlcv' AND timeframe = '1d' "
            "AND enabled = true "
            "AND symbol IS NOT NULL AND exchange IS NOT NULL "
            "AND exchange <> ALL(:skip)"
        ).bindparams(sa.bindparam("skip", value=list(_SKIP_EXCHANGES), type_=sa.ARRAY(sa.String)))
    ).fetchall()

    for symbol, exchange in rows:
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
            # Daily bars are NOT market-hours-gated - the final daily bar settles
            # at/after the close, so a market-hours-only poll would miss the
            # just-closed session. 86_400s cadence = one poll/symbol/day.
            "market_hours_only": False,
            "tier": 2,
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
    # 2. Disable redundant EODHD 1d polling for US+CC ONLY. Every US+CC symbol
    #    now has an explicit alpaca/1d policy (inserted above), and routing sends
    #    1d tasks to Alpaca anyway, so a standing EODHD daily poll is pure
    #    duplicate credit/event burn. INDX/FOREX/SHG rows are left enabled -
    #    Alpaca does not cover them.
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = false, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'ohlcv' "
            "AND timeframe = '1d' AND enabled = true "
            "AND exchange <> ALL(:skip)"
        ).bindparams(sa.bindparam("skip", value=list(_SKIP_EXCHANGES), type_=sa.ARRAY(sa.String)))
    )


def downgrade() -> None:
    conn = op.get_bind()

    # 1. Delete ONLY the alpaca/1d rows this migration added: US+CC symbols that
    #    do NOT have an enabled alpaca/1m policy. 0023's 96 rows (which DO have an
    #    enabled 1m sibling) are left intact so a single downgrade is surgical.
    conn.execute(
        sa.text(
            """
            DELETE FROM polling_policies p
            WHERE p.provider = 'alpaca' AND p.dataset_type = 'ohlcv' AND p.timeframe = '1d'
              AND p.exchange <> ALL(:skip)
              AND NOT EXISTS (
                  SELECT 1 FROM polling_policies m
                  WHERE m.provider = 'alpaca' AND m.dataset_type = 'ohlcv' AND m.timeframe = '1m'
                    AND m.enabled = true
                    AND m.symbol = p.symbol AND m.exchange = p.exchange
              )
            """
        ).bindparams(sa.bindparam("skip", value=list(_SKIP_EXCHANGES), type_=sa.ARRAY(sa.String)))
    )

    # 2. Re-enable the US+CC eodhd/1d polls this migration disabled (restores the
    #    pre-migration state observed on 2026-07-16, where they were enabled).
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = true, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'ohlcv' "
            "AND timeframe = '1d' AND enabled = false "
            "AND exchange <> ALL(:skip)"
        ).bindparams(sa.bindparam("skip", value=list(_SKIP_EXCHANGES), type_=sa.ARRAY(sa.String)))
    )
