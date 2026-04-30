"""Add config_hash generated column + UNIQUE(source_type, config_hash) on sources.

Revision ID: 0006_source_dedup_config_hash
Revises: 0005_add_next_attempt_at_cit
Create Date: 2026-04-30

WHY (PLAN-0055 Sub-Plan B): Sources are currently keyed only on `name`. Operators
who delete + recreate a source (e.g. fix a typo in config) get a brand-new id and
lose all watermark history → silent over-fetch. By adding a generated SHA-256 of
the canonical config and a UNIQUE on (source_type, config_hash), recreating with
identical config is a no-op (idempotent INSERT ON CONFLICT). The `last_run_config_hash`
column on `source_adapter_state` snapshots the hash at the last successful watermark
update so startup can WARN when config has drifted out from under a stale cursor.

Requires the `pgcrypto` extension (already enabled in init-databases.sh:48).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0006_source_dedup_config_hash"
down_revision: str = "0005_add_next_attempt_at_cit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive — pgcrypto is provisioned by init-databases.sh, but a bare DB
    # restored from backup may be missing it. CREATE EXTENSION is idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Generated column: Postgres recomputes on every INSERT/UPDATE of `config`.
    # We never write to it from the ORM (`init=False` on the Mapped column).
    op.execute(
        """
        ALTER TABLE sources
        ADD COLUMN config_hash CHAR(64)
        GENERATED ALWAYS AS (encode(digest(config::text, 'sha256'), 'hex')) STORED
        """
    )
    op.execute(
        "COMMENT ON COLUMN sources.config_hash IS "
        "'Generated SHA-256 of canonical config — drives dedup constraint.'"
    )

    # Dedup constraint. (source_type, config_hash) uniquely identifies a logical source;
    # `name` remains a separate UNIQUE for human-friendly lookup.
    op.create_unique_constraint(
        "uq_sources_dedup",
        "sources",
        ["source_type", "config_hash"],
    )

    # Snapshot of the config_hash at the moment of the last successful fetch.
    # Set by the watermark-update path; compared to `sources.config_hash` at startup
    # to detect drift (operator changed config but cursor still points at old run).
    op.add_column(
        "source_adapter_state",
        sa.Column(
            "last_run_config_hash",
            sa.String(64),
            nullable=True,
            comment="Snapshot of sources.config_hash at last successful fetch — used for drift WARN.",
        ),
    )


def downgrade() -> None:
    op.drop_column("source_adapter_state", "last_run_config_hash")
    op.drop_constraint("uq_sources_dedup", "sources", type_="unique")
    op.execute("ALTER TABLE sources DROP COLUMN IF EXISTS config_hash")
