"""Add AGE property index on the ``entity`` vertex's ``entity_id`` property.

Revision ID: 0049
Revises: 0048
Create Date: 2026-06-12

WHY THIS MIGRATION EXISTS (BP-687 follow-up):
  Anchor resolution for every graph traversal starts with an exact-property
  lookup of the form::

      MATCH (s:entity {entity_id: '<uuid>'})-[*L..L]-(t:entity {entity_id: '<uuid>'})

  (see ``cypher_path.py``, ``cypher_neighborhood.py``,
  ``age/path_discovery.py``, and ``workers/age_sync_worker.py`` — all of which
  use the **lowercase** ``entity`` vertex label, per BP-SA5-001).

  Apache AGE stores every vertex of a label in a single backing table
  ``worldview_graph."entity"`` with the user properties packed into an
  ``agtype`` ``properties`` column.  Without a property index, the anchor
  predicate ``{entity_id: '<uuid>'}`` compiles to a filter on
  ``agtype_access_operator(properties, '"entity_id"') = '<uuid>'`` and the
  planner has no choice but to **sequentially scan** the whole vertex table to
  resolve each anchor.

  The BP-687 fix (staged shortest-first path probing) removed the
  ``ORDER BY length(p)`` frontier blow-up, but the *staged probe still pays an
  unindexed anchor-resolution constant on every depth it tries* — i.e. each
  ``MATCH (s:entity {entity_id: …})`` re-seq-scans the vertex table.  As the
  graph grows this constant dominates short-path queries.  BP-687's
  documented follow-up is exactly this migration:
  "AGE ``create_property_index`` on ``entity.entity_id`` (intelligence-migrations, R24)."

WHAT IT DOES:
  1. Ensures the lowercase ``entity`` vertex label exists.  On a *fresh* volume
     the label is otherwise created lazily by the first
     ``MERGE (e:entity {entity_id: …})`` in ``AgeSyncWorker`` — which may not
     have run yet at migration time.  ``create_property_index`` requires the
     label's backing table to already exist, so we create the vlabel first
     (idempotently — ``create_vlabel`` raises if it already exists, caught by an
     inner handler).
  2. Creates an AGE **property index** on the ``entity_id`` property of the
     ``entity`` label::

         SELECT create_property_index('worldview_graph', 'entity', 'entity_id');

     AGE materialises this as a plain B-tree named ``entity_entity_id_idx`` in
     the ``worldview_graph`` schema over
     ``agtype_access_operator(properties, '"entity_id"')``.

IDEMPOTENCY (stale-volume safe):
  ``create_property_index`` raises if the index already exists, so re-running
  the migration on a volume that already has the index would otherwise fail.
  We guard two ways (belt-and-suspenders, matching the defensive precedent in
  migration 0041's AGE-label loop):
    (a) A ``pg_class``/``pg_namespace`` existence pre-check skips creation when
        ``worldview_graph.entity_entity_id_idx`` already exists.
    (b) The ``create_property_index`` call is wrapped in its own
        ``BEGIN/EXCEPTION`` so any residual "already exists" race only emits a
        ``NOTICE`` instead of aborting the migration.

BP-393 — NO ``CONCURRENTLY``:
  AGE's ``create_property_index`` issues a **plain** (non-concurrent)
  ``CREATE INDEX`` internally.  We deliberately do NOT attempt a manual
  ``CREATE INDEX CONCURRENTLY`` on the backing table: per BP-393, concurrent
  index DDL has caused migration failures here (it cannot run inside the
  migration's transaction, and is forbidden on partitioned tables), so all AGE
  index creation in this repo is plain.  This matches the precedent in
  migration 0004 (graph/label setup) and 0041 (AGE edge labels).

GRACEFUL DEGRADATION (AGE-less CI):
  All AGE DDL is wrapped in a ``DO $$`` block that ``LOAD 'age'`` first.
  Environments without the AGE shared library (e.g. the pgvector-only CI image)
  raise inside the block, are caught by the outer ``EXCEPTION WHEN OTHERS``, and
  the migration completes with a ``WARNING`` — the index simply is not created
  (the graph features are unavailable there anyway).  This is identical to the
  pattern used by migrations 0004 and 0041.

FORWARD-COMPATIBILITY (R11):
  Purely additive — creates one index (and ensures one vertex label).  No
  column/table/label is removed or renamed.  Existing rows are untouched.

DOWNGRADE:
  Drops the property index via ``drop_property_index('worldview_graph',
  'entity_entity_id_idx')`` (best-effort, guarded).  The ``entity`` vertex
  label and its data are intentionally LEFT IN PLACE — dropping the label would
  delete live graph vertices, and the label is owned/used by the running
  ``AgeSyncWorker`` regardless of this index.  Downgrade only removes the index.
"""

