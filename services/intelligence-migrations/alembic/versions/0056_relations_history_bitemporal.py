"""Add ``relations_history`` — bitemporal version store for relation confidence/validity.

Revision ID: 0056
Revises: 0055
Create Date: 2026-06-14

WHY THIS MIGRATION EXISTS (PLAN-0109 W3 — bitemporal valid-time):
  The redesigned confidence model (PLAN-0109) makes a relation's confidence and
  validity change over time (signals decay on a per-class cadence; stateful facts
  hold until a ``valid_to`` / contradiction invalidates them). ``relations`` only
  stores the CURRENT state, so "what did we believe about this relation on date X"
  is unanswerable. This append-only history table records one row per
  confidence/validity change, giving a true BITEMPORAL model:
    - VALID TIME       (``valid_from`` / ``valid_to``): when the fact is true in the world.
    - TRANSACTION TIME (``recorded_at``): when WE recorded that belief.
  "AS OF (transaction_time)" reconstruction:
    SELECT confidence FROM relations_history
     WHERE relation_id = :rid AND recorded_at <= :as_of
     ORDER BY recorded_at DESC LIMIT 1;

WHAT 0056 DOES (additive + forward-compatible, R5):
  1. Resolve the ACTUAL schema of ``relations`` at runtime (public vs ag_catalog —
     migration 0004 leaves search_path set session-wide).
  2. CREATE TABLE IF NOT EXISTS ``relations_history`` in that schema (append-only;
     no FK to the hash-partitioned ``relations`` to keep partition handling simple).
  3. CREATE INDEX on (relation_id, recorded_at DESC) for the AS-OF lookup.
  4. ASSERT (FAIL LOUD — BP-688) the table exists; RAISE EXCEPTION otherwise.

NO DATA REWRITE: purely additive. The worker begins appending rows on its next cycle.

DOWNGRADE: DROP TABLE IF EXISTS — discards the recorded history (acceptable: the
  current state always lives in ``relations``).
"""

from __future__ import annotations

from alembic import op

revision: str = "0056"
down_revision: str = "0055"
branch_labels = None
depends_on = None


_UPGRADE = """
DO $$
DECLARE
    _schema TEXT;
    _tbl TEXT;
    _ok BOOLEAN;
BEGIN
    -- Resolve the real schema of relations (public vs ag_catalog).
    SELECT n.nspname
      INTO _schema
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relname = 'relations' AND c.relkind IN ('r', 'p')
     ORDER BY (n.nspname = 'public') DESC
     LIMIT 1;
    IF _schema IS NULL THEN
        RAISE EXCEPTION
            'Migration 0056 ABORTED: relations table not found in any schema '
            '(expected from migration 0001).';
    END IF;
    _tbl := format('%I.relations_history', _schema);

    EXECUTE 'CREATE TABLE IF NOT EXISTS ' || _tbl || ' (
        history_id        UUID             NOT NULL DEFAULT gen_random_uuid(),
        relation_id       UUID             NOT NULL,
        subject_entity_id UUID             NOT NULL,
        object_entity_id  UUID             NOT NULL,
        canonical_type    VARCHAR(100)     NOT NULL,
        confidence        DOUBLE PRECISION,
        valid_from        TIMESTAMPTZ,
        valid_to          TIMESTAMPTZ,
        decay_class       VARCHAR(20),
        recorded_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
        PRIMARY KEY (history_id)
    )';

    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_relations_history_relation_recorded ON '
        || _tbl || ' (relation_id, recorded_at DESC)';

    SELECT to_regclass(_tbl) IS NOT NULL INTO _ok;
    IF NOT _ok THEN
        RAISE EXCEPTION
            'Migration 0056 FAILED: relations_history was not created on % (BP-688).', _schema;
    END IF;

    RAISE NOTICE
        '[migration 0056] relations_history (bitemporal version store) ready on %', _schema;
END;
$$
"""


_DOWNGRADE = """
DO $$
DECLARE
    _schema TEXT;
BEGIN
    SELECT n.nspname INTO _schema
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relname = 'relations' AND c.relkind IN ('r', 'p')
     ORDER BY (n.nspname = 'public') DESC
     LIMIT 1;
    IF _schema IS NULL THEN
        RAISE EXCEPTION 'Migration 0056 downgrade ABORTED: relations table not found.';
    END IF;
    EXECUTE 'DROP TABLE IF EXISTS ' || format('%I.relations_history', _schema);
    RAISE NOTICE '[migration 0056 downgrade] dropped relations_history on %', _schema;
END;
$$
"""


def upgrade() -> None:
    """Create the append-only ``relations_history`` bitemporal version store."""
    op.execute(_UPGRADE)


def downgrade() -> None:
    """Drop ``relations_history`` (discards recorded history; current state remains in relations)."""
    op.execute(_DOWNGRADE)
