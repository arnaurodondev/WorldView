"""Add CHECK constraint on canonical_entities.entity_type — PLAN-0089 F2 Step 1 (M1).

Revision ID: 0039
Revises: 0038
Create Date: 2026-05-20

WHY THIS MIGRATION EXISTS:
  PRD-0089 / PLAN-0089 wave F2 unifies the parallel ``entity_id`` /
  ``instrument_id`` UUID namespaces into a single canonical id per tradable
  security and flips URL routing from UUIDs to tickers (see
  ``docs/plans/0089-pages/F2-entity-id-unification-plan.md`` §2).

  The original plan §2.1 proposed adding a NEW ``kind`` column. The
  agreed-on option-c decision (see _DECISIONS.md §A DISCUSS-2 + §C FU-2.1..2.5)
  is to REUSE the pre-existing ``entity_type VARCHAR(50)`` column on
  ``canonical_entities`` as the kind discriminator — no new column added.

  This migration locks the discriminator domain to 11 canonical values via
  a CHECK constraint. The downstream seed-data rewrite (PLAN-0089 F2 Step 8)
  will rewrite any legacy values (``'company'``, ``'organization'``, etc.) to
  match this enum before the constraint is enforced on real data.

WHAT THIS MIGRATION DOES:
  1. Defensively REWRITES any rows whose ``entity_type`` is NOT in the
     11-value canonical enum to ``'unknown'``. RAISES a NOTICE with the
     row count so operators see if anything was rewritten. This makes the
     migration idempotent under any pre-existing data — including the
     legacy seeds from 0009 (``'organization'``, ``'location'``,
     ``'macroeconomic_indicator'``, etc.) and migration 0038's earlier
     ``'organization'`` rows on stale DBs.
  2. Adds ``ck_canonical_entities_entity_type`` CHECK constraint on the
     pre-existing ``canonical_entities.entity_type`` column. The 11
     canonical values are:
       'financial_instrument', 'person', 'event', 'sector', 'industry',
       'macro_indicator', 'place', 'product', 'index', 'currency', 'unknown'
  3. Does NOT add a new index — migration 0001 already created
     ``idx_entities_type ON canonical_entities (entity_type)`` (line 138).
     A second index on the same column would be redundant.

BELT-AND-SUSPENDERS NOTE:
  Migration 0038 was also patched (PLAN-0089 F2 Step 1 follow-up) to insert
  OpenAI / Anthropic with ``entity_type = 'unknown'`` directly, so on a
  fresh ``alembic upgrade head`` the Phase 1 UPDATE here rewrites zero rows
  and emits no NOTICE. The defensive UPDATE remains in place for any
  environment with stale data from prior 0038 applies or legacy 0009 seeds.

DOWNGRADE:
  Drops the CHECK constraint. The Phase 1 UPDATE is NOT reverted — those
  legacy values are not reachable through the new application code anyway,
  and re-introducing them would break the invariant this migration enforces.
  The pre-existing ``idx_entities_type`` index is untouched (it was created
  by migration 0001 and is not owned by this migration).
"""

from __future__ import annotations

from alembic import op

revision: str = "0039"
down_revision: str = "0038"
branch_labels = None
depends_on = None


# ── Canonical entity_type enum (11 values) ─────────────────────────────────────
# Single source of truth — duplicated in the SQL below for the CHECK body.
# Order matches the plan §2.1; ``'unknown'`` is the catch-all for upstream
# extractors that have not yet been taught the strict discriminator.
_CANONICAL_KINDS: tuple[str, ...] = (
    "financial_instrument",  # tradable; entity_id will == instruments.id post-F2
    "person",  # executives, fund managers, analysts
    "event",  # FOMC, earnings calls, M&A announcements
    "sector",  # GICS sector
    "industry",  # GICS sub-industry
    "macro_indicator",  # CPI, GDP, unemployment, ISM, etc.
    "place",  # country / region — for geographic exposures
    "product",  # consumer products / SKUs — e.g. iPhone, Model Y
    "index",  # market indices — ^GSPC, ^TNX, ^VIX
    "currency",  # USD, EUR, JPY — for FX exposures
    "unknown",  # provisional / unresolved — catch-all
)


def upgrade() -> None:
    """Add the CHECK constraint on canonical_entities.entity_type.

    Two-phase upgrade (PLAN-0089 F2 Step 1 follow-up):
      1. DEFENSIVE REWRITE — UPDATE any row whose entity_type is NOT in the
         11-value canonical enum to ``'unknown'``. This makes the migration
         idempotent under any pre-existing data (legacy seeds from 0009,
         migration 0038's original ``'organization'`` rows on a stale DB,
         or any future migration we haven't yet audited).
      2. ADD CONSTRAINT — once the data is known-clean, install the CHECK.

    The defensive rewrite is a one-time cleanup; the downgrade() does NOT
    undo it (the legacy values are not reachable through the new application
    code anyway, and re-introducing them would break the very invariant this
    migration enforces).
    """
    # Render the SQL VALUES list once so the migration body is auditable in
    # one glance. Each value is single-quoted and comma-separated. Reused by
    # both the defensive UPDATE and the CHECK constraint body.
    values_sql = ", ".join(f"'{kind}'" for kind in _CANONICAL_KINDS)

    # ── Phase 1: defensive rewrite of any legacy / non-canonical values ──
    # Wrapped in a DO block so we can RAISE NOTICE with the rewritten count.
    # GET DIAGNOSTICS captures the row count from the just-executed UPDATE.
    # Operators on real DBs (if any future env has them) get a heads-up if
    # this UPDATE actually touched rows — silent rewrites are dangerous.
    op.execute(
        f"""
        DO $$
        DECLARE
            rewritten_count INTEGER;
        BEGIN
            UPDATE canonical_entities
               SET entity_type = 'unknown'
             WHERE entity_type NOT IN ({values_sql});
            GET DIAGNOSTICS rewritten_count = ROW_COUNT;
            IF rewritten_count > 0 THEN
                RAISE NOTICE
                  '[migration 0039] rewrote % canonical_entities rows from '
                  'legacy entity_type values to ''unknown'' before adding '
                  'CHECK constraint',
                  rewritten_count;
            END IF;
        END
        $$
        """
    )

    # ── Phase 2: install the CHECK constraint on now-clean data ──
    op.execute(
        f"""
        ALTER TABLE canonical_entities
          ADD CONSTRAINT ck_canonical_entities_entity_type
          CHECK (entity_type IN ({values_sql}))
        """
    )

    # Index note: migration 0001 already created ``idx_entities_type`` on
    # ``canonical_entities (entity_type)`` — re-creating it would be redundant
    # and would clash with the existing name. Skip.


def downgrade() -> None:
    """Drop the CHECK constraint added in upgrade()."""
    op.execute("ALTER TABLE canonical_entities DROP CONSTRAINT IF EXISTS ck_canonical_entities_entity_type")
