"""Enhance events table and add sector/industry relation types.

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-04-05

Changes (all backward-compatible — nullable columns, new registry rows):
- events: ADD COLUMN event_subtype VARCHAR(50) NULL
- events: ADD COLUMN source_type VARCHAR(50) NULL
- events: ADD COLUMN structured_data JSONB NULL
- events: CREATE INDEX ix_events_entity_type_date (subject_entity_id, event_type, event_subtype, event_date DESC)
- relation_type_registry: INSERT 4 new rows (is_in_sector, is_in_industry, earnings_released, corporate_action)
"""

from alembic import op

revision = "b2c3d4e5f6a1"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Add structured enrichment columns to the events table.
    # events is RANGE-partitioned; ALTER TABLE propagates to all partitions.
    # -------------------------------------------------------------------------
    op.execute("ALTER TABLE events ADD COLUMN event_subtype VARCHAR(50) NULL")
    op.execute("ALTER TABLE events ADD COLUMN source_type   VARCHAR(50) NULL")
    op.execute("ALTER TABLE events ADD COLUMN structured_data JSONB NULL")

    # Composite index supports the pattern used by EventSearchUseCase (Wave C-2):
    # WHERE subject_entity_id = ? AND event_type = ANY(?) ORDER BY event_date DESC
    # Creating on the parent table; Postgres 12+ propagates to partition children.
    op.execute("""
CREATE INDEX ix_events_entity_type_date
    ON events (subject_entity_id, event_type, event_subtype, event_date DESC)
""")

    # -------------------------------------------------------------------------
    # Seed 4 new relation types required by S8 graph retrieval (Wave C-3/C-4).
    # ON CONFLICT DO NOTHING makes this idempotent in case of re-run.
    # -------------------------------------------------------------------------
    op.execute("""
INSERT INTO relation_type_registry
    (canonical_type, semantic_mode, decay_class, base_confidence, description)
VALUES
    ('is_in_sector',      'RELATION_STATE',  'PERMANENT', 0.90, 'GICS sector membership from EODHD'),
    ('is_in_industry',    'RELATION_STATE',  'DURABLE',   0.85, 'GICS industry group from EODHD'),
    ('earnings_released', 'TEMPORAL_CLAIM',  'FAST',      0.95, 'Quarterly/annual earnings event'),
    ('corporate_action',  'TEMPORAL_CLAIM',  'DURABLE',   0.90, 'Dividend, split, buyback events')
ON CONFLICT (canonical_type) DO NOTHING
""")


def downgrade() -> None:
    # Remove registry rows first (no FK dependencies to worry about)
    op.execute("""
DELETE FROM relation_type_registry
    WHERE canonical_type IN ('is_in_sector', 'is_in_industry', 'earnings_released', 'corporate_action')
""")

    # Drop index before dropping the columns it references
    op.execute("DROP INDEX IF EXISTS ix_events_entity_type_date")

    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS structured_data")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS source_type")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS event_subtype")
