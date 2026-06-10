"""Bump Alpaca 1m polling-policy priority to 100.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-10

PLAN-0109 Wave D-1 (H-1 resolved 2026-06-10) — Worker priority + fair-share
scheduling.

Background
----------
After 46 Alpaca 1m tasks completed in the first scheduler tick, the single
worker pivoted to EODHD daily/weekly/monthly batches and the remaining
~600 Alpaca 1m policies never ran that tick. All 649 policies shared
``priority = 20``.

Decision (H-1)
--------------
Alpaca-1m is the live ingestion backbone — it must NOT be preempted by
lower-cadence EODHD timeframes. Raise the priority of every enabled
``provider='alpaca' AND timeframe='1m'`` policy to ``100``. Other providers
stay at their existing priority (typically 20).

The Alpaca adapter already batches up to 1000 symbols per HTTP call
(``AlpacaProviderAdapter._BATCH_SIZE = 1000``) and ``worker.py`` already
takes the batch path when ``supports_batch=True``, so Alpaca-1m ingestion
of 649 symbols costs ~1-2 HTTP calls per minute — there is no API-cost
downside to raising the priority.

Forward-compat (R5)
-------------------
Only an UPDATE — no schema changes. Rollback reverts the priority to 20.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET priority = 100, updated_at = NOW() "
            "WHERE provider = 'alpaca' AND timeframe = '1m' AND enabled = true"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET priority = 20, updated_at = NOW() "
            "WHERE provider = 'alpaca' AND timeframe = '1m' AND enabled = true"
        )
    )
