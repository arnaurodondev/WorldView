#!/usr/bin/env python3
"""Reconcile the Apache AGE shadow graph against ``public.relations`` (FR-13).

ROOT CAUSE (see docs/audits/2026-06-13-fr13-age-relations-sync-gap-investigation.md):
the AGE sync worker (``age_sync_worker._sync_relations``) is *additive-only* — a
watermark-based Cypher ``MERGE`` that never issues a ``DELETE``.  Meanwhile the
relational side DOES delete ``relations`` rows: ``merge_ticker_duplicates.py``
(the BP-459 ticker-dedup) deletes self-loops + triple-collisions and never
touches AGE.  Result: AGE accumulates the *historical superset* of every
relation_id ever synced.  As measured 2026-06-13:

  * ~4,662 phantom EDGES — non-membership AGE edges whose ``relation_id`` is
    absent from ``public.relations`` (49.7% of non-membership edges).
  * ~609 phantom VERTICES — AGE ``entity`` vertices whose ``entity_id`` is absent
    from ``canonical_entities`` (merged-away dedup losers).
  * ~157 of the phantom edges are *fully dangling* (absent from BOTH ``relations``
    and ``relation_evidence``).

Phantoms skew ``node_degree`` (degree is counted from ``_ag_label_edge``), carry
stale frozen confidence, and surface as false topology in path discovery / the
weird-connections feed / the entity-graph UI.

This script performs a one-off reconcile, in three steps:

  (a) DELETE phantom edges — every non-membership AGE edge whose ``relation_id``
      property is NOT in ``public.relations`` is removed via Cypher
      ``MATCH ()-[r {relation_id: $rid}]->() DELETE r`` (batched).
  (b) DETACH DELETE phantom vertices — every AGE ``entity`` vertex whose
      ``entity_id`` is NOT in ``canonical_entities`` is removed (``DETACH`` also
      clears any residual edges still hanging off it).
  (c) REFRESH degree — re-run ``NodeDegreeRepository.refresh_from_age`` so
      ``node_degree`` + ``graph_stats`` reflect the cleaned topology.

SAFETY:
  * DRY-RUN BY DEFAULT.  Without ``--apply`` the script only COUNTS what it would
    delete and prints per-step totals; it executes NO Cypher ``DELETE`` and NO
    degree refresh.  Pass ``--apply`` to actually mutate the graph.
  * IDEMPOTENT.  After a successful ``--apply`` pass the orphan cohorts are empty,
    so a re-run reports 0 phantoms and is a no-op.  Cypher ``DELETE`` of an
    already-absent edge is harmless.
  * The agtype-safe SQL patterns mirror ``age_sync_worker`` / the FR-13
    investigation: edge property objects are rendered with
    ``format('%s', e.properties)::jsonb`` (a direct ``properties::text`` cast
    raises "agtype argument must resolve to a scalar value"), and the AGE label
    id is recovered from the high 16 bits of the graphid via
    ``(e.id::text::bigint >> 48)::int``.

Usage:
    # report only — no writes (default)
    python scripts/data/reconcile_age_graph.py
    python scripts/data/reconcile_age_graph.py --dry-run    # explicit, same as above

    # actually delete phantoms + refresh degree
    python scripts/data/reconcile_age_graph.py --apply

    # tune the per-step delete batch size
    python scripts/data/reconcile_age_graph.py --apply --batch-size 200

DSN overrides via env: ``INTELLIGENCE_DB_DSN`` (psycopg/sync, default local
docker-compose).  The async degree refresh derives an asyncpg URL from the same
DSN unless ``INTELLIGENCE_DB_ASYNC_DSN`` is set.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass

import psycopg
from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS

# Default DSN targets the local docker-compose Postgres (single instance).
# Override via env for other environments.
_INTEL_DSN = os.environ.get(
    "INTELLIGENCE_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/intelligence_db",
)

# AGE graph name / schema (matches AgeSyncWorker + NodeDegreeRepository).
_GRAPH = "worldview_graph"

# How many phantom edges/vertices to DELETE per Cypher round-trip.  AGE has no
# bulk delete-by-property, so we iterate; batching keeps the loop observable and
# bounds per-statement work.
_DEFAULT_BATCH = 500


# ── Orphan detection (read-only) ────────────────────────────────────────────────


def _membership_labels_sql_list() -> str:
    """Render MEMBERSHIP_RELATIONS as a SQL string literal list for ``NOT IN``.

    These labels (e.g. ``IS_IN_SECTOR``) are membership-style edges that are not
    keyed to a ``relations`` row in the same way and are explicitly EXCLUDED from
    the phantom-edge cohort (matching the FR-13 investigation §2.1).  The labels
    are compile-time constants (plain uppercase identifiers), never user input.
    """
    labels = sorted(MEMBERSHIP_RELATIONS)
    # Defence-in-depth: refuse to embed anything that is not a plain identifier.
    for label in labels:
        if not label.replace("_", "").isalnum() or not label.isupper():
            msg = f"Refusing to embed non-identifier membership label: {label!r}"
            raise ValueError(msg)
    return ", ".join(f"'{label}'" for label in labels)


# Read-only SQL: every non-membership AGE edge that carries a ``relation_id``
# property whose value is NOT present in ``public.relations``.  Returns the
# distinct phantom relation_ids (one Cypher DELETE per id removes all edges that
# carry it — there is normally exactly one).
def _phantom_edge_relation_ids_sql() -> str:
    # _GRAPH + membership labels are compile-time constants (never user input);
    # the SQL is parameter-free detection — S608 is a false positive here.
    membership = _membership_labels_sql_list()
    sql = f"""
