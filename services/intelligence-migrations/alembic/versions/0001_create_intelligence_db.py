"""Create intelligence_db initial schema.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-22
"""

import calendar  # noqa: F401 — used inside Block H/K/L loops

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Block A — Extensions
    # -------------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # -------------------------------------------------------------------------
    # Block B — decay_class_config (FK target for relations + relation_type_registry)
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE decay_class_config (
    decay_class               VARCHAR(20) PRIMARY KEY,
    half_life_days            FLOAT,
    decay_alpha               FLOAT        NOT NULL,
    recompute_interval_minutes INT         NOT NULL,
    description               TEXT
)
""")
    op.execute("""
INSERT INTO decay_class_config VALUES
    ('PERMANENT',  NULL,   0.000000, 10080, 'Board membership, incorporation facts'),
    ('DURABLE',    730.0,  0.000950, 10080, 'Long-term contracts, credit ratings'),
    ('SLOW',       180.0,  0.003851, 1440,  'Supplier relationships, strategic partnerships'),
    ('MEDIUM',     60.0,   0.011552, 360,   'Market share claims, analyst ratings'),
    ('FAST',       14.0,   0.049510, 60,    'Sentiment signals, short-term price targets'),
    ('EPHEMERAL',  3.0,    0.231049, 15,    'Intraday momentum, real-time sentiment')
""")

    # -------------------------------------------------------------------------
    # Block C — model_registry
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE model_registry (
    registry_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id         VARCHAR(200) NOT NULL,
    provider         VARCHAR(50)  NOT NULL,
    capability       VARCHAR(50)  NOT NULL,
    version          VARCHAR(50),
    dimension        INT,
    max_input_tokens INT          NOT NULL,
    is_active        BOOLEAN      NOT NULL DEFAULT true,
    performance_tier VARCHAR(20)  NOT NULL DEFAULT 'PRIMARY',
    config           JSONB,
    registered_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (model_id, provider, version)
)
""")

    # -------------------------------------------------------------------------
    # Block D — prompt_templates (FK target for relation_summaries)
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE prompt_templates (
    template_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             VARCHAR(200) NOT NULL,
    version          INT          NOT NULL,
    capability       VARCHAR(50)  NOT NULL,
    template_text    TEXT         NOT NULL,
    output_schema    JSONB        NOT NULL,
    model_constraints JSONB,
    is_active        BOOLEAN      NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (name, version)
)
""")

    # -------------------------------------------------------------------------
    # Block E — canonical_entities + entity_aliases + entity_profile_embeddings
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE canonical_entities (
    entity_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name VARCHAR(500)  NOT NULL,
    entity_type    VARCHAR(50)   NOT NULL,
    isin           VARCHAR(20),
    ticker         VARCHAR(20),
    exchange       VARCHAR(20),
    metadata       JSONB,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
)
""")
    op.execute("""
CREATE INDEX idx_entities_ticker_exchange ON canonical_entities (ticker, exchange)
    WHERE ticker IS NOT NULL
""")
    op.execute("CREATE INDEX idx_entities_isin ON canonical_entities (isin) WHERE isin IS NOT NULL")
    op.execute("CREATE INDEX idx_entities_type ON canonical_entities (entity_type)")

    op.execute("""
CREATE TABLE entity_aliases (
    alias_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id   UUID        NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
    alias_text  VARCHAR(500) NOT NULL,
    alias_type  VARCHAR(30)  NOT NULL,
    source      VARCHAR(50),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
)
""")
    op.execute(
        "CREATE UNIQUE INDEX uidx_entity_aliases_exact ON entity_aliases (lower(alias_text)) WHERE alias_type = 'EXACT'"
    )
    op.execute("CREATE INDEX idx_entity_aliases_text ON entity_aliases USING gin (alias_text gin_trgm_ops)")
    op.execute("CREATE INDEX idx_entity_aliases_entity ON entity_aliases (entity_id)")

    op.execute("""
CREATE TABLE entity_profile_embeddings (
    embedding_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id         UUID        NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
    embedding         VECTOR(1024) NOT NULL,
    model_id          VARCHAR(200) NOT NULL,
    profile_text      TEXT,
    embedding_stale   BOOLEAN      NOT NULL DEFAULT false,
    last_refreshed_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (entity_id, model_id)
)
""")
    op.execute("""
CREATE INDEX idx_entity_profile_emb_hnsw ON entity_profile_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WHERE embedding_stale = false
""")

    # -------------------------------------------------------------------------
    # Block F — relations (HASH-partitioned x 8)
    # partition_key is GENERATED ALWAYS AS STORED — never include in INSERT
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE relations (
    relation_id              UUID         NOT NULL DEFAULT gen_random_uuid(),
    subject_entity_id        UUID         NOT NULL,
    canonical_type           VARCHAR(100) NOT NULL,
    object_entity_id         UUID         NOT NULL,
    semantic_mode            VARCHAR(20)  NOT NULL DEFAULT 'RELATION_STATE',
    decay_class              VARCHAR(20)  NOT NULL REFERENCES decay_class_config(decay_class),
    decay_alpha              FLOAT        NOT NULL,
    base_confidence          FLOAT        NOT NULL DEFAULT 0.5,
    confidence               FLOAT,
    confidence_stale         BOOLEAN      NOT NULL DEFAULT true,
    confidence_last_computed_at TIMESTAMPTZ,
    first_evidence_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    latest_evidence_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    evidence_count           INT          NOT NULL DEFAULT 0,
    valid_from               TIMESTAMPTZ,
    valid_to                 TIMESTAMPTZ,
    valid_to_confidence      FLOAT,
    valid_to_source          VARCHAR(30),
    invalidated_by_event_id  UUID,
    relation_period_type     VARCHAR(20)  NOT NULL DEFAULT 'ONGOING',
    strongest_contra_score   FLOAT        NOT NULL DEFAULT 0.0,
    contra_count_by_type     JSONB        NOT NULL DEFAULT '{}',
    latest_contra_at         TIMESTAMPTZ,
    contra_stale             BOOLEAN      NOT NULL DEFAULT false,
    summary_stale            BOOLEAN      NOT NULL DEFAULT true,
    partition_key            INT          NOT NULL
        GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 8) STORED,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (relation_id, subject_entity_id)
) PARTITION BY HASH (subject_entity_id)
""")

    for i in range(8):
        op.execute(f"""
