"""Seed KG system-sentinel entities + add canonical_entities.is_system flag.

Revision ID: 0044
Revises: 0043
Create Date: 2026-05-23

PLAN-0093 Wave B-2 T-B-2-01.

WHY THIS MIGRATION EXISTS:
  Extraction pipelines sometimes resolve neither subject nor object of a
  relation to a real entity (e.g. macro-only news, ambiguous person names).
  The current fallback path was to insert a self-loop on a hard-coded UUID
  ``11111111-0004-7000-8000-000000000001`` that did not actually exist in
  ``canonical_entities`` — creating orphan FKs that broke any downstream
  JOIN on relations + entities (F-DB-012, F-KG-PERSIST-002).

  This migration:
    1. Adds a new BOOLEAN column ``is_system`` to ``canonical_entities``
       (DEFAULT false, NOT NULL).  Marks sentinel entities used as fallbacks.
    2. INSERTs five system sentinels (Macro / Unknown {Person, Organization,
       Place, Product}) — one per fallback entity_type.  All have
       ``is_system=true`` so they can be filtered out of user-facing
       result sets and excluded from the self-loop CHECK constraint added in
       wave B-2.
    3. ``enriched_at = utc_now()`` and ``data_completeness = 1.0`` so the
       enrichment sweep never picks them up (they aren't real entities).

IDEMPOTENCY:
  - ``ADD COLUMN IF NOT EXISTS`` is unsupported in older Alembic; we add
    the column unconditionally and rely on a guard check first.
  - INSERTs use ``ON CONFLICT (entity_id) DO NOTHING``.

DOWNGRADE:
  Removes the sentinel rows (``DELETE WHERE is_system = true``) and drops
  the column.  Safe because B-2 + later writes use these sentinels only
  for net-new extractions; pre-existing data is unaffected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str = "0043"
branch_labels = None
depends_on = None


# ── Sentinel entity IDs ───────────────────────────────────────────────────────
# Hand-picked UUIDv7-shaped values in the reserved 11111111-0004-7000-8xxx
# range.  These are stable across deployments so application code can
# import them without first querying.
_SENTINELS: list[tuple[str, str, str]] = [
    # (entity_id, canonical_name, entity_type)
    (
        "11111111-0004-7000-8000-000000000001",
        "Macro Sentinel",
        "macro_indicator",
    ),
    (
        "11111111-0004-7000-8000-000000000002",
        "Unknown Person",
        "person",
    ),
    (
        "11111111-0004-7000-8000-000000000003",
        "Unknown Organization",
        # F-LIVE-002 (Phase 5c, 2026-05-24): CHECK constraint
        # ``ck_canonical_entities_entity_type`` allows only 11 enum values
        # (financial_instrument, person, event, sector, industry,
        # macro_indicator, place, product, index, currency, unknown).
        # The original choice "organization" is not in the enum and caused
        # migration 0044 to fail at first INSERT, blocking 0045-0048 from
        # ever applying. Using "unknown" — the catch-all — matches the
        # semantic intent ("we don't know what kind of organization") and
        # satisfies the constraint.
        "unknown",
    ),
    (
        "11111111-0004-7000-8000-000000000004",
        "Unknown Place",
        "place",
    ),
    (
        "11111111-0004-7000-8000-000000000005",
        "Unknown Product",
        "product",
    ),
]


def upgrade() -> None:
    """Add ``is_system`` column + seed five sentinel rows."""

    # ── Step 1: add is_system column ──────────────────────────────────────────
    # Guard against re-runs from partial earlier deploys.  Idempotent.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'canonical_entities'
                   AND column_name = 'is_system'
            ) THEN
                ALTER TABLE canonical_entities
                    ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT false;
            END IF;
        END$$;
        """
    )

    # Partial index so the sentinel CHECK constraint (added in B-2 0045) and
    # downstream filters can be served cheaply.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_is_system ON canonical_entities (entity_id) " "WHERE is_system = true"
    )

    # ── Step 2: seed sentinels ────────────────────────────────────────────────
    # ``data_completeness = 1.0`` + ``enriched_at = NOW()`` keep the enrichment
    # sweep from picking these rows up (it filters where data_completeness < 0.5).
    # ``enrichment_attempts`` is bumped to its cap (3) for the same reason; the
    # sweep also skips rows with attempts ≥ 3.
    for entity_id, name, entity_type in _SENTINELS:
        op.execute(
            sa.text(
                """
                INSERT INTO canonical_entities (
                    entity_id, canonical_name, entity_type, ticker, exchange,
                    description, data_completeness, enriched_at, enrichment_attempts,
                    is_system, created_at, updated_at
                ) VALUES (
                    :entity_id, :name, :entity_type, NULL, NULL,
                    'System placeholder used when extraction cannot resolve a real entity',
                    1.0, NOW(), 3,
                    true, NOW(), NOW()
                )
                ON CONFLICT (entity_id) DO UPDATE SET
                    is_system = true,
                    canonical_name = EXCLUDED.canonical_name,
                    entity_type = EXCLUDED.entity_type
                """
            ).bindparams(entity_id=entity_id, name=name, entity_type=entity_type)
        )


def downgrade() -> None:
    """Remove sentinels + drop the column."""
    # Delete sentinels first so the column drop doesn't fail under any FK.
    op.execute("DELETE FROM canonical_entities WHERE is_system = true")
    op.execute("DROP INDEX IF EXISTS idx_entities_is_system")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'canonical_entities'
                   AND column_name = 'is_system'
            ) THEN
                ALTER TABLE canonical_entities DROP COLUMN is_system;
            END IF;
        END$$;
        """
    )
