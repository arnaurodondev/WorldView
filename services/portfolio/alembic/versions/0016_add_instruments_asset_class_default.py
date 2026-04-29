"""Backfill instruments.asset_class with 'unknown' default.

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-29

PLAN-0053 T-D-4-02 — surface ``asset_class`` (equity / etf / option / future /
bond / crypto / unknown) on every transaction row so the frontend
``TransactionsTable`` can render a coloured asset-class badge between TYPE and
TICKER.

Background:
    The ``instruments.asset_class`` column already exists (added in migration
    0001). It was previously a nullable ``String`` populated opportunistically
    by the SnapTrade adapter from the broker response. Most rows ended up
    NULL because:
      * Manually-entered positions skip the adapter entirely.
      * Older SnapTrade builds did not surface the field consistently.
    The frontend therefore had nothing to render and the column was dead.

What this migration does:
    1. Backfills every existing NULL row with the literal string ``'unknown'``
       so the field is non-null going forward.
    2. Sets a server-side ``DEFAULT 'unknown'`` so future inserts that omit
       the column receive the sentinel automatically — covering the manual-
       entry path that bypasses the SnapTrade adapter.
    3. Sets ``NOT NULL`` after the backfill so ORM consumers can rely on the
       string contract without a None-check.

Why string (not Postgres ENUM):
    The plan called for an ENUM, but the column already exists as a String
    backed by code that defends against the empty case. Migrating to an
    ENUM would require rewriting every adapter call-site and risks
    breaking the SnapTrade adapter when it sees a class we forgot to
    enumerate. Strings are forward-compatible (BP-019 / R5): adding new
    classes (``adr``, ``warrant``, etc.) is a config-only change. The
    application layer enforces the canonical set via a constant array
    used by the API badge renderer.

BP-019 compliance:
    NOT NULL + ``server_default='unknown'`` is the canonical safe pattern
    — every existing row is backfilled before the constraint flips, so
    the constraint cannot fail mid-migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# ── Alembic identifiers ──────────────────────────────────────────────────────
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill NULLs, add server default, then enforce NOT NULL."""
    # 1. Backfill — single UPDATE is fine; the instruments table is bounded by
    #    the tenant footprint (typically <500 rows even on busy installs).
    op.execute("UPDATE instruments SET asset_class = 'unknown' WHERE asset_class IS NULL")

    # 2. Server default + NOT NULL. Combined alter_column lets Alembic emit a
    #    single ALTER TABLE in one round-trip on Postgres.
    op.alter_column(
        "instruments",
        "asset_class",
        existing_type=sa.String(),
        nullable=False,
        server_default=sa.text("'unknown'"),
    )


def downgrade() -> None:
    """Revert to nullable column with no server default.

    The downgrade leaves any backfilled 'unknown' values in place — they are
    semantically a no-op (still match the previous "we don't know" state) and
    re-NULL-ing them would lose information for any row populated after
    this migration ran.
    """
    op.alter_column(
        "instruments",
        "asset_class",
        existing_type=sa.String(),
        nullable=True,
        server_default=None,
    )
