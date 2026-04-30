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
    """27 relation types seeded (20 from 0001 + 4 from 0002 + 3 new from 0004)."""
    result = conn.execute(text("SELECT count(*) FROM relation_type_registry"))
    assert result.scalar() == 27


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


# ── Migration 0003: fundamentals_ohlcv orphan cleanup ────────────────────────


def test_migration_0003_cleanup_preserves_company_rows(conn: sa.engine.Connection) -> None:
    """Migration 0003 cleanup SQL leaves fundamentals_ohlcv rows for financial_instrument intact."""
    entity_id = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type) "
            "VALUES (:id, 'Acme Corp', 'financial_instrument')"
        ),
        {"id": entity_id},
    )
    conn.execute(
        text("INSERT INTO entity_embedding_state (entity_id, view_type) VALUES (:id, 'fundamentals_ohlcv')"),
        {"id": entity_id},
    )

    # Run the same DELETE SQL used in migration 0003.
    conn.execute(
        text("""
            DELETE FROM entity_embedding_state ees
            WHERE ees.view_type = 'fundamentals_ohlcv'
              AND EXISTS (
                  SELECT 1 FROM canonical_entities ce
                  WHERE ce.entity_id = ees.entity_id
                    AND ce.entity_type != 'financial_instrument'
              )
        """)
    )

    result = conn.execute(
        text("SELECT count(*) FROM entity_embedding_state WHERE entity_id = :id AND view_type = 'fundamentals_ohlcv'"),
        {"id": entity_id},
    )
    assert result.scalar() == 1, "fundamentals_ohlcv row for financial_instrument must NOT be deleted"
    conn.rollback()


def test_migration_0003_cleanup_removes_non_company_rows(conn: sa.engine.Connection) -> None:
    """Migration 0003 cleanup SQL removes fundamentals_ohlcv rows for non-company entities."""
    non_company_types = ["person", "country", "organization", "regulatory_body", "index"]
    entity_ids: list[str] = []

    for entity_type in non_company_types:
        eid = str(uuid.uuid4())
        entity_ids.append(eid)
        conn.execute(
            text("INSERT INTO canonical_entities (entity_id, canonical_name, entity_type) VALUES (:id, :name, :type)"),
            {"id": eid, "name": f"Test {entity_type}", "type": entity_type},
        )
        conn.execute(
            text("INSERT INTO entity_embedding_state (entity_id, view_type) VALUES (:id, 'fundamentals_ohlcv')"),
            {"id": eid},
        )

    # Run the migration cleanup SQL.
    conn.execute(
        text("""
            DELETE FROM entity_embedding_state ees
            WHERE ees.view_type = 'fundamentals_ohlcv'
              AND EXISTS (
                  SELECT 1 FROM canonical_entities ce
                  WHERE ce.entity_id = ees.entity_id
                    AND ce.entity_type != 'financial_instrument'
              )
        """)
    )

    result = conn.execute(
        text(
            "SELECT count(*) FROM entity_embedding_state "
            "WHERE entity_id = ANY(:ids) AND view_type = 'fundamentals_ohlcv'"
        ),
        {"ids": entity_ids},
    )
    assert result.scalar() == 0, "fundamentals_ohlcv rows for non-company entities must all be deleted"
    conn.rollback()


def test_migration_0003_cleanup_preserves_other_view_types(conn: sa.engine.Connection) -> None:
    """Migration 0003 cleanup SQL does not touch definition or narrative rows."""
    entity_id = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type) VALUES (:id, 'Jane Doe', 'person')"
        ),
        {"id": entity_id},
    )
    for view_type in ("definition", "narrative", "fundamentals_ohlcv"):
        conn.execute(
            text("INSERT INTO entity_embedding_state (entity_id, view_type) VALUES (:id, :vt)"),
            {"id": entity_id, "vt": view_type},
        )

    # Run the migration cleanup SQL.
    conn.execute(
        text("""
            DELETE FROM entity_embedding_state ees
            WHERE ees.view_type = 'fundamentals_ohlcv'
              AND EXISTS (
                  SELECT 1 FROM canonical_entities ce
                  WHERE ce.entity_id = ees.entity_id
                    AND ce.entity_type != 'financial_instrument'
              )
        """)
    )

    result = conn.execute(
        text("SELECT view_type FROM entity_embedding_state WHERE entity_id = :id ORDER BY view_type"),
        {"id": entity_id},
    )
    remaining = [row[0] for row in result]
    assert remaining == ["definition", "narrative"], f"Expected only definition+narrative to remain, got: {remaining}"
    conn.rollback()