from __future__ import annotations

from alembic import op

revision: str = "0049"
down_revision: str = "0048"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Upgrade DDL — ensure lowercase ``entity`` vlabel, then create the property
# index on ``entity_id``.  Everything is best-effort inside a single DO block
# so AGE-less environments migrate cleanly (graph features simply disabled).
# ---------------------------------------------------------------------------
_CREATE_ENTITY_ID_PROPERTY_INDEX = """
DO $$
DECLARE
    _index_exists BOOLEAN;
BEGIN
    LOAD 'age';
    SET search_path = ag_catalog, "$user", public;

    -- 1. Ensure the lowercase ``entity`` vertex label exists.  On a fresh
    --    volume the label is otherwise created lazily by AgeSyncWorker's first
    --    MERGE; create_property_index needs the backing table to exist first.
    --    create_vlabel raises if the label already exists → catch + continue.
    BEGIN
        PERFORM create_vlabel('worldview_graph', 'entity');
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'vlabel ''entity'' already exists or could not be created: %', SQLERRM;
    END;

    -- 2. Idempotency pre-check: skip if AGE has already materialised the
    --    property index (B-tree ``entity_entity_id_idx`` in the
    --    ``worldview_graph`` schema).  Guards re-creation on stale volumes.
    SELECT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'worldview_graph'
          AND c.relname = 'entity_entity_id_idx'
          AND c.relkind = 'i'
    ) INTO _index_exists;

    -- 3. Create the property index (PLAIN, non-concurrent — BP-393).  Wrapped
    --    in its own handler so an "already exists" race only NOTICEs.
    IF NOT _index_exists THEN
        BEGIN
            PERFORM create_property_index('worldview_graph', 'entity', 'entity_id');
            RAISE NOTICE 'Created AGE property index worldview_graph.entity_entity_id_idx on (entity).entity_id';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'create_property_index on (entity).entity_id skipped (already exists?): %', SQLERRM;
        END;
    ELSE
        RAISE NOTICE 'AGE property index worldview_graph.entity_entity_id_idx already present — skipping creation';
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING
        'Apache AGE extension not available (%) — entity.entity_id property index not created. '
        'Install AGE and re-run migration 0049 to enable indexed anchor lookups.',
        SQLERRM;
END;
$$
"""

# ---------------------------------------------------------------------------
# Downgrade DDL — drop the property index only (leave the ``entity`` label and
# its live vertex data intact).  Best-effort + guarded for AGE-less envs.
# ---------------------------------------------------------------------------
_DROP_ENTITY_ID_PROPERTY_INDEX = """
DO $$
BEGIN
    LOAD 'age';
    SET search_path = ag_catalog, "$user", public;
    BEGIN
        PERFORM drop_property_index('worldview_graph', 'entity_entity_id_idx');
        RAISE NOTICE 'Dropped AGE property index worldview_graph.entity_entity_id_idx';
    EXCEPTION WHEN OTHERS THEN
        -- Fall back to a direct DROP INDEX in case drop_property_index is
        -- unavailable or the index name differs across AGE point releases.
        BEGIN
            EXECUTE 'DROP INDEX IF EXISTS worldview_graph."entity_entity_id_idx"';
            RAISE NOTICE 'Dropped index worldview_graph.entity_entity_id_idx via DROP INDEX fallback';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'entity.entity_id property index already absent or drop failed: %', SQLERRM;
        END;
    END;
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING
        'Apache AGE extension not available or index already absent (%) — skipping property-index drop.',
        SQLERRM;
END;
$$
"""


def upgrade() -> None:
    """Create the AGE property index on ``(entity).entity_id`` (BP-687 follow-up)."""
    op.execute(_CREATE_ENTITY_ID_PROPERTY_INDEX)


def downgrade() -> None:
    """Drop the AGE property index on ``(entity).entity_id`` (label data preserved)."""
    op.execute(_DROP_ENTITY_ID_PROPERTY_INDEX)
