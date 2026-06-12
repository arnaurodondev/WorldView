"""Create a GIN index on the ``entity`` vertex's ``properties`` so AGE anchor
lookups (``{entity_id: …}``) are index-served — and FAIL LOUD if creation does
not actually materialise an index.

Revision ID: 0050
Revises: 0049
Create Date: 2026-06-12

WHY THIS MIGRATION EXISTS (PLAN-0111 A — corrects the silent no-op in 0049):
  Migration 0049 reported success and advanced ``alembic_version`` to ``0049``,
  yet the index ``worldview_graph.entity_entity_id_idx`` was **never created**.
  Two compounding bugs made the failure invisible:

    1. 0049 called ``create_property_index('worldview_graph','entity',
       'entity_id')``.  **Apache AGE 1.5.0 (the version actually running here)
       does not ship a ``create_property_index`` function at all** — the call
       fails with ``function create_property_index(unknown, unknown, unknown)
       does not exist``.

    2. 0049 wrapped that call in an INNER ``BEGIN … EXCEPTION WHEN OTHERS THEN
       RAISE NOTICE`` block whose comment assumed the only possible failure was
       an "already exists" race.  In reality it swallowed the *function does not
       exist* error — the migration completed "successfully" with no index.

  Net effect: every Cypher anchor predicate ``MATCH (n:entity {entity_id: …})``
  was resolved by a **sequential scan** of ~15,500 vertices (≈24 ms/anchor,
  multiplied across the staged multi-hop probes), and 1,200+ ``path_insight_jobs``
  failed / timed out (compounded by the timeout inversion fixed separately in
  ``age/path_discovery.py``).

WHAT 0050 DOES (the create method that AGE 1.5 actually uses):
  Diagnosis (PLAN-0111 A-1) showed that AGE 1.5 compiles the anchor predicate
  ``{entity_id: '<uuid>'}`` to a **containment** filter on the whole property
  map::

      Filter: (n0.properties @> '{"entity_id": "<uuid>"}'::agtype)

  i.e. it uses the agtype ``@>`` operator — NOT
  ``agtype_access_operator(properties, '"entity_id"') = …``.  Therefore a btree
  *expression* index on ``agtype_access_operator(...)`` is provably useless here
  (the planner never picks it).  The index the planner WILL use for ``@>`` is a
  **GIN index on the ``properties`` column**::

      CREATE INDEX entity_properties_gin_idx
        ON worldview_graph."entity" USING gin (properties);

  With this index the anchor scan drops from a 15,500-row Seq Scan to a
  sub-millisecond ``Bitmap Index Scan on entity_properties_gin_idx`` (verified
  live, after ANALYZE: anchor lookup 24 ms → 0.15 ms).  NOTE: this fixes only
  the ANCHOR resolution; a multi-hop traversal's dominant cost is the edge-table
  expansion (per-label edge tables have no start_id/end_id index), so the full
  2-hop is NOT made sub-second by this index alone — that edge-index work is a
  separate follow-up.

  GIN (rather than a per-property btree) is the right structure because it
  indexes every key/value pair in the agtype map and natively supports ``@>`` —
  it covers *all* property-equality anchors AGE emits, not just ``entity_id``.

FAIL LOUD (the lesson from 0049's silent swallow — see BP-688):
  Unlike 0049, this migration does NOT swallow a real creation failure when AGE
  is present:
    * The only ``EXCEPTION WHEN OTHERS`` is the OUTER guard, and it ONLY tolerates
      a genuinely AGE-less environment (the pgvector-only CI image, detected by
      ``LOAD 'age'`` raising) — it re-RAISEs anything else.
    * After the ``CREATE INDEX`` we ASSERT the index exists in ``pg_class`` and
      ``RAISE EXCEPTION`` if it does not.  An AGE-present run can therefore never
      again report success while leaving the index uncreated.

IDEMPOTENCY (stale-volume safe):
  ``CREATE INDEX IF NOT EXISTS`` skips creation when the GIN index already
  exists; the post-create assertion still confirms presence.  Safe to re-run.

BP-393 — NO ``CONCURRENTLY``:
  Plain (non-concurrent) ``CREATE INDEX`` only.  ``CREATE INDEX CONCURRENTLY``
  cannot run inside a migration transaction and has caused failures here before
  (BP-393); the ``entity`` table (~15.5k rows) builds in well under a second.

FORWARD-COMPATIBILITY (R11):
  Purely additive — creates one index.  No column/table/label removed or renamed.

DOWNGRADE:
  Drops ``entity_properties_gin_idx`` only (vertex data left intact).
"""

