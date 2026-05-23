"""Verify that the 8 HASH partitions of the relations table exist."""

from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.mark.integration()
async def test_relations_has_eight_partitions(db_engine) -> None:
    """intelligence_db must have 8 hash partitions for the relations table."""
    async with db_engine.begin() as conn:
        result = await conn.execute(
            text("""
SELECT COUNT(*)
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child  ON child.oid  = i.inhrelid
WHERE parent.relname = 'relations'
"""),
        )
        count = result.scalar()

    assert count == 8, f"Expected 8 relation partitions, got {count}"


@pytest.mark.integration()
async def test_relation_evidence_raw_exists(db_engine) -> None:
    """relation_evidence_raw table must exist."""
    async with db_engine.begin() as conn:
        result = await conn.execute(
            text("""
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'relation_evidence_raw'
)
"""),
        )
        exists = result.scalar()

    assert exists, "relation_evidence_raw table not found — run intelligence-migrations"


@pytest.mark.integration()
async def test_partition_key_is_generated_always(db_engine) -> None:
    """partition_key must be a GENERATED ALWAYS AS STORED column."""
    async with db_engine.begin() as conn:
        result = await conn.execute(
            text("""
SELECT is_generated
FROM information_schema.columns
WHERE table_name = 'relations' AND column_name = 'partition_key'
"""),
        )
        row = result.fetchone()

    assert row is not None, "partition_key column not found in relations"
    assert row[0] in ("ALWAYS",), f"partition_key should be GENERATED ALWAYS, got: {row[0]}"
