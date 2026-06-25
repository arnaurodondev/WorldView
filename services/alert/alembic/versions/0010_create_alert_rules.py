"""Create alert_rules table (PLAN-0113 — standing user rules engine).

Adds the ``alert_rules`` table that backs the 5 user-creatable rule types
(PRICE_CROSS, NEWS_COUNT, NEWS_MOMENTUM, KG_CONNECTION, FUNDAMENTAL_CROSS).

Design:
  - ``rule_type`` + ``severity`` are VARCHAR + CHECK (BP-007) — never PG enums,
    so future rule types / severities add zero DDL.
  - The keying CHECK mirrors the domain invariant: KG_CONNECTION needs two
    distinct non-null nodes; every other type needs ``entity_id``.
  - ``last_state`` JSONB is the edge-trigger memory (nullable: a fresh rule has
    no state yet).
  - Partial indexes (``WHERE enabled``) keep the poller scan + event pre-filter
    cheap; a plain ``(tenant_id, user_id)`` index backs CRUD list.

Additive migration — downgrade simply drops the table (no data migration).
"""

from __future__ import annotations

from alembic import op

# revision identifiers
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE alert_rules (
        rule_id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id         UUID         NOT NULL,
        user_id           UUID         NOT NULL,
        rule_type         VARCHAR(50)  NOT NULL,
        name              VARCHAR(255) NOT NULL,
        entity_id         UUID,
        node_a_entity_id  UUID,
        node_b_entity_id  UUID,
        condition         JSONB        NOT NULL,
        severity          VARCHAR(10)  NOT NULL DEFAULT 'medium',
        enabled           BOOLEAN      NOT NULL DEFAULT TRUE,
        cooldown_seconds  INTEGER      NOT NULL DEFAULT 0,
        notify_in_app     BOOLEAN      NOT NULL DEFAULT TRUE,
        notify_email      BOOLEAN      NOT NULL DEFAULT FALSE,
        last_state        JSONB,
        created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ck_alert_rules_rule_type CHECK (
            rule_type IN ('PRICE_CROSS','NEWS_COUNT','NEWS_MOMENTUM','KG_CONNECTION','FUNDAMENTAL_CROSS')
        ),
        CONSTRAINT ck_alert_rules_severity CHECK (
            severity IN ('low','medium','high','critical')
        ),
        CONSTRAINT ck_alert_rules_cooldown CHECK (cooldown_seconds >= 0),
        CONSTRAINT ck_alert_rules_keying CHECK (
            (rule_type = 'KG_CONNECTION'
                AND node_a_entity_id IS NOT NULL
                AND node_b_entity_id IS NOT NULL
                AND node_a_entity_id <> node_b_entity_id)
            OR
            (rule_type <> 'KG_CONNECTION' AND entity_id IS NOT NULL)
        )
    )
    """)
    op.execute("CREATE INDEX idx_alert_rules_type_enabled ON alert_rules (rule_type) WHERE enabled")
    op.execute("CREATE INDEX idx_alert_rules_entity_enabled ON alert_rules (entity_id) WHERE enabled")
    op.execute(
        "CREATE INDEX idx_alert_rules_nodes_enabled "
        "ON alert_rules (node_a_entity_id, node_b_entity_id) WHERE enabled"
    )
    op.execute("CREATE INDEX idx_alert_rules_owner ON alert_rules (tenant_id, user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alert_rules")
