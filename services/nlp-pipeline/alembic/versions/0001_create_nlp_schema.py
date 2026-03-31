"""Create nlp_db initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-03-27

This migration creates the complete nlp_db schema for S6 NLP Pipeline.
It ONLY manages nlp_db — intelligence_db is owned by intelligence-migrations.

PRD reference: §6.4.3
ORM models: nlp_pipeline.infrastructure.nlp_db.models (BP-008: must stay in sync)
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. pgvector extension (required for VECTOR type and HNSW indexes)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. sections — structural sections of a document
    op.execute("""
        CREATE TABLE sections (
            section_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id         UUID        NOT NULL,
            section_index  INT         NOT NULL,
            section_type   TEXT,
            title          TEXT,
            speaker        TEXT,
            char_start     INT         NOT NULL,
            char_end       INT         NOT NULL,
            token_count    INT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_sections_doc ON sections (doc_id, section_index)")

    # 3. chunks (sentence-aware, references sections)
    op.execute("""
        CREATE TABLE chunks (
            chunk_id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
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

    # 4. chunk_embeddings — vector(1024) with HNSW partial index
    #    HNSW predicate: embedding_status = 'ready' (expires_at filter applied at query time — now() is not IMMUTABLE)
    op.execute("""
        CREATE TABLE chunk_embeddings (
            embedding_id     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            chunk_id         UUID         NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
            embedding        VECTOR(1024) NOT NULL,
            model_id         TEXT         NOT NULL,
            embedding_status TEXT         NOT NULL DEFAULT 'ready',
            expires_at       TIMESTAMPTZ,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            UNIQUE (chunk_id, model_id)
        )
    """)
    # HNSW indexes must be created via op.execute — Alembic does not natively support USING hnsw
    op.execute("""
        CREATE INDEX idx_chunk_emb_hnsw ON chunk_embeddings
            USING hnsw (embedding vector_cosine_ops)
            WHERE embedding_status = 'ready'
    """)
    op.execute("CREATE INDEX idx_chunk_emb_pending ON chunk_embeddings (created_at) WHERE embedding_status = 'pending'")
    op.execute("CREATE INDEX idx_chunk_emb_expires ON chunk_embeddings (expires_at) WHERE expires_at IS NOT NULL")

    # 5. section_embeddings — separate HNSW index (chunk and section ANN must not mix)
    op.execute("""
        CREATE TABLE section_embeddings (
            embedding_id UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            section_id   UUID         NOT NULL REFERENCES sections(section_id) ON DELETE CASCADE,
            embedding    VECTOR(1024) NOT NULL,
            model_id     TEXT         NOT NULL,
            expires_at   TIMESTAMPTZ,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            UNIQUE (section_id, model_id)
        )
    """)
    op.execute("""
        CREATE INDEX idx_section_emb_hnsw ON section_embeddings
            USING hnsw (embedding vector_cosine_ops)
    """)

    # 6. entity_mentions (references sections; resolution_stage set by Block 9)
    op.execute("""
        CREATE TABLE entity_mentions (
            mention_id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id                UUID        NOT NULL,
            section_id            UUID        REFERENCES sections(section_id) ON DELETE SET NULL,
            mention_text          TEXT        NOT NULL,
            mention_class         TEXT        NOT NULL,
            confidence            FLOAT       NOT NULL,
            char_start            INT         NOT NULL,
            char_end              INT         NOT NULL,
            resolved_entity_id    UUID,
            resolution_confidence FLOAT,
            resolution_stage      INT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_entity_mentions_doc ON entity_mentions (doc_id, mention_class)")
    op.execute(
        "CREATE INDEX idx_entity_mentions_resolved ON entity_mentions (resolved_entity_id) "
        "WHERE resolved_entity_id IS NOT NULL"
    )

    # 7. chunk_entity_mentions (junction table)
    op.execute("""
        CREATE TABLE chunk_entity_mentions (
            chunk_id   UUID NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
            mention_id UUID NOT NULL REFERENCES entity_mentions(mention_id) ON DELETE CASCADE,
            PRIMARY KEY (chunk_id, mention_id)
        )
    """)

    # 8. mention_resolutions — per-mention cascade audit trail (PRD §6.4.3)
    op.execute("""
        CREATE TABLE mention_resolutions (
            resolution_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            mention_id          UUID        NOT NULL
                                    REFERENCES entity_mentions(mention_id) ON DELETE CASCADE,
            stage               INT         NOT NULL,
            candidate_entity_id UUID,
            score               FLOAT       NOT NULL,
            is_winner           BOOLEAN     NOT NULL DEFAULT false,
            metadata            JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_mention_resolutions_mention ON mention_resolutions (mention_id)")

    # 9. document_entity_stats — aggregate NER stats per document (PRD §6.4.3)
    op.execute("""
        CREATE TABLE document_entity_stats (
            doc_id                  UUID        PRIMARY KEY,
            distinct_mention_count  INT         NOT NULL DEFAULT 0,
            high_conf_mention_count INT         NOT NULL DEFAULT 0,
            type_distribution       JSONB       NOT NULL DEFAULT '{}',
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # 10. routing_decisions (final_routing_tier set after Stage 2 novelty correction)
    op.execute("""
        CREATE TABLE routing_decisions (
            decision_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id              UUID        NOT NULL,
            routing_tier        TEXT        NOT NULL,
            final_routing_tier  TEXT,
            composite_score     FLOAT       NOT NULL,
            feature_scores_json JSONB       NOT NULL,
            decided_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_routing_doc ON routing_decisions (doc_id)")

    # 11. outbox_events
    op.execute("""
        CREATE TABLE outbox_events (
            event_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            topic          TEXT        NOT NULL,
            partition_key  TEXT        NOT NULL,
            payload_avro   BYTEA       NOT NULL,
            status         TEXT        NOT NULL DEFAULT 'pending',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            dispatched_at  TIMESTAMPTZ,
            retry_count    INT         NOT NULL DEFAULT 0,
            failed_at      TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_outbox_s6_pending ON outbox_events (created_at) WHERE status = 'pending'")

    # 12. dead_letter_queue
    op.execute("""
        CREATE TABLE dead_letter_queue (
            dlq_id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            original_event_id UUID        NOT NULL,
            topic             TEXT        NOT NULL,
            payload_avro      BYTEA       NOT NULL,
            error_detail      TEXT,
            status            TEXT        NOT NULL DEFAULT 'failed',
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at       TIMESTAMPTZ,
            resolution_note   TEXT
        )
    """)


def downgrade() -> None:
    # Drop in reverse FK dependency order; HNSW indexes are dropped with their tables
    op.execute("DROP TABLE IF EXISTS dead_letter_queue")
    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute("DROP TABLE IF EXISTS routing_decisions")
    op.execute("DROP TABLE IF EXISTS document_entity_stats")
    op.execute("DROP TABLE IF EXISTS mention_resolutions")
    op.execute("DROP TABLE IF EXISTS chunk_entity_mentions")
    op.execute("DROP TABLE IF EXISTS entity_mentions")
    op.execute("DROP TABLE IF EXISTS section_embeddings")
    op.execute("DROP TABLE IF EXISTS chunk_embeddings")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS sections")