# ── Migration 0004: AGE + temporal_events + entity_event_exposures ─────────────


def test_temporal_events_table_exists(conn: sa.engine.Connection) -> None:
    """temporal_events table created by migration 0004."""
    result = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = 'temporal_events'")
    )
    assert result.fetchone() is not None, "temporal_events table missing"


def test_temporal_events_columns(conn: sa.engine.Connection) -> None:
    """temporal_events has all required columns from PRD-0018 §6.4."""
    result = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'temporal_events' ORDER BY ordinal_position"
        )
    )
    columns = {row[0] for row in result}
    required = {
        "event_id",
        "event_type",
        "scope",
        "region",
        "title",
        "description",
        "source_article_ids",
        "source_url",
        "active_from",
        "active_until",
        "residual_impact_days",
        "confidence",
        "created_at",
        "updated_at",
    }
    missing = required - columns
    assert not missing, f"temporal_events missing columns: {missing}"


def test_temporal_events_natural_key_unique_index(conn: sa.engine.Connection) -> None:
    """temporal_events has functional unique index for deduplication."""
    result = conn.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'temporal_events' AND indexname = 'uidx_temporal_events_natural_key'"
        )
    )
    assert result.fetchone() is not None, "uidx_temporal_events_natural_key index missing"


def test_temporal_events_natural_key_prevents_duplicates(conn: sa.engine.Connection) -> None:
    """Inserting same (event_type, region, title, active_from::date) twice raises IntegrityError."""
    eid1 = uuid.uuid4()
    eid2 = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO temporal_events "
            "(event_id, event_type, scope, region, title, active_from, residual_impact_days, confidence) "
            "VALUES (:id, 'macro', 'NATIONAL', 'US', 'CPI Report', '2026-04-01 06:00:00+00', 30, 1.0)"
        ),
        {"id": str(eid1)},
    )
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            text(
                "INSERT INTO temporal_events "
                "(event_id, event_type, scope, region, title, active_from, residual_impact_days, confidence) "
                "VALUES (:id, 'macro', 'NATIONAL', 'US', 'CPI Report', '2026-04-01 08:00:00+00', 30, 1.0)"
            ),
            {"id": str(eid2)},
        )
    conn.rollback()


def test_entity_event_exposures_table_exists(conn: sa.engine.Connection) -> None:
    """entity_event_exposures table created by migration 0004."""
    result = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = 'entity_event_exposures'")
    )
    assert result.fetchone() is not None, "entity_event_exposures table missing"


def test_entity_event_exposures_unique_constraint(conn: sa.engine.Connection) -> None:
    """(event_id, entity_id, exposure_type) is unique in entity_event_exposures."""
    event_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    exp_id1 = uuid.uuid4()
    exp_id2 = uuid.uuid4()
    # Insert event first (FK constraint)
    conn.execute(
        text(
            "INSERT INTO temporal_events "
            "(event_id, event_type, scope, title, active_from, residual_impact_days, confidence) "
            "VALUES (:eid, 'geopolitical', 'GLOBAL', 'Test Event', '2026-04-01 00:00:00+00', 90, 0.9)"
        ),
        {"eid": str(event_id)},
    )
    conn.execute(
        text(
            "INSERT INTO entity_event_exposures "
            "(exposure_id, event_id, entity_id, exposure_type, confidence) "
            "VALUES (:xid, :eid, :entid, 'sector_exposure', 0.9)"
        ),
        {"xid": str(exp_id1), "eid": str(event_id), "entid": str(entity_id)},
    )
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            text(
                "INSERT INTO entity_event_exposures "
                "(exposure_id, event_id, entity_id, exposure_type, confidence) "
                "VALUES (:xid, :eid, :entid, 'sector_exposure', 0.7)"
            ),
            {"xid": str(exp_id2), "eid": str(event_id), "entid": str(entity_id)},
        )
    conn.rollback()


def test_relations_has_updated_at_column(conn: sa.engine.Connection) -> None:
    """relations table has updated_at TIMESTAMPTZ column (needed by AgeSyncWorker watermark)."""
    result = conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'relations' AND column_name = 'updated_at'"
        )
    )
    row = result.fetchone()
    assert row is not None, "relations.updated_at column missing"
    assert "timestamp" in row[1].lower(), f"Unexpected data_type: {row[1]}"


def test_age_extension_active(conn: sa.engine.Connection) -> None:
    """Apache AGE extension is installed (required for Cypher path queries)."""
    result = conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'age'"))
    assert result.fetchone() is not None, "AGE extension not installed"


