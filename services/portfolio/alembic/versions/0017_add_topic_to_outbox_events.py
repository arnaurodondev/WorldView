"""Add ``topic`` column to ``outbox_events`` for schema unification.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-09

PLAN-0087 #9 / qa-beta-data-platform F-003 — Outbox schema unification.

Background:
    The portfolio service's ``outbox_events`` table was the only outbox in
    the platform without a persisted ``topic`` column. Instead, the topic
    was derived at dispatch time from a Python ``EVENT_TOPIC_MAP`` keyed by
    ``event_type``. This silent coupling violated R8 (transactional outbox)
    in two ways:

      1. **Operational tooling**: SQL-only replay/inspection tools that
         scan ``outbox_events`` across services cannot see which topic a
         row will land on without loading service code.
      2. **Drift risk**: If a developer adds a new ``event_type`` but
         forgets to update ``EVENT_TOPIC_MAP``, dispatch raises a
         ``ValueError`` at runtime — yet the row was already accepted
         transactionally. The contract violation surfaces only on retry.

    Per ``docs/STANDARDS.md`` §3.4, every outbox MUST have a non-null
    ``topic`` column. This migration restores that invariant for the
    portfolio service.

What this migration does:
    1. Adds ``topic TEXT`` as nullable (forward-compat per R5/R11 — old
       writers that don't set it stay valid until the application is
       redeployed).
    2. Back-fills existing rows by joining ``event_type`` against the
       canonical map. Anything not in the map (which would be a bug —
       these rows would already fail to dispatch) is left NULL so the
       caller can spot it.
    3. The column stays nullable for now; tightening to NOT NULL is a
       follow-up after the application code persists ``topic`` on every
       insert (out of scope per the F-003 task brief).

Forward-compat (R5):
    Adding a nullable column is a forward-compatible schema change. Old
    code that ignores the column continues to insert successfully.

R32 — revision number ``0017`` chains after head ``0016`` from the
filesystem (``ls services/portfolio/alembic/versions/`` 2026-05-09).
"""

from __future__ import annotations

from alembic import op

# Alembic identifiers — chains after 0016 to keep the linear history.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None


# ─── Canonical event_type → topic mapping (mirrors EVENT_TOPIC_MAP) ───────────
# Kept here as raw SQL VALUES so the migration is self-contained — it must
# work even if the application package is at a future version that has
# renamed/removed events. If a row's event_type is not listed here, ``topic``
# is left NULL (the dispatcher will reject those at publish time anyway, so
# the NULL is informative, not destructive).
_EVENT_TOPIC_BACKFILL: list[tuple[str, str]] = [
    ("tenant.created", "portfolio.events.v1"),
    ("tenant.status_changed", "portfolio.events.v1"),
    ("user.created", "portfolio.events.v1"),
    ("user.status_changed", "portfolio.events.v1"),
    ("portfolio.created", "portfolio.events.v1"),
    ("portfolio.renamed", "portfolio.events.v1"),
    ("portfolio.archived", "portfolio.events.v1"),
    ("transaction.recorded", "portfolio.events.v1"),
    ("holding.changed", "portfolio.events.v1"),
    ("instrument_ref.created", "portfolio.events.v1"),
    ("watchlist.created", "portfolio.events.v1"),
    ("watchlist.deleted", "portfolio.events.v1"),
    ("watchlist.renamed", "portfolio.watchlist.updated.v1"),
    ("watchlist.item_added", "portfolio.watchlist.updated.v1"),
    ("watchlist.item_deleted", "portfolio.watchlist.updated.v1"),
]


def upgrade() -> None:
    # 1. Add the column. ``IF NOT EXISTS`` makes the migration safely
    # idempotent across local-dev DBs that may have been hot-patched.
    op.execute(
        """
        ALTER TABLE outbox_events
        ADD COLUMN IF NOT EXISTS topic TEXT
        """
    )

    # 2. Backfill existing rows from the canonical event_type → topic map.
    # Use a single UPDATE with a VALUES table for atomicity.
    if _EVENT_TOPIC_BACKFILL:
        # Build VALUES list as inline literals — values are static,
        # there's no SQL-injection vector (these are repo constants).
        values_sql = ", ".join(f"('{event_type}', '{topic}')" for event_type, topic in _EVENT_TOPIC_BACKFILL)
        op.execute(
            f"""
            UPDATE outbox_events o
            SET topic = m.topic
            FROM (VALUES {values_sql}) AS m(event_type, topic)
            WHERE o.event_type = m.event_type
              AND o.topic IS NULL
            """
        )


def downgrade() -> None:
    # The column is nullable so dropping it loses no application invariant.
    op.execute("ALTER TABLE outbox_events DROP COLUMN IF EXISTS topic")
