"""Create content_store_db initial schema.

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
    # 1. documents — referenced by minhash_signatures FK
    op.execute("""
        CREATE TABLE documents (
            doc_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_type      VARCHAR(50)  NOT NULL,
            source_url       TEXT,
            title            TEXT,
            published_at     TIMESTAMPTZ,
            ingested_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            content_hash     VARCHAR(64)  NOT NULL,
            normalized_hash  VARCHAR(64)  NOT NULL,
            status           VARCHAR(20)  NOT NULL DEFAULT 'stored',
            minio_silver_key TEXT         NOT NULL,
            word_count       INT,
            language         VARCHAR(10)  DEFAULT 'en',
            UNIQUE (content_hash)
        )
    """)
    op.execute("CREATE INDEX idx_documents_normalized_hash ON documents (normalized_hash)")
    op.execute("CREATE INDEX idx_documents_source_published" " ON documents (source_type, published_at DESC)")

    # 2. minhash_signatures — INTEGER[] is non-negotiable (never BYTEA)
    op.execute("""
        CREATE TABLE minhash_signatures (
            sig_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id        UUID NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
            signature     INTEGER[] NOT NULL,
            shingle_type  VARCHAR(50) NOT NULL DEFAULT 'word_bigram_char3gram',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (doc_id)
        )
    """)
    op.execute("CREATE INDEX idx_minhash_sig_created ON minhash_signatures (created_at DESC)")

    # 3. minhash_entity_mentions — entity_id is a logical FK to intelligence_db.canonical_entities
    #    NO Postgres-level FK constraint on entity_id
    op.execute("""
        CREATE TABLE minhash_entity_mentions (
            sig_id              UUID   NOT NULL REFERENCES minhash_signatures(sig_id) ON DELETE CASCADE,
            mention_text_hash   BIGINT NOT NULL,
            mention_text        VARCHAR(300),
            entity_id           UUID,
            resolution_status   VARCHAR(20) NOT NULL DEFAULT 'UNRESOLVED',
            resolved_at         TIMESTAMPTZ,
            PRIMARY KEY (sig_id, mention_text_hash)
        )
    """)
    op.execute("CREATE INDEX idx_minhash_mentions_hash" " ON minhash_entity_mentions (mention_text_hash, sig_id)")
    op.execute(
        "CREATE INDEX idx_minhash_mentions_entity"
        " ON minhash_entity_mentions (entity_id, sig_id)"
        " WHERE entity_id IS NOT NULL"
    )

    # 4. outbox_events
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
    op.execute("CREATE INDEX idx_outbox_s5_pending ON outbox_events (created_at)" " WHERE status = 'pending'")

    # 5. dead_letter_queue
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
    op.execute("DROP TABLE IF EXISTS dead_letter_queue")
    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute("DROP TABLE IF EXISTS minhash_entity_mentions")
    op.execute("DROP TABLE IF EXISTS minhash_signatures")
    op.execute("DROP TABLE IF EXISTS documents")
