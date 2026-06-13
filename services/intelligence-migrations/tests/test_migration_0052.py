"""Integration tests for migration 0052 — weirdness metric + node_degree (PLAN-0112 W3).

Migration 0052 lands the persisted weirdness metric:

  • CREATE TABLE ``node_degree`` (per-vertex degree, FR-5)
  • CREATE TABLE ``graph_stats`` (single-row normaliser store)
  • ALTER ``path_insights`` ADD 7 NULLable weirdness columns
  • two new indexes (global weird feed + endpoint filtering)

The session-scoped ``run_migrations`` fixture in conftest.py applies
``alembic upgrade head`` before these tests run, so the upgrade-contract tests
verify post-upgrade state.  The apply+rollback round-trip test drives the
0051↔0052 transition explicitly (downgrade to 0051, assert gone, upgrade back to
0052, assert present) so both directions are exercised.

Mark: integration (requires running Postgres with pgvector + AGE).
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text

pytestmark = pytest.mark.integration

_NEW_COLUMNS = (
    "dst_entity_id",
    "reliability",
    "unexpectedness",
    "semantic_distance",
    "novelty",
    "weirdness",
    "scorer_version",
)
_NEW_INDEXES = ("idx_path_insights_global_weird", "idx_path_insights_dst")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON c.relnamespace = n.oid "
            "WHERE c.relname = :tbl AND n.nspname = 'public' AND c.relkind = 'r'"
        ),
        {"tbl": table},
    ).fetchone()
    return row is not None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    # Schema-agnostic: migration 0032 may have placed path_insights in public
    # (live DB) or ag_catalog (fresh migration run after 0004 reorders the
    # search_path).  Look the column up in whatever schema the table lives in.
    row = conn.execute(
        text("SELECT 1 FROM information_schema.columns WHERE table_name = :tbl AND column_name = :col"),
        {"tbl": table, "col": column},
    ).fetchone()
    return row is not None


def _index_exists(conn: sa.engine.Connection, index_name: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :idx"),
        {"idx": index_name},
    ).fetchone()
    return row is not None


# ── Upgrade contract: node_degree ─────────────────────────────────────────────


def test_node_degree_table_exists(conn: sa.engine.Connection) -> None:
    assert _table_exists(conn, "node_degree"), "node_degree table not created by 0052"


def test_node_degree_columns(conn: sa.engine.Connection) -> None:
    for col in ("entity_id", "degree", "degree_meaningful", "refreshed_at"):
        assert _column_exists(conn, "node_degree", col), f"node_degree.{col} missing"


def test_node_degree_check_constraint_rejects_negative(conn: sa.engine.Connection) -> None:
    """CHECK (degree >= 0) must reject a negative degree."""
    # Need a real canonical entity to satisfy the FK; create one in a rollback tx.
    eid = "01910000-0000-7000-8000-000000052001"
    conn.execute(
        text(
            "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type, created_at, updated_at) "
            "VALUES (:eid, 'Degree Co', 'financial_instrument', NOW(), NOW()) ON CONFLICT (entity_id) DO NOTHING"
        ),
        {"eid": eid},
    )
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            text("INSERT INTO node_degree (entity_id, degree, degree_meaningful) VALUES (:eid, -1, 0)"),
            {"eid": eid},
        )
    conn.rollback()


def test_node_degree_fk_cascade_to_canonical_entities(conn: sa.engine.Connection) -> None:
    """A node_degree row must FK-reference an existing canonical entity."""
    bogus = "99999999-9999-7999-8999-999999052999"
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            text("INSERT INTO node_degree (entity_id, degree, degree_meaningful) VALUES (:eid, 0, 0)"),
            {"eid": bogus},
        )
    conn.rollback()


# ── Upgrade contract: graph_stats ─────────────────────────────────────────────


def test_graph_stats_table_exists(conn: sa.engine.Connection) -> None:
    assert _table_exists(conn, "graph_stats"), "graph_stats table not created by 0052"


def test_graph_stats_singleton_check(conn: sa.engine.Connection) -> None:
    """CHECK (id = 1) must reject any non-1 id."""
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(text("INSERT INTO graph_stats (id, total_edges) VALUES (2, 100)"))
    conn.rollback()


def test_graph_stats_single_row_upsert(conn: sa.engine.Connection) -> None:
    """The id=1 row upserts cleanly (single-row normaliser store contract)."""
    conn.execute(
        text(
            "INSERT INTO graph_stats (id, total_edges, total_meaningful_edges, max_degree, refreshed_at) "
            "VALUES (1, 9977, 5200, 287, NOW()) "
            "ON CONFLICT (id) DO UPDATE SET total_edges = EXCLUDED.total_edges"
        )
    )
    row = conn.execute(text("SELECT total_edges FROM graph_stats WHERE id = 1")).fetchone()
    assert row is not None and row[0] == 9977
    conn.rollback()


# ── Upgrade contract: path_insights columns + indexes ─────────────────────────


def test_path_insights_new_columns_present_and_nullable(conn: sa.engine.Connection) -> None:
    for col in _NEW_COLUMNS:
        # Schema-agnostic (path_insights may be in public or ag_catalog).
        row = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'path_insights' AND column_name = :col"
            ),
            {"col": col},
        ).fetchone()
        assert row is not None, f"path_insights.{col} missing after 0052"
        assert row[0] == "YES", f"path_insights.{col} must be NULLable (R5/BP-126)"


def test_path_insights_deprecated_columns_retained(conn: sa.engine.Connection) -> None:
    """0052 must NOT drop the deprecated columns (R5 additive-only)."""
    for col in ("surprise_score", "diversity_score", "template_match", "composite_score"):
        assert _column_exists(conn, "path_insights", col), f"deprecated column {col} was dropped — R5 violation"


def test_path_insights_new_indexes_exist(conn: sa.engine.Connection) -> None:
    for idx in _NEW_INDEXES:
        assert _index_exists(conn, idx), f"index {idx} missing after 0052"


# ── Apply + rollback round-trip (0051 ↔ 0052) ─────────────────────────────────


def test_apply_and_rollback_round_trip(db_url: str) -> None:
    """Drive 0052 down→up explicitly: downgrade to 0051 removes the additions,
    upgrade back to 0052 restores them.  Leaves the DB at head (0052) for the
    remaining session-scoped tests.
    """
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    os.environ["INTELLIGENCE_DB_URL"] = db_url
    engine = sa.create_engine(db_url, pool_pre_ping=True)

    # Downgrade 0052 → 0051: additions gone.
    command.downgrade(cfg, "0051")
    with engine.connect() as conn:
        assert not _table_exists(conn, "node_degree"), "node_degree should be dropped on downgrade to 0051"
        assert not _table_exists(conn, "graph_stats"), "graph_stats should be dropped on downgrade to 0051"
        for col in _NEW_COLUMNS:
            assert not _column_exists(conn, "path_insights", col), f"{col} should be dropped on downgrade"
        for idx in _NEW_INDEXES:
            assert not _index_exists(conn, idx), f"{idx} should be dropped on downgrade"

    # Upgrade back 0051 → 0052: additions restored.
    command.upgrade(cfg, "0052")
    with engine.connect() as conn:
        assert _table_exists(conn, "node_degree")
        assert _table_exists(conn, "graph_stats")
        for col in _NEW_COLUMNS:
            assert _column_exists(conn, "path_insights", col)
        for idx in _NEW_INDEXES:
            assert _index_exists(conn, idx)
    engine.dispose()
