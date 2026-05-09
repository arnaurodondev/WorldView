"""DDL-vs-ORM alignment tests for Market Ingestion (S2).

Guards against BP-008 (column drift) and BP-019 (migration gap).
Parses all Alembic migration DDL and compares column names against
the SQLAlchemy ORM metadata for each table in the service.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from market_ingestion.infrastructure.db.models import (
    IngestionTaskModel,
    OutboxEventModel,
    PollingPolicyModel,
    ProviderBudgetModel,
    SymbolTierModel,
    WatermarkModel,
)
from sqlalchemy import inspect as sa_inspect

pytestmark = pytest.mark.unit

_MIGRATION_DIR = Path(__file__).parent.parent.parent.parent / "alembic/versions"


def _extract_ddl_columns(migration_text: str, table_name: str) -> set[str]:
    """Extract column names for *table_name* across all migration DDL.

    Four sources are checked and unioned:
    1. ``op.create_table("<table_name>", sa.Column("<col>", ...))`` -- Alembic API.
    2. ``CREATE TABLE <table_name> (...)`` blocks -- raw SQL DDL.
    3. ``op.add_column("<table_name>", sa.Column("<col>", ...))`` -- later migrations.
    4. Raw ``ALTER TABLE <table_name> ADD COLUMN <col>`` SQL -- op.execute() DDL.
    """
    columns: set[str] = set()

    # -- Source 1: op.create_table() calls ------------------------------------
    # Match: op.create_table("table_name", sa.Column("col", ...), ...)
    create_table_pattern = rf'op\.create_table\(\s*["\']({table_name})["\']'
    for ct_match in re.finditer(create_table_pattern, migration_text):
        # Find all sa.Column("col_name", ...) within the create_table call
        start = ct_match.end()
        # Walk forward counting parens to find balanced closing of create_table()
        # We start inside the opening paren of create_table(
        depth = 1
        pos = start
        while pos < len(migration_text) and depth > 0:
            ch = migration_text[pos]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            pos += 1
        body = migration_text[start : pos - 1]
        # Extract sa.Column("col_name", ...) from the body
        for col_name in re.findall(r'sa\.Column\(\s*["\'](\w+)["\']', body):
            columns.add(col_name)

    # -- Source 2: Raw CREATE TABLE block -------------------------------------
    pattern = rf"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+{table_name}\s*\("
    match = re.search(pattern, migration_text, re.IGNORECASE)
    if match:
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
            if any(upper.startswith(kw) for kw in ("PRIMARY KEY", "UNIQUE", "CONSTRAINT", "FOREIGN KEY", "CHECK")):
                continue
            parts = line.split()
            if parts:
                columns.add(parts[0].strip('"'))

    # -- Source 3: op.add_column() calls --------------------------------------
    add_col_pattern = rf'op\.add_column\(\s*["\']({table_name})["\']?\s*,\s*sa\.Column\(\s*["\'](\w+)["\']'
    for m in re.finditer(add_col_pattern, migration_text):
        columns.add(m.group(2))

    # -- Source 4: Raw ALTER TABLE ADD COLUMN ---------------------------------
    # The optional ``IF NOT EXISTS`` is supported because newer migrations
    # (e.g., 0013_add_dispatched_at_to_outbox.py) use it for idempotency.
    alter_pattern = rf"ALTER\s+TABLE\s+{table_name}\s+ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)"
    for col_name in re.findall(alter_pattern, migration_text, re.IGNORECASE):
        columns.add(col_name)

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


class TestIngestionTasksDDLAlignment:
    """Verify ingestion_tasks ORM matches DDL across all migrations.

    Migration 0001 creates the table; migration 0010 adds fetched_by_provider.
    """

    def test_ingestion_tasks_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "ingestion_tasks")
        orm_cols = _get_orm_columns(IngestionTaskModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"

    def test_fetched_by_provider_in_orm(self) -> None:
        """Verify fetched_by_provider exists as a nullable column on the ORM model."""
        orm_cols = _get_orm_columns(IngestionTaskModel)
        assert "fetched_by_provider" in orm_cols, "fetched_by_provider column missing from IngestionTaskModel ORM"


class TestOutboxEventsDDLAlignment:
    def test_outbox_events_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "outbox_events")
        orm_cols = _get_orm_columns(OutboxEventModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestWatermarksDDLAlignment:
    def test_watermarks_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "ingestion_watermarks")
        orm_cols = _get_orm_columns(WatermarkModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestPollingPoliciesDDLAlignment:
    def test_polling_policies_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "polling_policies")
        orm_cols = _get_orm_columns(PollingPolicyModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestProviderBudgetsDDLAlignment:
    def test_provider_budgets_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "provider_budgets")
        orm_cols = _get_orm_columns(ProviderBudgetModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestSymbolTiersDDLAlignment:
    def test_symbol_tiers_ddl_matches_orm(self) -> None:
        migration_text = _read_all_migrations()
        ddl_cols = _extract_ddl_columns(migration_text, "symbol_tiers")
        orm_cols = _get_orm_columns(SymbolTierModel)

        missing_in_ddl = orm_cols - ddl_cols
        extra_in_ddl = ddl_cols - orm_cols

        assert not missing_in_ddl, f"ORM columns missing from DDL: {missing_in_ddl}"
        assert not extra_in_ddl, f"DDL columns not in ORM: {extra_in_ddl}"


class TestNoUUID4Defaults:
    def test_no_gen_random_uuid_in_migrations(self) -> None:
        """No migration should use gen_random_uuid() -- all IDs are app-generated UUIDv7 (R10, M-8)."""
        for path in sorted(_MIGRATION_DIR.glob("*.py")):
            content = path.read_text()
            assert (
                "gen_random_uuid()" not in content
            ), f"gen_random_uuid() found in {path.name} -- use app-generated UUIDv7 instead"
