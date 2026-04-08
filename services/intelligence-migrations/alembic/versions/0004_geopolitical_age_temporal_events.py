"""AGE extension, temporal_events, entity_event_exposures, new relation types.

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-04-08

Changes (PRD-0018 §6.4):
  relations:
    - ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    - CREATE INDEX idx_relations_updated_at ON relations (updated_at DESC)

  Apache AGE graph extension:
    - CREATE EXTENSION IF NOT EXISTS age
    - Create worldview_graph with Entity + TemporalEvent vertex labels
    - Create 27 relation-type edge labels (20 from 0001 + 4 from 0002 + 3 new) + EVENT_EXPOSES

  temporal_events (new table):
    - Stores geopolitical/regulatory/macro/sanctions/natural_disaster events
    - Lifecycle: PENDING_ACTIVE → ACTIVE → ENDED → RESIDUAL → EXPIRED
    - Natural-key unique index on (event_type, region, title, date_trunc('day', active_from))

  entity_event_exposures (new table):
    - Maps entities to temporal events with exposure type and confidence
    - GLOBAL-scope events link to sector/industry entities only (PRD-0018 §6.2)

  relation_type_registry:
    - 3 new rows: has_executive, revenue_from_country, operates_in_country

Downtime: zero — all changes are additive.

NOTE on AGE session setup:
  Every DB session that issues AGE Cypher must execute before any Cypher call:
    LOAD 'age';
    SET search_path = ag_catalog, "$user", public;
  This migration does this once at the start of upgrade(). Application code
  must also call these at the start of each session (enforced in AgeSyncWorker
  and CypherPathUseCase).
"""

from alembic import op

revision = "d4e5f6a1b2c3"
down_revision = "c3d4e5f6a1b2"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

_ADD_RELATIONS_UPDATED_AT = """
ALTER TABLE relations
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
"""

_CREATE_RELATIONS_UPDATED_AT_IDX = """
CREATE INDEX IF NOT EXISTS idx_relations_updated_at
    ON relations (updated_at DESC)
"""

_CREATE_AGE_EXTENSION = "CREATE EXTENSION IF NOT EXISTS age"

_LOAD_AGE = "LOAD 'age'"

# After SET search_path, AGE functions (create_graph, create_vlabel, etc.)
# are callable without the ag_catalog. prefix.
_SET_AGE_SEARCH_PATH = 'SET search_path = ag_catalog, "$user", public'

_CREATE_GRAPH = "SELECT * FROM create_graph('worldview_graph')"

# Vertex labels
_CREATE_VERTEX_LABELS = [
    "SELECT * FROM create_vlabel('worldview_graph', 'Entity')",
    "SELECT * FROM create_vlabel('worldview_graph', 'TemporalEvent')",
]

# Edge labels — 20 from migration 0001 + 4 from migration 0002 + 3 new (0004) + EVENT_EXPOSES
_CREATE_EDGE_LABELS = [
    # --- migration 0001 relation types ---
    "SELECT * FROM create_elabel('worldview_graph', 'EMPLOYS')",
    "SELECT * FROM create_elabel('worldview_graph', 'BOARD_MEMBER_OF')",
    "SELECT * FROM create_elabel('worldview_graph', 'SUBSIDIARY_OF')",
    "SELECT * FROM create_elabel('worldview_graph', 'ACQUIRED_BY')",
    "SELECT * FROM create_elabel('worldview_graph', 'LISTED_ON')",
    "SELECT * FROM create_elabel('worldview_graph', 'SUPPLIER_OF')",
    "SELECT * FROM create_elabel('worldview_graph', 'PARTNER_OF')",
    "SELECT * FROM create_elabel('worldview_graph', 'COMPETES_WITH')",
    "SELECT * FROM create_elabel('worldview_graph', 'REGULATES')",
    "SELECT * FROM create_elabel('worldview_graph', 'HEADQUARTERED_IN')",
    "SELECT * FROM create_elabel('worldview_graph', 'ANALYST_RATING')",
    "SELECT * FROM create_elabel('worldview_graph', 'MARKET_SHARE_CLAIM')",
    "SELECT * FROM create_elabel('worldview_graph', 'PRICE_TARGET')",
    "SELECT * FROM create_elabel('worldview_graph', 'EARNINGS_GUIDANCE')",
    "SELECT * FROM create_elabel('worldview_graph', 'SENTIMENT_SIGNAL')",
    "SELECT * FROM create_elabel('worldview_graph', 'CREDIT_RATING')",
    "SELECT * FROM create_elabel('worldview_graph', 'INVESTMENT_IN')",
    "SELECT * FROM create_elabel('worldview_graph', 'OWNS_STAKE_IN')",
    "SELECT * FROM create_elabel('worldview_graph', 'ISSUES_DEBT')",
    "SELECT * FROM create_elabel('worldview_graph', 'PRODUCES')",
    # --- migration 0002 relation types ---
    "SELECT * FROM create_elabel('worldview_graph', 'IS_IN_SECTOR')",
    "SELECT * FROM create_elabel('worldview_graph', 'IS_IN_INDUSTRY')",
    "SELECT * FROM create_elabel('worldview_graph', 'EARNINGS_RELEASED')",
    "SELECT * FROM create_elabel('worldview_graph', 'CORPORATE_ACTION')",
    # --- migration 0004 new relation types ---
    "SELECT * FROM create_elabel('worldview_graph', 'HAS_EXECUTIVE')",
    "SELECT * FROM create_elabel('worldview_graph', 'REVENUE_FROM_COUNTRY')",
    "SELECT * FROM create_elabel('worldview_graph', 'OPERATES_IN_COUNTRY')",
    # --- TemporalEvent → Entity exposure edge ---
    "SELECT * FROM create_elabel('worldview_graph', 'EVENT_EXPOSES')",
]

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
    # scope + active_from: supports scope-filtered listing with date range
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_scope_from ON temporal_events (scope, active_from)",
    # temporal range queries: active_from to active_until window queries
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_from_until ON temporal_events (active_from, active_until)",
    # type + scope filter: event_type AND scope combined filters
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_type_scope ON temporal_events (event_type, scope)",
    # region + recency: query-time global event injection by region (most recent first)
    "CREATE INDEX IF NOT EXISTS idx_temporal_events_region_from ON temporal_events (region, active_from DESC)",
    # natural deduplication key for EODHD economic events
    # date_trunc('day', active_from) ensures same-day re-runs don't create duplicates
    """
CREATE UNIQUE INDEX IF NOT EXISTS uidx_temporal_events_natural_key
    ON temporal_events (event_type, region, title, date_trunc('day', active_from))
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

_SEED_NEW_RELATION_TYPES = """
INSERT INTO relation_type_registry
    (canonical_type, semantic_mode, decay_class, base_confidence, description)
