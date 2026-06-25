"""Land the persisted weirdness metric (PLAN-0112 Wave 3, FR-4/FR-5).

Revision ID: 0052
Revises: 0051
Create Date: 2026-06-13

WHY THIS MIGRATION EXISTS (PLAN-0112 — connection-discovery redesign):
  The old ``path_insights.surprise_score`` saturated (p50 0.951) because it was
  defined *relative to the local sibling path set*, which both flattened the
  ranking and coupled the metric to the (slow) full-enumeration traversal.  The
  redesign replaces it with a per-path ``weirdness`` score computed from
  graph-GLOBAL statistics, so each path is scored independently:

      weirdness = reliability x (w_U*unexpectedness + w_S*semantic_distance + w_N*novelty)

  Computing ``unexpectedness`` (the hub-demoting term) cheaply requires the
  graph's per-vertex degree precomputed once per AGE-sync cycle rather than
  recomputed per query — hence the new ``node_degree`` table — plus a single-row
  ``graph_stats`` normaliser store holding the ``2m`` term (total edges).

WHAT 0052 DOES (all additive + forward-compatible, R5):
  1. CREATE TABLE ``node_degree`` — per-vertex undirected degree + meaningful
     degree (excluding membership edges), refreshed by the AGE-sync worker.
  2. CREATE TABLE ``graph_stats`` — a single-row (id=1) normaliser store
     (total_edges, total_meaningful_edges, max_degree, refreshed_at).
  3. ALTER ``path_insights`` ADD the new (all-NULLable) metric columns:
     dst_entity_id, reliability, unexpectedness, semantic_distance, novelty,
     weirdness, scorer_version.  ``composite_score`` is repurposed = weirdness
     (the discovery worker mirrors weirdness into composite_score; the existing
     anchor ranking index keeps working unchanged).
  4. Two new indexes powering the global "weird connections" feed and endpoint
     filtering.

FORWARD-COMPATIBILITY (R5 / BP-126):
  Every new ``path_insights`` column is NULLable with NO server default — old
  rows simply read back NULL and the domain entity defaults them to 0.0 / None.
  No column is dropped or renamed.  The deprecated ``surprise_score`` /
  ``diversity_score`` / ``template_match`` columns are intentionally KEPT.

FAIL LOUD (the 0049/0050 lesson — BP-688):
  After each CREATE we ASSERT the object exists in ``pg_class`` (tables/indexes)
  / ``information_schema`` (columns) and ``RAISE EXCEPTION`` if absent, so the
  migration can never report success on a silent no-op.  The OUTER handler
  tolerates ONLY a genuinely AGE-less CI image (``LOAD 'age'`` raising) — note
  none of the DDL here actually needs AGE (these are plain ``public`` tables), so
  the AGE probe is purely a courtesy to keep the bring-up shape identical to
  0050/0051; every other error propagates.

BP-393 — NO ``CONCURRENTLY``:
  Plain (non-concurrent) ``CREATE INDEX`` only; ``path_insights`` /
  ``canonical_entities`` are small and build well under a second.

DOWNGRADE:
  Drops the two new indexes, the seven ``path_insights`` columns, and the two
  new tables (``node_degree``, ``graph_stats``).  No pre-existing column or
  table is touched.
"""

from __future__ import annotations

from alembic import op

