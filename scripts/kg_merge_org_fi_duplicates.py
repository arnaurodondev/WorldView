#!/usr/bin/env python3
"""Cleanup migration: merge duplicate ORGANIZATION canonicals into their FINANCIAL_INSTRUMENT twin.

WHAT THIS FIXES
---------------
The knowledge graph carries a company as BOTH an ``organization`` canonical
(random-UUID, minted by NER → provisional promotion) AND a
``financial_instrument`` canonical (batch-seeded from market data, e.g.
``019f646a…``, carrying the ticker + market data).  The design intent
(nlp-pipeline ``entity_resolution.py``) is that the FINANCIAL_INSTRUMENT row IS
the canonical for a public company; the ORG duplicate fragments relations across
two nodes (2026-07 dedup audit: 65 org↔FI duplicates, ~16% of relations hung off
the wrong node — Apple: 2 relations on the ORG node vs 14 on the FI node).

The resolver leak that CREATES these duplicates is fixed separately by the guard
in ``provisional_enrichment_core.persist_enrichment`` +
``CanonicalEntityRepository.find_financial_instrument_for_company``.  This script
REPAIRS the graph that was already polluted before the guard shipped.

WHAT IT DOES (per org→FI pair)
------------------------------
REPOINTS every reference from the ORG ``entity_id`` to the FI ``entity_id``:
  intelligence_db:
    relations (subject/object), relations_history, relation_evidence_raw,
    claims (subject/claimer), events (subject), event_entities, entity_event_exposures,
    entity_narrative_versions, provisional_entity_queue.assigned_entity_id,
    node_degree (org rows deleted — FI recomputed), entity_embedding_state (org
    rows deleted — FI already embedded), entity_aliases (repointed + deduped;
    the org's name survives as an FI alias), path_insights, llm_usage_log
  Apache AGE ``worldview_graph``:
    edges in ``_ag_label_edge`` (start_id/end_id repointed to the FI vertex),
    the ORG vertex deleted
  nlp_db:
    mention_resolutions.candidate_entity_id, entity_mentions.resolved_entity_id,
    article_impact_windows.entity_id
Then DELETES the ORG ``canonical_entities`` row.

SAFETY
------
  * DRY-RUN by default: every statement runs inside a transaction that is ROLLED
    BACK, and the exact affected-row counts are printed.  Nothing changes until
    you pass ``--apply``.
  * Idempotent: after a successful apply the ORG rows are gone, so a re-run finds
    an empty mapping and is a no-op.  A partial/interrupted apply is safe to
    re-run (each step is "move refs from a now-absent ORG to the FI").
  * Self-loop safe: repointing a relation/edge that connected the ORG to its FI
    would create a ``fi → fi`` self-loop (violates ``chk_relations_no_self_loop``
    / pollutes AGE).  Those rows are DELETED before the repoint.
  * Ambiguous pairs (an ORG whose name/ticker matches >1 FI — e.g. "Alphabet"
    → GOOGL and GOOG) are SKIPPED by default and reported for manual decision.
    Pass ``--include-ambiguous`` to fold them into the deterministically-chosen
    FI (most relations, then lowest entity_id).

EXACT INVOCATION
----------------
Runs anywhere with network access to postgres + the ``asyncpg`` driver.  The
knowledge-graph pod already has both.  Recommended (in-cluster, fast):

    # 1. copy the script into a running KG pod
    export KUBECONFIG=~/.kube/config-worldview
    POD=$(kubectl -n worldview get pods -o name | grep knowledge-graph-6 | head -1)
    kubectl -n worldview cp scripts/kg_merge_org_fi_duplicates.py "${POD#pod/}":/tmp/merge.py

    # 2. DRY-RUN (default) — prints the full plan + per-table counts, changes NOTHING
    kubectl -n worldview exec "$POD" -- python /tmp/merge.py

    # 3. review the plan, then APPLY
    kubectl -n worldview exec "$POD" -- python /tmp/merge.py --apply

DSNs are auto-derived from the pod's ``KNOWLEDGE_GRAPH_DATABASE_URL`` env var
(intel = that DB; nlp = same server, database ``nlp_db``).  Override with
``--intel-dsn`` / ``--nlp-dsn`` if running elsewhere (e.g. against a port-forward).
"""