VALUES
    ('has_executive',        'RELATION_STATE',  'DURABLE', 0.90,
     'Company employs person in executive/board role (EODHD Insider Transactions API)'),
    ('revenue_from_country', 'TEMPORAL_CLAIM',  'MEDIUM',  0.80,
     'Company derives significant revenue from a country (EODHD fundamentals)'),
    ('operates_in_country',  'RELATION_STATE',  'SLOW',    0.80,
     'Company has operational presence in a country (EODHD fundamentals)')
ON CONFLICT (canonical_type) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Downgrade helpers
# ---------------------------------------------------------------------------

_DROP_NEW_RELATION_TYPES = """
DELETE FROM relation_type_registry
    WHERE canonical_type IN ('has_executive', 'revenue_from_country', 'operates_in_country')
"""

_DROP_ENTITY_EVENT_EXPOSURES = "DROP TABLE IF EXISTS entity_event_exposures"
_DROP_TEMPORAL_EVENTS = "DROP TABLE IF EXISTS temporal_events"

_DROP_GRAPH = "SELECT * FROM drop_graph('worldview_graph', true)"

_DROP_AGE_EXTENSION = "DROP EXTENSION IF EXISTS age"

_DROP_RELATIONS_UPDATED_AT_IDX = "DROP INDEX IF EXISTS idx_relations_updated_at"
_DROP_RELATIONS_UPDATED_AT = "ALTER TABLE relations DROP COLUMN IF EXISTS updated_at"


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ── Step 1: relations.updated_at (needed by AgeSyncWorker watermark sync) ──
    op.execute(_ADD_RELATIONS_UPDATED_AT)
    op.execute(_CREATE_RELATIONS_UPDATED_AT_IDX)

    # ── Step 2: AGE extension + graph setup ──────────────────────────────────
    # CREATE EXTENSION first, then LOAD + search_path (LOAD requires the extension to exist)
    op.execute(_CREATE_AGE_EXTENSION)
    op.execute(_LOAD_AGE)
    op.execute(_SET_AGE_SEARCH_PATH)

    op.execute(_CREATE_GRAPH)

    for stmt in _CREATE_VERTEX_LABELS:
        op.execute(stmt)

    for stmt in _CREATE_EDGE_LABELS:
        op.execute(stmt)

    # ── Step 3: temporal_events table ────────────────────────────────────────
    op.execute(_CREATE_TEMPORAL_EVENTS)
    for stmt in _CREATE_TEMPORAL_EVENTS_INDEXES:
        op.execute(stmt)

    # ── Step 4: entity_event_exposures table ─────────────────────────────────
    op.execute(_CREATE_ENTITY_EVENT_EXPOSURES)
    for stmt in _CREATE_ENTITY_EVENT_EXPOSURES_INDEXES:
        op.execute(stmt)

    # ── Step 5: seed new relation types ─────────────────────────────────────
    op.execute(_SEED_NEW_RELATION_TYPES)


def downgrade() -> None:
    # Reverse order: seed data → tables → AGE graph → extension → column

    op.execute(_DROP_NEW_RELATION_TYPES)
    op.execute(_DROP_ENTITY_EVENT_EXPOSURES)
    op.execute(_DROP_TEMPORAL_EVENTS)

    # AGE graph operations require LOAD + search_path even for downgrade
    op.execute(_LOAD_AGE)
    op.execute(_SET_AGE_SEARCH_PATH)
    op.execute(_DROP_GRAPH)
    op.execute(_DROP_AGE_EXTENSION)

    op.execute(_DROP_RELATIONS_UPDATED_AT_IDX)
    op.execute(_DROP_RELATIONS_UPDATED_AT)
