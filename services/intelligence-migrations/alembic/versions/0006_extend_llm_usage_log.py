"""Extend llm_usage_log with service_name, tenant_id, error_code (PLAN-0033 T-B-1-04).

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-22

Adds three columns to the existing ``llm_usage_log`` table in intelligence_db
(owned by the knowledge-graph service S7):

  service_name  VARCHAR(50) NOT NULL DEFAULT 'knowledge-graph'
                Allows future multi-service sharing of intelligence_db; enables
                filtering in the /internal/v1/llm-costs endpoint.

  tenant_id     UUID nullable
                For future multi-tenant isolation; NULL = system-level call.

  error_code    VARCHAR(50) nullable
                Short error classification (timeout | rate_limit | auth | model_error)
                when success=false.  NULL means success=true or unknown error.

Existing rows receive the server_default values automatically — no data migration needed.

BP-126 compliance: service_name is NOT NULL with server_default; others are nullable.
Downtime: zero — additive columns with defaults.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Allows S7 to identify its rows when intelligence_db is potentially shared
    op.add_column(
        "llm_usage_log",
        sa.Column(
            "service_name",
            sa.String(50),
            nullable=False,
            server_default="knowledge-graph",
        ),
    )
    # Multi-tenant: NULL = system/background task, UUID = specific tenant
    op.add_column(
        "llm_usage_log",
        sa.Column("tenant_id", sa.UUID(), nullable=True),
    )
    # Error classification for failed calls; NULL on success
    op.add_column(
        "llm_usage_log",
        sa.Column("error_code", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_usage_log", "error_code")
    op.drop_column("llm_usage_log", "tenant_id")
    op.drop_column("llm_usage_log", "service_name")
