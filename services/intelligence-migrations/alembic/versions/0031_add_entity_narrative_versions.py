"""Add ``entity_narrative_versions`` table and canonical_entities narrative pointer.

Revision ID: 0031
Revises: 0030
Create Date: 2026-05-08

WHY (T-A-01 — PRD-0074 §8.1, §8.2):
  The intelligence layer needs to store versioned LLM-generated narratives for
  each canonical entity.  Each version captures:
    - the full narrative text (50-10,000 chars),
    - which model generated it,
    - why it was generated (INITIAL, PERIODIC_REFRESH, etc.),
    - an input_snapshot JSONB fingerprint for idempotency,
    - a quality_score (0-1) from LLM self-evaluation, and
    - an ``is_current`` flag so callers can always retrieve the latest version
      with a simple ``WHERE is_current = TRUE`` predicate.

  A partial UNIQUE index on ``(entity_id) WHERE is_current = TRUE`` enforces
  the invariant that at most one version is current per entity at the DB level.

  ``canonical_entities`` gains two new nullable columns:
    - ``current_narrative_version_id`` -- FK back to the most recent version
      (ON DELETE SET NULL keeps the entity even if all its narratives are purged);
    - ``health_score`` -- a 0-1 composite score computed by NarrativeGenerationWorker
      and displayed in the entity header of the intelligence page.

FORWARD-COMPATIBILITY (R5):
  All new columns are nullable or have safe defaults.  Existing rows in
  ``canonical_entities`` are unchanged (both new columns default to NULL).

BACKWARD-COMPATIBILITY:
  ``downgrade()`` drops the FK columns from ``canonical_entities`` first (to
  release the FK constraint), then drops the table.

DOWNGRADE:
  Drops ``current_narrative_version_id`` and ``health_score`` from
  ``canonical_entities``, then drops ``entity_narrative_versions`` CASCADE.
"""

from __future__ import annotations

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Create entity_narrative_versions table
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE entity_narrative_versions (
    version_id         UUID        NOT NULL DEFAULT new_uuid7(),
    entity_id          UUID        NOT NULL,
    tenant_id          UUID,
    narrative_text     TEXT        NOT NULL
        CONSTRAINT chk_narrative_text_length
            CHECK (length(narrative_text) BETWEEN 50 AND 10000),
    model_id           TEXT        NOT NULL,
    generation_reason  TEXT        NOT NULL
        CONSTRAINT chk_narrative_generation_reason
            CHECK (generation_reason IN (
                'INITIAL',
                'PERIODIC_REFRESH',
                'DATA_UPDATE',
                'EVIDENCE_SURGE',
                'MANUAL_TRIGGER'
            )),
    input_snapshot     JSONB,
    generated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_current         BOOLEAN     NOT NULL DEFAULT FALSE,
    word_count         INT,
    quality_score      FLOAT,
    PRIMARY KEY (version_id),
    CONSTRAINT fk_entity_narrative_entity
        FOREIGN KEY (entity_id)
        REFERENCES canonical_entities (entity_id)
        ON DELETE CASCADE
)
""")

    # Partial unique index: at most 1 current version per entity.
    # CREATE INDEX CONCURRENTLY requires autocommit mode outside a transaction.
    with op.get_context().autocommit_block():
        op.execute("""
CREATE UNIQUE INDEX CONCURRENTLY uq_entity_narrative_current
    ON entity_narrative_versions (entity_id)
    WHERE is_current = TRUE
""")

    # Version history index: supports paginated history queries.
    with op.get_context().autocommit_block():
        op.execute("""
CREATE INDEX CONCURRENTLY idx_entity_narrative_history
    ON entity_narrative_versions (entity_id, generated_at DESC)
""")

    # -------------------------------------------------------------------------
    # 2. Add canonical_entities.current_narrative_version_id + health_score
    # -------------------------------------------------------------------------
    # Both are nullable — BP-126 does not apply (no NOT NULL without default).
    op.execute("""
ALTER TABLE canonical_entities
    ADD COLUMN IF NOT EXISTS current_narrative_version_id UUID
        REFERENCES entity_narrative_versions (version_id)
        ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS health_score FLOAT
        CONSTRAINT chk_canonical_health_score
            CHECK (health_score BETWEEN 0.0 AND 1.0)
""")


def downgrade() -> None:
    # Must drop FK columns from canonical_entities first to release the FK
    # constraint before dropping the referenced table.
    op.execute("""
ALTER TABLE canonical_entities
    DROP COLUMN IF EXISTS current_narrative_version_id,
    DROP COLUMN IF EXISTS health_score
""")
    op.execute("DROP TABLE IF EXISTS entity_narrative_versions CASCADE")
