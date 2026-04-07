"""DDL-vs-ORM alignment tests for rag_db — guards against BP-008 and BP-019.

Parses Alembic migration DDL and compares column names against the
SQLAlchemy ORM metadata. Ensures no drift between what the migration
creates and what the application expects.

Coverage rule: ALL tables in rag_db must have a test class here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rag_chat.infrastructure.db.models import MessageModel, ThreadModel
from sqlalchemy import inspect as sa_inspect

pytestmark = pytest.mark.unit

_MIGRATION_DIR = Path(__file__).parent.parent.parent.parent / "alembic/versions"


def _extract_ddl_columns(migration_text: str, table_name: str) -> set[str]:
    """Extract column names from CREATE TABLE + ALTER TABLE ADD COLUMN statements."""
    columns: set[str] = set()

    # ── CREATE TABLE ──────────────────────────────────────────────────────────
    pattern = rf"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+{table_name}\s*\("
    match = re.search(pattern, migration_text, re.IGNORECASE)
    if match:
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
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            if not line:
                continue
            upper = line.upper()
            # Skip constraint lines
            if any(
                upper.startswith(kw)
                for kw in ("PRIMARY KEY", "UNIQUE", "CONSTRAINT", "FOREIGN KEY", "CHECK", "REFERENCES")
            ):
                continue
            parts = line.split()
            if parts:
                columns.add(parts[0].strip('"'))

    # ── ALTER TABLE … ADD COLUMN ──────────────────────────────────────────────
    # Handles: ALTER TABLE <name> ADD COLUMN [IF NOT EXISTS] <col_name> <type>
    alter_pattern = rf"ALTER\s+TABLE\s+{table_name}\s+" rf"ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)"
    for m in re.finditer(alter_pattern, migration_text, re.IGNORECASE):
        columns.add(m.group(1))

    return columns


def _get_orm_columns(model: type) -> set[str]:
    """Get column names from a SQLAlchemy model."""
    mapper = sa_inspect(model)
    return {col.key for col in mapper.columns}


def _read_all_migrations() -> str:
    """Read and concatenate all migration files."""
    texts = []
    for path in sorted(_MIGRATION_DIR.glob("*.py")):
        texts.append(path.read_text())
    return "\n".join(texts)


class TestThreadsDDLAlignment:
    def test_threads_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "threads")
        orm_cols = _get_orm_columns(ThreadModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestMessagesDDLAlignment:
    def test_messages_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "messages")
        orm_cols = _get_orm_columns(MessageModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestNoUUID4Defaults:
    def test_no_gen_random_uuid_in_migrations(self) -> None:
        """No migration should use gen_random_uuid() — IDs are app-generated UUIDv7 (R10)."""
        for path in sorted(_MIGRATION_DIR.glob("*.py")):
            content = path.read_text()
            assert (
                "gen_random_uuid()" not in content
            ), f"gen_random_uuid() found in {path.name} — use app-generated UUIDv7 instead"