revision: str = "0052"
down_revision: str = "0051"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade DDL — create the two tables + path_insights columns + indexes, then
# ASSERT each materialised (FAIL LOUD — BP-688).  The OUTER EXCEPTION handler
# tolerates ONLY an AGE-less environment; every other error propagates.
# ---------------------------------------------------------------------------
_UPGRADE = """
DO $$
DECLARE
    _exists BOOLEAN;
    _pi_schema TEXT;
    _pi TEXT;  -- fully-qualified path_insights ("schema"."table")
BEGIN
    -- AGE probe (courtesy parity with 0050/0051; the DDL below does NOT need
    -- AGE — these are plain public tables).  On the pgvector-only CI image
    -- ``LOAD 'age'`` raises; we tolerate ONLY that and continue.
    BEGIN
        LOAD 'age';
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING
            'Apache AGE extension not available (%) — continuing; migration 0052 '
            'creates only plain public tables which do not require AGE.', SQLERRM;
    END;

    -- Resolve the ACTUAL schema of path_insights.  Migration 0004 leaves
    -- ``search_path = ag_catalog, "$user", public`` set session-wide, so a bare
    -- ``CREATE TABLE path_insights`` in 0032 can land in EITHER ag_catalog (fresh
    -- migration runs) or public (the live DB, built before that reordering).  We
    -- look it up here and address the table by its real schema so this migration
    -- applies cleanly in both placements (the 0037 "fully-qualify public" lesson,
    -- generalised).
    SELECT n.nspname
      INTO _pi_schema
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relname = 'path_insights' AND c.relkind = 'r'
     ORDER BY (n.nspname = 'public') DESC  -- prefer public if it somehow exists in both
     LIMIT 1;
    IF _pi_schema IS NULL THEN
        RAISE EXCEPTION
            'Migration 0052 ABORTED: path_insights table not found in any schema '
            '(expected from migration 0032).';
    END IF;
    _pi := format('%I.%I', _pi_schema, 'path_insights');

    -- 1. node_degree — per-vertex undirected degree (FR-5).  PK + FK CASCADE so
    --    a deleted canonical entity drops its degree row.
    CREATE TABLE IF NOT EXISTS public.node_degree (
        entity_id          UUID        NOT NULL,
        degree             INT         NOT NULL DEFAULT 0,
        degree_meaningful  INT         NOT NULL DEFAULT 0,
        refreshed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_node_degree PRIMARY KEY (entity_id),
        CONSTRAINT fk_node_degree_entity
            FOREIGN KEY (entity_id) REFERENCES public.canonical_entities (entity_id)
            ON DELETE CASCADE,
        CONSTRAINT chk_node_degree_nonneg CHECK (degree >= 0),
        CONSTRAINT chk_node_degree_meaningful_nonneg CHECK (degree_meaningful >= 0)
    );

    SELECT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = 'node_degree' AND c.relkind = 'r'
    ) INTO _exists;
    IF NOT _exists THEN
        RAISE EXCEPTION
            'Migration 0052 FAILED: table public.node_degree was not materialised (BP-688).';
    END IF;

    -- 2. graph_stats — single-row (id=1) normaliser store for the 2m term.
    CREATE TABLE IF NOT EXISTS public.graph_stats (
        id                     SMALLINT    NOT NULL,
        total_edges            INT,
        total_meaningful_edges INT,
        max_degree             INT,
        refreshed_at           TIMESTAMPTZ,
        CONSTRAINT pk_graph_stats PRIMARY KEY (id),
        CONSTRAINT chk_graph_stats_singleton CHECK (id = 1)
    );

    SELECT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = 'graph_stats' AND c.relkind = 'r'
    ) INTO _exists;
    IF NOT _exists THEN
        RAISE EXCEPTION
            'Migration 0052 FAILED: table public.graph_stats was not materialised (BP-688).';
    END IF;

    -- 3. path_insights — additive metric columns (all NULLable, no default).
    --    Addressed via the resolved ``_pi`` (real schema) so this works whether
    --    0032 placed the table in public or ag_catalog.
    EXECUTE 'ALTER TABLE ' || _pi || '
        ADD COLUMN IF NOT EXISTS dst_entity_id      UUID,
        ADD COLUMN IF NOT EXISTS reliability        DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS unexpectedness     DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS semantic_distance  DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS novelty            DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS weirdness          DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS scorer_version     TEXT';

    -- FK on dst_entity_id (CASCADE, nullable for old rows).  Added separately so
    -- the ADD COLUMN above stays idempotent; guard against re-adding the FK.
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_path_insights_dst_entity'
    ) THEN
        EXECUTE 'ALTER TABLE ' || _pi || '
            ADD CONSTRAINT fk_path_insights_dst_entity
                FOREIGN KEY (dst_entity_id) REFERENCES public.canonical_entities (entity_id)
                ON DELETE CASCADE';
    END IF;

    -- ASSERT the 7 columns exist (in the resolved schema).
    SELECT COUNT(*) = 7 FROM information_schema.columns
    WHERE table_schema = _pi_schema AND table_name = 'path_insights'
      AND column_name IN ('dst_entity_id', 'reliability', 'unexpectedness',
                          'semantic_distance', 'novelty', 'weirdness', 'scorer_version')
    INTO _exists;
    IF NOT _exists THEN
        RAISE EXCEPTION
            'Migration 0052 FAILED: not all 7 path_insights weirdness columns were '
            'added (BP-688).';
    END IF;

    -- 4. Indexes: global weird feed + endpoint filtering (on the resolved schema).
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_path_insights_global_weird ON ' || _pi
        || ' (weirdness DESC) WHERE weirdness IS NOT NULL';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_path_insights_dst ON ' || _pi
        || ' (dst_entity_id, weirdness DESC)';

    SELECT EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'idx_path_insights_global_weird' AND relkind = 'i'
    ) AND EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'idx_path_insights_dst' AND relkind = 'i'
    ) INTO _exists;
    IF NOT _exists THEN
        RAISE EXCEPTION
            'Migration 0052 FAILED: weirdness indexes were not materialised (BP-688).';
    END IF;

    RAISE NOTICE
        'Migration 0052 applied: node_degree + graph_stats tables, 7 path_insights '
        'weirdness columns, and 2 weirdness indexes created/verified.';
END;
$$
"""


# ---------------------------------------------------------------------------
# Downgrade DDL — drop the additions only (no pre-existing object touched).
# ---------------------------------------------------------------------------
_DOWNGRADE = """
DO $$
DECLARE
    _pi_schema TEXT;
    _pi TEXT;
BEGIN
    SELECT n.nspname INTO _pi_schema
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relname = 'path_insights' AND c.relkind = 'r'
     ORDER BY (n.nspname = 'public') DESC
     LIMIT 1;

    IF _pi_schema IS NOT NULL THEN
        _pi := format('%I.%I', _pi_schema, 'path_insights');
        EXECUTE 'DROP INDEX IF EXISTS ' || quote_ident(_pi_schema) || '.idx_path_insights_dst';
        EXECUTE 'DROP INDEX IF EXISTS ' || quote_ident(_pi_schema) || '.idx_path_insights_global_weird';
        EXECUTE 'ALTER TABLE ' || _pi || ' DROP CONSTRAINT IF EXISTS fk_path_insights_dst_entity';
        EXECUTE 'ALTER TABLE ' || _pi || '
            DROP COLUMN IF EXISTS dst_entity_id,
            DROP COLUMN IF EXISTS reliability,
            DROP COLUMN IF EXISTS unexpectedness,
            DROP COLUMN IF EXISTS semantic_distance,
            DROP COLUMN IF EXISTS novelty,
            DROP COLUMN IF EXISTS weirdness,
            DROP COLUMN IF EXISTS scorer_version';
    END IF;

    DROP TABLE IF EXISTS public.graph_stats;
    DROP TABLE IF EXISTS public.node_degree;
END;
$$
"""


def upgrade() -> None:
    """Create node_degree + graph_stats + path_insights weirdness columns/indexes."""
    op.execute(_UPGRADE)


def downgrade() -> None:
    """Drop the weirdness additions (no pre-existing object touched)."""
    op.execute(_DOWNGRADE)
