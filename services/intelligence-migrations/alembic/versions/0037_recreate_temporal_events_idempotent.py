"""Recreate temporal_events + entity_event_exposures if missing — D-P3-002 / D-P3-003 fix.

Revision ID: 0037
Revises: 0036
Create Date: 2026-05-09

WHY THIS MIGRATION EXISTS:
  Audit ``docs/audits/2026-05-09-audit-P3-freshness.md`` (D-P3-002 / D-P3-003)
  surfaced that ``earnings_calendar`` and ``economic_events`` consumers were
  silently dropping every Kafka message because the gold target table
  ``temporal_events`` did not exist in ``intelligence_db``::

      relation "temporal_events" does not exist
      [SQL: INSERT INTO temporal_events (event_id, event_type, scope, region, ...)]

  The same root cause cascades to the related dataset consumers
  (insider_transactions, macro_indicator) and to S7 main service queries —
  see D-P1-002 / D-P1-003 / D-P1-004 in the P1 audit.

  Migration 0004 originally declared ``temporal_events`` and
  ``entity_event_exposures``; migration 0007 added an ``IF NOT EXISTS``
  re-creation as a fallback for volumes that pre-dated 0004. Despite both,
  the live ``intelligence_db`` snapshot at audit time (alembic_version='0036',
  Postgres volume ~7 days old) is missing both tables. Most likely the volume
  was restored from a backup that pre-dated 0004 + 0007 had been applied with
  ``CREATE TABLE IF NOT EXISTS`` short-circuiting because alembic_version was
  already past 0007. Either way: the cure is to attempt a defensive re-creation
  guarded by ``CREATE TABLE IF NOT EXISTS``.

WHAT THIS MIGRATION DOES:
  1. ``CREATE TABLE IF NOT EXISTS temporal_events (...)`` — same shape as 0007
     but with the ``corporate`` event_type widening from 0018 already applied.
  2. ``CREATE INDEX IF NOT EXISTS ...`` for the four lookup indexes plus the
     functional unique index ``uidx_temporal_events_natural_key``.
  3. ``CREATE TABLE IF NOT EXISTS entity_event_exposures (...)`` and its two
     indexes.
  4. If ``temporal_events`` already had the old (pre-0018) CHECK constraint
     installed, drop and re-add the widened version. Idempotent — uses
     ``DROP CONSTRAINT IF EXISTS``.

IDEMPOTENT (R5 / forward-compatible):
  Every DDL statement uses ``IF NOT EXISTS`` / ``IF EXISTS``. Running this
  migration on a clean DB (where 0004 + 0007 + 0018 already created
  everything) is a NO-OP.

DOWNGRADE:
  Pure NO-OP — this migration only re-creates tables that 0004 + 0007 own.
  We deliberately do NOT drop the tables on rollback because 0004 + 0007 are
  earlier revisions that own them, and dropping here would weaken the
  invariant on rollback to 0036 → 0037 path.
"""

from __future__ import annotations

from alembic import op

# Alembic identifiers — required for chain detection.
revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# DDL fragments (kept as module-level constants to make grep / diff trivial)
# ---------------------------------------------------------------------------

# WHY this CHECK already includes 'corporate':
#   Migration 0018 widened the original 6-value CHECK to add 'corporate' so
#   the EarningsCalendarDatasetConsumer can write rows. If the live DB lost
#   ``temporal_events`` it most likely also lost the widened CHECK, so we
#   include the 7-value list directly here. A subsequent re-run of 0018 is
#   a NO-OP (DROP CONSTRAINT IF EXISTS / ADD CONSTRAINT will short-circuit
#   when the constraint name already exists).
_CREATE_TEMPORAL_EVENTS = """
CREATE TABLE IF NOT EXISTS public.temporal_events (
    event_id              UUID          NOT NULL,
    event_type            TEXT          NOT NULL,
    scope                 TEXT          NOT NULL,
    region                TEXT,
    title                 TEXT          NOT NULL,
    description           TEXT,
    source_article_ids    UUID[]        DEFAULT '{}',
    source_url            TEXT,
    active_from           TIMESTAMPTZ   NOT NULL,
    active_until          TIMESTAMPTZ,
    residual_impact_days  INT           NOT NULL DEFAULT 90,
    confidence            NUMERIC(4,3)  NOT NULL,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT pk_temporal_events PRIMARY KEY (event_id),
    CONSTRAINT ck_temporal_event_type CHECK (
        event_type IN (
            'geopolitical','regulatory','macro','sanctions',
            'natural_disaster','other','corporate'
        )
    ),
    CONSTRAINT ck_temporal_scope CHECK (
        scope IN ('LOCAL','REGIONAL','NATIONAL','GLOBAL')
    ),
    CONSTRAINT ck_temporal_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT ck_temporal_residual_days CHECK (residual_impact_days >= 0),
    CONSTRAINT ck_temporal_title_length CHECK (length(title) <= 500)
)
"""

