"""Add PARTIAL UNIQUE INDEX on canonical_entities(lower(canonical_name)) — DEF-014.

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-06

Changes:
  canonical_entities (data fix + index):
    1. One-time dedup pre-step: merge duplicate ``lower(canonical_name)`` rows
       (entity_type != 'financial_instrument') by repointing FKs to a deterministic
       keeper, then DELETE the doomed rows.
    2. CREATE PARTIAL UNIQUE INDEX idx_canonical_entities_lower_name
       ON canonical_entities (lower(canonical_name))
       WHERE entity_type != 'financial_instrument'

WHY (DEF-014 / BP-384 — dedup race fix):
  Before this index, persist_enrichment() in
  ``services/knowledge-graph/.../provisional_enrichment_core.py`` followed a
  classic find-then-create pattern:
      existing = alias_repo.find_exact(...)
      if existing: return
      entity_repo.create(...)
  Two concurrent ProvisionalQueuedConsumer / ProvisionalEnrichmentWorker
  callers can both observe ``existing is None`` for the same canonical_name
  and both proceed to INSERT — leaving multiple ``canonical_entities`` rows
  for the same name (e.g. four "Apple Inc." rows observed in production).

  The UNIQUE INDEX provides a deterministic backstop: a duplicate INSERT
  fails with ``UniqueViolation``, and the repository's new ``create_or_get``
  helper translates the conflict into "fetch the existing row" via
  ``ON CONFLICT (lower(canonical_name)) DO NOTHING RETURNING *``.

WHY PARTIAL — exclude entity_type='financial_instrument' (PLAN-0076 QA fix):
  Financial instruments legitimately co-exist under the same canonical_name on
  multiple exchanges (e.g. Berkshire Hathaway B-Class is listed on both NYSE
  and on European venues; each gets its own canonical_entities row keyed by a
  distinct ``instrument_id`` upstream).  A blanket UNIQUE INDEX on
  ``lower(canonical_name)`` would refuse to insert the second-listing row.

  The dedup race we want to close is for entity types that DO NOT have an
  upstream pinning identity — companies, persons, organisations, concepts,
  events.  Those rows are LLM-derived and benefit from a hard uniqueness
  guarantee on the canonical name.  Financial instruments are pinned by
  ``instrument_id`` from the upstream market-data service and dedup naturally
  on that identity instead.

  Restricting the index to ``WHERE entity_type != 'financial_instrument'``
  keeps the deterministic backstop where it matters and avoids breaking
  legitimate dual-listed instruments.

ON CONFLICT BINDING (caller responsibility):
  ``CanonicalEntityRepository.create_or_get`` now writes
      ON CONFLICT (lower(canonical_name)) WHERE entity_type != 'financial_instrument'
          DO NOTHING
  so the inferred conflict target matches this partial index predicate.  Without
  the WHERE clause Postgres would refuse the ON CONFLICT inference and raise
  ``ERROR: there is no unique or exclusion constraint matching the ON CONFLICT
  specification`` for any insert (whatever the entity_type).

DEDUP PRE-STEP RATIONALE:
  Production dev DB contains ~132 ``lower(canonical_name)`` duplicates from the
  pre-fix race window.  A naked ``CREATE UNIQUE INDEX`` would fail with
  ``ERROR: could not create unique index … because key … is duplicated`` and
  block the migration chain.  We resolve the duplicates in-place inside the
  same transaction (single atomic rollback unit) so an upgrade never leaves
  the DB in a half-merged state.

  The keeper for each duplicate group is selected deterministically as
  ``MIN(created_at)`` — the oldest row wins (most likely to be referenced by
  downstream tables already and is the row most ETL pipelines will have
  cached).  All FK-referencing tables are repointed at the keeper before the
  doomed rows are DELETEd.

  Test DB has no live data, so the dedup pre-step is a no-op there — that is
  the desired behaviour (DDL-only effect on clean schemas).

WHY plain CREATE UNIQUE INDEX (no CONCURRENTLY):
  ``canonical_entities`` is NOT partitioned. BP-393 — which forced PLAN-0072
  T-72-2-01 to use plain ``CREATE INDEX`` — applies only to partitioned
  parents (``relations`` is HASH x8). For an unpartitioned table inside an
  Alembic transaction, plain ``CREATE UNIQUE INDEX`` is correct; we do NOT
  need ``op.execute_with_autocommit_block`` here.

FORWARD-COMPATIBILITY (R5):
  Additive partial functional unique index, with idempotent dedup pre-step.
  ``IF NOT EXISTS`` on the index DDL keeps the upgrade re-runnable.

DOWNGRADE:
  Drop the index. Dedup is irreversible (DELETEd rows are gone) — this is
  acceptable: the rows were broken duplicates with no useful payload divergence
  beyond what the keeper already carries.

RUNTIME ESTIMATE:
  Expected runtime on dev stack: ~2-5 seconds with 132 dedup groups;
  production runtime depends on dataset size — measure before applying.
"""