CREATE TABLE relations_p{i} PARTITION OF relations
    FOR VALUES WITH (MODULUS 8, REMAINDER {i})
""")

    op.execute(
        "CREATE UNIQUE INDEX uidx_relations_triple ON relations (subject_entity_id, canonical_type, object_entity_id)"
    )
    op.execute("CREATE INDEX idx_relations_subject ON relations (subject_entity_id, canonical_type, confidence DESC)")
    op.execute("CREATE INDEX idx_relations_object ON relations (object_entity_id, canonical_type)")
    op.execute("""
CREATE INDEX idx_relations_stale_confidence ON relations (decay_class, latest_evidence_at DESC)
    WHERE confidence_stale = true
""")
    op.execute("""
CREATE INDEX idx_relations_stale_summary ON relations (confidence DESC, latest_evidence_at DESC)
    WHERE summary_stale = true
""")
    op.execute("""
CREATE INDEX idx_relations_valid ON relations (subject_entity_id, canonical_type)
    WHERE valid_to IS NULL AND relation_period_type = 'ONGOING'
""")

    # -------------------------------------------------------------------------
    # Block G — relation_evidence_raw (hot-path staging, append-only)
    # partition_key is GENERATED ALWAYS AS STORED — never include in INSERT
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE relation_evidence_raw (
    raw_id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_entity_id     UUID        NOT NULL,
    object_entity_id      UUID        NOT NULL,
    canonical_type        VARCHAR(100) NOT NULL,
    polarity              VARCHAR(20)  NOT NULL DEFAULT 'positive',
    claim_id              UUID,
    chunk_id              UUID,
    source_document_id    UUID         NOT NULL,
    extraction_confidence FLOAT        NOT NULL,
    source_trust_weight   FLOAT        NOT NULL DEFAULT 1.0,
    extracted_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    processed             BOOLEAN      NOT NULL DEFAULT false,
    processed_at          TIMESTAMPTZ,
    worker_claim_id       UUID,
    partition_key         INT          NOT NULL
        GENERATED ALWAYS AS (abs(hashtext(subject_entity_id::text)) % 8) STORED
)
""")
    op.execute("""
CREATE INDEX idx_raw_evidence_unprocessed ON relation_evidence_raw (extracted_at)
    WHERE processed = false
""")
    op.execute("CREATE INDEX idx_raw_evidence_subject ON relation_evidence_raw (subject_entity_id, extracted_at DESC)")
    op.execute("""
CREATE INDEX idx_raw_evidence_partition_unprocessed
    ON relation_evidence_raw (partition_key, extracted_at)
    WHERE processed = false
""")

    # -------------------------------------------------------------------------
    # Block H — relation_evidence (RANGE-partitioned by month, immutable)
    # Pre-seed 2024-01 through 2026-12 (36 partitions)
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE relation_evidence (
    evidence_id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_id           UUID        NOT NULL,
    doc_id                UUID        NOT NULL,
    chunk_id              UUID,
    evidence_text         TEXT,
    canonicalized_evidence_text TEXT,
    extraction_confidence FLOAT       NOT NULL,
    source_weight         FLOAT       NOT NULL DEFAULT 1.0,
    evidence_date         TIMESTAMPTZ NOT NULL,
    claim_id              UUID,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (evidence_date)
""")

    for year in range(2024, 2027):
        for month in range(1, 13):
            next_month = month + 1 if month < 12 else 1
            next_year = year if month < 12 else year + 1
            partition_name = f"relation_evidence_{year}_{month:02d}"
            op.execute(f"""
CREATE TABLE {partition_name} PARTITION OF relation_evidence
    FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
""")

    op.execute("CREATE INDEX idx_rel_evidence_relation ON relation_evidence (relation_id, evidence_date DESC)")
    op.execute("CREATE INDEX idx_rel_evidence_doc ON relation_evidence (doc_id)")
    op.execute("CREATE INDEX idx_rel_evidence_claim ON relation_evidence (claim_id) WHERE claim_id IS NOT NULL")

    # -------------------------------------------------------------------------
    # Block I — relation_contradiction_links
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE relation_contradiction_links (
    link_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_evidence_id UUID        NOT NULL REFERENCES relation_evidence(evidence_id),
    claim_id             UUID        NOT NULL,
    contradiction_type   VARCHAR(50) NOT NULL,
    strength             FLOAT       NOT NULL DEFAULT 1.0,
    detected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    invalidated_at       TIMESTAMPTZ,
    invalidation_reason  TEXT,
    UNIQUE (relation_evidence_id, claim_id)
)
""")
    op.execute("CREATE INDEX idx_contra_links_evidence ON relation_contradiction_links (relation_evidence_id)")
    op.execute("CREATE INDEX idx_contra_links_claim ON relation_contradiction_links (claim_id)")
    op.execute("""
CREATE INDEX idx_contra_links_active ON relation_contradiction_links (detected_at DESC)
    WHERE invalidated_at IS NULL
""")

    # -------------------------------------------------------------------------
    # Block J — relation_summaries (with HNSW index on summary_embedding)
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE relation_summaries (
    summary_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    relation_id        UUID        NOT NULL,
    summary_text       TEXT        NOT NULL,
    evidence_count     INT         NOT NULL,
    evidence_hash      VARCHAR(64) NOT NULL,
    summary_embedding  VECTOR(1024),
    embedding_model    VARCHAR(200),
    generated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_id           VARCHAR(200) NOT NULL,
    prompt_template_id UUID        NOT NULL REFERENCES prompt_templates(template_id),
    is_current         BOOLEAN     NOT NULL DEFAULT true,
    generation_trigger VARCHAR(50) NOT NULL
)
""")
    op.execute("""
