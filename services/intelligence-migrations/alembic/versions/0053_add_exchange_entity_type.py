"""Add 'exchange' to the canonical_entities entity_type CHECK constraint (FR-12).

Revision ID: 0053
Revises: 0052
Create Date: 2026-06-13

WHY THIS MIGRATION EXISTS (FR-12 — hub entity mis-typing):
  The ``entity_type`` discriminator on ``canonical_entities`` (locked to 11
  values by migration 0039 via ``ck_canonical_entities_entity_type``) has NO
  value for a stock exchange / trading venue.  With no correct home, every
  exchange was forced into a wrong bucket:
    - NYSE   -> financial_instrument  (degree ~292+ post-FR13)
    - NASDAQ -> index
    - "U.S." -> currency, "United States of America" -> unknown
  See ``docs/audits/2026-06-13-fr12-hub-mistyping-investigation.md`` §2.4 (1).

  This migration extends the CHECK to a 12th value, ``exchange``, so the
  prevention work (ENTITY_PROFILE prompt v2.1, provisional_enrichment_core
  fallback hardening) and the deterministic backfill
  (``scripts/data/retype_mishtyped_entities.py``) can actually write the
  correct type.

WHAT 0053 DOES (additive + forward-compatible, R5):
  1. Resolve the ACTUAL schema of ``canonical_entities`` at runtime — migration
     0004 leaves ``search_path = ag_catalog, "$user", public`` set session-wide,
     so the table can live in either ``ag_catalog`` (fresh migration runs) or
     ``public`` (the live DB built before that reordering).  We look it up and
     address the table by its real schema (the 0052 approach, generalised).
  2. DROP any pre-existing CHECK constraint on ``entity_type`` (dynamic lookup
     against ``pg_constraint`` — we do not hard-code the name, mirroring 0039).
  3. ADD ``ck_canonical_entities_entity_type`` over the 11 original values
     PLUS ``exchange``.
  4. ASSERT (FAIL LOUD — BP-688) that the new constraint exists and that it
     mentions ``exchange``; ``RAISE EXCEPTION`` otherwise so the migration can
     never report success on a silent no-op.

NO DATA REWRITE:
  Adding an allowed value cannot violate any existing row, so there is no
  UPDATE phase.  Re-typing existing mislabels is the job of the separate,
  reviewed backfill script (dry-run first) — NOT this DDL migration.

FORWARD-COMPATIBILITY (R5 / BP-126):
  The constraint is only WIDENED (a superset of the 0039 domain).  Every value
  that validated before still validates.

DOWNGRADE (guarded):
  Restoring the narrower 11-value CHECK is only safe if NO row uses ``exchange``
  yet — otherwise the ADD CONSTRAINT would fail with a CheckViolation and leave
  the table with no entity_type CHECK at all.  The downgrade therefore COUNTS
  ``exchange`` rows first and RAISES EXCEPTION (refusing to proceed) when any
  exist, so an operator must re-type them before downgrading.
"""

from __future__ import annotations

from alembic import op

revision: str = "0053"
down_revision: str = "0052"
branch_labels = None
depends_on = None


# ── Canonical entity_type enum after FR-12 (12 values) ─────────────────────────
# The first 11 are the migration-0039 domain; ``exchange`` is the FR-12 addition.
# Single source of truth — rendered into the CHECK body below.
_CANONICAL_KINDS_V2: tuple[str, ...] = (
    "financial_instrument",
    "person",
    "event",
    "sector",
    "industry",
    "macro_indicator",
    "place",
    "product",
    "index",
    "exchange",  # FR-12 addition — stock exchanges / trading venues
    "currency",
    "unknown",
)

# The original 11-value domain (migration 0039) — used only by downgrade() to
# restore the narrower CHECK.
_CANONICAL_KINDS_V1: tuple[str, ...] = tuple(k for k in _CANONICAL_KINDS_V2 if k != "exchange")


def _values_sql(kinds: tuple[str, ...]) -> str:
    """Render a quoted, comma-separated SQL VALUES list for an IN (...) clause.

    The result is interpolated into a single-quoted plpgsql ``EXECUTE '...'``
    literal, so each value's single quotes must be DOUBLED ('' ) to survive the
    surrounding plpgsql string (otherwise the literal terminates at the first
    quote → ``syntax error at or near "', '"``).
    """
    return ", ".join(f"''{kind}''" for kind in kinds)