# ruff: noqa: S608 — every interpolated identifier is a hardcoded module constant
# (table/column names in _REPOINT_TABLES etc.); all values are bound parameters.
# There is no user input anywhere in this ops script, so the SQL is injection-safe.

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field

import asyncpg  # type: ignore[import-untyped]

# ── Shared normalization ─────────────────────────────────────────────────────
# IDENTICAL to CanonicalEntityRepository.find_financial_instrument_for_company
# (the runtime guard).  A row this migration merges is exactly a row the guard
# would fold — the two can never diverge.  Strips corporate suffixes +
# punctuation so ``Apple`` == ``Apple Inc.`` and ``NVIDIA Corporation`` == ``Nvidia``.
_NORM_SQL = r"""btrim(regexp_replace(regexp_replace(regexp_replace(
    lower({col}), '[^a-z0-9]+', ' ', 'g'),
    '\y(inc|incorporated|corp|corporation|company|co|plc|ltd|limited|group|holdings|holding|nv|sa|ag|the|class [abc])\y', ' ', 'g'),
    '\s+', ' ', 'g'))"""

# Candidate org→FI pairs: ORG matches an FI by exact ticker OR normalized name.
_MAPPING_SQL = f"""
WITH norm AS (
    SELECT entity_id, entity_type, canonical_name, ticker,
           {_NORM_SQL.format(col="canonical_name")} AS nkey
    FROM canonical_entities
),
pairs AS (
    SELECT o.entity_id AS org_id, f.entity_id AS fi_id
    FROM canonical_entities o
    JOIN canonical_entities f
      ON upper(o.ticker) = upper(f.ticker) AND f.entity_type = 'financial_instrument'
    WHERE o.entity_type = 'organization' AND o.ticker IS NOT NULL
    UNION
    SELECT o.entity_id, f.entity_id
    FROM norm o JOIN norm f ON o.nkey = f.nkey AND f.entity_type = 'financial_instrument'
    WHERE o.entity_type = 'organization' AND o.nkey <> ''
)
SELECT p.org_id, o.canonical_name AS org_name, p.fi_id, f.canonical_name AS fi_name,
       (SELECT count(*) FROM relations r
          WHERE r.subject_entity_id = p.fi_id OR r.object_entity_id = p.fi_id) AS fi_rel_count
FROM pairs p
JOIN canonical_entities o ON o.entity_id = p.org_id
JOIN canonical_entities f ON f.entity_id = p.fi_id
ORDER BY o.canonical_name, fi_rel_count DESC, p.fi_id
"""


@dataclass
class Merge:
    org_id: str
    org_name: str
    fi_id: str
    fi_name: str


@dataclass
class StepCount:
    label: str
    rows: int


@dataclass
class Report:
    merges: list[Merge] = field(default_factory=list)
    ambiguous: dict[str, list[str]] = field(default_factory=dict)  # org_id -> [fi names]
    counts: list[StepCount] = field(default_factory=list)