_CREATE_TEMPORAL_EVENTS_INDEXES = [
    # WHY fully-qualify ``public.``: Apache AGE adds ``ag_catalog`` to the
    # search path of any session that has loaded the extension, and AGE
    # publishes its own ``temporal_events`` label there. Bare references would
    # ambiguously resolve depending on whether AGE was loaded in the
    # connection that ran the migration.
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_scope_from ON public.temporal_events (scope, active_from)",
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_from_until ON public.temporal_events (active_from, active_until)",
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_type_scope ON public.temporal_events (event_type, scope)",
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_region_from ON public.temporal_events (region, active_from DESC)",
    # Functional unique index for natural-key dedup. Same expression as 0007;
    # PG ignores duplicates of the index name so re-running is safe.
    """
CREATE UNIQUE INDEX IF NOT EXISTS uidx_temporal_events_natural_key
    ON public.temporal_events (event_type, region, title, date_trunc('day', timezone('UTC', active_from)))
""",
]

_CREATE_ENTITY_EVENT_EXPOSURES = """
CREATE TABLE IF NOT EXISTS public.entity_event_exposures (
    exposure_id    UUID          NOT NULL,
    event_id       UUID          NOT NULL,
    entity_id      UUID          NOT NULL,
    exposure_type  TEXT          NOT NULL,
    evidence_text  TEXT,
    confidence     NUMERIC(4,3)  NOT NULL,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT pk_entity_event_exposures PRIMARY KEY (exposure_id),
    CONSTRAINT fk_entity_event_exposures_event
        FOREIGN KEY (event_id) REFERENCES public.temporal_events (event_id) ON DELETE CASCADE,
    CONSTRAINT ck_exposure_type CHECK (
        exposure_type IN (
            'directly_affected','operationally_impacted','supply_chain',
            'revenue_geography','sector_exposure'
        )
    ),
    CONSTRAINT ck_exposure_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT uq_entity_event_exposures UNIQUE (event_id, entity_id, exposure_type)
)
"""

_CREATE_ENTITY_EVENT_EXPOSURES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_entity_event_exposures_event ON public.entity_event_exposures (event_id)",
    "CREATE INDEX IF NOT EXISTS idx_entity_event_exposures_entity ON public.entity_event_exposures (entity_id)",
]


# ---------------------------------------------------------------------------
# Constraint-repair fragments — only fire when ``temporal_events`` already
# existed before this migration and the CHECK constraint had not yet been
# widened by 0018. Wrapped in DO blocks so they short-circuit cleanly when
# the constraint is already at the new shape.
# ---------------------------------------------------------------------------

_REPAIR_EVENT_TYPE_CHECK = """
DO $migration_0037_repair$
DECLARE
    has_corporate BOOLEAN;
BEGIN
    -- Skip the repair entirely if public.temporal_events does not exist (will
    -- be created above with the correct CHECK in this same migration).
    --
    -- WHY filter on namespace=public: Apache AGE installs its own
    -- ``temporal_events`` label in the ``ag_catalog`` schema, so a bare
    -- ``relname='temporal_events'`` lookup matches the AGE label and reports
    -- a false positive on databases with the AGE extension active.
    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE c.relname = 'temporal_events'
          AND n.nspname = 'public'
    ) THEN
        RETURN;
    END IF;

    -- Inspect the existing CHECK constraint definition for 'corporate'.
    SELECT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        JOIN pg_namespace n ON t.relnamespace = n.oid
        WHERE t.relname = 'temporal_events'
          AND n.nspname = 'public'
          AND c.conname = 'ck_temporal_event_type'
          AND pg_get_constraintdef(c.oid) LIKE '%corporate%'
    )
    INTO has_corporate;

    IF NOT has_corporate THEN
        ALTER TABLE public.temporal_events DROP CONSTRAINT IF EXISTS ck_temporal_event_type;
        ALTER TABLE public.temporal_events
            ADD CONSTRAINT ck_temporal_event_type CHECK (
                event_type IN (
                    'geopolitical','regulatory','macro','sanctions',
                    'natural_disaster','other','corporate'
                )
            );
    END IF;
END
$migration_0037_repair$;
"""


def upgrade() -> None:
    # 1. Re-create temporal_events if missing. CREATE TABLE IF NOT EXISTS is
    #    idempotent — fresh installs that have already run 0004/0007 see a NO-OP.
    op.execute(_CREATE_TEMPORAL_EVENTS)
    for stmt in _CREATE_TEMPORAL_EVENTS_INDEXES:
        op.execute(stmt)

    # 2. Re-create entity_event_exposures (FK target now guaranteed to exist).
    op.execute(_CREATE_ENTITY_EVENT_EXPOSURES)
    for stmt in _CREATE_ENTITY_EVENT_EXPOSURES_INDEXES:
        op.execute(stmt)

    # 3. Repair the event_type CHECK if it was created without 'corporate'.
    #    This handles the rare case where temporal_events did exist (so the
    #    CREATE TABLE above was a no-op) but the 0018 widening never landed.
    op.execute(_REPAIR_EVENT_TYPE_CHECK)


def downgrade() -> None:
    # NO-OP: the tables touched here are owned by migrations 0004 + 0007, not
    # by this revision. Dropping them on downgrade-to-0036 would weaken the
    # invariant required by 0028's PRIMARY KEY assertion at the next upgrade.
    pass
