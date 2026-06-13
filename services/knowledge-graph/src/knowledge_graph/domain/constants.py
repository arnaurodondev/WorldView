"""Domain constants for the knowledge graph (PLAN-0112 W2, T-2-03).

This module owns the *membership* relation-label set used by the
connection-discovery engine (``GraphPathEngine``) and the weirdness scorer.

Why these are plain string constants — NOT ``RelationType`` enum values:

- AGE stores edge labels **uppercased, with spaces→underscores**, derived from
  ``relations.canonical_type`` by ``age_sync_worker._derive_edge_label`` (e.g.
  ``"listed_on"`` → ``"LISTED_ON"``).  The traversal Cypher therefore matches on
  these **uppercase** label strings.
- The ``RelationType`` StrEnum (``domain/enums.py``) is **lowercase** and only
  covers 16 of the relation types.  Two of the four membership relations
  (``IS_IN_SECTOR``, ``HEADQUARTERED_IN``) are **not** members of that enum at
  all — they live only in the AGE label space / ``relation_type_registry``.
  So this set MUST be defined as literal AGE-label strings, not derived from
  ``RelationType``.

Membership relations are low-information for "weird connection" discovery: every
company in a sector is ``IS_IN_SECTOR``-connected to thousands of peers, so a
2-hop ``A —IS_IN_SECTOR→ Sector ←IS_IN_SECTOR— B`` path is trivially true and
adds no insight.  Pruning them from the traversal both kills the combinatorial
hub blow-up (BP-689) and removes noise from the weirdness ranking (FR-3).

> **Layer note (R12)**: the domain layer must not import from infrastructure, so
> the ``TRAVERSABLE_RELATIONS`` set (= the AGE whitelist minus these membership
> labels) and the import-time validation that all four membership labels exist
> in that whitelist live in the *infrastructure* AGE engine module
> (``infrastructure/age/graph_path_engine.py``), where importing the AGE-sync
> worker's whitelist is legal.
"""

from __future__ import annotations

# ── Membership relations (pruned from weird-path discovery, FR-3) ──────────────
#
# Uppercase AGE edge-label strings (see module docstring for why these are not
# RelationType enum values).  Each is a "X is a member of category Y" edge whose
# fan-out is huge and whose presence carries no surprise.
MEMBERSHIP_RELATIONS: frozenset[str] = frozenset(
    {
        "IS_IN_SECTOR",  # company → GICS sector (huge fan-out)
        "LISTED_ON",  # security → exchange (every US equity → NASDAQ/NYSE)
        "OPERATES_IN_COUNTRY",  # company → country (geographic membership)
        "HEADQUARTERED_IN",  # company → country/region (geographic membership)
    },
)

__all__ = [
    "MEMBERSHIP_RELATIONS",
]
