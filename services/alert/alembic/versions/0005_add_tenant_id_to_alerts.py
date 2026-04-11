"""Add nullable tenant_id to alerts table

Revision ID: 0005
Revises: d4e5f6a7b8c9
Create Date: 2026-04-11

Changes:
- alerts: add tenant_id UUID NULL (forward-compat for multi-tenant isolation, PLAN-0025)
- Add partial index idx_alerts_tenant on tenant_id WHERE tenant_id IS NOT NULL
"""

from alembic import op

revision = "0005"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add nullable tenant_id column — zero-downtime safe; existing rows receive NULL.
    # No server_default needed: NULL is the correct value until auth (PLAN-0025) wires it.
    op.execute("ALTER TABLE alerts ADD COLUMN tenant_id UUID NULL")
    op.execute("CREATE INDEX idx_alerts_tenant ON alerts (tenant_id) WHERE tenant_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alerts_tenant")
    op.execute("ALTER TABLE alerts DROP COLUMN tenant_id")
