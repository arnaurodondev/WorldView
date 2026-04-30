"""Add UNIQUE index on entity_aliases (entity_id, normalized, alias_type) to prevent duplicate aliases.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-30

PLAN-0057 Wave A-2 — closes the second root cause of audit finding F-CRIT-12.

Background: migration 0001 created a partial unique index
``uidx_entity_aliases_normalized ON entity_aliases (normalized_alias_text)
WHERE alias_type = 'EXACT' AND is_active = true``. Non-EXACT alias types
(TICKER, ISIN, NAME, CUSIP, FIGI, LEI, PRIMARY_TICKER, LLM, ...) had **no**
uniqueness constraint, so seed_demo restarts and Kafka re-deliveries silently
duplicated rows (32 of 38 alias rows in the dev DB were 4x duplicates of seed
TICKER aliases).

This migration:
  1. Pre-cleans existing duplicates by keeping the oldest ``alias_id`` per
     (entity_id, normalized_alias_text, alias_type) tuple — safe because the
     normalized + alias_type combination identifies the same logical alias
     regardless of the original alias_text casing.
  2. Adds ``uidx_entity_aliases_entity_norm_type`` UNIQUE INDEX over
     (entity_id, normalized_alias_text, alias_type) WHERE is_active = true.

The new index complements the existing 0001 index — that one enforces "only
one EXACT alias system-wide per normalized text" (cross-entity), while this
one enforces "only one alias of any given type per entity per normalized text".

Idempotent: ``CREATE UNIQUE INDEX IF NOT EXISTS`` plus ``ON CONFLICT DO NOTHING``-
style pre-clean DELETE keeps repeated upgrades safe.
"""

from __future__ import annotations

from alembic import op

revision: str = "0008"
down_revision: str = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1 — pre-clean. Keep the row with the OLDEST ``created_at`` (which is
    # the actually-oldest insert) per (entity_id, normalized, alias_type) triple
    # and delete the rest. ``alias_id`` is the secondary tiebreaker for
    # determinism when two rows share a ``created_at`` timestamp.
    #
    # IMPORTANT: ``alias_id`` is ``gen_random_uuid()`` (UUIDv4, random), NOT
    # UUIDv7-monotonic, so it is NOT a reliable proxy for insertion order.
    # An earlier draft of this migration used ``WHERE a.alias_id > b.alias_id``
    # which preserved an ARBITRARY duplicate, not the oldest. Using
    # ``(created_at, alias_id)`` as the lexicographic key fixes that.
    op.execute(
        """
DELETE FROM entity_aliases a
USING entity_aliases b
WHERE (a.created_at, a.alias_id) > (b.created_at, b.alias_id)
  AND a.entity_id              = b.entity_id
  AND a.normalized_alias_text  = b.normalized_alias_text
  AND a.alias_type             = b.alias_type
"""
    )

    # Step 2 — install the UNIQUE index. Restricted to is_active=true so soft-deleted
    # aliases (when we add that flow) don't block re-creation.
    op.execute(
        """
CREATE UNIQUE INDEX IF NOT EXISTS uidx_entity_aliases_entity_norm_type
    ON entity_aliases (entity_id, normalized_alias_text, alias_type)
    WHERE is_active = true
"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uidx_entity_aliases_entity_norm_type")
    # Pre-clean is intentionally NOT undone in downgrade — the duplicates were
    # already redundant data; restoring them on rollback would be incorrect.
