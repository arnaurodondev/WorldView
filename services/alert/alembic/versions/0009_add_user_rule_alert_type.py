"""Add USER_RULE alert type (PLAN-0082 Wave B).

Because ``alert_type`` is stored as VARCHAR(100) — NOT a PostgreSQL enum —
no DDL change is required to accept the new ``"user_rule"`` value.  This
migration is a no-op schema change that documents the domain extension and
updates the check constraint comment.

WHY NO ALTER TYPE: ``AlertModel.alert_type`` maps to ``String(100)``.  The
PG enum approach was deliberately avoided in the original schema design to
allow forward-compatible value additions without DDL locks (BP-007).

Idempotent: downgrade is a no-op (VARCHAR constraint unchanged).
"""

from __future__ import annotations

from alembic import op

# revision identifiers
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No DDL required — alert_type is VARCHAR(100) so "user_rule" is already
    # a valid value at the storage layer.  We add a table comment to document
    # the extended enum so future engineers can grep this migration for context.
    op.execute(
        "COMMENT ON COLUMN alerts.alert_type IS "
        "'Valid values: SIGNAL | GRAPH_CHANGE | CONTRADICTION | user_rule "
        "(PLAN-0082 Wave B — user-initiated alert rules via LLM tool)'"
    )


def downgrade() -> None:
    # Removing the comment is safe and symmetrical; rows with alert_type=user_rule
    # are NOT deleted on downgrade (data-preservation policy, BP-007).
    op.execute("COMMENT ON COLUMN alerts.alert_type IS " "'Valid values: SIGNAL | GRAPH_CHANGE | CONTRADICTION'")
