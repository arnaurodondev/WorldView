"""Seed the 4 deeper Polymarket-stream sources (PLAN-0056 Wave B3).

Revision ID: 0011_seed_pm_wave2_sources
Revises: 0010_sec_edgar_cik_watchlist
Create Date: 2026-07-09

WHY (PLAN-0056 Wave B3): Wave B1 built the 4 deeper-stream adapters (Gamma
``/events``, CLOB ``/prices-history``, Data ``/trades``, Data ``/oi``) and Wave
B3 wired them into the worker + outbox dispatcher.  For the scheduler to poll
them a ``sources`` row must exist for each new ``source_type``.  This migration
inserts those 4 rows so a plain ``docker compose up`` starts polling all four
streams (per-stream cadence is set in ``scheduler_main`` from each provider's
``poll_interval_seconds``: events 1h, CLOB history 6h, trades 1h, OI daily —
PRD-0033 §4.2).

The CLOB / trades adapters read a ``markets`` work-list — a list of
``{"condition_id": ..., "token_ids": [...]}`` pairing each parent market
``conditionId`` with its child CLOB outcome tokens (PLAN-0056 Wave B4) — so the
resulting S3 price/trade rows carry ``market_id = conditionId`` and JOIN to
``prediction_markets``.  The OI adapter reads ``condition_ids``.  All are seeded
EMPTY here (the adapters gracefully no-op on an empty list); a later wave
populates them from the live market universe (derived from Gamma ``/markets``
``clobTokenIds``).

Mirrors the 0008 seeding pattern: deterministic SHA-256-derived UUIDs (stable
across re-deploys) + ``ON CONFLICT ON CONSTRAINT uq_sources_dedup DO NOTHING``
(``config_hash`` is a GENERATED column so it cannot appear in an ON CONFLICT
target list — the named constraint is referenced instead).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers
# NOTE: the revision id is deliberately SHORT ("0011_seed_pm_wave2_sources", 26
# chars). Alembic stores it in ``alembic_version.version_num varchar(32)``; the
# original id "0011_seed_polymarket_wave2_sources" was 34 chars → a fresh-DB
# ``alembic upgrade head`` raised StringDataRightTruncationError and rolled the
# whole migration back (PLAN-0056 deploy-fix). Keep any future id ≤ 32 chars.
revision: str = "0011_seed_pm_wave2_sources"
down_revision: str = "0010_sec_edgar_cik_watchlist"
branch_labels = None
depends_on = None


def _uuid_from_seed(seed: str) -> str:
    """Derive a deterministic UUID-formatted id from ``seed`` via SHA-256.

    Same helper pattern as migration 0008 so ids are stable across re-deploys.
    """
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# Deterministic ids — stable across re-deploys (same seed = same id).
_WAVE2_SOURCES = [
    {
        "id": _uuid_from_seed("source:polymarket_gamma_events:events"),
        "name": "polymarket-events",
        "source_type": "polymarket_gamma_events",
        "config": json.dumps({}),
        "enabled": True,
    },
    {
        "id": _uuid_from_seed("source:polymarket_clob:prices-history"),
        "name": "polymarket-clob-history",
        # CLOB adapter reads the ``markets`` work-list — {condition_id, token_ids}
        # pairs (PLAN-0056 Wave B4) — seeded empty; populated later.
        "source_type": "polymarket_clob",
        "config": json.dumps({"markets": []}),
        "enabled": True,
    },
    {
        "id": _uuid_from_seed("source:polymarket_data_trades:trades"),
        "name": "polymarket-trades",
        # Trades adapter reads the ``markets`` work-list — {condition_id, token_ids}
        # pairs (PLAN-0056 Wave B4) — seeded empty; populated later.
        "source_type": "polymarket_data_trades",
        "config": json.dumps({"markets": []}),
        "enabled": True,
    },
    {
        "id": _uuid_from_seed("source:polymarket_data_oi:open-interest"),
        "name": "polymarket-oi",
        # OI adapter reads ``condition_ids`` (seeded empty; populated later).
        "source_type": "polymarket_data_oi",
        "config": json.dumps({"condition_ids": []}),
        "enabled": True,
    },
]


def upgrade() -> None:
    now = datetime.now(tz=UTC)

    for src in _WAVE2_SOURCES:
        op.execute(
            sa.text(
                # CAST(... AS type) (not ::type) — asyncpg via sa.text() sends
                # params as VARCHAR, and :: confuses SA's bindparam parser.
                """
                INSERT INTO sources (id, name, source_type, config, enabled, created_at)
                VALUES (
                    CAST(:id AS uuid),
                    :name,
                    :source_type,
                    CAST(:config AS jsonb),
                    :enabled,
                    :created_at
                )
                ON CONFLICT ON CONSTRAINT uq_sources_dedup DO NOTHING
                """,
            ).bindparams(
                id=src["id"],
                name=src["name"],
                source_type=src["source_type"],
                config=src["config"],
                enabled=src["enabled"],
                created_at=now,
            ),
        )


def downgrade() -> None:
    ids = [src["id"] for src in _WAVE2_SOURCES]
    for source_id in ids:
        op.execute(sa.text("DELETE FROM sources WHERE id = CAST(:id AS uuid)").bindparams(id=source_id))