# ── Repoint plan ─────────────────────────────────────────────────────────────
# (table, [entity-id columns]).  Straight UPDATE col = fi WHERE col = org.
_REPOINT_TABLES: list[tuple[str, list[str]]] = [
    ("relations", ["subject_entity_id", "object_entity_id"]),
    ("relations_history", ["subject_entity_id", "object_entity_id"]),
    ("relation_evidence_raw", ["subject_entity_id", "object_entity_id"]),
    ("claims", ["subject_entity_id", "claimer_entity_id"]),
    ("events", ["subject_entity_id"]),
    ("provisional_entity_queue", ["assigned_entity_id"]),
    ("path_insights", ["anchor_entity_id", "dst_entity_id"]),
    ("llm_usage_log", ["entity_id"]),
]
# Tables with a UNIQUE(..., entity_id, ...) constraint: delete the ORG row when
# the FI already has one for the SAME match-key, then repoint the survivors.
# match_cols are the OTHER unique-key columns (entity_id is the one being moved):
#   event_entities            PK (event_id, entity_id)               → match event_id
#   entity_event_exposures    UNIQUE (event_id, entity_id, exposure_type) → match both
_DEDUP_ON_KEY: list[tuple[str, list[str]]] = [
    ("event_entities", ["event_id"]),
    ("entity_event_exposures", ["event_id", "exposure_type"]),
]
# Tables whose ORG rows are simply DROPPED (the FI carries its own authoritative
# copy; keying on entity_id these would violate a unique/PK on repoint):
#   node_degree               PK (entity_id)
#   entity_embedding_state    PK (entity_id, view_type)
#   entity_narrative_versions UNIQUE (entity_id) WHERE is_current  (uq_entity_narrative_current)
_DROP_ORG_ROWS = ["node_degree", "entity_embedding_state", "entity_narrative_versions"]

_NLP_REPOINT: list[tuple[str, str]] = [
    ("mention_resolutions", "candidate_entity_id"),
    ("entity_mentions", "resolved_entity_id"),
    ("article_impact_windows", "entity_id"),
]

# System sentinel entities exempt from the self-loop CHECK (kept for reference).
_SELF_LOOP_SENTINELS = (
    "11111111-0004-7000-8000-000000000001",
    "11111111-0004-7000-8000-000000000002",
    "11111111-0004-7000-8000-000000000003",
    "11111111-0004-7000-8000-000000000004",
    "11111111-0004-7000-8000-000000000005",
)


async def _load_mapping(conn: asyncpg.Connection, *, include_ambiguous: bool) -> Report:
    """Compute the org→FI merge plan, flagging (and by default skipping) ambiguous orgs."""
    rows = await conn.fetch(_MAPPING_SQL)
    # Group candidate FIs per org (rows already ordered fi_rel_count DESC, fi_id).
    per_org: dict[str, list[asyncpg.Record]] = {}
    for r in rows:
        per_org.setdefault(str(r["org_id"]), []).append(r)

    report = Report()
    for org_id, candidates in per_org.items():
        distinct_fi = {str(c["fi_id"]) for c in candidates}
        chosen = candidates[0]  # deterministic: most FI relations, then lowest fi_id
        if len(distinct_fi) > 1:
            report.ambiguous[org_id] = [f"{c['fi_name']} ({c['fi_id']})" for c in candidates]
            if not include_ambiguous:
                continue
        report.merges.append(
            Merge(
                org_id=org_id,
                org_name=str(chosen["org_name"]),
                fi_id=str(chosen["fi_id"]),
                fi_name=str(chosen["fi_name"]),
            )
        )
    return report


