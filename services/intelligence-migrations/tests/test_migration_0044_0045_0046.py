"""Integration tests for PLAN-0093 Wave B-2 migrations 0044, 0045, 0046.

Three migrations land in lockstep:

  • 0044 — seed 5 system-sentinel canonical_entities + add ``is_system`` column
  • 0045 — add DEFERRABLE FK constraints on ``relations.subject_entity_id``
           and ``relations.object_entity_id`` + a CHECK that bans self-loops
           on real entities (sentinels are whitelisted)
  • 0046 — relations.confidence NOT NULL DEFAULT base_confidence

The session-scoped ``run_migrations`` fixture in conftest.py has already
applied ``alembic upgrade head`` by the time these tests run, so each
test verifies post-upgrade state.

Mark: integration (requires running Postgres with pgvector + AGE).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ── Fixtures ─────────────────────────────────────────────────────────────────


# The five sentinel UUIDs declared in migration 0044.
_SENTINEL_IDS = (
    "11111111-0004-7000-8000-000000000001",  # Macro Sentinel
    "11111111-0004-7000-8000-000000000002",  # Unknown Person
    "11111111-0004-7000-8000-000000000003",  # Unknown Organization
    "11111111-0004-7000-8000-000000000004",  # Unknown Place
    "11111111-0004-7000-8000-000000000005",  # Unknown Product
)


# ── 0044 ─────────────────────────────────────────────────────────────────────


def test_migration_0044_upgrade_inserts_5_system_entities(conn: sa.engine.Connection) -> None:
    """After upgrade head: exactly 5 is_system=true rows exist with the expected IDs."""
    rows = conn.execute(
        text("SELECT entity_id::text, canonical_name, entity_type FROM canonical_entities WHERE is_system = true"),
    ).fetchall()
    ids = {r[0] for r in rows}
    assert ids == set(_SENTINEL_IDS), f"sentinel roster drift: {ids}"
    # Spot-check the Macro Sentinel shape.
    macro = next(r for r in rows if r[0] == "11111111-0004-7000-8000-000000000001")
    assert macro[1] == "Macro Sentinel"
    assert macro[2] == "macro_indicator"


def test_migration_0044_idempotent(conn: sa.engine.Connection) -> None:
    """Re-INSERTing the same sentinel rows via the ON CONFLICT path must not raise."""
    # Mirror the migration body's INSERT pattern.  ON CONFLICT DO UPDATE sets
    # is_system = true; running it twice keeps the row at the same final state.
    for entity_id in _SENTINEL_IDS:
        conn.execute(
            text(
                """
                INSERT INTO canonical_entities (
                    entity_id, canonical_name, entity_type, ticker, exchange,
                    description, data_completeness, enriched_at, enrichment_attempts,
                    is_system, created_at, updated_at
                ) VALUES (
                    :entity_id, 'duplicate', 'organization', NULL, NULL,
                    'duplicate', 1.0, NOW(), 3, true, NOW(), NOW()
                )
                ON CONFLICT (entity_id) DO UPDATE SET is_system = true
                """
            ),
            {"entity_id": entity_id},
        )
    count = conn.execute(
        text("SELECT COUNT(*) FROM canonical_entities WHERE is_system = true"),
    ).scalar_one()
    assert count == 5, f"sentinel count should stay 5 after re-insert, got {count}"
    conn.rollback()


def test_migration_0044_is_system_column_exists_and_indexed(conn: sa.engine.Connection) -> None:
    """The ``is_system`` column exists, is NOT NULL, defaults to false, and is partially indexed."""
    col = conn.execute(
        text(
            "SELECT data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'canonical_entities' AND column_name = 'is_system'"
        ),
    ).fetchone()
    assert col is not None, "is_system column missing"
    assert col[0] == "boolean"
    assert col[1] == "NO"  # NOT NULL
    assert "false" in str(col[2]).lower()

    # Partial index for downstream filters.
    idx = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = 'idx_entities_is_system'"),
    ).fetchone()
    assert idx is not None, "idx_entities_is_system partial index missing"


# ── 0045 ─────────────────────────────────────────────────────────────────────


def test_migration_0045_fk_constraints_exist(conn: sa.engine.Connection) -> None:
    """The two FK constraints on relations are present and DEFERRABLE."""
    rows = conn.execute(
        text(
            "SELECT conname, condeferrable, condeferred "
            "FROM pg_constraint "
            "WHERE conrelid = 'relations'::regclass "
            "  AND contype = 'f' "
            "  AND conname IN ('fk_relations_subject_entity', 'fk_relations_object_entity')"
        ),
    ).fetchall()
    names = {r[0] for r in rows}
    assert names == {
        "fk_relations_subject_entity",
        "fk_relations_object_entity",
    }, f"expected both FK constraints, got {names}"
    for r in rows:
        assert r[1] is True, f"{r[0]} must be DEFERRABLE"
        assert r[2] is True, f"{r[0]} must be INITIALLY DEFERRED"


def test_migration_0045_blocks_orphan_relation_write(conn: sa.engine.Connection) -> None:
    """INSERTing a relation that points at a non-existent entity must fail at commit."""
    # Use real sentinel + bogus partner. The sentinel exists; the bogus side
    # should trigger the FK violation at commit (deferred check).
    bogus = "99999999-9999-7999-8999-999999999999"
    with conn.begin() as tx:  # noqa: F841 — explicit transaction so commit triggers deferred check
        # Deferred FKs check at COMMIT; the INSERT itself succeeds.
        conn.execute(
            text(
                """
                INSERT INTO relations (
                    subject_entity_id, canonical_type, object_entity_id,
                    semantic_mode, decay_class, decay_alpha, base_confidence,
                    confidence, confidence_stale, summary_stale,
                    first_evidence_at, latest_evidence_at, evidence_count
                ) VALUES (
                    :subject, 'EMPLOYS', :object,
                    'RELATION_STATE', 'DURABLE', 0.00095, 0.5,
                    0.5, true, true, NOW(), NOW(), 1
                )
                """
            ),
            {"subject": _SENTINEL_IDS[0], "object": bogus},
        )
        with pytest.raises(sa.exc.IntegrityError):
            # Force the deferred FK check.
            conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_migration_0045_check_blocks_self_loop_on_real_entity(conn: sa.engine.Connection) -> None:
    """``chk_relations_no_self_loop`` rejects self-loops on real entities."""
    # Insert a real entity first; ensure it ends up with is_system = false.
    real_id = "01910000-0000-7000-8000-000000099999"
    conn.execute(
        text(
            """
            INSERT INTO canonical_entities (
                entity_id, canonical_name, entity_type, created_at, updated_at
            ) VALUES (:eid, 'Real Co', 'organization', NOW(), NOW())
            ON CONFLICT (entity_id) DO NOTHING
            """
        ),
        {"eid": real_id},
    )
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            text(
                """
                INSERT INTO relations (
                    subject_entity_id, canonical_type, object_entity_id,
                    semantic_mode, decay_class, decay_alpha, base_confidence,
                    confidence, confidence_stale, summary_stale,
                    first_evidence_at, latest_evidence_at, evidence_count
                ) VALUES (
                    :eid, 'EMPLOYS', :eid,
                    'RELATION_STATE', 'DURABLE', 0.00095, 0.5,
                    0.5, true, true, NOW(), NOW(), 1
                )
                """
            ),
            {"eid": real_id},
        )
    conn.rollback()


def test_migration_0045_check_allows_self_loop_on_sentinel(conn: sa.engine.Connection) -> None:
    """``chk_relations_no_self_loop`` permits self-loops on the 5 whitelisted sentinels."""
    sentinel = _SENTINEL_IDS[0]  # Macro Sentinel
    # Should not raise.
    conn.execute(
        text(
            """
            INSERT INTO relations (
                subject_entity_id, canonical_type, object_entity_id,
                semantic_mode, decay_class, decay_alpha, base_confidence,
                confidence, confidence_stale, summary_stale,
                first_evidence_at, latest_evidence_at, evidence_count
            ) VALUES (
                :eid, 'SENTIMENT_SIGNAL', :eid,
                'RELATION_STATE', 'DURABLE', 0.00095, 0.5,
                0.5, true, true, NOW(), NOW(), 1
            )
            ON CONFLICT (subject_entity_id, canonical_type, object_entity_id) DO NOTHING
            """
        ),
        {"eid": sentinel},
    )
    conn.rollback()


# ── 0046 ─────────────────────────────────────────────────────────────────────


def test_migration_0046_confidence_is_not_null(conn: sa.engine.Connection) -> None:
    """``relations.confidence`` is NOT NULL after migration 0046."""
    col = conn.execute(
        text(
            "SELECT is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'relations' AND column_name = 'confidence'"
        ),
    ).fetchone()
    assert col is not None
    assert col[1] == "NO", "relations.confidence must be NOT NULL after 0046"
    # Server default = base_confidence.
    assert col[2] is not None and "base_confidence" in str(
        col[2]
    ), f"expected server_default = base_confidence, got {col[2]!r}"


def test_migration_0046_null_confidence_insert_rejected(conn: sa.engine.Connection) -> None:
    """Explicitly inserting NULL confidence must raise NotNullViolation."""
    sentinel = _SENTINEL_IDS[0]
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            text(
                """
                INSERT INTO relations (
                    subject_entity_id, canonical_type, object_entity_id,
                    semantic_mode, decay_class, decay_alpha, base_confidence,
                    confidence, confidence_stale, summary_stale,
                    first_evidence_at, latest_evidence_at, evidence_count
                ) VALUES (
                    :eid, 'SENTIMENT_SIGNAL', :eid,
                    'RELATION_STATE', 'DURABLE', 0.00095, 0.5,
                    NULL, true, true, NOW(), NOW(), 1
                )
                """
            ),
            {"eid": sentinel},
        )
    conn.rollback()


def test_migration_0046_default_used_when_omitted(conn: sa.engine.Connection) -> None:
    """Omitting ``confidence`` from the INSERT yields row.confidence = base_confidence."""
    sentinel = _SENTINEL_IDS[1]  # Unknown Person
    conn.execute(
        text(
            """
            INSERT INTO relations (
                subject_entity_id, canonical_type, object_entity_id,
                semantic_mode, decay_class, decay_alpha, base_confidence,
                confidence_stale, summary_stale,
                first_evidence_at, latest_evidence_at, evidence_count
            ) VALUES (
                :eid, 'SENTIMENT_SIGNAL', :eid,
                'RELATION_STATE', 'DURABLE', 0.00095, 0.42,
                true, true, NOW(), NOW(), 1
            )
            ON CONFLICT (subject_entity_id, canonical_type, object_entity_id) DO UPDATE
                SET base_confidence = EXCLUDED.base_confidence
            """
        ),
        {"eid": sentinel},
    )
    row = conn.execute(
        text(
            "SELECT confidence FROM relations "
            "WHERE subject_entity_id = :eid AND canonical_type = 'SENTIMENT_SIGNAL' AND object_entity_id = :eid"
        ),
        {"eid": sentinel},
    ).fetchone()
    assert row is not None
    # server_default = base_confidence applies on INSERT.
    assert row[0] == pytest.approx(0.42), f"expected confidence=base_confidence=0.42, got {row[0]}"
    conn.rollback()
