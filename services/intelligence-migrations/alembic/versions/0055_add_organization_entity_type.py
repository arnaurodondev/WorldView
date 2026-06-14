"""Add 'organization' to the canonical_entities entity_type CHECK constraint (FR-12).

Revision ID: 0055
Revises: 0054
Create Date: 2026-06-13

WHY THIS MIGRATION EXISTS (FR-12 — tickerless company / org mis-typing):
  Migration 0053 widened ``ck_canonical_entities_entity_type`` to 12 values by
  adding ``exchange``.  That still leaves NO correct home for the large tail of
  tickerless ``financial_instrument`` canonicals that are private companies,
  government bodies / agencies, universities, research firms, non-profits, and
  foundations (SpaceX, Anthropic, Y Combinator, Zacks, Duke Energy Foundation,
  Etihad).  These are real ORGANISATIONS but are NOT tradeable securities and
  carry no ticker — forcing them through the 12-value taxonomy makes them
  ``unknown``, which loses the (correct) "this is an organisation" signal.
  See ``docs/audits/2026-06-13-fr12-hub-mistyping-investigation.md``.

  This migration extends the CHECK to a 13th value, ``organization``, so the
  ENTITY_PROFILE prompt v2.2 and the reprofile backfill
  (``scripts/data/reprofile_tickerless_entities.py``) can write the correct type.

WHAT 0055 DOES (additive + forward-compatible, R5) — mirrors 0053 EXACTLY:
  1. Resolve the ACTUAL schema of ``canonical_entities`` at runtime (public vs
     ag_catalog — migration 0004 leaves search_path set session-wide).
  2. DROP any pre-existing CHECK constraint on ``entity_type`` (dynamic lookup
     against ``pg_constraint`` — we do not hard-code the name).
  3. ADD ``ck_canonical_entities_entity_type`` over the 12 post-0053 values PLUS
     ``organization`` (13 total).
  4. ASSERT (FAIL LOUD — BP-688) that the new constraint exists and mentions
     ``organization``; ``RAISE EXCEPTION`` otherwise so the migration can never
     report success on a silent no-op.

NO DATA REWRITE:
  Adding an allowed value cannot violate any existing row — re-typing existing
  mislabels is the job of the separate, reviewed backfill script (dry-run first).

FORWARD-COMPATIBILITY (R5 / BP-126):
  The constraint is only WIDENED (a superset of the 0053 domain).  Every value
  that validated before still validates.

DOWNGRADE (guarded):
  Restoring the narrower 12-value CHECK is only safe if NO row uses
  ``organization`` yet — otherwise the ADD CONSTRAINT would fail with a
  CheckViolation and leave the table with no entity_type CHECK at all.  The
  downgrade COUNTS ``organization`` rows first and RAISES EXCEPTION (refusing to
  proceed) when any exist, so an operator must re-type them before downgrading.
"""

from __future__ import annotations

from alembic import op

revision: str = "0055"
down_revision: str = "0054"
branch_labels = None
depends_on = None


# ── Canonical entity_type enum after this migration (13 values) ────────────────
# The first 12 are the migration-0053 domain; ``organization`` is the FR-12
# addition.  Single source of truth — rendered into the CHECK body below.
_CANONICAL_KINDS_V3: tuple[str, ...] = (
    "financial_instrument",
    "person",
    "event",
    "sector",
    "industry",
    "macro_indicator",
    "place",
    "product",
    "index",
    "exchange",
    "organization",  # FR-12 addition — private companies / agencies / non-profits / institutions
    "currency",
    "unknown",
)

# The 12-value domain (post migration 0053) — used only by downgrade() to
# restore the narrower CHECK.
_CANONICAL_KINDS_V2: tuple[str, ...] = tuple(k for k in _CANONICAL_KINDS_V3 if k != "organization")


def _values_sql(kinds: tuple[str, ...]) -> str:
    """Render a quoted, comma-separated SQL VALUES list for an IN (...) clause.

    The result is interpolated into a single-quoted plpgsql ``EXECUTE '...'``
    literal, so each value's single quotes must be DOUBLED ('' ) to survive the
    surrounding plpgsql string (otherwise the literal terminates at the first
    quote → ``syntax error at or near "', '"``).  This is the BP carried over
    from migration 0053.
    """
    return ", ".join(f"''{kind}''" for kind in kinds)