async def _apply_intelligence(conn: asyncpg.Connection, merges: list[Merge], report: Report) -> None:
    """Repoint + delete inside intelligence_db (relational tables + AGE graph)."""
    # AGE extension + search_path (ag_catalog for cypher(), public keeps the
    # relational tables resolvable).  Inside the txn so a dry-run rollback reverts it.
    await _age_setup(conn)
    for m in merges:
        org, fi = m.org_id, m.fi_id
        tag = f"{m.org_name} → {m.fi_name}"

        # 1. Delete relations/edges that would become fi→fi self-loops on repoint.
        for tbl in ("relations", "relations_history", "relation_evidence_raw"):
            res = await conn.execute(
                f"DELETE FROM {tbl} "
                "WHERE (subject_entity_id = $1 AND object_entity_id = $2) "
                "   OR (subject_entity_id = $2 AND object_entity_id = $1)",
                org,
                fi,
            )
            _tally(report, f"[{tag}] {tbl}: delete org↔fi self-loop rows", res)

        # 1b. relations dedup — the SAME edge often exists on BOTH the org and the
        #     fi node (that IS the fragmentation).  ``relations`` carries a
        #     per-partition UNIQUE (subject_entity_id, canonical_type,
        #     object_entity_id), so repointing an org relation that duplicates an
        #     existing fi relation would violate it.  Delete the org duplicate
        #     first (the fi relation is authoritative; its evidence/confidence is
        #     already accrued on the canonical node).  Both directions:
        res = await conn.execute(
            "DELETE FROM relations ro WHERE ro.subject_entity_id = $1 "
            "AND EXISTS (SELECT 1 FROM relations rf WHERE rf.subject_entity_id = $2 "
            "  AND rf.canonical_type = ro.canonical_type AND rf.object_entity_id = ro.object_entity_id)",
            org,
            fi,
        )
        _tally(report, f"[{tag}] relations: drop org dup (subject-side) already on fi", res)
        res = await conn.execute(
            "DELETE FROM relations ro WHERE ro.object_entity_id = $1 "
            "AND EXISTS (SELECT 1 FROM relations rf WHERE rf.object_entity_id = $2 "
            "  AND rf.canonical_type = ro.canonical_type AND rf.subject_entity_id = ro.subject_entity_id)",
            org,
            fi,
        )
        _tally(report, f"[{tag}] relations: drop org dup (object-side) already on fi", res)

        # 2. Straight repoints.
        for tbl, cols in _REPOINT_TABLES:
            for col in cols:
                res = await conn.execute(
                    f"UPDATE {tbl} SET {col} = $2 WHERE {col} = $1",
                    org,
                    fi,
                )
                _tally(report, f"[{tag}] {tbl}.{col}: repoint", res)

        # 3. Key-scoped dedup tables: drop ORG row when FI already owns the same
        #    unique key (all match_cols equal), then repoint the survivors.
        for tbl, match_cols in _DEDUP_ON_KEY:
            match_pred = " AND ".join(f"f.{c} = t.{c}" for c in match_cols)
            res_del = await conn.execute(
                f"DELETE FROM {tbl} t WHERE t.entity_id = $1 "
                f"AND EXISTS (SELECT 1 FROM {tbl} f WHERE {match_pred} AND f.entity_id = $2)",
                org,
                fi,
            )
            _tally(report, f"[{tag}] {tbl}: drop org row colliding with fi", res_del)
            res_up = await conn.execute(f"UPDATE {tbl} SET entity_id = $2 WHERE entity_id = $1", org, fi)
            _tally(report, f"[{tag}] {tbl}.entity_id: repoint", res_up)

        # 4. entity_aliases: repoint, deduping against the FI's existing aliases.
        res_adel = await conn.execute(
            "DELETE FROM entity_aliases a WHERE a.entity_id = $1 "
            "AND EXISTS (SELECT 1 FROM entity_aliases f WHERE f.entity_id = $2 "
            "  AND f.normalized_alias_text = a.normalized_alias_text AND f.alias_type = a.alias_type)",
            org,
            fi,
        )
        _tally(report, f"[{tag}] entity_aliases: drop org alias colliding with fi", res_adel)
        res_aup = await conn.execute("UPDATE entity_aliases SET entity_id = $2 WHERE entity_id = $1", org, fi)
        _tally(report, f"[{tag}] entity_aliases: repoint (org name survives as fi alias)", res_aup)

        # 5. Drop ORG-only bookkeeping rows (FI carries its own; recomputed downstream).
        for tbl in _DROP_ORG_ROWS:
            res = await conn.execute(f"DELETE FROM {tbl} WHERE entity_id = $1", org)
            _tally(report, f"[{tag}] {tbl}: drop org rows", res)

        # 6. Apache AGE — repoint edges onto the FI vertex, delete the ORG vertex.
        await _apply_age(conn, org, fi, tag, report)

        # 7. Finally delete the ORG canonical row (all refs now repointed).
        res = await conn.execute("DELETE FROM canonical_entities WHERE entity_id = $1", org)
        _tally(report, f"[{tag}] canonical_entities: delete org row", res)


