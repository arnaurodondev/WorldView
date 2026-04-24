"""Reduce polling cadence for fundamentals, macro_indicator, and economic_events.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-24

EODHD quota reduction (PLAN-0036 W2-7/W2-8):
  - fundamentals:      86400s (1d)  → 7776000s (90d), tier=2
  - macro_indicator:   604800s (7d) → 7776000s (90d), tier=2
  - economic_events:   86400s (1d)  → 7776000s (90d), tier=2

Fundamentals data for public equities is quarterly; polling daily burns API
credits for data that hasn't changed. Macro indicators and economic events
change at most monthly, so a 90-day floor matches practical data freshness.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_QUARTERLY_INTERVAL = 7_776_000  # 90 days in seconds

_POLICIES_TABLE = sa.table(
    "polling_policies",
    sa.column("dataset_type", sa.String),
    sa.column("base_interval_sec", sa.Integer),
    sa.column("tier", sa.Integer),
)

_SLOW_DATASET_TYPES = ("fundamentals", "macro_indicator", "economic_events")


def upgrade() -> None:
    # Quarterly cadence for dataset types that change at most once per quarter.
    op.execute(
        _POLICIES_TABLE.update()
        .where(_POLICIES_TABLE.c.dataset_type.in_(_SLOW_DATASET_TYPES))
        .values(base_interval_sec=_QUARTERLY_INTERVAL, tier=2)
    )


def downgrade() -> None:
    # Restore original intervals per dataset type.
    for dataset_type, original_interval in [
        ("fundamentals", 86400),
        ("economic_events", 86400),
        ("macro_indicator", 604800),
    ]:
        op.execute(
            _POLICIES_TABLE.update()
            .where(_POLICIES_TABLE.c.dataset_type == dataset_type)
            .values(base_interval_sec=original_interval)
        )
