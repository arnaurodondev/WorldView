"""Add screen_field_metadata table.

Revision ID: 004
Revises: 003
Create Date: 2026-04-07

Introduces the ``screen_field_metadata`` table used by the Screener feature
(PRD-0017 §6.4).  Stores metadata for each screenable fundamental metric:
display label, unit, field type, observed min/max, and null fraction.

One row per distinct metric name (~50 rows; static set seeded by the
``ScreenFieldsMetadataUseCase`` background job introduced in Wave B-2).

No downgrade data-loss risk — the table is a derived metadata cache.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screen_field_metadata",
        sa.Column("field_name", sa.Text, primary_key=True),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column(
            "field_type",
            sa.Text,
            nullable=False,
            server_default="numeric",
        ),
        sa.Column("unit", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("observed_min", sa.Numeric, nullable=True),
        sa.Column("observed_max", sa.Numeric, nullable=True),
        sa.Column(
            "null_fraction",
            sa.Numeric,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "field_type IN ('numeric', 'text')",
            name="ck_screen_field_metadata_field_type",
        ),
        sa.CheckConstraint(
            "null_fraction >= 0 AND null_fraction <= 1",
            name="ck_screen_field_metadata_null_fraction",
        ),
    )


def downgrade() -> None:
    op.drop_table("screen_field_metadata")
