"""Relational (plain-Postgres) infrastructure adapters for the knowledge graph.

Currently holds the ``RelationalGraphPathAdapter`` (PLAN-0113): a recursive-CTE
traversal engine over the ``graph_edges`` materialized view that implements the
``GraphPathEngine`` port without Apache AGE, for the connection-discovery hot
path.
"""

from __future__ import annotations