from __future__ import annotations

from alembic import op

revision: str = "0050"
down_revision: str = "0049"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Upgrade DDL — create the GIN index on (entity).properties, then ASSERT it
# materialised.  The outer EXCEPTION handler tolerates ONLY an AGE-less
# environment (LOAD 'age' fails); every other error propagates (FAIL LOUD).
# ---------------------------------------------------------------------------
_CREATE_ENTITY_PROPERTIES_GIN_INDEX = """
DO $$
DECLARE
    _age_available BOOLEAN := TRUE;
    _index_exists  BOOLEAN;
BEGIN
    -- Probe for the AGE shared library.  On the pgvector-only CI image this
    -- raises; we catch ONLY this case and skip (graph features unavailable).
    BEGIN
        LOAD 'age';
    EXCEPTION WHEN OTHERS THEN
        _age_available := FALSE;
        RAISE WARNING
            'Apache AGE extension not available (%) — entity.properties GIN index '
            'not created. Install AGE and re-run migration 0050 for indexed anchor '
            'lookups.', SQLERRM;
    END;

    IF _age_available THEN
        SET search_path = ag_catalog, "$user", public;

        -- 1. Create the GIN index on the agtype ``properties`` map.  AGE 1.5
        --    compiles ``{entity_id: …}`` anchors to ``properties @> '{...}'``,
        --    which a GIN index serves.  PLAIN / non-concurrent (BP-393).
        --    NOT wrapped in a NOTICE-swallowing handler — a real failure here
        --    MUST abort the migration (this is exactly what 0049 got wrong).
        CREATE INDEX IF NOT EXISTS entity_properties_gin_idx
            ON worldview_graph."entity"
            USING gin (properties);

        -- 2. ASSERT the index actually exists.  Guards against any future
        --    silent no-op (AGE arg-signature drift, label renames, etc.):
        --    if the CREATE somehow produced nothing, FAIL LOUD here.
        SELECT EXISTS (
            SELECT 1
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'worldview_graph'
              AND c.relname = 'entity_properties_gin_idx'
              AND c.relkind = 'i'
        ) INTO _index_exists;

        IF NOT _index_exists THEN
            RAISE EXCEPTION
                'Migration 0050 FAILED: GIN index worldview_graph.entity_properties_gin_idx '
                'was not materialised after CREATE INDEX. Refusing to report success '
                '(this is the 0049 silent-swallow class — BP-688).';
        END IF;

        RAISE NOTICE
            'Created/verified AGE GIN index worldview_graph.entity_properties_gin_idx '
            'on (entity).properties — anchor lookups are now index-served.';
    END IF;
END;
$$
"""

# ---------------------------------------------------------------------------
# Downgrade DDL — drop the GIN index only (leave the ``entity`` label and its
# live vertex data intact).  Best-effort + guarded for AGE-less envs.
# ---------------------------------------------------------------------------
_DROP_ENTITY_PROPERTIES_GIN_INDEX = """
DO $$
BEGIN
    BEGIN
        LOAD 'age';
        SET search_path = ag_catalog, "$user", public;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING
            'Apache AGE extension not available (%) — skipping GIN index drop.',
            SQLERRM;
        RETURN;
    END;

    DROP INDEX IF EXISTS worldview_graph."entity_properties_gin_idx";
    RAISE NOTICE 'Dropped AGE GIN index worldview_graph.entity_properties_gin_idx';
END;
$$
"""


def upgrade() -> None:
    """Create the AGE GIN index on ``(entity).properties`` (PLAN-0111 A; corrects 0049)."""
    op.execute(_CREATE_ENTITY_PROPERTIES_GIN_INDEX)


def downgrade() -> None:
    """Drop the AGE GIN index on ``(entity).properties`` (label data preserved)."""
    op.execute(_DROP_ENTITY_PROPERTIES_GIN_INDEX)
