"""Create the ``graph_edges`` materialized view (relational traversal hot path).

Revision ID: 0063
Revises: 0062
Create Date: 2026-06-25

WHY THIS MIGRATION EXISTS (PLAN-0113):
  Connection discovery (entity↔entity pathfinding) currently runs against Apache
  AGE via Cypher variable-length-edge traversal.  On the live graph the AGE
  pairwise probe measures ~0.9 s p95 *idle* but degrades to ~17 s under
  contention (every traversal needs ``LOAD 'age'`` on a write session and AGE's
  VLE executor competes with ingestion).  A plain-Postgres recursive-CTE
  traversal over a flat edge projection measured ~4 ms p50 / ~53 ms p95 on the
  SAME data (prototype: scripts/eval/bench_relational_traversal_prototype.py).

  This materialized view is the persistent, indexed form of that prototype's
  session-temp projection: a BOTH-DIRECTIONS, deduplicated edge list derived from
  ``relations`` that the new ``RelationalGraphPathAdapter`` traverses with an
  ordinary recursive CTE (no AGE, no write session, read-replica friendly).

WHAT THIS MIGRATION ADDS:
  MATERIALIZED VIEW ``graph_edges`` with one row per (directed) edge:
    - relation_id        — source ``relations.relation_id`` (carried for scoring)
    - src / dst          — directed endpoints (BOTH orientations emitted)
    - typ                — AGE-style edge label: UPPER(REPLACE(canonical_type,' ','_'))
    - confidence         — source edge confidence
    - subject_entity_id  — the TRUE stored subject, so the adapter can compute
                           ``edge_forward`` (src == subject_entity_id) for parity
                           with the AGE engine's directionality handling.

  Filter: ``confidence > 0.1`` (matches the prototype + the relational adapter's
  default floor) AND ``subject_entity_id <> object_entity_id`` (no self-loops).

  Both directions are emitted (forward subject→object AND reverse object→subject)
  so the recursive CTE can walk an UNDIRECTED graph with a single ``e.src = node``
  join — exactly mirroring the AGE undirected VLE semantics.

INDEXES:
  - ``uidx_graph_edges_rel_src_dst`` UNIQUE (relation_id, src, dst): required for
    ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` (Postgres needs a unique index to
    refresh without an exclusive lock).  The pair (src, dst) differs between the
    forward and reverse rows of the same relation_id, so the triple is unique.
  - ``idx_graph_edges_src`` btree (src): the recursive-CTE frontier expansion
    joins ``graph_edges.src = current_node`` — this index makes each expansion an
    index scan instead of a seq scan.
  - ``idx_graph_edges_dst`` btree (dst): symmetric helper (reverse lookups /
    planner flexibility).

WHY plain (non-CONCURRENTLY) CREATE here:
  ``CREATE MATERIALIZED VIEW`` and its indexes are built inside the serial,
  one-shot intelligence-migrations init container at deploy time (BP-393), where
  a plain transactional build is the established convention.  CONCURRENTLY is for
  later REFRESHes against a live view (a unique index now exists to support it).

IDEMPOTENCY:
  ``IF NOT EXISTS`` on the view and all indexes — safe to re-run against a DB
  that already has them (stale volume).

DOWNGRADE:
  Drops the indexes and the view.  Fully reversible; nothing else references the
  view (the adapter is feature-flagged off by default), so dropping it cannot
  break a running service.

SCHEMA QUALIFICATION (collision guard):
  The matview is created EXPLICITLY in ``public`` (``public.graph_edges``).  Some
  pre-built Apache-AGE Postgres images carry a stray identically-named matview in
  the ``ag_catalog`` schema (a leftover from an earlier projection experiment).
  An UNQUALIFIED ``graph_edges`` reference could resolve to that one whenever the
  AGE search_path (``ag_catalog`` first) is active on a session.  Qualifying to
  ``public.graph_edges`` here (and in the adapter SQL) removes all ambiguity: the
  relational engine always reads exactly the matview this migration owns.
"""

from __future__ import annotations

from alembic import op

revision: str = "0063"
down_revision: str = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both-directions, deduplicated edge projection from ``relations``.  The
    # UNION (not UNION ALL) deduplicates identical (relation_id, src, dst, ...)
    # rows that could arise from the two legs; in practice the forward and
    # reverse legs differ in (src, dst) so both survive.  ``typ`` is normalised
    # to the AGE edge-label form (uppercase, spaces→underscores) so the adapter's
    # MEMBERSHIP_RELATIONS filter (which uses AGE labels) matches directly.
    op.execute(
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS public.graph_edges AS
            SELECT
                relation_id,
                subject_entity_id AS src,
                object_entity_id  AS dst,
                upper(replace(canonical_type, ' ', '_')) AS typ,
                confidence,
                subject_entity_id
              FROM relations
             WHERE confidence > 0.1
               AND subject_entity_id <> object_entity_id
            UNION
            SELECT
                relation_id,
                object_entity_id  AS src,
                subject_entity_id AS dst,
                upper(replace(canonical_type, ' ', '_')) AS typ,
                confidence,
                subject_entity_id
              FROM relations
             WHERE confidence > 0.1
               AND subject_entity_id <> object_entity_id
        WITH DATA
        """
    )

    # UNIQUE index — mandatory for REFRESH MATERIALIZED VIEW CONCURRENTLY.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uidx_graph_edges_rel_src_dst
            ON public.graph_edges (relation_id, src, dst)
        """
    )
    # Frontier-expansion index: recursive CTE joins on src.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_graph_edges_src
            ON public.graph_edges (src)
        """
    )
    # Symmetric reverse-lookup index.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_graph_edges_dst
            ON public.graph_edges (dst)
        """
    )


def downgrade() -> None:
    # Indexes are dropped automatically with the view, but drop explicitly first
    # for clarity/idempotency parity with the upgrade.
    op.execute("DROP INDEX IF EXISTS public.idx_graph_edges_dst")
    op.execute("DROP INDEX IF EXISTS public.idx_graph_edges_src")
    op.execute("DROP INDEX IF EXISTS public.uidx_graph_edges_rel_src_dst")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS public.graph_edges")
