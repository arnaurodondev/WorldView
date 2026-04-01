"""Initial schema for the market-ingestion service.

Revision ID: 0001
Revises: (none)
Create Date: 2026-03-12

Tables:
  ingestion_tasks, ingestion_watermarks, polling_policies,
  provider_budgets, outbox_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- ingestion_tasks -------------------------------------------------------
    op.create_table(
        "ingestion_tasks",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("dataset_type", sa.String(50), nullable=False),
        sa.Column("dataset_variant", sa.String(100), nullable=True),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=True),
        sa.Column("timeframe", sa.String(10), nullable=True),
        sa.Column("range_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("range_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_by", sa.String(100), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedupe_key", sa.String(500), nullable=False),
        sa.Column("is_backfill", sa.Boolean(), nullable=False),
        sa.Column("result_ref_bucket", sa.Text(), nullable=True),
        sa.Column("result_ref_key", sa.Text(), nullable=True),
        sa.Column("result_ref_sha256", sa.Text(), nullable=True),
        sa.Column("result_ref_mime_type", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingestion_tasks_claimable",
        "ingestion_tasks",
        ["status", "locked_until", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "uq_ingestion_tasks_dedupe_key",
        "ingestion_tasks",
        ["provider", "dedupe_key"],
        unique=True,
    )
    op.create_index("ix_ingestion_tasks_status", "ingestion_tasks", ["status"])
    op.create_index("ix_ingestion_tasks_symbol", "ingestion_tasks", ["symbol"])
    op.create_index("ix_ingestion_tasks_provider_status", "ingestion_tasks", ["provider", "status"])
    op.create_index(
        "ix_ingestion_tasks_active_check",
        "ingestion_tasks",
        ["provider", "dataset_type", "symbol", "exchange", "timeframe", "dataset_variant", "status"],
    )

    # -- ingestion_watermarks --------------------------------------------------
    op.create_table(
        "ingestion_watermarks",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("dataset_type", sa.String(50), nullable=False),
        sa.Column("dataset_variant", sa.String(100), nullable=True),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=True),
        sa.Column("timeframe", sa.String(10), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_bar_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_sha256", sa.String(64), nullable=True),
        sa.Column("backfill_phase", sa.String(20), nullable=False),
        sa.Column("backfill_until_date", sa.Date(), nullable=True),
        sa.Column("current_backfill_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            """
        CREATE UNIQUE INDEX uq_ingestion_watermarks_natural_key
        ON ingestion_watermarks (
            provider, dataset_type, dataset_variant, symbol, exchange, timeframe
        ) NULLS NOT DISTINCT
    """
        )
    )
    op.create_index("ix_ingestion_watermarks_provider", "ingestion_watermarks", ["provider"])
    op.create_index(
        "ix_ingestion_watermarks_provider_dataset_type",
        "ingestion_watermarks",
        ["provider", "dataset_type"],
    )
    op.create_index("ix_ingestion_watermarks_symbol", "ingestion_watermarks", ["symbol"])

    # -- polling_policies ------------------------------------------------------
    op.create_table(
        "polling_policies",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("dataset_type", sa.String(50), nullable=False),
        sa.Column("dataset_variant", sa.String(100), nullable=True),
        sa.Column("symbol", sa.String(50), nullable=True),
        sa.Column("exchange", sa.String(20), nullable=True),
        sa.Column("timeframe", sa.String(10), nullable=True),
        sa.Column("base_interval_sec", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("min_interval_sec", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("jitter_sec", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("adaptive_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("adaptive_k", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("adaptive_half_life_sec", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("backfill_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("backfill_start_date", sa.Date(), nullable=True),
        sa.Column("backfill_chunk_days", sa.Integer(), nullable=True, server_default="30"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_polling_policies_enabled",
        "polling_policies",
        ["enabled"],
        postgresql_where=sa.text("enabled = true"),
    )
    op.create_index(
        "ix_polling_policies_matching",
        "polling_policies",
        ["provider", "dataset_type", "dataset_variant", "symbol", "exchange", "timeframe"],
    )
    op.create_index("ix_polling_policies_priority", "polling_policies", ["priority"])

    # -- provider_budgets ------------------------------------------------------
    op.create_table(
        "provider_budgets",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("current_tokens", sa.Float(), nullable=False, server_default="1000.0"),
        sa.Column("refill_rate_per_second", sa.Float(), nullable=False, server_default="10.0"),
        sa.Column("last_refill_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", name="uq_provider_budgets_provider"),
    )
    op.create_index("ix_provider_budgets_provider", "provider_budgets", ["provider"])

    # -- outbox_events ---------------------------------------------------------
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("correlation_id", sa.String(120), nullable=True),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("key", sa.LargeBinary(), nullable=True),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_by", sa.String(120), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outbox_events_claimable",
        "outbox_events",
        ["status", "locked_until", "next_attempt_at", "created_at"],
    )
    op.create_index("ix_outbox_events_retry", "outbox_events", ["status", "next_attempt_at"])
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_created_at", "outbox_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("provider_budgets")
    op.drop_table("polling_policies")
    op.drop_table("ingestion_watermarks")
    op.drop_table("ingestion_tasks")
