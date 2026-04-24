"""Create temporal_events and entity_event_exposures if not present.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-24

Background:
  Migration 0004 defined the temporal_events and entity_event_exposures DDL.
  Deployments where the postgres volume predates the 0004 DDL but has
  alembic_version already at 0006 (stamped from a prior migration run) will
  not have had these tables created. This migration creates them idempotently
  using CREATE TABLE IF NOT EXISTS, ensuring a clean state regardless of
  volume history.

  Safe to run multiple times (all DDL uses IF NOT EXISTS / DO NOTHING).
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


_CREATE_TEMPORAL_EVENTS = """
CREATE TABLE IF NOT EXISTS temporal_events (
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
        event_type IN ('geopolitical','regulatory','macro','sanctions','natural_disaster','other')
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
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_scope_from ON temporal_events (scope, active_from)",
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_from_until ON temporal_events (active_from, active_until)",
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_type_scope ON temporal_events (event_type, scope)",
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_region_from ON temporal_events (region, active_from DESC)",
    """
CREATE UNIQUE INDEX IF NOT EXISTS uidx_temporal_events_natural_key
    ON temporal_events (event_type, region, title, date_trunc('day', timezone('UTC', active_from)))
""",
]

_CREATE_ENTITY_EVENT_EXPOSURES = """
CREATE TABLE IF NOT EXISTS entity_event_exposures (
    exposure_id    UUID          NOT NULL,
    event_id       UUID          NOT NULL,
    entity_id      UUID          NOT NULL,
    exposure_type  TEXT          NOT NULL,
    evidence_text  TEXT,
    confidence     NUMERIC(4,3)  NOT NULL,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT pk_entity_event_exposures PRIMARY KEY (exposure_id),
    CONSTRAINT fk_entity_event_exposures_event
        FOREIGN KEY (event_id) REFERENCES temporal_events (event_id) ON DELETE CASCADE,
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
    "CREATE INDEX IF NOT EXISTS idx_entity_event_exposures_event ON entity_event_exposures (event_id)",
    "CREATE INDEX IF NOT EXISTS idx_entity_event_exposures_entity ON entity_event_exposures (entity_id)",
]


def upgrade() -> None:
    # Idempotent creation — safe if tables already exist (fresh installs)
    op.execute(_CREATE_TEMPORAL_EVENTS)
    for stmt in _CREATE_TEMPORAL_EVENTS_INDEXES:
        op.execute(stmt)
    op.execute(_CREATE_ENTITY_EVENT_EXPOSURES)
    for stmt in _CREATE_ENTITY_EVENT_EXPOSURES_INDEXES:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS entity_event_exposures")
    op.execute("DROP TABLE IF EXISTS temporal_events")
