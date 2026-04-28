"""Add partial unique index on ``watchlist_members(watchlist_id, instrument_id)``.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-28

PLAN-0046 iter-4 / F-404.

Problem:
    A watchlist could end up with two rows that both resolve to the
    same instrument — one inserted via the seed-style ``entity_id``
    (``01900000-...-1001``) and one via the KG-style ``entity_id``
    (``11111111-0001-...``). The existing
    ``uq_watchlist_members_watchlist_entity`` only guards against
    duplicate entity_ids, not duplicate instrument_ids. The user then
    sees the same ticker rendered twice on the watchlist panel.

Fix:
    Add a partial unique index keyed on ``(watchlist_id, instrument_id)``
    with the predicate ``WHERE instrument_id IS NOT NULL``. This:
      * lets multiple rows coexist while ``instrument_id`` is NULL —
        the watchlist accepts unresolved entities (e.g. fresh entities
        from KG that S3 hasn't broadcast yet); these rows will resolve
        later and at most one of them can have a non-NULL instrument_id
        per watchlist.
      * blocks any second insert with the same already-resolved
        ``instrument_id``, even if it carries a different ``entity_id``.

The use case ``AddWatchlistMemberUseCase`` already raises
``WatchlistMemberAlreadyExistsError`` on the existing entity_id
constraint; the API layer maps that to 409 (Conflict) via
``EntityAlreadyExistsError`` MRO. With this new index in place, the
SQL layer enforces the same property for instrument-level dups, and a
manual INSERT (or a future ``add_by_instrument`` path) that violates
the new index will surface as ``IntegrityError`` and be mapped to 409
by the existing error handler.

Forward-compatibility (R11):
    * Partial index — does not require backfill or rewrite.
    * Idempotent — guarded by ``IF NOT EXISTS`` semantics via inspector
      check so the migration can be re-applied without failure.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEX_NAME = "uq_watchlist_members_watchlist_instrument"


def upgrade() -> None:
    # Idempotent guard for re-applies on dev DBs.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes("watchlist_members")}
    if _INDEX_NAME in existing:
        return

    # Partial unique index. Why use raw SQL (op.execute) rather than
    # ``op.create_index(unique=True, postgresql_where=...)``? Either form
    # works on Postgres; we choose ``op.execute`` for explicitness — the
    # SQL above the line shows exactly what the DB sees, which makes
    # incident-time grep'ing easier when a 409 surfaces.
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX_NAME}
        ON watchlist_members (watchlist_id, instrument_id)
        WHERE instrument_id IS NOT NULL
        """,
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
