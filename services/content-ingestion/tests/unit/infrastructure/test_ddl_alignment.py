"""DDL-vs-ORM alignment tests — guards against BP-008 and BP-019.

Parses Alembic migration DDL and compares column names against
the SQLAlchemy ORM metadata for the Content Ingestion service.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from content_ingestion.infrastructure.db.models import (
    ContentIngestionTaskModel,
    DeadLetterQueueModel,
    FetchLogModel,
    OutboxEventModel,
    SourceAdapterStateModel,
    SourceModel,
)
from sqlalchemy import inspect as sa_inspect

pytestmark = pytest.mark.unit

_MIGRATION_DIR = Path(__file__).parent.parent.parent.parent / "alembic/versions"


def _extract_ddl_columns(migration_text: str, table_name: str) -> set[str]:
    """Extract column names from a CREATE TABLE statement in migration SQL."""
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


class TestSourcesDDLAlignment:
    def test_sources_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "sources")
        orm_cols = _get_orm_columns(SourceModel)

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


class TestSourceAdapterStateDDLAlignment:
    def test_source_adapter_state_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "source_adapter_state")
        orm_cols = _get_orm_columns(SourceAdapterStateModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestArticleFetchLogDDLAlignment:
    def test_article_fetch_log_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "article_fetch_log")
        orm_cols = _get_orm_columns(FetchLogModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestContentIngestionTasksDDLAlignment:
    def test_content_ingestion_tasks_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "content_ingestion_tasks")
        orm_cols = _get_orm_columns(ContentIngestionTaskModel)

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
