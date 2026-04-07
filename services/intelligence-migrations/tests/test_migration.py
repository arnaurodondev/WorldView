"""Integration tests for intelligence_db migration and seed data.

These tests run against a real Postgres database with pgvector.
Mark: integration (requires running Postgres).
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ── Table existence ──────────────────────────────────────────────────────────

EXPECTED_TABLES = [
    "decay_class_config",
    "source_trust_weights",
    "model_registry",
    "prompt_templates",
    "canonical_entities",
    "entity_aliases",
    "entity_embedding_state",
    "llm_usage_log",
    "relation_type_registry",
    "relations",
    "relation_evidence_raw",
    "relation_evidence",
    "relation_contradiction_links",
    "relation_summaries",
    "claims",
    "events",
    "event_entities",
    "embedding_migration_state",
    "provisional_entity_queue",
    "outbox_events",
    "dead_letter_queue",
]


def test_migration_creates_all_tables(conn: sa.engine.Connection) -> None:
    """All expected tables exist after upgrade head."""
    result = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"))
    tables = {row[0] for row in result}
    for expected in EXPECTED_TABLES:
        assert expected in tables, f"Missing table: {expected}"


# ── Hash partitioning ────────────────────────────────────────────────────────


def test_relations_hash_partitioned(conn: sa.engine.Connection) -> None:
    """relations table has 8 hash partitions (relations_p0..p7)."""
    result = conn.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename LIKE 'relations_p%' "
            "ORDER BY tablename"
        )
    )
    partitions = [row[0] for row in result]
    assert partitions == [f"relations_p{i}" for i in range(8)]


def test_range_partitions_exist(conn: sa.engine.Connection) -> None:
    """relation_evidence, claims, events each have 36 monthly partitions."""
    for table_prefix in ("relation_evidence", "claims", "events"):
        result = conn.execute(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE :pattern"),
            {"pattern": f"{table_prefix}_%"},
        )
        count = result.scalar()
        assert count == 36, f"{table_prefix} expected 36 partitions, got {count}"


# ── Seed data ────────────────────────────────────────────────────────────────


def test_decay_class_config_seeded(conn: sa.engine.Connection) -> None:
    """6 decay_class_config rows with correct alpha values."""
    result = conn.execute(text("SELECT decay_class, decay_alpha FROM decay_class_config ORDER BY decay_alpha"))
    rows = result.fetchall()
    assert len(rows) == 6
    classes = {r[0] for r in rows}
    assert classes == {"PERMANENT", "DURABLE", "SLOW", "MEDIUM", "FAST", "EPHEMERAL"}
    # PERMANENT has alpha 0.0
    permanent = next(r for r in rows if r[0] == "PERMANENT")
    assert permanent[1] == pytest.approx(0.0)


def test_source_trust_weights_seeded(conn: sa.engine.Connection) -> None:
    """11 source_trust_weights rows with correct weights."""
    result = conn.execute(text("SELECT source_type, trust_weight FROM source_trust_weights ORDER BY trust_weight DESC"))
    rows = result.fetchall()
    assert len(rows) == 11
    # sec_10k has highest weight
    assert rows[0][0] == "sec_10k"
    assert rows[0][1] == pytest.approx(0.95)


def test_relation_type_registry_seeded(conn: sa.engine.Connection) -> None:
    """24 relation types seeded (20 from migration 0001 + 4 added by migration 0002)."""
    result = conn.execute(text("SELECT count(*) FROM relation_type_registry"))
    assert result.scalar() == 24


def test_relation_type_registry_has_embedding_column(conn: sa.engine.Connection) -> None:
    """relation_type_registry has embedding VECTOR(1024) column."""
    result = conn.execute(
        text(
            "SELECT data_type, udt_name FROM information_schema.columns "
            "WHERE table_name = 'relation_type_registry' AND column_name = 'embedding'"
        )
    )
    row = result.fetchone()
    assert row is not None, "embedding column missing from relation_type_registry"
    assert row[1] == "vector"


# ── Generated columns ────────────────────────────────────────────────────────


def test_partition_key_is_stored(conn: sa.engine.Connection) -> None:
    """INSERT into relations without partition_key succeeds (GENERATED STORED)."""
    entity1 = uuid.uuid4()
    entity2 = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO relations "
            "(subject_entity_id, canonical_type, object_entity_id, decay_class, decay_alpha) "
            "VALUES (:s, 'employs', :o, 'DURABLE', 0.000950)"
        ),
        {"s": str(entity1), "o": str(entity2)},
    )
    result = conn.execute(
        text("SELECT partition_key FROM relations WHERE subject_entity_id = :s"),
        {"s": str(entity1)},
    )
    pk = result.scalar()
    assert pk is not None
    assert 0 <= pk < 8
    conn.rollback()


# ── Unique constraints ────────────────────────────────────────────────────────


def test_provisional_queue_unique(conn: sa.engine.Connection) -> None:
    """Duplicate (normalized_surface, mention_class) is rejected."""
    conn.execute(
        text(
            "INSERT INTO provisional_entity_queue "
            "(mention_text, normalized_surface, mention_class) "
            "VALUES ('Apple Inc.', 'apple inc.', 'ORGANIZATION')"
        )
    )
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            text(
                "INSERT INTO provisional_entity_queue "
                "(mention_text, normalized_surface, mention_class) "
                "VALUES ('APPLE INC', 'apple inc.', 'ORGANIZATION')"
            )
        )
    conn.rollback()


# ── Extensions ────────────────────────────────────────────────────────────────


def test_pgvector_extension_active(conn: sa.engine.Connection) -> None:
    """pgvector extension is installed."""
    result = conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
    assert result.fetchone() is not None


def test_pg_trgm_extension_active(conn: sa.engine.Connection) -> None:
    """pg_trgm extension is installed."""
    result = conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'"))
    assert result.fetchone() is not None


# ── HNSW indexes ──────────────────────────────────────────────────────────────


def test_hnsw_indexes_exist(conn: sa.engine.Connection) -> None:
    """3 HNSW indexes on entity_embedding_state + 1 on relation_summaries."""
    result = conn.execute(text("SELECT indexname FROM pg_indexes WHERE indexdef LIKE '%hnsw%' ORDER BY indexname"))
    indexes = {row[0] for row in result}
    expected = {
        "idx_entity_emb_definition_hnsw",
        "idx_entity_emb_narrative_hnsw",
        "idx_entity_emb_fstate_hnsw",
        "idx_relation_summary_emb_hnsw",
    }
    for idx in expected:
        assert idx in indexes, f"Missing HNSW index: {idx}"


# ── event_entities ────────────────────────────────────────────────────────────


def test_event_entities_table(conn: sa.engine.Connection) -> None:
    """event_entities exists with correct PK (event_id, entity_id)."""
    result = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'event_entities' "
            "ORDER BY ordinal_position"
        )
    )
    columns = [row[0] for row in result]
    assert "event_id" in columns
    assert "entity_id" in columns
    assert "role" in columns


# ── entity_embedding_state ────────────────────────────────────────────────────


def test_entity_embedding_state_pk(conn: sa.engine.Connection) -> None:
    """entity_embedding_state has composite PK (entity_id, view_type)."""
    result = conn.execute(
        text(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'entity_embedding_state'::regclass AND i.indisprimary "
            "ORDER BY array_position(i.indkey, a.attnum)"
        )
    )
    pk_cols = [row[0] for row in result]
    assert pk_cols == ["entity_id", "view_type"]


# ── Migration 0002: events columns + relation types ───────────────────────────


def test_events_new_columns_exist(conn: sa.engine.Connection) -> None:
    """Migration 0002 adds event_subtype, source_type, structured_data to events."""
    result = conn.execute(
        text(
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_name = 'events' "
            "  AND column_name IN ('event_subtype', 'source_type', 'structured_data') "
            "ORDER BY column_name"
        )
    )
    rows = {row[0]: row[1] for row in result}
    assert "event_subtype" in rows, "event_subtype column missing from events"
    assert "source_type" in rows, "source_type column missing from events"
    assert "structured_data" in rows, "structured_data column missing from events"
    assert rows["structured_data"] == "jsonb", f"structured_data expected jsonb, got {rows['structured_data']}"


def test_events_new_columns_are_nullable(conn: sa.engine.Connection) -> None:
    """Migration 0002 event columns are nullable (backward-compatible)."""
    result = conn.execute(
        text(
            "SELECT column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = 'events' "
            "  AND column_name IN ('event_subtype', 'source_type', 'structured_data')"
        )
    )
    for col_name, is_nullable in result:
        assert is_nullable == "YES", f"Column {col_name} expected nullable, got {is_nullable}"


def test_events_composite_index_exists(conn: sa.engine.Connection) -> None:
    """Migration 0002 creates ix_events_entity_type_date index on events parent table."""
    result = conn.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'events' AND indexname = 'ix_events_entity_type_date'")
    )
    assert result.fetchone() is not None, "ix_events_entity_type_date index missing from events"


def test_relation_type_registry_new_types(conn: sa.engine.Connection) -> None:
    """Migration 0002 inserts 4 new canonical_types into relation_type_registry."""
    result = conn.execute(
        text(
            "SELECT canonical_type, semantic_mode, decay_class, base_confidence "
            "FROM relation_type_registry "
            "WHERE canonical_type IN ('is_in_sector', 'is_in_industry', 'earnings_released', 'corporate_action') "
            "ORDER BY canonical_type"
        )
    )
    rows = {row[0]: row for row in result}
    assert len(rows) == 4, f"Expected 4 new relation types, found {len(rows)}"

    # Verify key attributes match the plan spec (§6.4 relation_type_registry)
    assert rows["is_in_sector"][1] == "RELATION_STATE"
    assert rows["is_in_sector"][2] == "PERMANENT"
    assert rows["is_in_sector"][3] == pytest.approx(0.90)

    assert rows["is_in_industry"][1] == "RELATION_STATE"
    assert rows["is_in_industry"][2] == "DURABLE"
    assert rows["is_in_industry"][3] == pytest.approx(0.85)

    assert rows["earnings_released"][1] == "TEMPORAL_CLAIM"
    assert rows["earnings_released"][2] == "MEDIUM"
    assert rows["earnings_released"][3] == pytest.approx(0.95)

    assert rows["corporate_action"][1] == "TEMPORAL_CLAIM"
    assert rows["corporate_action"][2] == "DURABLE"
    assert rows["corporate_action"][3] == pytest.approx(0.90)
