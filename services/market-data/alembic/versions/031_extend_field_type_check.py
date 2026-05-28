"""WL-5c QA finding #2 — extend screen_field_metadata.field_type CHECK to admit 'date'.

PLAN-0089 Wave L-5a/L-5c QA report (2026-05-28), finding #2:
  Migration 028 had to seed the two calendar fields (``next_earnings_date``,
  ``next_dividend_date``) with ``field_type='numeric'`` and ``unit='date'``
  because the original ``ck_screen_field_metadata_field_type`` CHECK
  constraint (created by migration 004) only admits ``('numeric', 'text')``.

  Downstream UI rendering switches on ``field_type``: a numeric "date" field
  would be rendered as a plain number rather than a calendar widget. The
  L-5c lock-step app.py entries carry the same workaround.

This migration extends the CHECK constraint to also admit ``'date'`` and
re-types the two L-5c calendar rows to ``field_type='date'`` so the
storage, the API surface, and the UI are all aligned. ``app.py``'s
``_get_static_screen_fields()`` is updated lock-step in the same commit.

Forward-compat (R11): the constraint widens — old code that only ever
writes ``'numeric'`` or ``'text'`` still passes the CHECK. Existing rows
not touched by this migration retain their current ``field_type``.

Idempotency: each step uses ``IF EXISTS`` / ``IF NOT EXISTS`` or
inspects ``information_schema`` so re-running is a no-op.
"""

from __future__ import annotations

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Widen the CHECK constraint to admit 'date' and re-type the L-5c fields."""
    # ── 1) Drop the original 'numeric'/'text' constraint ────────────────────
    # Using IF EXISTS so a re-run after a partial failure is harmless.
    op.execute("ALTER TABLE screen_field_metadata DROP CONSTRAINT IF EXISTS ck_screen_field_metadata_field_type")

    # ── 2) Add the widened constraint ──────────────────────────────────────
    # NOT VALID is intentionally NOT used: the existing rows already satisfy
    # the superset condition, so an immediate full check is cheap and safer.
    op.execute(
        "ALTER TABLE screen_field_metadata "
        "ADD CONSTRAINT ck_screen_field_metadata_field_type "
        "CHECK (field_type IN ('numeric', 'text', 'date'))"
    )

    # ── 3) Re-type the L-5c calendar fields to the canonical 'date' value ──
    # Keyed by the static field_name list — no user input enters the SQL.
    op.execute(
        "UPDATE screen_field_metadata "
        "SET field_type = 'date' "
        "WHERE field_name IN ('next_earnings_date', 'next_dividend_date')"
    )


def downgrade() -> None:
    """Reverse the upgrade: re-type rows back to 'numeric' and restore the old CHECK."""
    # ── 1) Re-type the L-5c rows back to 'numeric' so the narrower constraint
    #       still passes. (The original workaround stored 'numeric'+unit='date'.)
    op.execute(
        "UPDATE screen_field_metadata "
        "SET field_type = 'numeric' "
        "WHERE field_name IN ('next_earnings_date', 'next_dividend_date')"
    )

    # ── 2) Drop the widened constraint and restore the original. ──────────
    op.execute("ALTER TABLE screen_field_metadata DROP CONSTRAINT IF EXISTS ck_screen_field_metadata_field_type")
    op.execute(
        "ALTER TABLE screen_field_metadata "
        "ADD CONSTRAINT ck_screen_field_metadata_field_type "
        "CHECK (field_type IN ('numeric', 'text'))"
    )
