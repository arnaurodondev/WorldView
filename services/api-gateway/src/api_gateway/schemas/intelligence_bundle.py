"""Entity intelligence bundle response schema (PLAN-0099 H).

WHY this endpoint exists (Agent D audit I1 + I2):
  - The Intelligence tab on the instrument page fires 4 independent S9 calls
    on mount (entity detail, brief, depth=2 graph, paths) plus a redundant
    depth=1 graph from ContextPanel. Each call has its own TLS handshake +
    auth round-trip; the tab is wave-serialized by the slowest leg.
  - This bundle collapses all four into one ``asyncio.gather`` so the tab
    renders after a single round-trip, then the hydrator pre-warms each
    per-widget TanStack cache via ``setQueryData``.

Each leg is independently nullable — failed legs degrade to None and the
page still renders. ``extra="allow"`` lets upstream services add fields
without forcing a schema update here.

Mirrors the F-2 dashboard_bundle.py pattern.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class EntityIntelligenceBundleResponse(BaseModel):
    """Intelligence-tab bundle — collapses N initial entity queries into 1 round-trip.

    Fields (all nullable — failed legs degrade to None):
      detail               : Entity detail (canonical_name/description/metadata) from S7
      brief                : Per-instrument AI brief (S8 rag-chat)
      graph_d2             : Depth=2 knowledge-graph neighbourhood from S7 (via S9
                             /v1/entities/{id}/graph?depth=2) — already orphan-filtered.
                             Hydrated under the depth=2 cache key so GraphColumn skips
                             its own initial fetch.
      paths                : Top-N multi-hop opportunity paths (S7 via S9 /paths).
      intelligence_summary : Entity intelligence aggregate (S7 — health score, narrative,
                             confidence breakdown).
    """

    model_config = ConfigDict(extra="allow")

    detail: dict[str, Any] | None = None
    brief: dict[str, Any] | None = None
    graph_d2: dict[str, Any] | None = None
    paths: dict[str, Any] | None = None
    intelligence_summary: dict[str, Any] | None = None