CREATE UNIQUE INDEX uidx_relation_summaries_current ON relation_summaries (relation_id)
    WHERE is_current = true
""")
    op.execute("CREATE INDEX idx_relation_summaries_relation ON relation_summaries (relation_id, generated_at DESC)")
    op.execute("""
CREATE INDEX idx_relation_summary_emb_hnsw ON relation_summaries
    USING hnsw (summary_embedding vector_cosine_ops)
    WHERE is_current = true AND summary_embedding IS NOT NULL
""")

    # -------------------------------------------------------------------------
    # Block K — claims (RANGE-partitioned by month)
    # Pre-seed 2024-01 through 2026-12 (36 partitions)
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE claims (
    claim_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                UUID        NOT NULL,
    chunk_id              UUID,
    claimer_entity_id     UUID,
    subject_entity_id     UUID,
    claim_type            VARCHAR(100) NOT NULL,
    polarity              VARCHAR(20)  NOT NULL DEFAULT 'positive',
    claim_text            TEXT         NOT NULL,
    extraction_confidence FLOAT        NOT NULL,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
) PARTITION BY RANGE (created_at)
""")
    for year in range(2024, 2027):
        for month in range(1, 13):
            next_month = month + 1 if month < 12 else 1
            next_year = year if month < 12 else year + 1
            op.execute(f"""
CREATE TABLE claims_{year}_{month:02d} PARTITION OF claims
    FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
""")
    op.execute("""
CREATE INDEX idx_claims_contradiction_detection ON claims
    (subject_entity_id, claim_type, polarity, created_at DESC)
    WHERE subject_entity_id IS NOT NULL AND polarity != 'neutral'
""")
    op.execute("""
CREATE INDEX idx_claims_by_claimer ON claims
    (claimer_entity_id, claim_type, created_at DESC)
    WHERE claimer_entity_id IS NOT NULL
""")

    # -------------------------------------------------------------------------
    # Block L — events (RANGE-partitioned by month)
    # Pre-seed 2024-01 through 2026-12 (36 partitions)
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE events (
    event_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                UUID        NOT NULL,
    subject_entity_id     UUID,
    event_type            VARCHAR(100) NOT NULL,
    event_date            TIMESTAMPTZ,
    event_text            TEXT,
    extraction_confidence FLOAT        NOT NULL,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
) PARTITION BY RANGE (created_at)
""")
    for year in range(2024, 2027):
        for month in range(1, 13):
            next_month = month + 1 if month < 12 else 1
            next_year = year if month < 12 else year + 1
            op.execute(f"""
