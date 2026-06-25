"""Add learned-router shadow columns to routing_decisions.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-12

PLAN-0111 Wave C-6 — the learned routing classifier runs in SHADOW mode: on every
article it computes a *proposed* tier + calibrated P(yield) that we persist
alongside the existing static-router decision so we can analyse agreement before
any LIVE flip. This migration adds three nullable, additive columns:

  * ``learned_tier``        TEXT             — the proposed RoutingTier value
                                               (deep|medium|light), NULL when the
                                               learned router was off or failed.
  * ``learned_p_yield``     DOUBLE PRECISION — the calibrated P(yield) [0,1].
  * ``learned_router_mode`` TEXT             — the mode that produced the row
                                               ("off"|"shadow"|"live"), for audit.

All three are NULLABLE and purely additive — forward-compatible (BP-126), no
table rewrite, safe to roll back. The static-router columns are untouched, so
existing reads and the routing path are unaffected. Note the learned tier never
takes the value 'suppress' (the classifier does not predict SUPPRESS), but the
CHECK allows the full enum for forward-compatibility with a future LIVE mode.
"""

from __future__ import annotations

from alembic import op

revision: str = "0021"
down_revision: str = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All ADD COLUMN IF NOT EXISTS — idempotent against drifted volumes.
    op.execute("ALTER TABLE routing_decisions ADD COLUMN IF NOT EXISTS learned_tier TEXT")
    op.execute("ALTER TABLE routing_decisions ADD COLUMN IF NOT EXISTS learned_p_yield DOUBLE PRECISION")
    op.execute("ALTER TABLE routing_decisions ADD COLUMN IF NOT EXISTS learned_router_mode TEXT")

    # Constrain learned_tier to the RoutingTier enum values (lower-case StrEnum).
    op.execute("ALTER TABLE routing_decisions DROP CONSTRAINT IF EXISTS routing_decisions_learned_tier_chk")
    op.execute(
        "ALTER TABLE routing_decisions "
        "ADD CONSTRAINT routing_decisions_learned_tier_chk "
        "CHECK (learned_tier IS NULL OR learned_tier IN "
        "('deep','medium','light','suppress'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE routing_decisions DROP CONSTRAINT IF EXISTS routing_decisions_learned_tier_chk")
    op.execute("ALTER TABLE routing_decisions DROP COLUMN IF EXISTS learned_router_mode")
    op.execute("ALTER TABLE routing_decisions DROP COLUMN IF EXISTS learned_p_yield")
    op.execute("ALTER TABLE routing_decisions DROP COLUMN IF EXISTS learned_tier")
