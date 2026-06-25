"""Seed Tier-1-US tickerless-company polling policies (derived-bar-aware).

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-15

Seeds Alpaca/EODHD polling policies for 36 Tier-1-US tickerless companies
(Marvell, Nike, Micron, Western Digital, GlobalFoundries, Deckers, Newmont, …)
that are mentioned in the news corpus but have no symbol wired into
``ingestion_db.polling_policies`` — so no OHLCV (Alpaca) / fundamentals (EODHD)
ingestion ever runs for them.

Per-symbol policy set (3 rows) — DERIVED-BAR-AWARE
--------------------------------------------------
This migration was originally drafted with FIVE policy kinds per symbol, mirroring
a then-fully-covered live symbol.  Two of those — EODHD ``1w`` and ``1mo`` OHLCV —
are now RETIRED: weekly/monthly bars are DERIVED on the fly from daily bars by
market-data (S3) ``GET /api/v1/ohlcv/bars``.  Migration 0020 already disabled all
existing ``1w``/``1mo`` polling policies for the same reason.  Seeding fresh
``1w``/``1mo`` rows here would re-introduce exactly the noise 0020 removed (empty
polls, watermark churn, wasted EODHD quota), so they are DROPPED.  The result is
the canonical fully-covered set MINUS the now-redundant weekly/monthly polls:

  #  provider  dataset_type  variant   timeframe  base_int  min_int  jitter  prio  tier
  1  alpaca    ohlcv         NULL      1m         60        60       5       100   <cand tier>
  2  eodhd     ohlcv         NULL      1d         21600     3600     60      5     2
  3  eodhd     fundamentals  General   NULL       86400     3600     300     2     2

Only the Alpaca 1m policy tracks the candidate tier; EODHD rows are uniformly
tier=2.  Other columns set explicitly to mirror live data:
enabled=true, market_hours_only=false, post_market_only=false,
backfill_enabled=false, backfill_chunk_days=30; adaptive_* / created_at /
updated_at left at DB defaults.

Why this is now safe to apply (gate removed)
--------------------------------------------
The original revision was GATED behind an ``APPLY_TIER1_US_SEED`` env flag because
(a) it seeded wasteful 1w/1mo EODHD polls and (b) EODHD daily quota was exhausted.
Reason (a) is eliminated — those rows are gone.  Reason (b) is no longer a blocker:
seeding a policy is just an INSERT of a config row; it does not itself call EODHD.
The Alpaca 1m rows cost zero EODHD quota.  The EODHD 1d/fundamentals rows are
serviced by the scheduler/worker, which has a robust quota guard chain — a
pre-flight monthly-quota check + circuit breaker (``run_pre_fetch_guards`` in
``application/use_cases/strategies/pipeline.py``) that DEFERS (persist_retry) the
task BEFORE any HTTP call when quota is exhausted, plus 429 ``Retry-After``-aware
exponential backoff with jitter and a capped attempt count in the fundamentals
refresh worker (BP-114 mitigation).  So even against 0-headroom EODHD the seeded
policies back off gracefully and never storm.  The gate is therefore removed:
``upgrade`` seeds unconditionally, and a bare ``alembic upgrade head`` provisions
these symbols declaratively.

Row count
---------
36 symbols x 3 policy kinds = 108 candidate rows.  Idempotency (below) skips any
6-tuple already present, so the actual inserted count is (108 minus already-present).
On the 2026-06-15 dry-run snapshot the previously-present overlap was concentrated
in the already-covered symbols; this migration inserts NO ``1w``/``1mo`` rows under
any circumstance.

Idempotency
-----------
There is NO unique constraint on polling_policies — only the non-unique matching
index ix_polling_policies_matching on
(provider, dataset_type, dataset_variant, symbol, exchange, timeframe).  So we
de-dup ourselves: before each insert we SELECT for an existing row on exactly
that 6-tuple (NULL-safe via IS NOT DISTINCT FROM, because dataset_variant and
timeframe are nullable) and skip if present.  Re-running upgrade() is a no-op.
``id`` is a fresh 26-char ULID (common.ids.new_ulid), matching every live row.

Downgrade
---------
Deletes EXACTLY the rows this migration's template would insert, matched on the
full 6-tuple for the Tier-1-US symbol set (NULL-safe).  It only removes policies
whose 6-tuple is in this migration's template, so pre-existing policies for other
symbols/timeframes are untouched.  CAVEAT: because idempotency means we only ever
INSERT a 6-tuple that was previously absent, a single downgrade is reversible.
However, if a Tier-1-US 6-tuple already existed before this migration ran,
downgrade would also delete that pre-existing row — these rows are
indistinguishable by 6-tuple.  This matches the seed script's match-key semantics
and the absence of any other discriminator on the table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from common.ids import new_ulid

# revision identifiers, used by Alembic.
revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Resolved Tier-1-US apply-ready list (36 symbols) — copied verbatim from
# scripts/data/seed_tier_policies.py::TIER1_US_CANDIDATES so this migration is
# self-contained.  All exchange="US", tier=1.  (symbol, exchange, tier)
# ---------------------------------------------------------------------------
_TIER1_US_CANDIDATES: list[tuple[str, str, int]] = [
    ("MRVL", "US", 1),  # Marvell Technology
    ("NKE", "US", 1),  # NIKE
    ("MU", "US", 1),  # Micron Tech
    ("WDC", "US", 1),  # Western Digital
    ("GFS", "US", 1),  # GLOBALFOUNDRIES Inc.
    ("DECK", "US", 1),  # DECKERS OUTDOOR CORP
    ("NEM", "US", 1),  # Newmont Mining (Newmont Corp)
    ("CTRN", "US", 1),  # Citi Trends Inc
    ("ITIC", "US", 1),  # Investors Title Co.
    ("TMHC", "US", 1),  # Taylor Morrison Home
    ("PINS", "US", 1),  # PINTEREST
    ("RDW", "US", 1),  # Redwire
    ("BF.B", "US", 1),  # Brown-Forman (Class B)
    ("RH", "US", 1),  # RH (Restoration Hardware)
    ("ATI", "US", 1),  # ATI Inc.
    ("SYK", "US", 1),  # Stryker
    ("FLEX", "US", 1),  # Flex Ltd. (US-listed)
    ("SMCI", "US", 1),  # Super Micro
    ("RGTI", "US", 1),  # Rigetti Computing
    ("WHR", "US", 1),  # Whirlpool
    ("TPR", "US", 1),  # Tapestry
    ("PEBO", "US", 1),  # Peoples Bancorp
    ("ALGM", "US", 1),  # Allegro MicroSystems
    ("PLD", "US", 1),  # Prologis
    ("FIBK", "US", 1),  # First Interstate BancSystem
    ("MCK", "US", 1),  # McKesson
    ("SMTC", "US", 1),  # Semtech Corp
    ("PLUS", "US", 1),  # ePlus Inc
    ("BB", "US", 1),  # BlackBerry (US-listed, NYSE)
    ("ROG", "US", 1),  # Rogers Corp
    ("CELH", "US", 1),  # Celsius Holdings
    ("ETN", "US", 1),  # Eaton Corp. Plc (NYSE)
    ("LHX", "US", 1),  # L3Harris
    ("AAOI", "US", 1),  # Applied Optoelectronics
    ("CPA", "US", 1),  # Copa Holdings (NYSE)
    ("IAC", "US", 1),  # IAC Inc.
]

# ---------------------------------------------------------------------------
# Canonical per-symbol policy template (verified from live data 2026-06-15),
# DERIVED-BAR-AWARE: only {alpaca 1m, eodhd 1d, eodhd fundamentals}.  The EODHD
# ``1w``/``1mo`` OHLCV rows are intentionally OMITTED — weekly/monthly bars are
# derived on the fly from daily bars in market-data (S3), and migration 0020
# already disabled every existing 1w/1mo polling policy for that reason.
# Each spec: (provider, dataset_type, dataset_variant, timeframe,
#             base_interval_sec, min_interval_sec, jitter_sec, priority).
# symbol/exchange/tier are filled per candidate.  The Alpaca 1m policy tracks
# the candidate tier; all EODHD policies are tier=2.
# ---------------------------------------------------------------------------
_PolicySpec = tuple[str, str, str | None, str | None, int, int, int, int]

_POLICY_SPECS: list[_PolicySpec] = [
    ("alpaca", "ohlcv", None, "1m", 60, 60, 5, 100),
    ("eodhd", "ohlcv", None, "1d", 21600, 3600, 60, 5),
    ("eodhd", "fundamentals", "General", None, 86400, 3600, 300, 2),
]


def _planned_rows() -> list[dict]:
    """Expand the 36 candidates x 3 specs into 108 candidate policy dicts.

    Idempotency at upgrade time reduces this to the rows actually absent.  No
    ``1w``/``1mo`` rows are ever produced (derived bars — see module docstring).
    """
    rows: list[dict] = []
    for symbol, exchange, cand_tier in _TIER1_US_CANDIDATES:
        for provider, dataset_type, variant, timeframe, base_int, min_int, jitter, priority in _POLICY_SPECS:
            row_tier = cand_tier if provider == "alpaca" else 2
            rows.append(
                {
                    "provider": provider,
                    "dataset_type": dataset_type,
                    "dataset_variant": variant,
                    "symbol": symbol,
                    "exchange": exchange,
                    "timeframe": timeframe,
                    "base_interval_sec": base_int,
                    "min_interval_sec": min_int,
                    "jitter_sec": jitter,
                    "priority": priority,
                    "tier": row_tier,
                }
            )
    return rows


# NULL-safe existence check on the matching 6-tuple (mirrors
# ix_polling_policies_matching). IS NOT DISTINCT FROM handles NULL variant/tf.
_EXISTS_SQL = sa.text(
    """
    SELECT 1 FROM polling_policies
    WHERE provider = :provider
      AND dataset_type = :dataset_type
      AND dataset_variant IS NOT DISTINCT FROM :dataset_variant
      AND symbol = :symbol
      AND exchange = :exchange
      AND timeframe IS NOT DISTINCT FROM :timeframe
    LIMIT 1
    """
)

_INSERT_SQL = sa.text(
    """
    INSERT INTO polling_policies (
        id, provider, dataset_type, dataset_variant, symbol, exchange, timeframe,
        base_interval_sec, min_interval_sec, jitter_sec, priority,
        enabled, market_hours_only, post_market_only,
        backfill_enabled, backfill_chunk_days, tier
    ) VALUES (
        :id, :provider, :dataset_type, :dataset_variant, :symbol, :exchange, :timeframe,
        :base_interval_sec, :min_interval_sec, :jitter_sec, :priority,
        TRUE, FALSE, FALSE,
        FALSE, 30, :tier
    )
    """
)

# Delete matched on the full 6-tuple (NULL-safe). Used by downgrade.
_DELETE_SQL = sa.text(
    """
    DELETE FROM polling_policies
    WHERE provider = :provider
      AND dataset_type = :dataset_type
      AND dataset_variant IS NOT DISTINCT FROM :dataset_variant
      AND symbol = :symbol
      AND exchange = :exchange
      AND timeframe IS NOT DISTINCT FROM :timeframe
    """
)


def upgrade() -> None:
    # Seeds unconditionally (gate removed — see module docstring "Why this is now
    # safe to apply").  Each insert is a NULL-safe-deduped config row; the
    # scheduler/worker quota-guard chain (pre-flight quota check + circuit breaker
    # + 429 backoff) handles EODHD quota-exceeded at fetch time, so seeding never
    # storms the provider.
    conn = op.get_bind()
    for row in _planned_rows():
        match = {
            "provider": row["provider"],
            "dataset_type": row["dataset_type"],
            "dataset_variant": row["dataset_variant"],
            "symbol": row["symbol"],
            "exchange": row["exchange"],
            "timeframe": row["timeframe"],
        }
        # NULL-safe 6-tuple dedup: skip if an equivalent policy already exists.
        if conn.execute(_EXISTS_SQL, match).first() is not None:
            continue
        conn.execute(_INSERT_SQL, {"id": new_ulid(), **row})


def downgrade() -> None:
    conn = op.get_bind()
    # Delete exactly the 6-tuples this migration's template covers (NULL-safe).
    # Only Tier-1-US template rows are matched; other symbols/timeframes are
    # untouched. See module docstring for the pre-existing-row caveat.
    for row in _planned_rows():
        conn.execute(
            _DELETE_SQL,
            {
                "provider": row["provider"],
                "dataset_type": row["dataset_type"],
                "dataset_variant": row["dataset_variant"],
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "timeframe": row["timeframe"],
            },
        )