WITH nm AS (
    SELECT format('%s', e.properties)::jsonb AS props
    FROM {_GRAPH}._ag_label_edge e
    JOIN ag_catalog.ag_graph g ON g.name = '{_GRAPH}'
    JOIN ag_catalog.ag_label l
      ON l.graph = g.graphid
     AND l.id = (e.id::text::bigint >> 48)::int
    WHERE l.name NOT IN ({membership})
)
SELECT DISTINCT (props->>'relation_id') AS relation_id
FROM nm
WHERE props ? 'relation_id'
  AND NOT EXISTS (
        SELECT 1 FROM public.relations pr
        WHERE pr.relation_id = (props->>'relation_id')::uuid
  )
"""  # noqa: S608
    return sql


# Read-only SQL: every AGE ``entity`` vertex whose ``entity_id`` property is NOT
# present in ``canonical_entities`` (the merged-away dedup losers).
def _phantom_vertex_entity_ids_sql() -> str:
    # _GRAPH is a compile-time constant; parameter-free detection — S608 false positive.
    sql = f"""
WITH v AS (
    SELECT trim(both '"' from
        ag_catalog.agtype_access_operator(ve.properties, '"entity_id"'::ag_catalog.agtype)::text
    ) AS entity_id
    FROM {_GRAPH}.entity ve
)
SELECT DISTINCT entity_id
FROM v
WHERE entity_id ~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
  AND NOT EXISTS (
        SELECT 1 FROM public.canonical_entities ce
        WHERE ce.entity_id = v.entity_id::uuid
  )
