"""Create nlp_db initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-03-22
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. pgvector extension (required for VECTOR type and HNSW indexes)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. sections
    op.execute("""
        CREATE TABLE sections (
            section_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id         UUID        NOT NULL,
            section_index  INT         NOT NULL,
            section_type   VARCHAR(50),
            title          TEXT,
            char_start     INT         NOT NULL,
            char_end       INT         NOT NULL,
            token_count    INT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_sections_doc ON sections (doc_id, section_index)")

    # 3. chunks (references sections)
    op.execute("""
        CREATE TABLE chunks (
            chunk_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id              UUID        NOT NULL,
            section_id          UUID        NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
            chunk_index         INT         NOT NULL,
            char_start          INT         NOT NULL,
            char_end            INT         NOT NULL,
            token_count         INT         NOT NULL,
            sentence_start_idx  INT,
            sentence_end_idx    INT,
            speaker             TEXT,
            heading_path        TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_chunks_doc ON chunks (doc_id, chunk_index)")
    op.execute("CREATE INDEX idx_chunks_section ON chunks (section_id)")

    # 4. entity_mentions (references sections)
    op.execute("""
        CREATE TABLE entity_mentions (
            mention_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id                UUID        NOT NULL,
            section_id            UUID REFERENCES sections(section_id) ON DELETE SET NULL,
            mention_text          TEXT        NOT NULL,
            mention_class         VARCHAR(50) NOT NULL,
            confidence            FLOAT       NOT NULL,
            char_start            INT         NOT NULL,
            char_end              INT         NOT NULL,
            resolved_entity_id    UUID,
            resolution_confidence FLOAT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_entity_mentions_doc ON entity_mentions (doc_id, mention_class)")
    op.execute(
        "CREATE INDEX idx_entity_mentions_resolved"
        " ON entity_mentions (resolved_entity_id)"
        " WHERE resolved_entity_id IS NOT NULL"
    )

    # 5. chunk_entity_mentions (junction table)
    op.execute("""
        CREATE TABLE chunk_entity_mentions (
            chunk_id   UUID NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
            mention_id UUID NOT NULL REFERENCES entity_mentions(mention_id) ON DELETE CASCADE,
            PRIMARY KEY (chunk_id, mention_id)
        )
    """)

    # 6. chunk_embeddings — VECTOR(1024) with HNSW partial index
    op.execute("""
        CREATE TABLE chunk_embeddings (
            embedding_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            chunk_id         UUID         NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
            embedding        VECTOR(1024) NOT NULL,
            model_id         VARCHAR(200) NOT NULL,
            embedding_status VARCHAR(20)  NOT NULL DEFAULT 'ready',
            expires_at       TIMESTAMPTZ,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            UNIQUE (chunk_id, model_id)
        )
    """)
    # HNSW indexes must be created via op.execute — Alembic does not support USING hnsw natively
    op.execute("""
        CREATE INDEX idx_chunk_emb_hnsw ON chunk_embeddings
            USING hnsw (embedding vector_cosine_ops)
            WHERE (expires_at IS NULL OR expires_at > now())
    """)
    op.execute("CREATE INDEX idx_chunk_emb_pending ON chunk_embeddings (created_at) WHERE embedding_status = 'pending'")
    op.execute("CREATE INDEX idx_chunk_emb_expires ON chunk_embeddings (expires_at) WHERE expires_at IS NOT NULL")

    # 7. section_embeddings — separate HNSW index (chunk and section ANN must not pollute each other)
    op.execute("""
        CREATE TABLE section_embeddings (
            embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            section_id   UUID         NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
            embedding    VECTOR(1024) NOT NULL,
            model_id     VARCHAR(200) NOT NULL,
            expires_at   TIMESTAMPTZ,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            UNIQUE (section_id, model_id)
        )
    """)
    op.execute("""
        CREATE INDEX idx_section_emb_hnsw ON section_embeddings
            USING hnsw (embedding vector_cosine_ops)
            WHERE (expires_at IS NULL OR expires_at > now())
    """)

    # 8. routing_decisions
    op.execute("""
        CREATE TABLE routing_decisions (
            decision_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id              UUID        NOT NULL,
            routing_tier        VARCHAR(20) NOT NULL,
            composite_score     FLOAT       NOT NULL,
            feature_scores_json JSONB       NOT NULL,
            decided_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_routing_doc ON routing_decisions (doc_id)")

    # 9. outbox_events
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
    op.execute("CREATE INDEX idx_outbox_s6_pending ON outbox_events (created_at) WHERE status = 'pending'")

    # 10. dead_letter_queue
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


def downgrade() -> None:
    # Drop in reverse FK dependency order; HNSW indexes are dropped automatically with their tables
    op.execute("DROP TABLE IF EXISTS dead_letter_queue")
    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute("DROP TABLE IF EXISTS routing_decisions")
    op.execute("DROP TABLE IF EXISTS section_embeddings")
    op.execute("DROP TABLE IF EXISTS chunk_embeddings")
    op.execute("DROP TABLE IF EXISTS chunk_entity_mentions")
    op.execute("DROP TABLE IF EXISTS entity_mentions")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS sections")
