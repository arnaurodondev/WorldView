"""Freshness gate for the prod-smoke migration-drift check.

The prod-QA harness (``scripts/prod_qa/thresholds.py`` and, mirrored,
``scripts/prod_e2e_smoke.py``) hard-codes ``EXPECTED_ALEMBIC_HEADS`` — the head
Alembic revision each service DB is expected to sit at in production. When a
migration is merged but this map is NOT bumped, the harness flags a healthy DB
as ``STALE IMAGE`` (a FALSE POSITIVE), which emails the operator and — because a
non-zero smoke exit never records a CronJob success — also trips the critical
``ProdSmokeTestNotRunning`` alert. That exact drift happened on 2026-07-18
(ingestion_db 0024→0025, market_data_db 044→045).

This test closes the loop the harness comment always asked for ("a CI freshness
gate should assert this map == ``alembic heads`` for each service"): it computes
the true head of every service's migration DAG from the version files on disk
and asserts the map matches. A future migration that forgets to bump the map now
fails CI instead of silently paging the operator months later.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_expected_heads() -> dict[str, str]:
    """Import ``EXPECTED_ALEMBIC_HEADS`` from the harness thresholds module."""
    path = _REPO_ROOT / "scripts" / "prod_qa" / "thresholds.py"
    spec = importlib.util.spec_from_file_location("_prodqa_thresholds", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return dict(mod.EXPECTED_ALEMBIC_HEADS)


# DB name (as used in EXPECTED_ALEMBIC_HEADS) → service directory that owns its
# Alembic migrations. intelligence_db is owned by the intelligence-migrations
# service (S6/S7 share it and set ALEMBIC_ENABLED=false).
_DB_TO_SERVICE_DIR: dict[str, str] = {
    "alert_db": "alert",
    "content_ingestion_db": "content-ingestion",
    "content_store_db": "content-store",
    "ingestion_db": "market-ingestion",
    "intelligence_db": "intelligence-migrations",
    "market_data_db": "market-data",
    "nlp_db": "nlp-pipeline",
    "portfolio_db": "portfolio",
    "rag_db": "rag-chat",
}

_REVISION_RE = re.compile(r"""^\s*revision(?::\s*str)?\s*=\s*['"]([^'"]+)['"]""", re.MULTILINE)
_DOWN_REVISION_RE = re.compile(r"""^\s*down_revision(?::[^=]+)?\s*=\s*['"]([^'"]+)['"]""", re.MULTILINE)

# DBs where the RELEASE ref (git main) is intentionally AHEAD of the migration
# head currently applied in production — a deliberate deploy lag, NOT a stale
# map. The value is the repo/main head; the harness map deliberately pins the
# lower, actually-deployed head so the smoke check does not page on a migration
# the operator has chosen not to apply yet. Each entry is a REAL, tracked
# "prod is N migrations behind main" gap — keep this list short and audited.
#
#   intelligence_db: main head 0068 (0068_relation_evidence_default_partition —
#   DEFAULT partition that unblocks the evidence promoter) is not yet applied in
#   prod (DB@0067). Tracked in docs/audits/2026-07-19-alert-audit.md. Remove this
#   entry (and bump the map to 0068) once 0068 is deployed.
_KNOWN_PROD_LAG: dict[str, str] = {
    "intelligence_db": "0068",
}


def _revision_graph(service_dir: str) -> dict[str, str | None]:
    """Return {revision: down_revision} for every migration in a service."""
    versions = _REPO_ROOT / "services" / service_dir / "alembic" / "versions"
    graph: dict[str, str | None] = {}
    for f in versions.glob("*.py"):
        text = f.read_text()
        rev = _REVISION_RE.search(text)
        if not rev:
            continue
        down = _DOWN_REVISION_RE.search(text)
        graph[rev.group(1)] = down.group(1) if down else None
    return graph


def _compute_head(service_dir: str) -> str:
    """Return the single head revision of a service's Alembic version DAG.

    The head is the revision that no other migration references as its
    ``down_revision``. A well-formed linear history has exactly one.
    """
    graph = _revision_graph(service_dir)
    heads = set(graph) - {d for d in graph.values() if d is not None}
    assert len(heads) == 1, f"{service_dir}: expected exactly one head, found {sorted(heads)}"
    return next(iter(heads))


def _is_ancestor_or_equal(service_dir: str, candidate: str, head: str) -> bool:
    """True if ``candidate`` lies on the down_revision chain from ``head``."""
    graph = _revision_graph(service_dir)
    cur: str | None = head
    seen: set[str] = set()
    while cur is not None and cur not in seen:
        if cur == candidate:
            return True
        seen.add(cur)
        cur = graph.get(cur)
    return False


def test_all_dbs_have_a_service_dir_mapping() -> None:
    """Every DB in the harness map must be resolvable to a migrations dir."""
    expected = _load_expected_heads()
    missing = set(expected) - set(_DB_TO_SERVICE_DIR)
    assert not missing, f"unmapped DBs in EXPECTED_ALEMBIC_HEADS: {sorted(missing)}"


@pytest.mark.parametrize("db", sorted(_DB_TO_SERVICE_DIR))
def test_expected_head_matches_migration_dag(db: str) -> None:
    """The pinned head must equal the true head of the service's migration DAG.

    Fails loudly the moment a migration is merged without bumping the harness
    map — the drift that produced the 2026-07-18 false-positive smoke FAILs.
    DBs with a deliberate, documented prod deploy-lag (``_KNOWN_PROD_LAG``) are
    instead required to pin a real ancestor of the (lagged) main head, so the
    gap stays truthful without paging on an undeployed migration.
    """
    expected = _load_expected_heads()
    service_dir = _DB_TO_SERVICE_DIR[db]
    assert db in expected, f"{db} missing from EXPECTED_ALEMBIC_HEADS"
    true_head = _compute_head(service_dir)

    if db in _KNOWN_PROD_LAG:
        # The annotation must stay in sync with the actual repo head...
        assert _KNOWN_PROD_LAG[db] == true_head, (
            f"{db}: _KNOWN_PROD_LAG pins main head '{_KNOWN_PROD_LAG[db]}' but the "
            f"migration DAG head is now '{true_head}'. Update _KNOWN_PROD_LAG (and "
            f"decide whether the pinned prod head should advance too)."
        )
        # ...and the map must pin a REAL earlier revision on the head's chain.
        assert _is_ancestor_or_equal(service_dir, expected[db], true_head), (
            f"{db}: EXPECTED_ALEMBIC_HEADS pins '{expected[db]}', which is not an "
            f"ancestor of main head '{true_head}' — stale or typo'd revision."
        )
        return

    assert expected[db] == true_head, (
        f"{db}: EXPECTED_ALEMBIC_HEADS pins '{expected[db]}' but the migration "
        f"DAG head is '{true_head}'. Bump the map in scripts/prod_qa/thresholds.py "
        f"AND scripts/prod_e2e_smoke.py (they must stay in sync)."
    )


def test_smoke_and_thresholds_maps_agree() -> None:
    """The two copies of the map (harness + standalone smoke) must not diverge."""
    from_thresholds = _load_expected_heads()

    smoke_path = _REPO_ROOT / "scripts" / "prod_e2e_smoke.py"
    text = smoke_path.read_text()
    block = text.split("EXPECTED_ALEMBIC_HEADS", 1)[1].split("}", 1)[0]
    smoke_map = dict(re.findall(r"""['"]([a-z_]+_db)['"]\s*:\s*['"]([^'"]+)['"]""", block))

    assert smoke_map == from_thresholds, (
        "EXPECTED_ALEMBIC_HEADS diverged between scripts/prod_e2e_smoke.py and "
        f"scripts/prod_qa/thresholds.py: smoke={smoke_map} thresholds={from_thresholds}"
    )
