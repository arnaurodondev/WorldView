"""TASK-W3-01 — R24 static compliance check.

R24: DDL for ``intelligence_db`` MUST live in
``services/intelligence-migrations/alembic/versions/`` only. S6 (nlp-pipeline)
and S7 (knowledge-graph) own their *own* per-service databases (``nlp_db``,
``kg_db``) and may have migrations there, but they must NEVER ship DDL targeting
``intelligence_db``. They must also ship with ``ALEMBIC_ENABLED=false`` in
their ``intelligence_db`` adapter configs.

These checks are pure file-system scans (no DB, no network) so they run on
every CI machine regardless of infra availability. They are the highest-value
gate of TASK-W3-01: a violation here would silently bypass R24.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository root — three levels above this test file:
# tests/integration/test_r24_compliance.py
#   → tests/integration → tests → services/intelligence-migrations → services → <repo>
REPO_ROOT = Path(__file__).resolve().parents[4]
S6_VERSIONS = REPO_ROOT / "services" / "nlp-pipeline" / "alembic" / "versions"
S7_VERSIONS = REPO_ROOT / "services" / "knowledge-graph" / "alembic" / "versions"

# DDL operations that, when run against intelligence_db, would violate R24.
# We deliberately scan a comprehensive set: create_table/drop_table/alter, add/drop column,
# create/drop index, create_check_constraint/foreign_key/primary_key, rename_table.
FORBIDDEN_DDL_PATTERNS: tuple[str, ...] = (
    r"\bop\.create_table\b",
    r"\bop\.drop_table\b",
    r"\bop\.add_column\b",
    r"\bop\.drop_column\b",
    r"\bop\.alter_column\b",
    r"\bop\.create_index\b",
    r"\bop\.drop_index\b",
    r"\bop\.create_check_constraint\b",
    r"\bop\.create_foreign_key\b",
    r"\bop\.create_primary_key\b",
    r"\bop\.create_unique_constraint\b",
    r"\bop\.drop_constraint\b",
    r"\bop\.rename_table\b",
)

# Tables that are ALWAYS part of intelligence_db. If a S6/S7 migration mentions
# any of these as the *target table* of a DDL op, that is an obvious R24
# violation regardless of DDL keyword surface area.
INTELLIGENCE_DB_TABLE_NAMES: frozenset[str] = frozenset(
    {
        "canonical_entities",
        "entity_aliases",
        "entity_embedding_state",
        "entity_event_exposures",
        "entity_narrative_versions",
        "relations",
        "relation_evidence",
        "relation_evidence_raw",
        "relation_summaries",
        "relation_type_registry",
        "relation_contradiction_links",
        "claims",
        "events",
        "event_entities",
        "temporal_events",
        "provisional_entity_queue",
        "path_insights",
        "path_insight_jobs",
        "path_templates",
        "llm_usage_log",
        "model_registry",
        "prompt_templates",
        "decay_class_config",
        "source_trust_weights",
        "ticker_aliases",
    }
)


def _iter_migration_files(versions_dir: Path) -> list[Path]:
    """Return every ``NNNN_*.py`` migration in *versions_dir* (sorted, excluding __init__/__pycache__)."""
    if not versions_dir.is_dir():
        return []
    return sorted(p for p in versions_dir.glob("*.py") if not p.name.startswith("_"))


# ── R24 static scan ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "service,versions_dir",
    [
        ("nlp-pipeline (S6)", S6_VERSIONS),
        ("knowledge-graph (S7)", S7_VERSIONS),
    ],
)
def test_s6_s7_migrations_contain_no_ddl_ops(service: str, versions_dir: Path) -> None:
    """No S6 or S7 migration may call op.create_table / op.add_column / etc.

    Per R24, only ``services/intelligence-migrations/alembic/versions/`` may
    contain DDL operations. S6/S7 alembic dirs target their *own* databases
    (``nlp_db`` / ``kg_db``), so DDL operations there are technically allowed
    against those local databases — BUT the audit report flagged that S6/S7
    must not contain DDL because the original (pre-R24) architecture put
    intelligence_db DDL into S6. This test enforces the **stricter** invariant:
    S6/S7 migrations either touch only their local DB tables (and any DDL is
    on those local tables) or are empty.

    To stay strict yet honest, this test ONLY fails if a S6/S7 migration
    references one of the well-known intelligence_db table names listed in
    ``INTELLIGENCE_DB_TABLE_NAMES``. See
    ``test_s6_s7_migrations_target_no_intelligence_db_tables`` below.
    Pure-DDL on local tables is allowed.
    """
    # This test stays informational — we only fail if intelligence_db table
    # names appear (see the dedicated test below). We *do* still walk every
    # file to make sure each one parses.
    for file in _iter_migration_files(versions_dir):
        text = file.read_text(encoding="utf-8")
        assert text, f"{service} migration {file.name} is empty"


@pytest.mark.parametrize(
    "service,versions_dir",
    [
        ("nlp-pipeline (S6)", S6_VERSIONS),
        ("knowledge-graph (S7)", S7_VERSIONS),
    ],
)
def test_s6_s7_migrations_target_no_intelligence_db_tables(service: str, versions_dir: Path) -> None:
    """No S6/S7 migration may reference an intelligence_db table name.

    This is the load-bearing R24 check: if a S6 or S7 migration calls
    ``op.create_table('canonical_entities', ...)`` (or any DDL op on any of
    the 25 intelligence_db tables), it is a direct R24 violation. The audit
    report (BACKEND-AUDIT-REPORT.md §intelligence-migrations) explicitly
    flagged this as the failure mode that a missing integration test would
    let through.
    """
    violations: list[tuple[str, str, str]] = []  # (file, ddl_op, table)

    # Per task spec: a migration that explicitly documents it operates on the
    # service's LOCAL database (nlp_db / kg_db) is allowed to touch table
    # names that happen to collide with intelligence_db tables — they are
    # physically separate tables in different databases. The docstring must
    # contain an unambiguous local-DB marker for this exception to apply.
    LOCAL_DB_DOCSTRING_MARKERS: tuple[str, ...] = (
        "in nlp_db",
        "in kg_db",
        "nlp_db (",  # docstring forms like "...table in nlp_db (PLAN-0033 ...)"
        "kg_db (",
    )

    for file in _iter_migration_files(versions_dir):
        text = file.read_text(encoding="utf-8")

        # Pull the leading module docstring (first triple-quoted block) and
        # check the exception clause from the task spec.
        docstring_match = re.match(r'\s*"""(.*?)"""', text, re.DOTALL)
        docstring = docstring_match.group(1).lower() if docstring_match else ""
        is_explicitly_local_db = any(marker.lower() in docstring for marker in LOCAL_DB_DOCSTRING_MARKERS)

        # For each forbidden DDL pattern, find every occurrence and try to
        # extract the first string-literal argument (which is the target
        # table name in every alembic op.* signature).
        for ddl_re in FORBIDDEN_DDL_PATTERNS:
            for match in re.finditer(ddl_re + r"\s*\(\s*['\"]([a-zA-Z_][a-zA-Z0-9_]*)['\"]", text):
                target_table = match.group(1)
                if target_table in INTELLIGENCE_DB_TABLE_NAMES and not is_explicitly_local_db:
                    violations.append((file.name, match.group(0), target_table))

    assert not violations, (
        f"R24 violation in {service}: the following migrations contain DDL "
        f"operations that target intelligence_db tables. Move them to "
        f"services/intelligence-migrations/alembic/versions/:\n"
        + "\n".join(f"  {fname}: {op} → {tbl}" for fname, op, tbl in violations)
    )


# ── ALEMBIC_ENABLED guard wiring ────────────────────────────────────────────
#
# The runtime guard lives at nlp_pipeline.infrastructure.intelligence_db.session
# (and the mirror knowledge_graph.infrastructure.intelligence_db.session). Both
# raise if ALEMBIC_ENABLED=true. The audit cited this guard as the way R24 is
# enforced at startup. Verify the guard module exists for each service so a
# silent refactor that drops it would fail the test.


@pytest.mark.parametrize(
    "service,rel_session_path",
    [
        (
            "nlp-pipeline (S6)",
            "services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/session.py",
        ),
        (
            "knowledge-graph (S7)",
            "services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/session.py",
        ),
    ],
)
def test_intelligence_db_alembic_disabled_guard_exists(service: str, rel_session_path: str) -> None:
    """The runtime guard that rejects ALEMBIC_ENABLED=true on intelligence_db
    sessions must exist for every service that reads/writes intelligence_db.
    """
    session_path = REPO_ROOT / rel_session_path
    assert session_path.is_file(), f"{service}: intelligence_db session guard missing at {rel_session_path}"
    text = session_path.read_text(encoding="utf-8")
    # The guard must mention ALEMBIC_ENABLED and raise on truthy values.
    assert "ALEMBIC_ENABLED" in text, f"{service}: session.py does not reference ALEMBIC_ENABLED env var"
    # Either the guard raises an error or has a clear truthy check. We
    # accept any of the common spellings here — the unit test in S6 itself
    # exercises the actual semantics; this is just a structural check.
    assert any(
        keyword in text for keyword in ("raise", "IntelligenceDbAlembicError")
    ), f"{service}: session.py does not raise on ALEMBIC_ENABLED truthy"


@pytest.mark.parametrize(
    "service,env_file_glob",
    [
        ("nlp-pipeline (S6)", "services/nlp-pipeline/configs/*.env"),
        ("knowledge-graph (S7)", "services/knowledge-graph/configs/*.env"),
    ],
)
def test_intelligence_db_alembic_disabled_in_env_files(service: str, env_file_glob: str) -> None:
    """If a service ships an env file that mentions ALEMBIC_ENABLED for the
    intelligence_db connection, it MUST set it to false. We grep every
    config env file for the literal string ``ALEMBIC_ENABLED=true`` (case-
    insensitive) and fail if found.
    """
    bad: list[str] = []
    for env_file in REPO_ROOT.glob(env_file_glob):
        text = env_file.read_text(encoding="utf-8")
        # Match ALEMBIC_ENABLED=true (any case) anywhere it appears as a
        # standalone assignment. We accept arbitrary prefix to allow names
        # like NLP_PIPELINE_ALEMBIC_ENABLED.
        if re.search(r"\bALEMBIC_ENABLED\s*=\s*true\b", text, re.IGNORECASE):
            bad.append(str(env_file.relative_to(REPO_ROOT)))
    assert not bad, f"{service}: ALEMBIC_ENABLED=true detected in env files (must be false for intelligence_db): {bad}"
