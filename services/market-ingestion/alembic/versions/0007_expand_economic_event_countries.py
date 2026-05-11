"""D-W2: Expand economic event polling policies to JP, CN, and EU.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-24

The initial seed (0002) only included economic event polling for USA, EUR,
and GBR.  This migration adds JP (Japan), CN (China), and EU (Euro Area)
to broaden macro coverage to the G7's major Asian economies and the EU bloc.

Symbols follow the existing EVENTS.<COUNTRY> convention used by the EODHD
economic events endpoint.  All new policies inherit the same 86 400 s (daily)
base interval as the USA/EUR/GBR policies seeded in 0002.

INSERT uses ON CONFLICT DO NOTHING for full idempotency — re-running the
migration against a DB that already has the rows is safe.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# New countries to add — ISO 3-letter codes used by EODHD economic events API.
_NEW_COUNTRIES = ("JPN", "CHN", "EU")


def _ulid_from_seed(seed: str) -> str:
    """Generate a deterministic 26-char ULID-like ID from a seed string.

    Mirrors the same helper used in 0002 to keep ID generation consistent
    across all seed and expansion migrations.
    """
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"01HX{h[:22].upper()}"


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(tz=UTC)

    for country in _NEW_COUNTRIES:
        symbol = f"EVENTS.{country}"
        # Deterministic ID matches the pattern from 0002's _insert_policy()
        # seed format: "{provider}:{dataset_type}:{symbol}:{exchange}:{timeframe}:{variant}"
        policy_id = _ulid_from_seed(f"eodhd:economic_events:{symbol}::::")

        conn.execute(
            sa.text(
                "INSERT INTO polling_policies ("
                "  id, provider, dataset_type, dataset_variant, symbol, exchange,"
                "  timeframe, base_interval_sec, min_interval_sec, jitter_sec,"
                "  adaptive_enabled, adaptive_k, adaptive_half_life_sec, priority,"
                "  enabled, backfill_enabled, backfill_start_date, backfill_chunk_days,"
                "  market_hours_only, created_at, updated_at"
                ") VALUES ("
                "  :id, :provider, :dataset_type, NULL, :symbol, NULL,"
                "  NULL, :base_interval_sec, :min_interval_sec, :jitter_sec,"
                "  false, 1.0, 3600, 0,"
                "  true, false, NULL, NULL,"
                "  false, :created_at, :updated_at"
                ") ON CONFLICT DO NOTHING"
            ).bindparams(
                id=policy_id,
                provider="eodhd",
                dataset_type="economic_events",
                symbol=symbol,
                base_interval_sec=86400,
                min_interval_sec=8640,  # 10 % of base — matches 0002's max(60, interval // 10)
                jitter_sec=10,
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove only the rows added by this migration — identified by their
    # deterministic IDs so the downgrade is safe even if rows were updated
    # between the upgrade and downgrade.
    policy_ids = [_ulid_from_seed(f"eodhd:economic_events:EVENTS.{country}::::") for country in _NEW_COUNTRIES]
    conn.execute(
        sa.text("DELETE FROM polling_policies WHERE id = ANY(:ids)").bindparams(
            sa.bindparam("ids", value=policy_ids, type_=sa.ARRAY(sa.String))
        )
    )
