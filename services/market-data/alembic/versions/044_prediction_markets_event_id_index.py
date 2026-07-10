"""prediction_markets.event_id partial index + prediction hypertable retention.

Revision ID: 044
Revises: 043
Create Date: 2026-07-10

WHY THIS MIGRATION EXISTS (PLAN-0056 QA — data findings):

  FIX 3 (index): migration 043 added ``prediction_markets.event_id`` (nullable)
  as the link from a market to its Polymarket event group, but shipped NO index.
  The event consumer and the entity-predictions read API filter/join on
  ``event_id`` (``WHERE event_id = :event_id`` / grouping markets by event), so a
  supporting index avoids a sequential scan over ``prediction_markets``. We use a
  PARTIAL index (``WHERE event_id IS NOT NULL``) — the column is nullable and the
  majority of legacy rows have no event link, so a partial index is smaller and
  only covers the rows that are ever queried by event.

  FIX 4 (retention): ``prediction_market_trades`` is the unbounded stream (one
  row per fill) and ``prediction_market_prices`` grows per token per interval.
  Left unbounded these TimescaleDB hypertables grow without limit. We register a
  180-day retention policy on both so Timescale's background job drops chunks
  older than the window. Chosen over "document-only" because trades is genuinely
  unbounded and a guarded policy is safe (see guards below).

SAFETY GUARDS:
  * The retention DDL is wrapped in a PL/pgSQL block that only runs when the
    ``timescaledb`` extension is installed — on a plain-Postgres test DB the
    block is a no-op, so the migration never fails for lack of the extension.
  * ``if_not_exists => true`` makes ``add_retention_policy`` idempotent (safe to
    re-run); ``if_exists => true`` makes the downgrade's removal idempotent.

R11 forward-compat: index + retention job only — additive, and the downgrade
  cleanly reverses both. Does NOT touch the already-shipped 043 objects.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "044"
down_revision: str = "043"
branch_labels = None
depends_on = None

# 180-day retention window for the prediction hypertables.
_RETENTION_INTERVAL = "180 days"
_RETENTION_TABLES = ("prediction_market_trades", "prediction_market_prices")


def upgrade() -> None:
    # ── FIX 3: partial index on prediction_markets.event_id ──────────────────
    op.create_index(
        "ix_prediction_markets_event_id",
        "prediction_markets",
        ["event_id"],
        unique=False,
        postgresql_where=sa.text("event_id IS NOT NULL"),
    )

    # ── FIX 4: 180-day retention on the prediction hypertables (guarded) ──────
    add_calls = "\n".join(
        f"    PERFORM add_retention_policy('{table}', INTERVAL '{_RETENTION_INTERVAL}', if_not_exists => true);"
        for table in _RETENTION_TABLES
    )
    op.execute(
        "DO $$\n"
        "BEGIN\n"
        "  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN\n"
        f"{add_calls}\n"
        "  END IF;\n"
        "END\n"
        "$$;"
    )


def downgrade() -> None:
    remove_calls = "\n".join(
        f"    PERFORM remove_retention_policy('{table}', if_exists => true);" for table in _RETENTION_TABLES
    )
    op.execute(
        "DO $$\n"
        "BEGIN\n"
        "  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN\n"
        f"{remove_calls}\n"
        "  END IF;\n"
        "END\n"
        "$$;"
    )
    op.drop_index("ix_prediction_markets_event_id", table_name="prediction_markets")
