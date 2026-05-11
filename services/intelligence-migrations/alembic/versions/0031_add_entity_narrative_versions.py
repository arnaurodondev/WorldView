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
  Drops ``new_uuid7()`` Postgres function (introduced here, used by 0032+).

NOTE (BP-420 — new_uuid7 Postgres function):
  Migrations 0031, 0032, and 0036 reference ``new_uuid7()`` as a Postgres
  column DEFAULT.  This function was never registered in the database
  (earlier migrations used ``gen_random_uuid()`` which is built-in).
  This migration creates the function using PL/pgSQL so all subsequent
  migrations that reference it in DDL succeed.

  The implementation produces a standards-compliant UUIDv7 (RFC 9562):
    - Bits 0-47:  Unix epoch milliseconds (big-endian)
    - Bits 48-51: version nibble = 0x7
    - Bits 52-63: random 12-bit sub-millisecond counter
    - Bit 64:     variant high bit = 1
    - Bits 65:    variant second bit = 0
    - Bits 66-127: random 62 bits
"""

from __future__ import annotations

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 0. Register new_uuid7() Postgres function (BP-420 fix).
    #    This function is required by DEFAULT new_uuid7() in this migration and
    #    in 0032 (path_insight_jobs / path_insights) and 0036 (path_templates).
    #    It generates a standards-compliant UUIDv7 (RFC 9562) whose first 48 bits
    #    are the current Unix-epoch millisecond timestamp, making primary keys
    #    time-ordered without a separate created_at index scan.
    # -------------------------------------------------------------------------
    op.execute("""
CREATE OR REPLACE FUNCTION new_uuid7()
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    -- Milliseconds since Unix epoch (48-bit timestamp field).
    ts_ms  BIGINT;
    -- 12 random bits placed in the sub-millisecond counter field (bits 52-63).
    rand_a BIGINT;
    -- 62 random bits for the "rand_b" field (bits 66-127).
    rand_b BIGINT;
    -- The four 16-bit hex groups that form the UUID string.
    part1  TEXT;
    part2  TEXT;
    part3  TEXT;
    part4  TEXT;
    part5  TEXT;
BEGIN
    -- Current Unix timestamp in milliseconds (will fill bits 0-47).
    ts_ms  := EXTRACT(EPOCH FROM clock_timestamp()) * 1000;

    -- 12 random bits for rand_a (sub-millisecond precision / anti-collision).
    rand_a := floor(random() * 4096)::BIGINT;           -- 0x000 - 0xFFF

    -- 62 random bits for rand_b; the top 2 bits are forced to 0b10 (variant).
    rand_b := floor(random() * (2^62)::BIGINT)::BIGINT;

    -- Build each 16-bit group of the canonical UUID format:
    --   xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    --   ^^^^^^^^ bits 0-31  : top 32 bits of the 48-bit ms timestamp
    part1 := lpad(to_hex((ts_ms >> 16) & x'FFFFFFFF'::BIGINT), 8, '0');

    --   ^^^^ bits 32-47 : bottom 16 bits of the ms timestamp
    part2 := lpad(to_hex(ts_ms & x'FFFF'::BIGINT), 4, '0');

    --   ^^^^ bits 48-63 : version nibble (7) + 12-bit rand_a
    part3 := lpad(to_hex((x'7000'::BIGINT | rand_a)), 4, '0');

    --   ^^^^ bits 64-79 : variant bits (10xx xxxx xxxx xxxx) + top 14 bits of rand_b
    --   Force variant = 0b10 by setting bit 63 and clearing bit 62.
    part4 := lpad(to_hex((x'8000'::BIGINT | (rand_b >> 48)) & x'BFFF'::BIGINT | x'8000'::BIGINT), 4, '0');

    --   ^^^^^^^^^^^^ bits 80-127 : bottom 48 bits of rand_b
    part5 := lpad(to_hex(rand_b & x'FFFFFFFFFFFF'::BIGINT), 12, '0');

    RETURN (part1 || '-' || part2 || '-' || part3 || '-' || part4 || '-' || part5)::UUID;
END;
$$
""")

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
    # Drop the new_uuid7() function registered in upgrade().
    # CASCADE ensures any DEFAULT expressions referencing it are cleaned up.
    op.execute("DROP FUNCTION IF EXISTS new_uuid7() CASCADE")
