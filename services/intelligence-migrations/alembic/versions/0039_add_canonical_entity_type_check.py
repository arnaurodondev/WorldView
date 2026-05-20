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

PRE-EXISTING-CONSTRAINT DISCOVERY (Step 1 follow-up 2, 2026-05-20):
  During ``make dev-rebuild`` validation we discovered that the live dev
  intelligence_db ALREADY has a CHECK constraint named
  ``ck_canonical_entity_type`` (singular, no plural in name) that enforces
  a DIFFERENT 12-value legacy enum:
    'company', 'financial_instrument', 'person', 'organization',
    'country', 'currency', 'commodity', 'index', 'sector', 'concept',
    'event', 'other'
  This constraint is not present in any tracked migration in the repo — it
  is code-path drift from an earlier hand-rolled DDL or a since-deleted
  migration. The dev DB has ~2000 rows using these legacy values.

  The naive "UPDATE NOT IN canonical → 'unknown'" approach FAILS because
  ``'unknown'`` is NOT in the pre-existing constraint's allowed list, so
  the UPDATE itself raises CheckViolation before we can install the new
  constraint.

WHAT THIS MIGRATION DOES (three phases):
  1. DROP any pre-existing CHECK constraint on ``entity_type`` (whatever
     it is named) so subsequent UPDATEs can rewrite values freely. Uses
     a dynamic lookup against ``pg_constraint`` so we don't hard-code the
     legacy constraint name. NOTICE-logs what it dropped so operators see
     the cleanup happen.
  2. REMAP legacy values per the canonical mapping table below:
       'company'      → 'financial_instrument' if ticker IS NOT NULL,
                        else 'unknown'
       'organization' → 'unknown'   (mostly private cos / gov bodies / NGOs)
       'other'        → 'unknown'
       'concept'      → 'unknown'   (industries are now tagged explicitly)
       'commodity'    → 'unknown'   (v1 does not carry commodities)
       'country'      → 'place'
       (Any remaining non-canonical) → 'unknown'
     Each remap step emits a NOTICE with the row count when it touches
     anything — silent rewrites are dangerous, especially over ~2000 rows.
  3. ADD the new constraint ``ck_canonical_entities_entity_type`` (plural
     — keep this name stable; downstream code and tests reference it) over
     the 11 canonical values.

BELT-AND-SUSPENDERS NOTE:
  Migration 0038 was also patched in commit bea77cdc (PLAN-0089 F2 Step 1
  follow-up 1) to insert OpenAI / Anthropic with ``entity_type = 'unknown'``
  directly, so on a fresh ``alembic upgrade head`` Phase 2 rewrites zero
  rows and emits no NOTICEs. The defensive remap remains in place for any
  environment with legacy / drifted data.