# ---------------------------------------------------------------------------
# Upgrade DDL — resolve schema, drop any pre-existing entity_type CHECK, add the
# widened (13-value) CHECK, then ASSERT it materialised (FAIL LOUD — BP-688).
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
            'Migration 0055 ABORTED: canonical_entities table not found in any '
            'schema (expected from migration 0001).';
    END IF;
    _ce := format('%I.%I', _ce_schema, 'canonical_entities');

    -- Drop ANY pre-existing CHECK constraint mentioning entity_type (dynamic
    -- lookup — mirrors migration 0039/0053; in practice this is
    -- ck_canonical_entities_entity_type from 0053).
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
            '[migration 0055] dropped pre-existing entity_type CHECK constraint % '
            'before installing the widened 13-value (FR-12) constraint', _con;
    END IF;

    -- Install the widened CHECK (12 post-0053 values + ''organization'').
    EXECUTE 'ALTER TABLE ' || _ce ||
            ' ADD CONSTRAINT ck_canonical_entities_entity_type' ||
            ' CHECK (entity_type IN ({_values_sql(_CANONICAL_KINDS_V3)}))';

    -- FAIL LOUD (BP-688): assert the constraint exists AND mentions ''organization''.
    SELECT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = _ce::regclass
           AND conname = 'ck_canonical_entities_entity_type'
           AND contype = 'c'
           AND pg_get_constraintdef(oid) LIKE '%organization%'
    ) INTO _ok;
    IF NOT _ok THEN
        RAISE EXCEPTION
            'Migration 0055 FAILED: ck_canonical_entities_entity_type was not '
            'installed with the ''organization'' value (BP-688).';
    END IF;

    RAISE NOTICE
        '[migration 0055] ck_canonical_entities_entity_type now accepts 13 values '
        '(added ''organization'') on %', _ce;
END;
$$
"""


# ---------------------------------------------------------------------------
# Downgrade DDL — restore the narrower 12-value CHECK, but REFUSE if any row
# already uses ``organization`` (re-adding the narrow CHECK would CheckViolation
# and leave the table unconstrained).  Operator must re-type those rows first.
# ---------------------------------------------------------------------------
_DOWNGRADE = f"""
DO $$
DECLARE
    _ce_schema TEXT;
    _ce TEXT;
    _con TEXT;
    _n_org BIGINT;
BEGIN
    SELECT n.nspname INTO _ce_schema
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relname = 'canonical_entities' AND c.relkind = 'r'
     ORDER BY (n.nspname = 'public') DESC
     LIMIT 1;
    IF _ce_schema IS NULL THEN
        RAISE EXCEPTION
            'Migration 0055 downgrade ABORTED: canonical_entities table not found.';
    END IF;
    _ce := format('%I.%I', _ce_schema, 'canonical_entities');

    -- Guard: refuse to narrow the CHECK while any row uses ''organization''.
    EXECUTE 'SELECT count(*) FROM ' || _ce || ' WHERE entity_type = ''organization'''
        INTO _n_org;
    IF _n_org > 0 THEN
        RAISE EXCEPTION
            'Migration 0055 downgrade REFUSED: % row(s) still use entity_type '
            '''organization''. Re-type them to a pre-FR-12 value before downgrading '
            '(narrowing the CHECK now would fail and drop the constraint entirely).',
            _n_org;
    END IF;

    -- Drop the widened constraint and re-add the 12-value CHECK.
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
            ' CHECK (entity_type IN ({_values_sql(_CANONICAL_KINDS_V2)}))';
    RAISE NOTICE
        '[migration 0055 downgrade] restored 12-value entity_type CHECK on %', _ce;
END;
$$
"""


def upgrade() -> None:
    """Widen ck_canonical_entities_entity_type to accept ``organization`` (FR-12)."""
    op.execute(_UPGRADE)


def downgrade() -> None:
    """Restore the 12-value CHECK — refuses if any ``organization`` row exists."""
    op.execute(_DOWNGRADE)