CREATE TABLE events_{year}_{month:02d} PARTITION OF events
    FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
""")
    op.execute("""
CREATE INDEX idx_events_subject ON events (subject_entity_id, event_type, event_date DESC)
    WHERE subject_entity_id IS NOT NULL
""")

    # -------------------------------------------------------------------------
    # Block M — embedding_migration_state
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE embedding_migration_state (
    migration_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    model_from         VARCHAR(200) NOT NULL,
    model_to           VARCHAR(200) NOT NULL,
    target_table       VARCHAR(100) NOT NULL,
    phase              VARCHAR(30)  NOT NULL,
    backfill_progress  FLOAT        NOT NULL DEFAULT 0.0,
    started_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at       TIMESTAMPTZ,
    notes              TEXT
)
""")

    # -------------------------------------------------------------------------
    # Block N — provisional_entity_queue
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE provisional_entity_queue (
    queue_id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    mention_text       VARCHAR(500) NOT NULL,
    mention_class      VARCHAR(50)  NOT NULL,
    context_snippet    TEXT,
    status             VARCHAR(20)  NOT NULL DEFAULT 'pending',
    assigned_entity_id UUID,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at        TIMESTAMPTZ,
    retry_count        INT          NOT NULL DEFAULT 0
)
""")
    op.execute("CREATE INDEX idx_provisional_pending ON provisional_entity_queue (created_at) WHERE status = 'pending'")

    # -------------------------------------------------------------------------
    # Block O — outbox_events + dead_letter_queue
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE outbox_events (
    event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic          VARCHAR(200)  NOT NULL,
    partition_key  TEXT          NOT NULL,
    payload_avro   BYTEA         NOT NULL,
    status         VARCHAR(20)   NOT NULL DEFAULT 'pending',
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    dispatched_at  TIMESTAMPTZ,
    retry_count    INT           NOT NULL DEFAULT 0,
    failed_at      TIMESTAMPTZ
)
""")
    op.execute("CREATE INDEX idx_outbox_intel_pending ON outbox_events (created_at) WHERE status = 'pending'")

    op.execute("""
CREATE TABLE dead_letter_queue (
    dlq_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_event_id UUID         NOT NULL,
    topic             VARCHAR(200) NOT NULL,
    payload_avro      BYTEA        NOT NULL,
    error_detail      TEXT,
    status            VARCHAR(20)  NOT NULL DEFAULT 'failed',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ,
    resolution_note   TEXT
)
""")

    # -------------------------------------------------------------------------
    # Block P — relation_type_registry (20-row seed from PRD §8)
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE relation_type_registry (
    type_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_type  VARCHAR(100) NOT NULL UNIQUE,
    semantic_mode   VARCHAR(20)  NOT NULL,
    decay_class     VARCHAR(20)  NOT NULL REFERENCES decay_class_config(decay_class),
    base_confidence FLOAT        NOT NULL DEFAULT 0.5,
    description     TEXT,
    is_active       BOOLEAN      NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
)
""")
    op.execute("""