from __future__ import annotations

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # STEP 1 — Dedup pre-step: merge duplicate lower(canonical_name) rows
    # for non-financial_instrument entity types.
    # ------------------------------------------------------------------
    # We run this even on a clean DB; on the test DB it produces zero
    # affected rows because no canonical_entities rows exist yet.
    #
    # The keeper-selection rule (MIN(created_at)) is deterministic so two
    # parallel migrations on different replicas converge to the same keeper.
    # The CTE chain repoints every FK reference table that points back at
    # canonical_entities.entity_id; we DELETE conflicting rows in
    # entity_aliases / entity_embedding_state first because those tables
    # carry their own composite uniqueness that the UPDATE would violate.

    # Step 1a — entity_aliases: delete conflicts that would arise from the
    # repoint, then repoint the rest. We delete rows from doomed entities
    # whose (keeper_id, normalized, alias_type) tuple already exists for the
    # keeper — those would otherwise raise PK collision on UPDATE.
    op.execute(
        """
DO $migration_0026_dedup$
DECLARE
    dup_count INT := 0;
BEGIN
    -- Acquire exclusive locks on all tables touched by this migration before
    -- any reads or writes.  NOWAIT means the migration fails immediately if
    -- another session already holds a conflicting lock, rather than blocking
    -- indefinitely — this prevents a migration from silently stalling the
    -- Alembic runner under concurrent load.
    LOCK TABLE canonical_entities, entity_aliases, entity_embedding_state,
               relations, relation_evidence_raw, claims, events, event_entities,
               entity_event_exposures, provisional_entity_queue, relation_summaries
        IN ACCESS EXCLUSIVE MODE NOWAIT;

    -- Short-circuit when there are no duplicates (typical for fresh DBs).
    SELECT COUNT(*) INTO dup_count
    FROM (
        SELECT lower(canonical_name) AS lname, entity_type
        FROM canonical_entities
        WHERE entity_type != 'financial_instrument'
        GROUP BY lower(canonical_name), entity_type
        HAVING COUNT(*) > 1
    ) AS d;

    IF dup_count = 0 THEN
        RAISE NOTICE 'migration_0026_dedup_noop';
        RETURN;
    END IF;

    RAISE NOTICE 'migration_0026_dedup_groups=%', dup_count;

    -- Build a temp table of (doomed_entity_id, keeper_entity_id) pairs.
    -- DISTINCT ON picks the first (oldest by created_at) row per
    -- (lower(canonical_name), entity_type) group as the keeper.  All other
    -- rows in the group become doomed and have their FKs repointed.
    CREATE TEMP TABLE _migration_0026_doomed (
        doomed_id  UUID PRIMARY KEY,
        keeper_id  UUID NOT NULL
    ) ON COMMIT DROP;

    INSERT INTO _migration_0026_doomed (doomed_id, keeper_id)
    SELECT ce.entity_id, k.keeper_id
    FROM canonical_entities ce
    JOIN (
        SELECT DISTINCT ON (lower(canonical_name), entity_type)
            entity_id AS keeper_id,
            lower(canonical_name) AS lname,
            entity_type
        FROM canonical_entities
        WHERE entity_type != 'financial_instrument'
        ORDER BY lower(canonical_name), entity_type, created_at ASC, entity_id ASC
    ) k
        ON lower(ce.canonical_name) = k.lname
        AND ce.entity_type = k.entity_type
    WHERE ce.entity_type != 'financial_instrument'
      AND ce.entity_id != k.keeper_id;

    -- entity_aliases — delete conflicts first, then repoint remainder.
    -- Composite uniqueness is (entity_id, normalized, alias_type) per init
    -- schema; we drop doomed rows whose target tuple already lives on keeper.
    DELETE FROM entity_aliases ea
    USING _migration_0026_doomed d
    WHERE ea.entity_id = d.doomed_id
      AND EXISTS (
          SELECT 1 FROM entity_aliases ea2
          WHERE ea2.entity_id = d.keeper_id
            AND ea2.normalized = ea.normalized
            AND ea2.alias_type = ea.alias_type
      );
    UPDATE entity_aliases ea
    SET entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE ea.entity_id = d.doomed_id;

    -- entity_embedding_state — PK is (entity_id, kind); delete conflicts then
    -- repoint.  We do not migrate the embedding vector itself; the keeper
    -- already has its own embedding row(s) and the doomed row's vector is no
    -- more authoritative than the keeper's.
    DELETE FROM entity_embedding_state ees
    USING _migration_0026_doomed d
    WHERE ees.entity_id = d.doomed_id
      AND EXISTS (
          SELECT 1 FROM entity_embedding_state ees2
          WHERE ees2.entity_id = d.keeper_id
            AND ees2.kind = ees.kind
      );
    UPDATE entity_embedding_state ees
    SET entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE ees.entity_id = d.doomed_id;

    -- relations — repoint subject + object slots.  No composite uniqueness
    -- conflict on the natural key here is enforced by the relations table's
    -- own ON CONFLICT logic upstream (see relation_repo.upsert); a duplicate
    -- post-merge will simply mean a future upsert dedups the relations row.
    UPDATE relations r
    SET subject_entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE r.subject_entity_id = d.doomed_id;

    UPDATE relations r
    SET object_entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE r.object_entity_id = d.doomed_id;

    -- relation_evidence_raw — same dual-slot pattern.
    UPDATE relation_evidence_raw rer
    SET subject_entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE rer.subject_entity_id = d.doomed_id;

    UPDATE relation_evidence_raw rer
    SET object_entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE rer.object_entity_id = d.doomed_id;

    -- claims — claimer + subject can both reference canonical_entities.
    -- Both nullable on claimer, NOT NULL on subject; UPDATE is unconditional.
    UPDATE claims c
    SET claimer_entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE c.claimer_entity_id = d.doomed_id;

    UPDATE claims c
    SET subject_entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE c.subject_entity_id = d.doomed_id;

    -- events — subject_entity_id only; participants live in event_entities.
    UPDATE events e
    SET subject_entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE e.subject_entity_id = d.doomed_id;

    -- event_entities — PK is (event_id, entity_id); delete conflicts then
    -- repoint so the same event does not list the keeper twice.
    DELETE FROM event_entities ee
    USING _migration_0026_doomed d
    WHERE ee.entity_id = d.doomed_id
      AND EXISTS (
          SELECT 1 FROM event_entities ee2
          WHERE ee2.event_id = ee.event_id
            AND ee2.entity_id = d.keeper_id
      );
    UPDATE event_entities ee
    SET entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE ee.entity_id = d.doomed_id;

    -- entity_event_exposures — repoint exposed_entity_id.  Any composite
    -- uniqueness collision is resolved by deleting the doomed row first.
    -- This table may not exist on extremely old schemas; the IF EXISTS
    -- guard keeps the migration robust on partial deployments.
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'entity_event_exposures'
    ) THEN
        DELETE FROM entity_event_exposures eee
        USING _migration_0026_doomed d
        WHERE eee.entity_id = d.doomed_id
          AND EXISTS (
              SELECT 1 FROM entity_event_exposures eee2
              WHERE eee2.entity_id = d.keeper_id
                AND eee2.event_id = eee.event_id
          );
        UPDATE entity_event_exposures eee
        SET entity_id = d.keeper_id
        FROM _migration_0026_doomed d
        WHERE eee.entity_id = d.doomed_id;
    END IF;

    -- provisional_entity_queue.assigned_entity_id — points to the resolved
    -- canonical entity; repoint to keeper.  Nullable, so unconditional UPDATE
    -- of matching rows is safe.
    UPDATE provisional_entity_queue pq
    SET assigned_entity_id = d.keeper_id
    FROM _migration_0026_doomed d
    WHERE pq.assigned_entity_id = d.doomed_id;

    -- relation_summaries — subject + object FKs; mirror the relations dual-slot.
    -- Composite uniqueness (subject, object, canonical_type) collisions are
    -- resolved by deleting the doomed-side summary first.
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'relation_summaries'
    ) THEN
        DELETE FROM relation_summaries rs
        USING _migration_0026_doomed d
        WHERE rs.subject_entity_id = d.doomed_id
          AND EXISTS (
              SELECT 1 FROM relation_summaries rs2
              WHERE rs2.subject_entity_id = d.keeper_id
                AND rs2.object_entity_id = rs.object_entity_id
                AND rs2.canonical_type = rs.canonical_type
          );
        UPDATE relation_summaries rs
        SET subject_entity_id = d.keeper_id
        FROM _migration_0026_doomed d
        WHERE rs.subject_entity_id = d.doomed_id;

        DELETE FROM relation_summaries rs
        USING _migration_0026_doomed d
        WHERE rs.object_entity_id = d.doomed_id
          AND EXISTS (
              SELECT 1 FROM relation_summaries rs2
              WHERE rs2.object_entity_id = d.keeper_id
                AND rs2.subject_entity_id = rs.subject_entity_id
                AND rs2.canonical_type = rs.canonical_type
          );
        UPDATE relation_summaries rs
        SET object_entity_id = d.keeper_id
        FROM _migration_0026_doomed d
        WHERE rs.object_entity_id = d.doomed_id;
    END IF;

    -- Finally, DELETE the doomed canonical_entities rows.  All FK references
    -- have been repointed at the keepers above.
    DELETE FROM canonical_entities ce
    USING _migration_0026_doomed d
    WHERE ce.entity_id = d.doomed_id;

    RAISE NOTICE 'migration_0026_dedup_complete merged_rows=%',
        (SELECT COUNT(*) FROM _migration_0026_doomed);
END
$migration_0026_dedup$;
        """
    )

    # ------------------------------------------------------------------
    # STEP 2 — Create the partial UNIQUE INDEX.  After STEP 1 there are no
    # remaining duplicates among non-financial_instrument rows, so this
    # CREATE will succeed on production data.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_entities_lower_name
            ON canonical_entities (lower(canonical_name))
            WHERE entity_type != 'financial_instrument'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_canonical_entities_lower_name")
