"""Denormalise ``ticker``, ``name`` and ``instrument_id`` onto ``watchlist_members``.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-28

PLAN-0046 Wave 2 / T-46-2-01.

Forward-compatible: all three new columns are NULLABLE with no server_default.
Historical rows are left as NULL — the read path treats NULL as "not yet
resolved" and the user can re-add the symbol to populate it. A backfill script
is intentionally out of scope (see plan §T-46-2-01 acceptance: "best-effort").

Why we denormalise (R9 compliance):
    The watchlist UI needs ``ticker``/``name`` for every row and the live quote
    lookup needs ``instrument_id``. Going through the KG (S7) at read time
    would require either (a) a cross-service HTTP fan-out per page load, or
    (b) S1 reading another service's database directly — both forbidden.
    Resolving once at add-time and persisting the snapshot side-steps both
    issues. Stale renames are tolerable for a watchlist row.

Why ``instrument_id`` is also stored here (and not derived from ``entity_id``
at read time):
    The local ``instruments`` table indexes by ``(symbol, exchange)`` and only
    optionally carries ``entity_id``. A reverse lookup ``entity_id →
    instrument_id`` would require an extra query on every list. Since the
    add-time resolution already produces the instrument_id, we persist it.

See: docs/plans/0046-portfolio-correctness-and-analytics-plan.md (T-46-2-01)
     docs/audits/2026-04-28-qa-plan-0044-followup-report.md (F-003)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

# Alembic identifiers
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``ticker``, ``name`` and ``instrument_id`` columns to ``watchlist_members``.

    All three are nullable so existing rows remain valid without backfill.
    No FK on ``instrument_id`` — keeping it as a soft reference matches how
    ``WatchlistMember.entity_id`` is treated (R7: cross-service IDs are not
    declared as DB-level foreign keys).
    """
    op.add_column(
        "watchlist_members",
        sa.Column("ticker", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "watchlist_members",
        sa.Column("name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "watchlist_members",
        sa.Column("instrument_id", PGUUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    """Drop the three columns. Safe — all are nullable with no FK or index."""
    op.drop_column("watchlist_members", "instrument_id")
    op.drop_column("watchlist_members", "name")
    op.drop_column("watchlist_members", "ticker")
