"""Seed Wave L-2 snapshot fields into ``screen_field_metadata`` idempotently.

Revision ID: 024
Revises: 023
Create Date: 2026-05-27

PLAN-0089 Wave L-2 (T-WL2-02).

WHY THIS MIGRATION EXISTS:
  The application bootstrap (``app.py::_screen_fields_refresh_loop``) is the
  primary owner of ``screen_field_metadata`` rows — it upserts all 23 static
  field definitions every 6 hours from the in-memory list in
  ``_get_static_screen_fields()``. However:

  1) Fresh deployments must serve ``GET /fundamentals/screen/fields`` correctly
     immediately on first boot — *before* the first refresh loop tick. Without
     a DB seed, the cache miss falls through to an empty DB read and the
     endpoint returns ``{fields: []}`` until the first refresh completes.

  2) Operators running ``alembic upgrade head`` against a previously-upgraded
     database expect the table to reflect every L-2 row even if the host
     never ran the application (e.g. fresh CI environment).

  This migration therefore inserts the seven L-2 snapshot fields directly,
  matching ``_get_static_screen_fields()`` exactly. ON CONFLICT DO NOTHING
  makes the migration safe to re-run, and safe even when the bootstrap loop
  already populated the rows.

FORWARD-COMPAT (R11): the screen_field_metadata table schema was created in
  an earlier migration; we only INSERT rows, never ALTER the table. Field
  types match the CHECK constraint (``field_type IN ('numeric', 'text')``)
  — the six numeric metrics use ``numeric`` and ``credit_rating`` uses
  ``text``.

DOWNGRADE: delete the seven rows by primary key (``field_name``). This is
  intentionally narrow — we never delete rows that operators or other
  migrations may have inserted under the same key.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


# Canonical list mirrors ``app.py::_get_static_screen_fields()`` Wave L-2
# block. Each tuple: (field_name, label, field_type, unit, description).
# Keep these aligned with the application's in-memory list — divergence will
# cause the 6-hour refresh loop to overwrite this migration's rows with
# (possibly different) values.
_L2_FIELDS: tuple[tuple[str, str, str, str | None, str], ...] = (
    (
        "eps_ttm",
        "EPS (TTM)",
        "numeric",
        "USD",
        "Earnings per share — trailing twelve months",
    ),
    (
        "avg_volume_30d",
        "Avg Volume 30d",
        "numeric",
        "shares",
        "Average daily trading volume over the past 30 days",
    ),
    (
        "free_cash_flow",
        "Free Cash Flow",
        "numeric",
        "USD",
        "Operating cash flow minus capital expenditures",
    ),
    (
        "fcf_margin",
        "FCF Margin",
        "numeric",
        "%",
        "Free cash flow as a percentage of revenue",
    ),
    (
        "interest_coverage",
        "Interest Coverage",
        "numeric",
        "x",
        "EBIT divided by interest expense",
    ),
    (
        "net_debt_to_ebitda",
        "Net Debt/EBITDA",
        "numeric",
        "x",
        "(Total debt - cash) / EBITDA; negative = net cash position",
    ),
    (
        "credit_rating",
        "Credit Rating",
        "text",
        None,
        "S&P / EODHD credit rating string (e.g. AA+, BBB-)",
    ),
)


def upgrade() -> None:
    """Insert the seven L-2 rows; no-op on conflict (idempotent)."""
    # Parameter-bound INSERT avoids any string interpolation of values, and
    # the static field-list (above) means there is no user input anywhere.
    sql = (
        "INSERT INTO screen_field_metadata "
        "(field_name, label, field_type, unit, description, null_fraction) "
        "VALUES (:field_name, :label, :field_type, :unit, :description, 0) "
        "ON CONFLICT (field_name) DO NOTHING"
    )
    for field_name, label, field_type, unit, description in _L2_FIELDS:
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
    """Delete only the seven L-2 rows by primary key."""
    sql = "DELETE FROM screen_field_metadata WHERE field_name = :field_name"
    for field_name, *_ in _L2_FIELDS:
        op.execute(sa.text(sql).bindparams(field_name=field_name))
