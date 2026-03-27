"""Create content_store_db initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-03-22

Creates all 7 tables matching the ORM models exactly (guard BP-008, BP-019):
  - documents
  - minhash_signatures
  - minhash_entity_mentions
  - outbox_events
  - dead_letter_queue
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
            doc_id           UUID        PRIMARY KEY,
            source_type      VARCHAR(50) NOT NULL,
            source_url       TEXT,
            title            TEXT,
            published_at     TIMESTAMPTZ,
            ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            content_hash     VARCHAR(64) NOT NULL,
            normalized_hash  VARCHAR(64) NOT NULL,
            status           VARCHAR(20) NOT NULL DEFAULT 'stored',
            dedup_result     VARCHAR(30) NOT NULL DEFAULT 'unique',
            minio_silver_key TEXT,
            word_count       INT,
            language         VARCHAR(10) DEFAULT 'en',
            corroborates_doc_id UUID,
            is_backfill      BOOLEAN     NOT NULL DEFAULT FALSE,
            UNIQUE (content_hash)
        )
    """)
    op.execute("CREATE INDEX idx_documents_normalized_hash ON documents (normalized_hash)")
    op.execute("CREATE INDEX idx_documents_source_published ON documents (source_type, published_at DESC)")
    op.execute(
        "CREATE INDEX idx_documents_corroborates"
        " ON documents (corroborates_doc_id)"
        " WHERE corroborates_doc_id IS NOT NULL"
    )

    # 2. minhash_signatures — INTEGER[] is non-negotiable (never BYTEA)
    op.execute("""
        CREATE TABLE minhash_signatures (
            sig_id        UUID PRIMARY KEY,
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
    op.execute("CREATE INDEX idx_minhash_mentions_hash ON minhash_entity_mentions (mention_text_hash, sig_id)")
    op.execute(
        "CREATE INDEX idx_minhash_mentions_entity"
        " ON minhash_entity_mentions (entity_id, sig_id)"
        " WHERE entity_id IS NOT NULL"
    )

    # 4. outbox_events — matches OutboxEventModel exactly (BP-008, BP-019)
    op.execute("""
        CREATE TABLE outbox_events (
            id             UUID        PRIMARY KEY,
            aggregate_type TEXT        NOT NULL,
            aggregate_id   UUID        NOT NULL,
            event_type     TEXT        NOT NULL,
            topic          TEXT        NOT NULL DEFAULT 'content.article.stored.v1',
            payload        JSONB       NOT NULL DEFAULT '{}',
            status         TEXT        NOT NULL DEFAULT 'pending',
            lease_owner    TEXT,
            leased_until   TIMESTAMPTZ,
            attempts       SMALLINT    NOT NULL DEFAULT 0,
            max_attempts   SMALLINT    NOT NULL DEFAULT 5,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            dispatched_at  TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE INDEX ix_outbox_claimable ON outbox_events (status, leased_until)
        WHERE status IN ('pending', 'processing')
    """)

    # 5. dead_letter_queue — includes payload_json for requeue (M-2 fix)
    op.execute("""
        CREATE TABLE dead_letter_queue (
            dlq_id            UUID        PRIMARY KEY,
            original_event_id UUID        NOT NULL,
            topic             TEXT        NOT NULL,
            payload_avro      BYTEA       NOT NULL,
            payload_json      JSONB,
            error_detail      TEXT,
            status            TEXT        NOT NULL DEFAULT 'failed',
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
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
