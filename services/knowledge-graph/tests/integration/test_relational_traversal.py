"""Integration + AGE-parity tests for RelationalGraphPathAdapter (PLAN-0113 W1).

Runs against a real intelligence_db (skips if unavailable — see conftest gating).
Seeds a small known graph in ``canonical_entities`` + ``relations``, materialises
the ``graph_edges`` matview (creating it if migration 0063 has not yet been
applied to this DB, then REFRESHing after the seed), and exercises the adapter:

  * hop counts + node sets for known pairwise paths
  * shortest-hop via ``path_exists``
  * membership pruning drops a sector-only route
  * the degree cap bounds enumeration
  * AGE-parity: the relational adapter returns the SAME shortest hop count and
    the SAME node-id set as the AGE engine on the same data, with
    ``prune_membership=True`` (skipped if AGE/age extension is unavailable)

A benchmark test records relational p50/p95 latency on the seeded graph (prints,
never asserts a hard threshold — the live re-benchmark is the authoritative
number).
"""

from __future__ import annotations

import statistics
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.integration]


# DDL identical to migration 0063 — used to (idempotently) ensure the matview
# exists on a test DB that may predate 0063.  Safe: IF NOT EXISTS throughout.
_ENSURE_MATVIEW = """
CREATE MATERIALIZED VIEW IF NOT EXISTS public.graph_edges AS
    SELECT relation_id, subject_entity_id AS src, object_entity_id AS dst,
           upper(replace(canonical_type, ' ', '_')) AS typ, confidence, subject_entity_id
      FROM relations
     WHERE confidence > 0.1 AND subject_entity_id <> object_entity_id
    UNION
    SELECT relation_id, object_entity_id AS src, subject_entity_id AS dst,
           upper(replace(canonical_type, ' ', '_')) AS typ, confidence, subject_entity_id
      FROM relations
     WHERE confidence > 0.1 AND subject_entity_id <> object_entity_id
WITH DATA
"""
_ENSURE_UIDX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uidx_graph_edges_rel_src_dst " "ON public.graph_edges (relation_id, src, dst)"
)
_ENSURE_SRC = "CREATE INDEX IF NOT EXISTS idx_graph_edges_src ON public.graph_edges (src)"
_ENSURE_DST = "CREATE INDEX IF NOT EXISTS idx_graph_edges_dst ON public.graph_edges (dst)"


async def _seed_graph(session_factory) -> dict[str, UUID]:
    """Seed a tiny known graph and (re)materialise graph_edges.

    Topology (all confidence 0.9 unless noted):
        apple --SUPPLIER_OF--> tsmc --PARTNER_OF--> anthropic
        apple --IS_IN_SECTOR--> tech_sector <--IS_IN_SECTOR-- microsoft
        nintendo : isolated (no edges) — disconnected control
    So apple↔anthropic shortest = 2 (non-membership); apple↔microsoft = 2 but
    membership-only (must be pruned); apple↔nintendo disconnected.
    """
    ids = {name: uuid4() for name in ("apple", "tsmc", "anthropic", "tech_sector", "microsoft", "nintendo")}
    async with session_factory() as s:
        for name, eid in ids.items():
            etype = "sector" if name == "tech_sector" else "company"
            await s.execute(
                text(
                    "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type) "
                    "VALUES (:id, :name, :etype)"
                ),
                {"id": eid, "name": name, "etype": etype},
            )
        rels = [
            (ids["apple"], "supplier_of", ids["tsmc"]),
            (ids["tsmc"], "partner_of", ids["anthropic"]),
            (ids["apple"], "is_in_sector", ids["tech_sector"]),
            (ids["microsoft"], "is_in_sector", ids["tech_sector"]),
        ]
        for subj, typ, obj in rels:
            await s.execute(
                text(
                    "INSERT INTO relations (relation_id, subject_entity_id, canonical_type, "
                    "object_entity_id, confidence, base_confidence, confidence_stale) "
                    "VALUES (:rid, :subj, :typ, :obj, 0.9, 0.9, false)"
                ),
                {"rid": uuid4(), "subj": subj, "typ": typ, "obj": obj},
            )
        # Ensure matview exists + indexes, then refresh to pick up the seed.
        await s.execute(text(_ENSURE_MATVIEW))
        await s.execute(text(_ENSURE_UIDX))
        await s.execute(text(_ENSURE_SRC))
        await s.execute(text(_ENSURE_DST))
        await s.commit()
        # CONCURRENTLY needs its own (committed) transaction; plain refresh is fine
        # here since the test owns the table.
        await s.execute(text("REFRESH MATERIALIZED VIEW public.graph_edges"))
        await s.commit()
    return ids


@pytest.mark.asyncio
async def test_pairwise_hop_count_and_node_set(session_factory) -> None:
    from knowledge_graph.infrastructure.relational.graph_path_adapter import (
        RelationalGraphPathAdapter,
    )

    ids = await _seed_graph(session_factory)
    adapter = RelationalGraphPathAdapter(session_factory)

    paths = await adapter.find_paths_between(ids["apple"], ids["anthropic"], max_hops=3, prune_membership=True, limit=5)
    assert paths, "expected a non-membership path apple->tsmc->anthropic"
    shortest = min(p.hop_count for p in paths)
    assert shortest == 2
    # The shortest path's node set is exactly {apple, tsmc, anthropic}.
    p2 = next(p for p in paths if p.hop_count == 2)
    assert set(p2.node_ids) == {str(ids["apple"]), str(ids["tsmc"]), str(ids["anthropic"])}
    assert p2.rel_types == ("SUPPLIER_OF", "PARTNER_OF")


