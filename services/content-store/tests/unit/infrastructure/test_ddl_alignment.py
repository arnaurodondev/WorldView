"""DDL-vs-ORM alignment tests — guards against BP-008 and BP-019.

Parses Alembic migration DDL and compares column names against
the SQLAlchemy ORM metadata. Ensures no drift between what the
migration creates and what the application expects.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from content_store.infrastructure.db.models import (
    DeadLetterQueueModel,
    DedupHashModel,
    DocumentModel,
    DuplicateClusterModel,
    MinHashEntityMentionModel,
    MinHashSignatureModel,
    OutboxEventModel,
)
from sqlalchemy import inspect as sa_inspect

pytestmark = pytest.mark.unit

_MIGRATION_DIR = Path(__file__).parent.parent.parent.parent / "alembic/versions"


def _extract_ddl_columns(migration_text: str, table_name: str) -> set[str]:
    """Extract column names from a CREATE TABLE statement in migration SQL."""
    # Find CREATE TABLE <name> then extract balanced parens body
    pattern = rf"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+{table_name}\s*\("
    match = re.search(pattern, migration_text, re.IGNORECASE)
    if not match:
        return set()

    # Walk forward counting parens to find the balanced closing paren
    start = match.end()  # position after opening '('
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
        # Skip constraints (PRIMARY KEY, UNIQUE, CONSTRAINT, FOREIGN KEY)
        upper = line.upper()
        if any(upper.startswith(kw) for kw in ("PRIMARY KEY", "UNIQUE", "CONSTRAINT", "FOREIGN KEY", "CHECK")):
            continue
        # First word is the column name (constraint lines already skipped above)
        parts = line.split()
        if parts:
            columns.add(parts[0].strip('"'))
    return columns


def _get_orm_columns(model: type) -> set[str]:
    """Get column names from a SQLAlchemy model."""
    mapper = sa_inspect(model)
    return {col.key for col in mapper.columns}


def _read_all_migrations() -> str:
    """Read all migration files and concatenate their content."""
    texts = []
    for path in sorted(_MIGRATION_DIR.glob("*.py")):
        texts.append(path.read_text())
    return "\n".join(texts)


class TestDocumentsDDLAlignment:
    def test_documents_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "documents")
        orm_cols = _get_orm_columns(DocumentModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestOutboxEventsDDLAlignment:
    def test_outbox_events_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "outbox_events")
        orm_cols = _get_orm_columns(OutboxEventModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestDeadLetterQueueDDLAlignment:
    def test_dead_letter_queue_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "dead_letter_queue")
        orm_cols = _get_orm_columns(DeadLetterQueueModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestDedupHashesDDLAlignment:
    def test_dedup_hashes_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "dedup_hashes")
        orm_cols = _get_orm_columns(DedupHashModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestDuplicateClustersDDLAlignment:
    def test_duplicate_clusters_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "duplicate_clusters")
        orm_cols = _get_orm_columns(DuplicateClusterModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestMinHashSignaturesDDLAlignment:
    def test_minhash_signatures_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "minhash_signatures")
        orm_cols = _get_orm_columns(MinHashSignatureModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestMinHashEntityMentionsDDLAlignment:
    def test_minhash_entity_mentions_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "minhash_entity_mentions")
        orm_cols = _get_orm_columns(MinHashEntityMentionModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestNoUUID4Defaults:
    def test_no_gen_random_uuid_in_migrations(self) -> None:
        """No migration should use gen_random_uuid() — all IDs are app-generated UUIDv7 (R10, M-8)."""
        for path in sorted(_MIGRATION_DIR.glob("*.py")):
            content = path.read_text()
            assert (
                "gen_random_uuid()" not in content
            ), f"gen_random_uuid() found in {path.name} — use app-generated UUIDv7 instead"
