"""Unit tests for ORM model definitions (no DB required)."""

from __future__ import annotations

import pytest
from content_store.infrastructure.db.models import (
    Base,
    DeadLetterQueueModel,
    DedupHashModel,
    DocumentModel,
    DuplicateClusterModel,
    MinHashEntityMentionModel,
    MinHashSignatureModel,
    OutboxEventModel,
    ProcessedEventModel,
)
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import ARRAY

pytestmark = pytest.mark.unit


class TestTableNames:
    def test_all_eight_tables_registered(self) -> None:
        expected = {
            "documents",
            "dedup_hashes",
            "duplicate_clusters",
            "minhash_signatures",
            "minhash_entity_mentions",
            "outbox_events",
            "dead_letter_queue",
            "processed_events",
        }
        actual = set(Base.metadata.tables.keys())
        assert expected == actual


class TestDocumentModel:
    def test_primary_key(self) -> None:
        mapper = inspect(DocumentModel)
        pk_cols = [c.name for c in mapper.primary_key]
        assert pk_cols == ["doc_id"]

    def test_content_hash_unique(self) -> None:
        col = DocumentModel.__table__.c.content_hash
        assert col.unique is True

    def test_nullable_fields(self) -> None:
        table = DocumentModel.__table__
        assert table.c.source_url.nullable is True
        assert table.c.title.nullable is True
        assert table.c.published_at.nullable is True
        assert table.c.minio_silver_key.nullable is True
        assert table.c.word_count.nullable is True
        assert table.c.corroborates_doc_id.nullable is True

    def test_required_fields(self) -> None:
        table = DocumentModel.__table__
        assert table.c.source_type.nullable is False
        assert table.c.content_hash.nullable is False
        assert table.c.normalized_hash.nullable is False
        assert table.c.status.nullable is False
        assert table.c.dedup_result.nullable is False
        assert table.c.is_backfill.nullable is False


class TestDedupHashModel:
    def test_unique_constraint(self) -> None:
        constraints = [c.name for c in DedupHashModel.__table__.constraints if hasattr(c, "name")]
        assert "uq_dedup_hashes_type_value" in constraints

    def test_cascade_delete(self) -> None:
        fk = next(iter(DedupHashModel.__table__.c.doc_id.foreign_keys))
        assert fk.ondelete == "CASCADE"


class TestDuplicateClusterModel:
    def test_unique_pair_constraint(self) -> None:
        constraints = [c.name for c in DuplicateClusterModel.__table__.constraints if hasattr(c, "name")]
        assert "uq_duplicate_clusters_pair" in constraints


class TestMinHashSignatureModel:
    def test_signature_is_integer_array(self) -> None:
        """CRITICAL: signature must be INTEGER[], never BYTEA."""
        col = MinHashSignatureModel.__table__.c.signature
        assert isinstance(col.type, ARRAY)
        # The item_type of the ARRAY should be Integer
        assert col.type.item_type.__class__.__name__ == "Integer"

    def test_doc_id_unique(self) -> None:
        col = MinHashSignatureModel.__table__.c.doc_id
        assert col.unique is True

    def test_cascade_delete(self) -> None:
        fk = next(iter(MinHashSignatureModel.__table__.c.doc_id.foreign_keys))
        assert fk.ondelete == "CASCADE"


class TestMinHashEntityMentionModel:
    def test_composite_primary_key(self) -> None:
        mapper = inspect(MinHashEntityMentionModel)
        pk_cols = sorted(c.name for c in mapper.primary_key)
        assert pk_cols == ["mention_text_hash", "sig_id"]

    def test_entity_id_no_fk_constraint(self) -> None:
        """entity_id is a logical FK — NO Postgres constraint."""
        col = MinHashEntityMentionModel.__table__.c.entity_id
        assert len(list(col.foreign_keys)) == 0

    def test_entity_id_nullable(self) -> None:
        col = MinHashEntityMentionModel.__table__.c.entity_id
        assert col.nullable is True


class TestOutboxEventModel:
    def test_primary_key(self) -> None:
        mapper = inspect(OutboxEventModel)
        pk_cols = [c.name for c in mapper.primary_key]
        assert pk_cols == ["id"]


class TestDeadLetterQueueModel:
    def test_primary_key(self) -> None:
        mapper = inspect(DeadLetterQueueModel)
        pk_cols = [c.name for c in mapper.primary_key]
        assert pk_cols == ["dlq_id"]


class TestProcessedEventModel:
    def test_primary_key(self) -> None:
        mapper = inspect(ProcessedEventModel)
        pk_cols = [c.name for c in mapper.primary_key]
        assert pk_cols == ["event_id"]

    def test_processed_at_not_nullable(self) -> None:
        col = ProcessedEventModel.__table__.c.processed_at
        assert col.nullable is False

    def test_processed_at_has_server_default(self) -> None:
        col = ProcessedEventModel.__table__.c.processed_at
        assert col.server_default is not None
