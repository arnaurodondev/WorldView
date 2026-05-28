"""Seed Wave L-3 computed-metric fields into ``screen_field_metadata`` idempotently.

Revision ID: 029
Revises: 024
Create Date: 2026-05-28

PLAN-0089 Wave L-3 (T-WL3-05).

WHY down_revision="024" (skipping 025-028):
  Migrations 025-028 are reserved/contested in the parallel-session range
  (multiple sibling worktrees may produce migrations in that band). The L-5c
  session used the same skip-pattern; the integrator will linearise the chain
  on merge. The DDL we touch here (INSERT into screen_field_metadata) is
  independent of any change in 025-028, so the skip is safe.

WHY THIS MIGRATION EXISTS (same rationale as 024):
  The application bootstrap (``app.py::_screen_fields_refresh_loop``) owns
  ``screen_field_metadata`` rows and re-upserts every 6 hours from the
  in-memory list in ``_get_static_screen_fields()``. Fresh deployments must
  serve ``GET /fundamentals/screen/fields`` correctly on first boot *before*
  the first refresh tick — without a DB seed the endpoint returns ``{fields:[]}``.

LOCK-STEP REQUIREMENT (CRITICAL):
  The eight rows below MUST be byte-identical to the L-3 block appended to
  ``_get_static_screen_fields()`` in app.py. Divergence causes the 6-hour
  refresh loop to silently overwrite this migration's rows with different
  values, which silently breaks frontend label/unit rendering. See
  ``services/market-data/.claude-context.md`` pitfall L-3.

CHECK constraint:
  ``ck_screen_field_metadata_field_type`` admits only ``'numeric'`` or
  ``'text'``. All eight metrics are ratios → ``field_type='numeric'``,
  ``unit='percent_1'`` (a fractional 0-1 value, rendered as percent by the
  frontend by multiplying by 100 — matches the ``daily_return`` convention).

DOWNGRADE: delete the eight rows by primary key.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "029"
down_revision = "024"
branch_labels = None
depends_on = None


# Canonical list — mirrors ``app.py::_get_static_screen_fields()`` Wave L-3 block.
# Tuple: (field_name, label, field_type, unit, description, category).
# NOTE: ``screen_field_metadata`` does not currently have a category column
# (categories are layered in the frontend mapper), but we keep the value here
# for parity with the spec and audit traceability.
_L3_FIELDS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "dist_from_52w_high_pct",
        "52W%↑",
        "numeric",
        "percent_1",
        "Distance from 52-week high as a fraction (e.g. -0.10 = 10% below)",
    ),
    (
        "dist_from_52w_low_pct",
        "52W%↓",
        "numeric",
        "percent_1",
        "Distance from 52-week low as a fraction (e.g. 0.25 = 25% above)",
    ),
    (
        "return_1m",
        "1M RTN",
        "numeric",
        "percent_1",
        "1-month total return as a fraction",
    ),
    (
        "return_3m",
        "3M RTN",
        "numeric",
        "percent_1",
        "3-month total return as a fraction",
    ),
    (
        "return_6m",
        "6M RTN",
        "numeric",
        "percent_1",
        "6-month total return as a fraction",
    ),
    (
        "return_ytd",
        "YTD RTN",
        "numeric",
        "percent_1",
        "Year-to-date total return as a fraction",
    ),
    (
        "return_1y",
        "1Y RTN",
        "numeric",
        "percent_1",
        "1-year total return as a fraction",
    ),
    (
        "return_3y",
        "3Y RTN",
        "numeric",
        "percent_1",
        "3-year total return as a fraction",
    ),
)


def upgrade() -> None:
    """Insert the eight L-3 rows; no-op on conflict (idempotent)."""
    sql = (
        "INSERT INTO screen_field_metadata "
        "(field_name, label, field_type, unit, description, null_fraction) "
        "VALUES (:field_name, :label, :field_type, :unit, :description, 0) "
        "ON CONFLICT (field_name) DO NOTHING"
    )
    for field_name, label, field_type, unit, description in _L3_FIELDS:
        op.execute(
            sa.text(sql).bindparams(
                field_name=field_name,
                label=label,
                field_type=field_type,
                unit=unit,
                description=description,
            )
        )


def downgrade() -> None:
    """Delete only the eight L-3 rows by primary key."""
    sql = "DELETE FROM screen_field_metadata WHERE field_name = :field_name"
    for field_name, *_ in _L3_FIELDS:
        op.execute(sa.text(sql).bindparams(field_name=field_name))
