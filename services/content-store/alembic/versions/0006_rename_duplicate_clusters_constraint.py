"""Rename duplicate_clusters unique constraint to match ORM model name.

Migration 0002 created the duplicate_clusters table with raw SQL:
    UNIQUE (primary_doc_id, duplicate_doc_id)
which PostgreSQL auto-named as
    ``duplicate_clusters_primary_doc_id_duplicate_doc_id_key``.

The ORM model (DuplicateClusterModel) and the DuplicateClusterRepository both
reference the constraint as ``uq_duplicate_clusters_pair``.  This mismatch caused
every ``INSERT ... ON CONFLICT ON CONSTRAINT uq_duplicate_clusters_pair DO NOTHING``
to raise ``UndefinedObjectError``, which then left the SQLAlchemy session in a
broken state outside the asyncio greenlet, producing cascading ``MissingGreenlet``
errors and blocking offset commits on 11/12 partitions (BP-442).

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-10
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename the auto-generated constraint name to the canonical ORM name.
    # The DO block is idempotent: it only renames if the old name exists.
    # On fresh volumes where 0002 already uses the explicit name (future), this
    # is a no-op and the migration still succeeds.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'duplicate_clusters_primary_doc_id_duplicate_doc_id_key'
                  AND conrelid = 'duplicate_clusters'::regclass
            ) THEN
                ALTER TABLE duplicate_clusters
                    RENAME CONSTRAINT "duplicate_clusters_primary_doc_id_duplicate_doc_id_key"
                    TO "uq_duplicate_clusters_pair";
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
                WHERE conname = 'uq_duplicate_clusters_pair'
                  AND conrelid = 'duplicate_clusters'::regclass
            ) THEN
                ALTER TABLE duplicate_clusters
                    RENAME CONSTRAINT "uq_duplicate_clusters_pair"
                    TO "duplicate_clusters_primary_doc_id_duplicate_doc_id_key";
            END IF;
        END
        $$;
    """)
