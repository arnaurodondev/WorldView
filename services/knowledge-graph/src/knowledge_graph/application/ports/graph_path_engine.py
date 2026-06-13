"""GraphPathEngine port — the single graph-traversal abstraction (PLAN-0112 T-2-01).

PRD-0112 §6.5 / FR-2: all connection discovery (per-anchor batch discovery AND
on-demand pairwise pathfinding) goes through this one port.  The concrete
implementation (``infrastructure/age/graph_path_engine.py::AgeGraphPathEngine``)
consolidates the proven staged variable-length-edge (VLE) probing from
``CypherPathUseCase`` (BP-687) and retires the slow untyped-explicit-edge form
(``path_discovery.py::_build_2hop_sql/_build_3hop_sql``, BP-689).

Architecture (R25): this is an application-layer port (ABC).  Use cases and
workers depend on this abstraction, never on the AGE adapter directly.

``RawPath`` lives here (the application layer) rather than in ``infrastructure``
so the port can reference its own return type without the application layer
importing infrastructure (layer-boundary rule R12).  The old import location
``infrastructure.age.path_discovery.RawPath`` is preserved as a re-export for
backward compatibility with existing call sites and tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True)
class RawPath:
    """A single multi-hop path returned by the graph traversal engine.

    All data required for scoring is pre-extracted so Python scoring code never
    needs to re-query the DB.  Nodes are listed in path order (start → … → end);
    each edge ``i`` connects ``node_ids[i] → node_ids[i + 1]``.
    """

    # entity_id values for each node in order (start → ... → end)
    node_ids: tuple[str, ...]
    # canonical_name of each node (same order as node_ids)
    node_names: tuple[str, ...]
    # entity_type of each node
    node_types: tuple[str, ...]
    # relation_type (AGE edge label) of each edge (len = len(node_ids) - 1)
    rel_types: tuple[str, ...]
    # confidence of each edge (same order as rel_types)
    edge_confs: tuple[float, ...]
    # relation_id (UUID) of each edge — parsed from relationships(p) properties.
    # Used by WeirdnessScorer (W3) to join relations.first_evidence_at (novelty)
    # without re-querying the graph.  Defaults to empty for legacy callers /
    # rows where the edge carried no relation_id property (PLAN-0112 T-2-01).
    rel_ids: tuple[UUID, ...] = field(default_factory=tuple)

    @property
    def hop_count(self) -> int:
        return len(self.rel_types)


class GraphPathEngine(ABC):
    """Abstract graph-traversal engine (PRD-0112 §6.5, FR-2).

    Implementations MUST use the typed variable-length-edge (VLE) primitive for
    both existence/length and full path detail (never the untyped ``-[r]-``
    explicit form, BP-689), and MUST apply the AGE-session Postgres hygiene GUCs
    (``statement_timeout`` + ``max_parallel_workers_per_gather = 0``) on the same
    connection that runs the traversal query.
    """

    @abstractmethod
    async def path_exists(
        self,
        source: UUID,
        target: UUID,
        *,
        max_hops: int,
    ) -> int | None:
        """Return the shortest hop-count between ``source`` and ``target``.

        Probes exact hop lengths 1..``max_hops`` in ascending order and returns
        the first length that connects them (staged shortest-first, BP-687), or
        ``None`` if no path exists within ``max_hops``.
        """
        raise NotImplementedError

    @abstractmethod
    async def find_paths_between(
        self,
        source: UUID,
        target: UUID,
        *,
        max_hops: int,
        prune_membership: bool,
        limit: int,
    ) -> list[RawPath]:
        """Return up to ``limit`` shortest paths between two bound endpoints.

        Both ends of the VLE pattern are bound to ``source`` / ``target``.  When
        ``prune_membership`` is True the typed VLE allow-list excludes the
        membership relations (FR-3).
        """
        raise NotImplementedError

    @abstractmethod
    async def find_paths_from_anchor(
        self,
        entity_id: UUID,
        *,
        max_hops: int,
        prune_membership: bool,
        limit: int,
    ) -> list[RawPath]:
        """Return up to ``limit`` paths radiating from a single anchor.

        The source end is bound to ``entity_id``; the target end is left free
        (open discovery).  Membership-pruned when ``prune_membership`` is True.
        """
        raise NotImplementedError


__all__ = [
    "GraphPathEngine",
    "RawPath",
]
