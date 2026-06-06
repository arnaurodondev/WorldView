"""entity_mentions.tenant_id NOT NULL.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-23

PLAN-0093 Wave B-3 T-B-3-03.

WHY THIS MIGRATION EXISTS:
  Migration 0010 (2026-04-24) added ``tenant_id`` as nullable to ship
  zero-downtime to legacy rows.  Today ~all production rows have NULL
  tenant_id because the article consumer was happily writing without it
  when the Kafka envelope omitted the header (F-DB-010).  That breaks
  every tenant-scoped query (they all fall back to ``IS NULL OR ...``
  which leaks cross-tenant data).

WHAT IT DOES:
  Per the PLAN-0093 "Pre-Prod Simplifications" preamble, TRUNCATE
  ``entity_mentions`` (no data to preserve) and flip ``tenant_id`` to
  NOT NULL.  A tenant-only index is also added for the tenant-scoped
  filters added by PLAN-0086 (multi-tenant pipeline) — the existing
  composite index ``idx_entity_mentions_tenant_entity`` covers
  (tenant_id, resolved_entity_id) but not pure tenant_id range scans.

DOWNGRADE:
  Restores nullable; the supplementary index is dropped.
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str = "0019"
branch_labels = None
depends_on = None


# PLAN-0093 Phase 5 (QA-4 A.4.1) — production TRUNCATE guard.
# Prefer the shared helper at ``alembic/_guards.py``; inline fallback if the
# alembic runtime ``sys.path`` doesn't expose siblings.
try:  # pragma: no cover - import path varies by alembic invocation mode
    from _guards import assert_truncate_allowed  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback path

    def assert_truncate_allowed(table: str) -> None:
        """Inline fallback — see alembic/_guards.py for the canonical version."""
        if (
            os.environ.get("APP_ENV", "").lower() == "production"
            and os.environ.get("ALLOW_DESTRUCTIVE_MIGRATION") != "1"
        ):
            raise RuntimeError(
                f"Refusing to TRUNCATE {table!r} in APP_ENV=production. "
                "Set ALLOW_DESTRUCTIVE_MIGRATION=1 to override (requires SRE sign-off)."
            )


def upgrade() -> None:
    """TRUNCATE legacy rows + flip tenant_id NOT NULL + add tenant-only index."""
    # Production safety guard (PLAN-0093 QA-4 A.4.1) — refuses to truncate
    # in APP_ENV=production unless ALLOW_DESTRUCTIVE_MIGRATION=1.
    assert_truncate_allowed("entity_mentions")

    # CASCADE so child tables (e.g. chunk_entity_mentions if any FK exists)
    # also clear.  Pre-prod data is disposable.
    op.execute("TRUNCATE TABLE entity_mentions CASCADE")

    op.alter_column(
        "entity_mentions",
        "tenant_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    # Tenant-only index — supports the tenant filter on its own (the
    # composite ``idx_entity_mentions_tenant_entity`` from 0010 needs
    # resolved_entity_id to be useful).
    op.execute("CREATE INDEX IF NOT EXISTS ix_entity_mentions_tenant ON entity_mentions (tenant_id)")


def downgrade() -> None:
    """Drop the tenant-only index + restore nullable."""
    op.execute("DROP INDEX IF EXISTS ix_entity_mentions_tenant")
    op.alter_column(
        "entity_mentions",
        "tenant_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