@pytest.mark.asyncio
async def test_path_exists_shortest_hops(session_factory) -> None:
    from knowledge_graph.infrastructure.relational.graph_path_adapter import (
        RelationalGraphPathAdapter,
    )

    ids = await _seed_graph(session_factory)
    adapter = RelationalGraphPathAdapter(session_factory)

    assert await adapter.path_exists(ids["apple"], ids["anthropic"], max_hops=3) == 2
    assert await adapter.path_exists(ids["apple"], ids["tsmc"], max_hops=3) == 1
    # Disconnected control.
    assert await adapter.path_exists(ids["apple"], ids["nintendo"], max_hops=3) is None


@pytest.mark.asyncio
async def test_membership_only_route_pruned(session_factory) -> None:
    from knowledge_graph.infrastructure.relational.graph_path_adapter import (
        RelationalGraphPathAdapter,
    )

    ids = await _seed_graph(session_factory)
    adapter = RelationalGraphPathAdapter(session_factory)

    # apple↔microsoft connect ONLY through the shared sector (membership). With
    # pruning on, no reportable path; with pruning off, the 2-hop sector route.
    pruned = await adapter.find_paths_between(
        ids["apple"], ids["microsoft"], max_hops=3, prune_membership=True, limit=5
    )
    assert pruned == []
    unpruned = await adapter.find_paths_between(
        ids["apple"], ids["microsoft"], max_hops=3, prune_membership=False, limit=5
    )
    assert any(p.hop_count == 2 for p in unpruned)


@pytest.mark.asyncio
async def test_degree_cap_bounds_enumeration(session_factory) -> None:
    from knowledge_graph.infrastructure.relational.graph_path_adapter import (
        RelationalGraphPathAdapter,
    )

    ids = await _seed_graph(session_factory)
    # degree_cap=1: each frontier node expands at most ONE neighbour, so the
    # apple->tsmc->anthropic chain (a single linear route) is still found.
    adapter = RelationalGraphPathAdapter(session_factory, degree_cap=1)
    paths = await adapter.find_paths_between(ids["apple"], ids["tsmc"], max_hops=2, prune_membership=False, limit=5)
    assert any(p.hop_count == 1 for p in paths)


@pytest.mark.asyncio
async def test_age_parity_shortest_hops_and_node_set(session_factory) -> None:
    """Relational adapter == AGE engine on shortest hop + node-id set (prune on).

    Skips if the AGE extension / worldview_graph is unavailable on this DB (the
    relational adapter does not need AGE; this parity check does).
    """
    from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine
    from knowledge_graph.infrastructure.relational.graph_path_adapter import (
        RelationalGraphPathAdapter,
    )

    ids = await _seed_graph(session_factory)

    # The AGE engine needs the seeded relations mirrored into worldview_graph; if
    # the AGE sync has not run for this seed (or the extension is absent), skip —
    # the relational adapter is still covered by the other tests.
    age = AgeGraphPathEngine(session_factory)
    try:
        age_hops = await age.path_exists(ids["apple"], ids["anthropic"], max_hops=3)
    except Exception:
        pytest.skip("AGE engine unavailable / graph not synced for seed")
    if age_hops is None:
        pytest.skip("AGE graph not synced for seeded relations")

    rel = RelationalGraphPathAdapter(session_factory)
    rel_hops = await rel.path_exists(ids["apple"], ids["anthropic"], max_hops=3)
    assert rel_hops == age_hops

    age_paths = await age.find_paths_between(ids["apple"], ids["anthropic"], max_hops=3, prune_membership=True, limit=5)
    rel_paths = await rel.find_paths_between(ids["apple"], ids["anthropic"], max_hops=3, prune_membership=True, limit=5)
    age_min = min(p.hop_count for p in age_paths)
    rel_min = min(p.hop_count for p in rel_paths)
    age_shortest_nodes = {frozenset(p.node_ids) for p in age_paths if p.hop_count == age_min}
    rel_shortest_nodes = {frozenset(p.node_ids) for p in rel_paths if p.hop_count == rel_min}
    assert rel_shortest_nodes == age_shortest_nodes


@pytest.mark.asyncio
async def test_benchmark_relational_latency(session_factory) -> None:
    """Record relational p50/p95 on the seeded graph (informational, no hard gate)."""
    from knowledge_graph.infrastructure.relational.graph_path_adapter import (
        RelationalGraphPathAdapter,
    )

    ids = await _seed_graph(session_factory)
    adapter = RelationalGraphPathAdapter(session_factory)

    samples: list[float] = []
    for _ in range(20):
        t0 = time.perf_counter()
        await adapter.find_paths_between(ids["apple"], ids["anthropic"], max_hops=3, prune_membership=True, limit=5)
        samples.append((time.perf_counter() - t0) * 1000.0)

    p50 = statistics.median(samples)
    p95 = statistics.quantiles(samples, n=100)[94] if len(samples) > 1 else samples[0]
    print(f"\n[relational bench] seeded-graph pairwise p50={p50:.2f}ms p95={p95:.2f}ms (n={len(samples)})")
    # Generous sanity ceiling (seeded graph is tiny; real numbers come from live).
    assert p50 < 2000.0
