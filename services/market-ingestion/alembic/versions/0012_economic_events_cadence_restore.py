"""Restore economic_events polling cadence from 90d back to daily.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-03

WHY: Migration 0009 set economic_events cadence to 90 days (7,776,000s) to
reduce EODHD API quota spend. However, economic calendar events are published
weekly and the dashboard widget reads from `temporal_events` which stays
empty between 90-day fetches. Daily polling (86,400s) restores a useful
refresh rate without excessive credit burn — the economic events endpoint
is cheap (1 credit) compared to fundamentals (10 credits).

macro_indicator remains at 90d; only economic_events is restored.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_DAILY_INTERVAL = 86_400  # 1 day in seconds
_QUARTERLY_INTERVAL = 7_776_000  # 90 days — the value set by migration 0009

_POLICIES_TABLE = sa.table(
    "polling_policies",
    sa.column("dataset_type", sa.String),
    sa.column("base_interval_sec", sa.Integer),
    sa.column("tier", sa.Integer),
)


def upgrade() -> None:
    # Restore economic_events to daily cadence so the dashboard widget has fresh data.
    op.execute(
        _POLICIES_TABLE.update()
        .where(_POLICIES_TABLE.c.dataset_type == "economic_events")
        .values(base_interval_sec=_DAILY_INTERVAL, tier=1)
    )


def downgrade() -> None:
    # Revert to the 90-day cadence from migration 0009.
    op.execute(
        _POLICIES_TABLE.update()
        .where(_POLICIES_TABLE.c.dataset_type == "economic_events")
        .values(base_interval_sec=_QUARTERLY_INTERVAL, tier=2)
    )
