"""DDL-vs-ORM alignment tests for nlp_db — guards against BP-008 and BP-019.

Parses Alembic migration DDL and compares column names against
the SQLAlchemy ORM metadata. Ensures no drift between what the
migration creates and what the application expects.

Coverage rule: ALL tables in nlp_db must have a test here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from nlp_pipeline.infrastructure.nlp_db.models import (
    ArticlePriceImpactModel,
    ChunkEmbeddingModel,
    ChunkEntityMentionModel,
    ChunkModel,
    DeadLetterQueueModel,
    DocumentEntityStatsModel,
    DocumentSourceMetadataModel,
    EmbeddingPendingModel,
    EntityMentionModel,
    MentionResolutionModel,
    OutboxEventModel,
    RoutingDecisionModel,
    SectionEmbeddingModel,
    SectionModel,
)
from sqlalchemy import inspect as sa_inspect

pytestmark = pytest.mark.unit

_MIGRATION_DIR = Path(__file__).parent.parent.parent.parent / "alembic/versions"


def _extract_ddl_columns(migration_text: str, table_name: str) -> set[str]:
    """Extract column names from CREATE TABLE and ALTER TABLE ADD COLUMN statements."""
    pattern = rf"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+{table_name}\s*\("
    match = re.search(pattern, migration_text, re.IGNORECASE)
    if not match:
        return set()

    # Walk forward counting parens to find the balanced closing paren
    start = match.end()
    depth = 1
    pos = start
    while pos < len(migration_text) and depth > 0:
        if migration_text[pos] == "(":
            depth += 1
        elif migration_text[pos] == ")":
            depth -= 1
        pos += 1

    body = migration_text[start : pos - 1]
    columns: set[str] = set()
    for line in body.split("\n"):
        line = line.strip().rstrip(",")
        if not line:
            continue
        upper = line.upper()
        if any(
            upper.startswith(kw)
            for kw in (
                "PRIMARY KEY",
                "UNIQUE",
                "CONSTRAINT",
                "FOREIGN KEY",
                "CHECK",
                "REFERENCES",
            )
        ):
            continue
        parts = line.split()
        if parts:
            columns.add(parts[0].strip('"'))

    # Also collect columns added via ALTER TABLE ... ADD COLUMN (raw SQL)
    alter_pattern = rf"ALTER\s+TABLE\s+{table_name}\s+ADD\s+COLUMN\s+(\w+)"
    for m in re.finditer(alter_pattern, migration_text, re.IGNORECASE):
        columns.add(m.group(1))

    # Also collect columns added via Alembic op.add_column() calls
    # Pattern: op.add_column("table_name", sa.Column("col_name", ...))
    alembic_pattern = rf'op\.add_column\(\s*"{table_name}"\s*,\s*sa\.Column\(\s*"(\w+)"'
    for m in re.finditer(alembic_pattern, migration_text):
        columns.add(m.group(1))

    return columns


def _get_orm_columns(model: type) -> set[str]:
    """Return column *names* (not Python attribute names) from a SQLAlchemy model."""
    mapper = sa_inspect(model)
    return {col.key for col in mapper.columns}  # type: ignore[union-attr]


def _read_all_migrations() -> str:
    texts = []
    for path in sorted(_MIGRATION_DIR.glob("*.py")):
        texts.append(path.read_text())
    return "\n".join(texts)


def _assert_aligned(table_name: str, model: type) -> None:
    migration_text = _read_all_migrations()
    ddl_cols = _extract_ddl_columns(migration_text, table_name)
    orm_cols = _get_orm_columns(model)

    missing_in_ddl = orm_cols - ddl_cols
    extra_in_ddl = ddl_cols - orm_cols

    assert not missing_in_ddl, f"[{table_name}] ORM columns missing from DDL: {missing_in_ddl}"
    assert not extra_in_ddl, f"[{table_name}] DDL columns not in ORM: {extra_in_ddl}"


class TestSectionsDDLAlignment:
    def test_sections_ddl_matches_orm(self) -> None:
        _assert_aligned("sections", SectionModel)


class TestChunksDDLAlignment:
    def test_chunks_ddl_matches_orm(self) -> None:
        _assert_aligned("chunks", ChunkModel)


class TestChunkEmbeddingsDDLAlignment:
    def test_chunk_embeddings_ddl_matches_orm(self) -> None:
        _assert_aligned("chunk_embeddings", ChunkEmbeddingModel)


class TestSectionEmbeddingsDDLAlignment:
    def test_section_embeddings_ddl_matches_orm(self) -> None:
        _assert_aligned("section_embeddings", SectionEmbeddingModel)


class TestEntityMentionsDDLAlignment:
    def test_entity_mentions_ddl_matches_orm(self) -> None:
        _assert_aligned("entity_mentions", EntityMentionModel)


class TestMentionResolutionsDDLAlignment:
    def test_mention_resolutions_ddl_matches_orm(self) -> None:
        _assert_aligned("mention_resolutions", MentionResolutionModel)


class TestDocumentEntityStatsDDLAlignment:
    def test_document_entity_stats_ddl_matches_orm(self) -> None:
        _assert_aligned("document_entity_stats", DocumentEntityStatsModel)


class TestChunkEntityMentionsDDLAlignment:
    def test_chunk_entity_mentions_ddl_matches_orm(self) -> None:
        _assert_aligned("chunk_entity_mentions", ChunkEntityMentionModel)


class TestRoutingDecisionsDDLAlignment:
    def test_routing_decisions_ddl_matches_orm(self) -> None:
        _assert_aligned("routing_decisions", RoutingDecisionModel)


class TestOutboxEventsDDLAlignment:
    def test_outbox_events_ddl_matches_orm(self) -> None:
        _assert_aligned("outbox_events", OutboxEventModel)


class TestDeadLetterQueueDDLAlignment:
    def test_dead_letter_queue_ddl_matches_orm(self) -> None:
        _assert_aligned("dead_letter_queue", DeadLetterQueueModel)


class TestDocumentSourceMetadataDDLAlignment:
    def test_document_source_metadata_ddl_matches_orm(self) -> None:
        _assert_aligned("document_source_metadata", DocumentSourceMetadataModel)


class TestEmbeddingPendingDDLAlignment:
    def test_embedding_pending_ddl_matches_orm(self) -> None:
        _assert_aligned("embedding_pending", EmbeddingPendingModel)


class TestArticlePriceImpactsDDLAlignment:
    def test_article_price_impacts_ddl_matches_orm(self) -> None:
        _assert_aligned("article_price_impacts", ArticlePriceImpactModel)