async def _age_setup(conn: asyncpg.Connection) -> None:
    """Load the AGE extension + search_path once per connection.

    asyncpg cannot run two ``;``-separated commands in a single ``execute`` call,
    so LOAD and SET are issued separately.  Run once before any graph query.
    """
    await conn.execute("LOAD 'age'")
    await conn.execute("SET search_path = ag_catalog, public")


async def _graphid(conn: asyncpg.Connection, entity_id: str) -> int | None:
    """Return the AGE vertex graphid (as bigint) for a canonical entity_id, or None."""
    row = await conn.fetchrow(
        "SELECT (id::text)::bigint AS gid FROM cypher('worldview_graph', $c$ "
        f"MATCH (n) WHERE n.entity_id = '{entity_id}' RETURN id(n) AS id $c$) AS (id agtype)"
    )
    return int(row["gid"]) if row else None


async def _apply_age(conn: asyncpg.Connection, org: str, fi: str, tag: str, report: Report) -> None:
    """Repoint worldview_graph edges from the ORG vertex to the FI vertex; drop ORG vertex."""
    org_gid = await _graphid(conn, org)
    fi_gid = await _graphid(conn, fi)
    if org_gid is None:
        _tally(report, f"[{tag}] AGE: no org vertex (skip)", "SKIP 0")
        return
    if fi_gid is None:
        # FI has no vertex yet — detach org edges is unsafe; leave for review.
        _tally(report, f"[{tag}] AGE: FI vertex MISSING — org edges left in place", "SKIP 0")
        return

    # a) delete edges directly between org & fi (would become fi→fi self-loops)
    res = await conn.execute(
        "DELETE FROM worldview_graph._ag_label_edge "
        "WHERE ((start_id::text)::bigint = $1 AND (end_id::text)::bigint = $2) "
        "   OR ((start_id::text)::bigint = $2 AND (end_id::text)::bigint = $1)",
        org_gid,
        fi_gid,
    )
    _tally(report, f"[{tag}] AGE edges: delete org↔fi self-loop edges", res)

    # b) repoint start_id / end_id onto the FI vertex (SET uses the FI vertex's
    #    graphid-typed id via a join, so no bigint→graphid cast is needed).
    for endpoint in ("start_id", "end_id"):
        res = await conn.execute(
            "UPDATE worldview_graph._ag_label_edge e SET "
            f"{endpoint} = fivtx.id "
            "FROM worldview_graph.entity fivtx "
            "WHERE (fivtx.id::text)::bigint = $2 "
            f"AND (e.{endpoint}::text)::bigint = $1",
            org_gid,
            fi_gid,
        )
        _tally(report, f"[{tag}] AGE edges.{endpoint}: repoint to fi vertex", res)

    # c) delete the now-orphaned ORG vertex.
    res = await conn.execute("DELETE FROM worldview_graph.entity WHERE (id::text)::bigint = $1", org_gid)
    _tally(report, f"[{tag}] AGE vertex: delete org vertex", res)


async def _apply_nlp(conn: asyncpg.Connection, merges: list[Merge], report: Report) -> None:
    """Repoint entity references inside nlp_db."""
    for m in merges:
        for tbl, col in _NLP_REPOINT:
            res = await conn.execute(f"UPDATE {tbl} SET {col} = $2 WHERE {col} = $1", m.org_id, m.fi_id)
            _tally(report, f"[nlp_db] [{m.org_name} → {m.fi_name}] {tbl}.{col}: repoint", res)