"""  # noqa: S608
    return sql


def find_phantom_edge_relation_ids(intel: psycopg.Connection) -> list[str]:
    """Return distinct ``relation_id`` strings of phantom (orphaned) AGE edges."""
    _setup_age_session_sync(intel)
    rows = intel.execute(_phantom_edge_relation_ids_sql()).fetchall()
    return [str(r[0]) for r in rows if r[0] is not None]


def find_phantom_vertex_entity_ids(intel: psycopg.Connection) -> list[str]:
    """Return distinct ``entity_id`` strings of phantom AGE entity vertices."""
    _setup_age_session_sync(intel)
    rows = intel.execute(_phantom_vertex_entity_ids_sql()).fetchall()
    return [str(r[0]) for r in rows if r[0] is not None]


# ── AGE session + Cypher DELETE (mutating) ──────────────────────────────────────


def _setup_age_session_sync(conn: psycopg.Connection) -> None:
    """Load the AGE extension + set search_path for this (sync) connection.

    Mirrors ``age_sync_worker._setup_age_session`` — every connection that issues
    AGE Cypher (or the agtype helpers used in detection) must run these first.
    """
    conn.execute("LOAD 'age'")
    conn.execute('SET search_path = ag_catalog, "$user", worldview_graph, public')


# AGE Cypher DELETE templates.  The graph name is a static constant (no
# interpolation); the data value is passed as the agtype JSON parameter ``$1``.
_CYPHER_DELETE_EDGE = (
    "SELECT * FROM ag_catalog.cypher('"  # noqa: S608 — _GRAPH constant; value is agtype JSON param
    + _GRAPH
    + "', $$ MATCH ()-[r {relation_id: $relation_id}]->() DELETE r $$, %(params)s) AS (r ag_catalog.agtype)"
)
_CYPHER_DELETE_VERTEX = (
    "SELECT * FROM ag_catalog.cypher('"  # noqa: S608 — _GRAPH constant; value is agtype JSON param
    + _GRAPH
    + "', $$ MATCH (e:entity {entity_id: $entity_id}) DETACH DELETE e $$, %(params)s) AS (r ag_catalog.agtype)"
)


def delete_phantom_edges(intel: psycopg.Connection, relation_ids: list[str], *, batch_size: int) -> int:
    """DELETE every AGE edge carrying one of *relation_ids*.  Returns count attempted.

    One Cypher round-trip per relation_id (AGE has no bulk delete-by-property);
    ``batch_size`` bounds how many we flush before logging progress.  Re-running
    against an already-absent edge is a harmless no-op (idempotent).
    """
    _setup_age_session_sync(intel)
    done = 0
    for rid in relation_ids:
        intel.execute(_CYPHER_DELETE_EDGE, {"params": json.dumps({"relation_id": rid})})
        done += 1
        if done % batch_size == 0:
            print(f"    ...deleted {done}/{len(relation_ids)} phantom edges")
    return done


def delete_phantom_vertices(intel: psycopg.Connection, entity_ids: list[str], *, batch_size: int) -> int:
    """DETACH DELETE every AGE entity vertex in *entity_ids*.  Returns count attempted."""
    _setup_age_session_sync(intel)
    done = 0
    for eid in entity_ids:
        intel.execute(_CYPHER_DELETE_VERTEX, {"params": json.dumps({"entity_id": eid})})
        done += 1
        if done % batch_size == 0:
            print(f"    ...deleted {done}/{len(entity_ids)} phantom vertices")
    return done


# ── Degree refresh (async, step c) ──────────────────────────────────────────────


def _async_dsn() -> str:
    """Derive an asyncpg SQLAlchemy URL for the degree refresh from the sync DSN."""
    override = os.environ.get("INTELLIGENCE_DB_ASYNC_DSN")
    if override:
        return override
    # psycopg sync DSN → SQLAlchemy asyncpg URL.
    dsn = _INTEL_DSN
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
    return dsn


async def _refresh_node_degrees_async() -> None:
    """Re-run NodeDegreeRepository.refresh_from_age over the cleaned graph."""
    # Imported lazily so dry-run / unit tests that never touch the DB do not pay
    # the SQLAlchemy + asyncpg import cost (and so the module imports cleanly even
    # where asyncpg is absent).
    from knowledge_graph.infrastructure.intelligence_db.repositories.node_degree_repository import (
        NodeDegreeRepository,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_async_dsn(), echo=False, future=True, pool_pre_ping=True)
    try:
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as session:
            repo = NodeDegreeRepository(session)
            stats = await repo.refresh_from_age()
            await session.commit()
        print(
            f"    degree refreshed: total_edges={stats.total_edges} "
            f"total_meaningful_edges={stats.total_meaningful_edges} max_degree={stats.max_degree}"
        )
    finally:
        await engine.dispose()


def refresh_node_degrees() -> None:
    """Synchronous entry point for the async degree refresh (step c)."""
    asyncio.run(_refresh_node_degrees_async())


# ── Orchestration ───────────────────────────────────────────────────────────────


@dataclass
class ReconcileReport:
    """Per-step counts for one reconcile pass."""

    phantom_edges: int
    phantom_vertices: int
    applied: bool


def reconcile(intel: psycopg.Connection, *, apply: bool, batch_size: int) -> ReconcileReport:
    """Run the FR-13 reconcile (steps a, b, c).  Read-only unless *apply* is True.

    Detection always runs (read-only).  When *apply* is False the function only
    reports the counts it WOULD delete and performs no mutation and no degree
    refresh.  When *apply* is True it executes the Cypher deletes, commits, and
    refreshes ``node_degree`` / ``graph_stats``.
    """
    print("Step (a): detecting phantom edges (relation_id ∉ public.relations)...")
    phantom_edge_ids = find_phantom_edge_relation_ids(intel)
    print(f"  phantom edges (distinct relation_ids): {len(phantom_edge_ids)}")

    print("Step (b): detecting phantom vertices (entity_id ∉ canonical_entities)...")
    phantom_vertex_ids = find_phantom_vertex_entity_ids(intel)
    print(f"  phantom vertices: {len(phantom_vertex_ids)}")

    if not apply:
        print("\nDRY RUN — no Cypher DELETE issued, no degree refresh.")
        print(
            f"Would delete {len(phantom_edge_ids)} phantom edge(s) "
            f"and {len(phantom_vertex_ids)} phantom vertex(es), then refresh degree."
        )
        print("Re-run with --apply to execute.")
        return ReconcileReport(
            phantom_edges=len(phantom_edge_ids),
            phantom_vertices=len(phantom_vertex_ids),
            applied=False,
        )

    print("\nAPPLYING — deleting phantom edges...")
    n_edges = delete_phantom_edges(intel, phantom_edge_ids, batch_size=batch_size)
    print(f"  deleted {n_edges} phantom edge(s)")

    print("Deleting phantom vertices (DETACH DELETE)...")
    n_vertices = delete_phantom_vertices(intel, phantom_vertex_ids, batch_size=batch_size)
    print(f"  deleted {n_vertices} phantom vertex(es)")

    intel.commit()
    print("  committed AGE deletions")

    print("Step (c): refreshing node_degree + graph_stats from cleaned graph...")
    refresh_node_degrees()

    print(f"\nDone. Deleted {n_edges} edge(s) + {n_vertices} vertex(es); degree refreshed.")
    return ReconcileReport(phantom_edges=n_edges, phantom_vertices=n_vertices, applied=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Reconcile the AGE shadow graph against public.relations (FR-13).",
    )
    group = ap.add_mutually_exclusive_group()
    group.add_argument(
        "--apply",
        action="store_true",
        help="Execute the Cypher DELETEs + degree refresh (default is dry-run).",
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts only, no writes (the default behaviour).",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH,
        help=f"Phantom deletes per progress flush (default {_DEFAULT_BATCH}).",
    )
    args = ap.parse_args()

    apply = bool(args.apply)
    mode = "APPLY" if apply else "DRY RUN"
    print(f"FR-13 AGE↔relations reconcile — mode={mode}\n")

    with psycopg.connect(_INTEL_DSN) as intel:
        reconcile(intel, apply=apply, batch_size=args.batch_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