INSERT INTO relation_type_registry (canonical_type, semantic_mode, decay_class, base_confidence, description)
VALUES
    ('employs',              'RELATION_STATE',  'DURABLE',   0.70, 'Board, C-suite roles; event-invalidatable'),
    ('board_member_of',      'RELATION_STATE',  'DURABLE',   0.75, NULL),
    ('subsidiary_of',        'RELATION_STATE',  'SLOW',      0.65, NULL),
    ('acquired_by',          'RELATION_STATE',  'PERMANENT', 0.85, 'Finalized by merger_completed event'),
    ('listed_on',            'RELATION_STATE',  'DURABLE',   0.80, 'Invalidated by delisted event'),
    ('supplier_of',          'RELATION_STATE',  'SLOW',      0.55, NULL),
    ('partner_of',           'RELATION_STATE',  'SLOW',      0.50, NULL),
    ('competes_with',        'RELATION_STATE',  'MEDIUM',    0.45, NULL),
    ('regulates',            'RELATION_STATE',  'DURABLE',   0.75, NULL),
    ('headquartered_in',     'RELATION_STATE',  'PERMANENT', 0.80, NULL),
    ('analyst_rating',       'TEMPORAL_CLAIM',  'FAST',      0.60, 'Historically anchored; not validity-gated'),
    ('market_share_claim',   'TEMPORAL_CLAIM',  'MEDIUM',    0.50, NULL),
    ('price_target',         'TEMPORAL_CLAIM',  'FAST',      0.55, NULL),
    ('earnings_guidance',    'TEMPORAL_CLAIM',  'MEDIUM',    0.60, NULL),
    ('sentiment_signal',     'TEMPORAL_CLAIM',  'EPHEMERAL', 0.45, NULL),
    ('credit_rating',        'TEMPORAL_CLAIM',  'DURABLE',   0.70, NULL),
    ('investment_in',        'RELATION_STATE',  'MEDIUM',    0.60, NULL),
    ('owns_stake_in',        'RELATION_STATE',  'MEDIUM',    0.65, NULL),
    ('issues_debt',          'TEMPORAL_CLAIM',  'MEDIUM',    0.55, NULL),
    ('produces',             'RELATION_STATE',  'SLOW',      0.60, 'Commodity production')
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS relation_type_registry CASCADE")
    op.execute("DROP TABLE IF EXISTS dead_letter_queue CASCADE")
    op.execute("DROP TABLE IF EXISTS outbox_events CASCADE")
    op.execute("DROP TABLE IF EXISTS provisional_entity_queue CASCADE")
    op.execute("DROP TABLE IF EXISTS embedding_migration_state CASCADE")
    op.execute("DROP TABLE IF EXISTS events CASCADE")
    op.execute("DROP TABLE IF EXISTS claims CASCADE")
    op.execute("DROP TABLE IF EXISTS relation_summaries CASCADE")
    op.execute("DROP TABLE IF EXISTS relation_contradiction_links CASCADE")
    op.execute("DROP TABLE IF EXISTS relation_evidence CASCADE")
    op.execute("DROP TABLE IF EXISTS relation_evidence_raw CASCADE")
    op.execute("DROP TABLE IF EXISTS relations CASCADE")
    op.execute("DROP TABLE IF EXISTS entity_profile_embeddings CASCADE")
    op.execute("DROP TABLE IF EXISTS entity_aliases CASCADE")
    op.execute("DROP TABLE IF EXISTS canonical_entities CASCADE")
    op.execute("DROP TABLE IF EXISTS prompt_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS model_registry CASCADE")
    op.execute("DROP TABLE IF EXISTS decay_class_config CASCADE")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