# ---------------------------------------------------------------------------
# Upgrade DDL — resolve schema, drop any pre-existing entity_type CHECK, add the
# widened (12-value) CHECK, then ASSERT it materialised (FAIL LOUD — BP-688).
# ---------------------------------------------------------------------------
_UPGRADE = f"""
DO $$
DECLARE
    _ce_schema TEXT;
    _ce TEXT;            -- fully-qualified canonical_entities ("schema"."table")
    _con TEXT;           -- pre-existing constraint name (if any)
    _ok BOOLEAN;
BEGIN
    -- Resolve the real schema of canonical_entities (public vs ag_catalog) —
    -- the 0052 lesson generalised.
    SELECT n.nspname
      INTO _ce_schema
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relname = 'canonical_entities' AND c.relkind = 'r'
     ORDER BY (n.nspname = 'public') DESC  -- prefer public if it exists in both
     LIMIT 1;
    IF _ce_schema IS NULL THEN
        RAISE EXCEPTION
            'Migration 0053 ABORTED: canonical_entities table not found in any '
            'schema (expected from migration 0001).';
    END IF;
    _ce := format('%I.%I', _ce_schema, 'canonical_entities');

    -- Drop ANY pre-existing CHECK constraint mentioning entity_type (dynamic
    -- lookup — mirrors migration 0039; in practice this is
    -- ck_canonical_entities_entity_type from 0039).
    SELECT conname
      INTO _con
      FROM pg_constraint
     WHERE conrelid = _ce::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%entity_type%'
     LIMIT 1;
    IF _con IS NOT NULL THEN
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', _ce, _con);
        RAISE NOTICE
            '[migration 0053] dropped pre-existing entity_type CHECK constraint % '
            'before installing the widened 12-value (FR-12) constraint', _con;
    END IF;

    -- Install the widened CHECK (11 original values + ''exchange'').
    EXECUTE 'ALTER TABLE ' || _ce ||
            ' ADD CONSTRAINT ck_canonical_entities_entity_type' ||
            ' CHECK (entity_type IN ({_values_sql(_CANONICAL_KINDS_V2)}))';

    -- FAIL LOUD (BP-688): assert the constraint exists AND mentions ''exchange''.
    SELECT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = _ce::regclass
           AND conname = 'ck_canonical_entities_entity_type'
           AND contype = 'c'
           AND pg_get_constraintdef(oid) LIKE '%exchange%'
    ) INTO _ok;
    IF NOT _ok THEN
        RAISE EXCEPTION
            'Migration 0053 FAILED: ck_canonical_entities_entity_type was not '
            'installed with the ''exchange'' value (BP-688).';
    END IF;

    RAISE NOTICE
        '[migration 0053] ck_canonical_entities_entity_type now accepts 12 values '
        '(added ''exchange'') on %', _ce;
END;
$$
"""


# ---------------------------------------------------------------------------
# Downgrade DDL — restore the narrower 11-value CHECK, but REFUSE if any row
# already uses ``exchange`` (re-adding the narrow CHECK would CheckViolation and
# leave the table unconstrained).  Operator must re-type those rows first.
# ---------------------------------------------------------------------------
_DOWNGRADE = f"""
DO $$
DECLARE
    _ce_schema TEXT;
    _ce TEXT;
    _con TEXT;
    _n_exchange BIGINT;
BEGIN
    SELECT n.nspname INTO _ce_schema
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relname = 'canonical_entities' AND c.relkind = 'r'
     ORDER BY (n.nspname = 'public') DESC
     LIMIT 1;
    IF _ce_schema IS NULL THEN
        RAISE EXCEPTION
            'Migration 0053 downgrade ABORTED: canonical_entities table not found.';
    END IF;
    _ce := format('%I.%I', _ce_schema, 'canonical_entities');

    -- Guard: refuse to narrow the CHECK while any row uses ''exchange''.
    EXECUTE 'SELECT count(*) FROM ' || _ce || ' WHERE entity_type = ''exchange'''
        INTO _n_exchange;
    IF _n_exchange > 0 THEN
        RAISE EXCEPTION
            'Migration 0053 downgrade REFUSED: % row(s) still use entity_type '
            '''exchange''. Re-type them to a pre-FR-12 value before downgrading '
            '(narrowing the CHECK now would fail and drop the constraint entirely).',
            _n_exchange;
    END IF;

    -- Drop the widened constraint and re-add the original 11-value CHECK.
    SELECT conname INTO _con
      FROM pg_constraint
     WHERE conrelid = _ce::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%entity_type%'
     LIMIT 1;
    IF _con IS NOT NULL THEN
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', _ce, _con);
    END IF;

    EXECUTE 'ALTER TABLE ' || _ce ||
            ' ADD CONSTRAINT ck_canonical_entities_entity_type' ||
            ' CHECK (entity_type IN ({_values_sql(_CANONICAL_KINDS_V1)}))';
    RAISE NOTICE
        '[migration 0053 downgrade] restored 11-value entity_type CHECK on %', _ce;
END;
$$
"""


def upgrade() -> None:
    """Widen ck_canonical_entities_entity_type to accept ``exchange`` (FR-12)."""
    op.execute(_UPGRADE)


def downgrade() -> None:
    """Restore the 11-value CHECK — refuses if any ``exchange`` row exists."""
    op.execute(_DOWNGRADE)
