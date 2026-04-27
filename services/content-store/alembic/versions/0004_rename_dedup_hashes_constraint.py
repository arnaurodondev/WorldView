"""Rename dedup_hashes unique constraint to match ORM model name.

Migration 0002 created the dedup_hashes table with raw SQL:
    UNIQUE (hash_type, hash_value)
which PostgreSQL auto-named as ``dedup_hashes_hash_type_hash_value_key``.

The ORM model (DedupHashModel) and the DedupHashRepository both reference
the constraint as ``uq_dedup_hashes_type_value``.  This mismatch caused every
``INSERT ... ON CONFLICT ON CONSTRAINT uq_dedup_hashes_type_value DO NOTHING``
to raise ``UndefinedObjectError``, blocking all article storage (BP-230).

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename the auto-generated constraint name to the canonical ORM model name.
    # Safe to run on existing volumes (constraint exists) and on fresh volumes if
    # migration 0002 has been updated to use the explicit name (op is idempotent-ish;
    # it will error on fresh installs if the old name no longer exists — addressed by
    # the conditional guard below).
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'dedup_hashes_hash_type_hash_value_key'
                  AND conrelid = 'dedup_hashes'::regclass
            ) THEN
                ALTER TABLE dedup_hashes
                    RENAME CONSTRAINT "dedup_hashes_hash_type_hash_value_key"
                    TO "uq_dedup_hashes_type_value";
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_dedup_hashes_type_value'
                  AND conrelid = 'dedup_hashes'::regclass
            ) THEN
                ALTER TABLE dedup_hashes
                    RENAME CONSTRAINT "uq_dedup_hashes_type_value"
                    TO "dedup_hashes_hash_type_hash_value_key";
            END IF;
        END
        $$;
    """)
