"""Add a partial index on outbox_events for unpublished rows.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-16

Durable dispatcher hardening (follow-up to the 2026-06-15 wedged-dispatcher
incident, see docs/audits/2026-06-15-market-ingestion-worker-claims-zero.md).

The dispatcher's hot-path claim is already covered by ``ix_outbox_events_claimable``
(``status, locked_until, next_attempt_at, created_at``).  What was MISSING was an
index supporting the "how big is the unpublished backlog?" monitoring/cleanup
queries (``WHERE published_at IS NULL``).  During the incident the ``outbox_events``
table had bloated to ~206 MB for ~87k rows, so an un-indexed ``count(*) … WHERE
published_at IS NULL`` scan took 8-15 s and timed out — which actively hampered
diagnosing the stall.  This partial index makes the backlog gauge / any retention
sweep an index-only scan that stays fast as the table grows.

Plain (non-CONCURRENT) ``CREATE INDEX`` per repo convention — Alembic runs each
migration in a transaction and ``CREATE INDEX CONCURRENTLY`` cannot run inside one
(BP-393: a prior CONCURRENTLY-in-migration was converted to plain).  The lock is
brief on a freshly-VACUUMed table.

R32 — revision ``0021`` chains after head ``0020`` from the filesystem
(``ls services/market-ingestion/alembic/versions/`` 2026-06-16).  The Tier-1
policy-seed migration was renumbered to ``0022`` so this infra index stays
*ungated* and applies independently (``alembic upgrade 0021``) without dragging in
the gated policy seed.
"""

from __future__ import annotations

from alembic import op

# Alembic identifiers — chains after 0020 to keep the linear history.
revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_outbox_events_unpublished"


def upgrade() -> None:
    # Partial index: only unpublished rows are indexed, so it stays tiny
    # (proportional to the backlog, not the full history) and serves both the
    # backlog-size gauge and any future "delete published rows older than N days"
    # retention sweep.  ``IF NOT EXISTS`` keeps the migration idempotent across
    # hot-patched local-dev DBs.
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_INDEX_NAME}
        ON outbox_events (created_at)
        WHERE published_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
