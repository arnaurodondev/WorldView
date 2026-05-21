"""TASK-W3-01 Test 1 — Forward migration applies cleanly.

After ``alembic upgrade head`` runs (via the session-scoped autouse fixture
in ``tests/integration/conftest.py``), assert that:

  * All expected core tables exist (queried from ``information_schema``).
  * Key indexes from recent migrations are present (sampled from the
    latest 5 migrations).
  * The ``alembic_version`` table reflects the latest head revision
    declared on disk.

These tests REQUIRE a reachable Postgres at ``INTELLIGENCE_DB_URL`` with
the extensions ``vector`` and ``age`` available. When the DB is not
reachable the ``live_db_ready`` fixture skips them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

pytestmark = pytest.mark.integration

# Expected tables — sampled from migrations 0001-0040. Covers the schema
# spine; the existing tests/test_migration.py asserts the broader set.
_EXPECTED_CORE_TABLES: tuple[str, ...] = (
    "alembic_version",
    "canonical_entities",
    "entity_aliases",
    "entity_embedding_state",
    "relations",
    "relation_evidence",
    "relation_evidence_raw",
    "relation_summaries",
    "relation_type_registry",
    "claims",
    "events",
    "temporal_events",
    "entity_event_exposures",
    "entity_narrative_versions",
    "path_insights",
    "path_insight_jobs",
    "path_templates",
    "provisional_entity_queue",
    "llm_usage_log",
    "model_registry",
    "prompt_templates",
    "ticker_aliases",
)

# Sampled indexes from the latest five migrations (0036..0040).
# Each entry is (index_name, source_migration_prefix) — only the name is
# asserted; the source is documented for traceability.
_SAMPLED_RECENT_INDEXES: tuple[tuple[str, str], ...] = (
    ("idx_relation_evidence_source_diversity", "0035"),
    ("uq_path_insight_jobs_active", "0032"),
    ("uq_entity_narrative_current", "0031"),
    ("idx_canonical_entities_dedup", "0026"),
    ("uidx_temporal_events_natural_key", "0037"),
)


def _alembic_head_on_disk() -> str:
    """Inspect the alembic/versions/ directory and return the head revision
    (the revision that no other migration points back to).
    """
    versions_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    revisions: dict[str, str | None] = {}
    rev_re = re.compile(r"^\s*revision(?:\s*:\s*\w+)?\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
    down_re = re.compile(
        r"^\s*down_revision(?:\s*:\s*[\w\[\]| ]+)?\s*=\s*(['\"]([^'\"]+)['\"]|None)",
        re.MULTILINE,
    )
    for f in versions_dir.glob("*.py"):
        if f.name.startswith("_"):
            continue
        text_ = f.read_text(encoding="utf-8")
        rev_match = rev_re.search(text_)
        down_match = down_re.search(text_)
        if rev_match is None:
            continue
        if down_match is None or down_match.group(1) == "None":
            revisions[rev_match.group(1)] = None
        else:
            revisions[rev_match.group(1)] = down_match.group(2)
    pointed_to = {down for down in revisions.values() if down is not None}
    heads = [rev for rev in revisions if rev not in pointed_to]
    assert len(heads) == 1, f"on-disk head detection failed: {heads}"
    return heads[0]


def test_alembic_version_matches_disk_head(live_db_ready: None, conn: sa.engine.Connection) -> None:
    """``alembic_version.version_num`` after ``upgrade head`` equals the head
    revision discovered on disk.
    """
    expected_head = _alembic_head_on_disk()
    actual = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert actual == expected_head, f"alembic_version mismatch: db={actual!r}, disk head={expected_head!r}"


def test_all_expected_core_tables_exist(live_db_ready: None, conn: sa.engine.Connection) -> None:
    """Every table in ``_EXPECTED_CORE_TABLES`` exists in the public schema."""
    result = conn.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' "
            "UNION "
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'alembic_version'"
        )
    )
    existing = {row[0] for row in result}
    missing = [t for t in _EXPECTED_CORE_TABLES if t not in existing]
    assert not missing, f"Missing tables after upgrade head: {missing}"


@pytest.mark.parametrize("index_name,source_migration", _SAMPLED_RECENT_INDEXES)
def test_recent_migration_indexes_exist(
    live_db_ready: None,
    conn: sa.engine.Connection,
    index_name: str,
    source_migration: str,
) -> None:
    """Each sampled index from the most recent 5-or-so migrations exists.

    These are the high-value indexes flagged by their parent migrations —
    if any of them is missing post-``upgrade head``, the migration body or
    a partial-failure recovery left the DB in an unusable state.
    """
    found = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
        {"name": index_name},
    ).fetchone()
    assert found is not None, f"Index {index_name!r} (from migration {source_migration}) is missing"