def _tally(report: Report, label: str, execute_result: str) -> None:
    """Record affected-row count from an asyncpg execute() status string (e.g. 'UPDATE 7')."""
    try:
        rows = int(str(execute_result).split()[-1])
    except (ValueError, IndexError):
        rows = 0
    if rows:
        report.counts.append(StepCount(label=label, rows=rows))


def _derive_dsns(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve intel/nlp DSNs from args or the KG service env var."""
    intel = args.intel_dsn or os.environ.get("KNOWLEDGE_GRAPH_DATABASE_URL", "")
    intel = intel.replace("postgresql+asyncpg://", "postgresql://")
    if not intel:
        sys.exit("No intel DSN: pass --intel-dsn or set KNOWLEDGE_GRAPH_DATABASE_URL")
    nlp = args.nlp_dsn
    if not nlp:
        # Same server, database nlp_db.
        nlp = intel.rsplit("/", 1)[0] + "/nlp_db"
    return intel, nlp


def _print_report(report: Report, *, applied: bool) -> None:
    mode = "APPLIED" if applied else "DRY-RUN (rolled back — nothing changed)"
    print(f"\n{'=' * 78}\nKG org↔FI duplicate merge — {mode}\n{'=' * 78}")
    print(f"\nMerges planned: {len(report.merges)}")
    for m in report.merges:
        print(f"  • {m.org_name:38.38} ({m.org_id})")
        print(f"      → {m.fi_name:36.36} ({m.fi_id})")
    if report.ambiguous:
        print("\n⚠ Ambiguous orgs SKIPPED (>1 FI candidate — resolve manually or --include-ambiguous):")
        for org_id, fis in report.ambiguous.items():
            print(f"  • org {org_id} → {fis}")
    print(f"\nRow changes ({len(report.counts)} non-empty steps):")
    for c in report.counts:
        print(f"  {c.rows:>6}  {c.label}")
    total = sum(c.rows for c in report.counts)
    print(f"\nTotal rows affected: {total}")


async def _run(args: argparse.Namespace) -> None:
    intel_dsn, nlp_dsn = _derive_dsns(args)
    report = Report()

    intel = await asyncpg.connect(intel_dsn)
    nlp = await asyncpg.connect(nlp_dsn)
    try:
        loaded = await _load_mapping(intel, include_ambiguous=args.include_ambiguous)
        report.merges = loaded.merges
        report.ambiguous = loaded.ambiguous
        if not report.merges:
            print("No org→FI duplicates to merge (graph already clean).")
            if report.ambiguous:
                _print_report(report, applied=False)
            return

        # nlp_db first (idempotent; a later intel failure leaves nlp pointing at
        # the valid FI), then intelligence_db (+ AGE). Both wrapped in a txn so a
        # dry-run rolls back cleanly.
        nlp_tx = nlp.transaction()
        intel_tx = intel.transaction()
        await nlp_tx.start()
        await intel_tx.start()
        try:
            await _apply_nlp(nlp, report.merges, report)
            await _apply_intelligence(intel, report.merges, report)
            if args.apply:
                await nlp_tx.commit()
                await intel_tx.commit()
            else:
                await intel_tx.rollback()
                await nlp_tx.rollback()
        except Exception:
            await intel_tx.rollback()
            await nlp_tx.rollback()
            raise
    finally:
        await intel.close()
        await nlp.close()

    _print_report(report, applied=args.apply)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="Execute the merge (default: dry-run, rolls back).")
    p.add_argument(
        "--include-ambiguous",
        action="store_true",
        help="Also fold orgs matching >1 FI into the deterministically-chosen FI.",
    )
    p.add_argument(
        "--intel-dsn", default=None, help="intelligence_db DSN (default: from KNOWLEDGE_GRAPH_DATABASE_URL)."
    )
    p.add_argument("--nlp-dsn", default=None, help="nlp_db DSN (default: same server, db=nlp_db).")
    args = p.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