DOWNGRADE:
  Drops the new ``ck_canonical_entities_entity_type`` constraint. It does
  NOT restore the pre-existing ``ck_canonical_entity_type`` (singular)
  constraint — that constraint was untracked code-path drift, never lived
  in this migration chain, and bringing it back would re-poison the schema
  with the legacy 12-value enum. The data rewrite from Phase 2 is also NOT
  reversed (those legacy values are not reachable through the new
  application code, and re-introducing them would break the invariants
  the rest of F2 relies on).
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
    """Install the new CHECK constraint after dropping any drifted predecessor.

    Three-phase upgrade (PLAN-0089 F2 Step 1 follow-up 2, 2026-05-20):
      1. DROP pre-existing CHECK on entity_type (if any) — required because
         the dev DB has an untracked ``ck_canonical_entity_type`` constraint
         enforcing a 12-value legacy enum that excludes ``'unknown'``, which
         would block Phase 2's UPDATE.
      2. REMAP legacy entity_type values to the canonical 11-value enum,
         using ticker-presence as the disambiguator for ``'company'``.
      3. ADD ``ck_canonical_entities_entity_type`` CHECK constraint over
         the 11 canonical values.

    The data rewrites in Phase 2 are NOT undone by downgrade() — see the
    module docstring for rationale.
    """
    # Render the SQL VALUES list once so the migration body is auditable
    # in one glance. Each value is single-quoted and comma-separated.
    values_sql = ", ".join(f"'{kind}'" for kind in _CANONICAL_KINDS)

    # ── Phase 1: drop ANY pre-existing CHECK constraint on entity_type ──
    # We look up the constraint dynamically via pg_constraint because:
    #   - The drifted constraint is named ``ck_canonical_entity_type`` (singular)
    #     in the live dev DB but might be named differently in other envs.
    #   - We don't want to hard-code "drop a constraint name we don't own".
    # The query filters on:
    #   - the canonical_entities table
    #   - contype = 'c' (CHECK constraint)
    #   - the constraint definition mentions ``entity_type``
    # If multiple matched, only the first is dropped — but in practice there
    # is at most one such constraint at a time.
    op.execute(
        """
        DO $$
        DECLARE
            constraint_name TEXT;
        BEGIN
            SELECT conname INTO constraint_name
            FROM pg_constraint
            WHERE conrelid = 'canonical_entities'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%entity_type%';
            IF constraint_name IS NOT NULL THEN
                EXECUTE format(
                  'ALTER TABLE canonical_entities DROP CONSTRAINT %I',
                  constraint_name
                );
                RAISE NOTICE
                  '[migration 0039] dropped pre-existing CHECK constraint % '
                  'on canonical_entities.entity_type before installing the '
                  'canonical 11-value constraint',
                  constraint_name;
            END IF;
        END
        $$
        """
    )

    # ── Phase 2: remap legacy entity_type values to canonical enum ──
    # Mapping table (per user's domain decisions, 2026-05-20):
    #   'company'      → 'financial_instrument' if ticker IS NOT NULL
    #                  → 'unknown'              otherwise
    #   'organization' → 'unknown'   (mostly private cos / gov bodies / NGOs;
    #                                  not tradable, not a financial instrument)
    #   'other'        → 'unknown'
    #   'concept'      → 'unknown'   (industries are tagged explicitly now)
    #   'commodity'    → 'unknown'   (v1 does not carry commodities as a kind)
    #   'country'      → 'place'
    #   (anything else NOT in canonical list) → 'unknown'
    #
    # Each UPDATE is wrapped in its own GET DIAGNOSTICS + RAISE NOTICE
    # block so operators see exactly how many rows each remap touched.
    # We deliberately do the company→FI remap FIRST (before the catch-all)
    # so company-with-ticker is rescued before the residual sweep would
    # otherwise re-label it as 'unknown'.
    op.execute(
        f"""
        DO $$
        DECLARE
            rewritten_count INTEGER;
        BEGIN
            -- 2a: 'company' WITH ticker → 'financial_instrument'
            -- These are public listed companies; the ticker presence is
            -- the strongest signal we have that the row is a tradable.
            UPDATE canonical_entities
               SET entity_type = 'financial_instrument'
             WHERE entity_type = 'company' AND ticker IS NOT NULL;
            GET DIAGNOSTICS rewritten_count = ROW_COUNT;
            IF rewritten_count > 0 THEN
                RAISE NOTICE
                  '[migration 0039] remapped % ''company''-with-ticker rows '
                  'to ''financial_instrument''',
                  rewritten_count;
            END IF;

            -- 2b: 'country' → 'place'
            -- Direct rename; the canonical enum uses the broader 'place'
            -- bucket which subsumes country / region.
            UPDATE canonical_entities
               SET entity_type = 'place'
             WHERE entity_type = 'country';
            GET DIAGNOSTICS rewritten_count = ROW_COUNT;
            IF rewritten_count > 0 THEN
                RAISE NOTICE
                  '[migration 0039] remapped % ''country'' rows to ''place''',
                  rewritten_count;
            END IF;

            -- 2c: residual sweep — anything NOT in canonical enum → 'unknown'
            -- After 2a + 2b this covers: 'organization', 'other', 'concept',
            -- 'commodity', 'company'-WITHOUT-ticker, plus any future legacy
            -- value we haven't yet seen. Last so the company→FI rescue runs
            -- before this catch-all could re-label it.
            UPDATE canonical_entities
               SET entity_type = 'unknown'
             WHERE entity_type NOT IN ({values_sql});
            GET DIAGNOSTICS rewritten_count = ROW_COUNT;
            IF rewritten_count > 0 THEN
                RAISE NOTICE
                  '[migration 0039] rewrote % residual non-canonical '
                  'canonical_entities rows to ''unknown''',
                  rewritten_count;
            END IF;
        END
        $$
        """
    )

    # ── Phase 3: install the new CHECK constraint on now-clean data ──
    # Name is ``ck_canonical_entities_entity_type`` (plural ``entities``,
    # matches the table name); deliberately distinct from the legacy
    # ``ck_canonical_entity_type`` so we can tell which one is in force.
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
    """Drop the CHECK constraint added in upgrade().

    DESIGN NOTE: we deliberately do NOT restore the pre-existing
    ``ck_canonical_entity_type`` (singular) constraint that Phase 1 dropped.
    That constraint was untracked code-path drift — it never lived in this
    migration chain, it enforced an obsolete 12-value enum, and bringing it
    back on downgrade would re-poison the schema with a domain that the
    rest of F2 has moved past. If a future migration genuinely needs an
    entity_type CHECK at this point in the chain, it should add its own
    forward migration with a clear name and audit trail.

    The Phase 2 data rewrites are likewise NOT reverted — those legacy
    values are not reachable through the new application code anyway.
    """
    op.execute("ALTER TABLE canonical_entities DROP CONSTRAINT IF EXISTS ck_canonical_entities_entity_type")