def test_prd_0018_relation_types_seeded(conn: sa.engine.Connection) -> None:
    """3 new relation types from PRD-0018 are seeded in relation_type_registry."""
    result = conn.execute(
        text(
            "SELECT canonical_type FROM relation_type_registry "
            "WHERE canonical_type IN ('has_executive', 'revenue_from_country', 'operates_in_country') "
            "ORDER BY canonical_type"
        )
    )
    seeded = {row[0] for row in result}
    assert seeded == {"has_executive", "revenue_from_country", "operates_in_country"}


# ── PLAN-0057 A-2: entity_aliases UNIQUE per (entity_id, normalized, alias_type) ───


def test_entity_aliases_uidx_entity_norm_type_exists(conn: sa.engine.Connection) -> None:
    """The PLAN-0057 A-2 unique index is present after migration 0008."""
    result = conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uidx_entity_aliases_entity_norm_type'")
    )
    row = result.scalar_one_or_none()
    assert row is not None, "uidx_entity_aliases_entity_norm_type missing — migration 0008 did not run"
    # Sanity-check the index covers the right columns
    assert "entity_id" in row
    assert "normalized_alias_text" in row
    assert "alias_type" in row
    assert "is_active" in row  # partial: WHERE is_active = true


def test_entity_aliases_unique_blocks_duplicate_ticker(conn: sa.engine.Connection) -> None:
    """Inserting two TICKER aliases with same (entity_id, normalized_alias_text)
    raises IntegrityError. This guards the 32-of-38 duplicate seed_demo TICKER
    pattern called out in audit F-CRIT-12.
    """
    eid = uuid.uuid4()
    # Need a canonical to satisfy FK
    conn.execute(
        text(
            "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type, metadata) "
            "VALUES (:eid, 'TestCo', 'financial_instrument', '{}'::jsonb)"
        ),
        {"eid": str(eid)},
    )
    conn.execute(
        text(
            "INSERT INTO entity_aliases (entity_id, alias_text, normalized_alias_text, alias_type, is_active, source) "
            "VALUES (:eid, 'TSTC', 'tstc', 'TICKER', true, 'test')"
        ),
        {"eid": str(eid)},
    )
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            text(
                "INSERT INTO entity_aliases "
                "(entity_id, alias_text, normalized_alias_text, alias_type, is_active, source) "
                "VALUES (:eid, 'TSTC', 'tstc', 'TICKER', true, 'test_dup')"
            ),
            {"eid": str(eid)},
        )
    conn.rollback()


def test_entity_aliases_unique_allows_distinct_alias_types(conn: sa.engine.Connection) -> None:
    """Two aliases with same (entity_id, normalized_alias_text) but DIFFERENT
    alias_types are allowed (e.g., 'AAPL' as both TICKER and PRIMARY_TICKER).
    """
    eid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type, metadata) "
            "VALUES (:eid, 'AlphaCo', 'financial_instrument', '{}'::jsonb)"
        ),
        {"eid": str(eid)},
    )
    conn.execute(
        text(
            "INSERT INTO entity_aliases (entity_id, alias_text, normalized_alias_text, alias_type, is_active, source) "
            "VALUES (:eid, 'ALFA', 'alfa', 'TICKER', true, 'test')"
        ),
        {"eid": str(eid)},
    )
    conn.execute(
        text(
            "INSERT INTO entity_aliases (entity_id, alias_text, normalized_alias_text, alias_type, is_active, source) "
            "VALUES (:eid, 'ALFA', 'alfa', 'PRIMARY_TICKER', true, 'test')"
        ),
        {"eid": str(eid)},
    )
    conn.rollback()


def test_entity_aliases_unique_allows_distinct_entities(conn: sa.engine.Connection) -> None:
    """Same alias_text + alias_type for two DIFFERENT entities is allowed (the
    older partial unique index handles cross-entity uniqueness for EXACT only).
    """
    eid_a = uuid.uuid4()
    eid_b = uuid.uuid4()
    for eid, name in ((eid_a, "AlphaCo"), (eid_b, "BravoCo")):
        conn.execute(
            text(
                "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type, metadata) "
                "VALUES (:eid, :name, 'financial_instrument', '{}'::jsonb)"
            ),
            {"eid": str(eid), "name": name},
        )
        conn.execute(
            text(
                "INSERT INTO entity_aliases "
                "(entity_id, alias_text, normalized_alias_text, alias_type, is_active, source) "
                "VALUES (:eid, 'XYZ', 'xyz', 'CUSIP', true, 'test')"
            ),
            {"eid": str(eid)},
        )
    conn.rollback()
