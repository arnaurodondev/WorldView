"""Add mutation idempotency_key columns + partial unique indexes.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-19

REQ-002 / TASK-W0-02..05: persist the caller-supplied ``Idempotency-Key``
header on three mutation endpoints so safe retries from the frontend never
create duplicate rows.

Tables touched:
  * ``portfolios``            — REQ-002a (POST /v1/portfolios)
  * ``watchlist_members``     — REQ-002b (POST /v1/watchlists/{id}/members)
  * ``feedback_submissions``  — REQ-002d (POST /v1/feedback/submissions)

REQ-002c (brokerage-connections/{id}/sync) is handled entirely in Valkey
because the worker is already DB-level idempotent — no schema change there.

For each table:
  1. Add nullable ``idempotency_key UUID`` (default NULL keeps existing rows
     valid; the existing non-idempotent call-path stays unchanged for clients
     that don't send the header).
  2. Create a PARTIAL UNIQUE INDEX on ``(tenant_id, idempotency_key)`` WHERE
     ``idempotency_key IS NOT NULL``. Postgres partial unique index syntax
     is the standard way to enforce "unique when present" without forcing a
     value on legacy rows. Watchlist members don't carry tenant_id directly
     so we scope by watchlist_id instead — caller's tenant is bound by the
     watchlist row.

Forward-compat (R5/R11):
  Adding a nullable column with no default is forward-compatible — old code
  ignores the column entirely; the partial unique index only fires when a
  non-NULL value is provided.

Rollback:
  ``downgrade()`` drops the three indexes then the columns. Safe because the
  column is nullable and unindexed in downgrade order.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ── portfolios ────────────────────────────────────────────────────────────
    op.add_column(
        "portfolios",
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Partial unique index — only enforces uniqueness on non-NULL keys so existing
    # rows (and any future row created without a header) remain valid.
    op.create_index(
        "uq_portfolios_tenant_idempotency_key",
        "portfolios",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # ── watchlist_members ────────────────────────────────────────────────────
    op.add_column(
        "watchlist_members",
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Scope by watchlist_id — each watchlist row already binds the tenant, so
    # using ``(watchlist_id, idempotency_key)`` keeps the index narrow without
    # joining tenants in.
    op.create_index(
        "uq_watchlist_members_watchlist_idempotency_key",
        "watchlist_members",
        ["watchlist_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # ── feedback_submissions ──────────────────────────────────────────────────
    op.add_column(
        "feedback_submissions",
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "uq_feedback_submissions_tenant_idempotency_key",
        "feedback_submissions",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_feedback_submissions_tenant_idempotency_key",
        table_name="feedback_submissions",
    )
    op.drop_column("feedback_submissions", "idempotency_key")

    op.drop_index(
        "uq_watchlist_members_watchlist_idempotency_key",
        table_name="watchlist_members",
    )
    op.drop_column("watchlist_members", "idempotency_key")

    op.drop_index(
        "uq_portfolios_tenant_idempotency_key",
        table_name="portfolios",
    )
    op.drop_column("portfolios", "idempotency_key")
