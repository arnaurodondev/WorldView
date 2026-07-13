"""Widen ck_alert_rules_rule_type to include 'PREDICTION' (PLAN-0056 Wave D3).

Adds the user-configurable ``PREDICTION`` standing-rule type. ``rule_type`` is
VARCHAR + CHECK (BP-007 — never a PG enum), so this is a pure CHECK swap: drop
the old constraint, recreate it with the extra allowed value.

No change is needed for ``alerts.alert_type`` — that column is VARCHAR(100) with
NO CHECK constraint, so the new ``AlertType.PREDICTION`` value ('prediction')
persists without DDL (BP-007).

Additive + reversible: downgrade restores the pre-D3 5-value CHECK. Any
PREDICTION rows would violate the narrower constraint on downgrade, so we delete
them first (there are none in a fresh D3 deploy; this keeps the downgrade safe
and idempotent).
"""

from __future__ import annotations

from alembic import op

# revision identifiers
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_OLD_TYPES = "'PRICE_CROSS','NEWS_COUNT','NEWS_MOMENTUM','KG_CONNECTION','FUNDAMENTAL_CROSS'"
_NEW_TYPES = _OLD_TYPES + ",'PREDICTION'"


def upgrade() -> None:
    op.execute("ALTER TABLE alert_rules DROP CONSTRAINT IF EXISTS ck_alert_rules_rule_type")
    op.execute(
        f"ALTER TABLE alert_rules ADD CONSTRAINT ck_alert_rules_rule_type " f"CHECK (rule_type IN ({_NEW_TYPES}))"
    )


def downgrade() -> None:
    # Remove any PREDICTION rules so the narrower CHECK can be re-applied.
    op.execute("DELETE FROM alert_rules WHERE rule_type = 'PREDICTION'")
    op.execute("ALTER TABLE alert_rules DROP CONSTRAINT IF EXISTS ck_alert_rules_rule_type")
    op.execute(
        f"ALTER TABLE alert_rules ADD CONSTRAINT ck_alert_rules_rule_type " f"CHECK (rule_type IN ({_OLD_TYPES}))"
    )
