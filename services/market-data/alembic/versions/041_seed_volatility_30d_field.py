"""Seed the ``volatility_30d`` computed-metric field into ``screen_field_metadata``.

Revision ID: 041
Revises: 040
Create Date: 2026-06-18

PLAN-0089 L-3 ops follow-up (audit 2026-06-16-prd0089-l3-computed-metrics-ops:
the runbook + plan claimed "8 metrics" but the worker only emitted 7 — this
seeds the 8th screenable computed metric, ``volatility_30d``, now that the
worker computes it).

WHY THIS MIGRATION EXISTS (same rationale as 029):
  ``screen_field_metadata`` rows are owned by the application bootstrap
  (``app.py::_screen_fields_refresh_loop``), which re-upserts every 6 hours from
  ``_get_static_screen_fields()``. Fresh deployments must serve
  ``GET /fundamentals/screen/fields`` correctly on first boot, before the first
  refresh tick — so the row is also seeded here.

LOCK-STEP REQUIREMENT (CRITICAL):
  The row below MUST be byte-identical to the ``volatility_30d`` entry appended
  to ``_get_static_screen_fields()`` in app.py. Divergence makes the 6-hour
  refresh loop silently overwrite this seed with different values, breaking the
  frontend label/unit rendering. Enforced by
  ``tests/unit/test_l3_volatility_lockstep.py``.

CHECK constraint: ``field_type='numeric'`` (admitted by
``ck_screen_field_metadata_field_type``). ``unit='percent_1'`` — annualised vol
is a fraction (0.35 = 35%), rendered as percent by the frontend (x100), same
convention as the return metrics.

FORWARD-COMPAT (R11): additive single-row INSERT, ``ON CONFLICT DO NOTHING``
(idempotent). No column removed/renamed.

DOWNGRADE: delete the single seeded row by primary key.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


# (field_name, label, field_type, unit, description) — mirrors the app.py entry.
_VOLATILITY_FIELD = (
    "volatility_30d",
    "VOL 30D",
    "numeric",
    "percent_1",
    "Annualised realised volatility over the trailing 30 trading days (a fraction)",
)


def upgrade() -> None:
    """Insert the volatility_30d row; no-op on conflict (idempotent)."""
    field_name, label, field_type, unit, description = _VOLATILITY_FIELD
    op.execute(
        sa.text(
            "INSERT INTO screen_field_metadata "
            "(field_name, label, field_type, unit, description, null_fraction) "
            "VALUES (:field_name, :label, :field_type, :unit, :description, 0) "
            "ON CONFLICT (field_name) DO NOTHING"
        ).bindparams(
            field_name=field_name,
            label=label,
            field_type=field_type,
            unit=unit,
            description=description,
        )
    )


def downgrade() -> None:
    """Delete the volatility_30d row by primary key."""
    op.execute(
        sa.text("DELETE FROM screen_field_metadata WHERE field_name = :field_name").bindparams(
            field_name=_VOLATILITY_FIELD[0]
        )
    )
