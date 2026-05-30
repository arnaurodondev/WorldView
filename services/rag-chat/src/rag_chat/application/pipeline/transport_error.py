"""Transport-error marker used by ``ToolExecutor`` to surface upstream outages.

PLAN-0103 W2 (BP-623): when a tool's underlying HTTP call fails at the
transport layer (DNS, connect refused, timeout, upstream 5xx) the
``BaseUpstreamClient`` raises ``UpstreamTransportError``.  The
``ToolExecutor.execute`` method catches that exception and returns a
``TransportErrorMarker`` instance in place of the usual tool result.

The orchestrator's tool-result interpretation loop checks for this marker BEFORE
applying the legacy ``ok / empty / error`` classification, so a downed upstream
no longer masquerades as "0 items returned" (which the LLM previously rendered
as "No data was found" — see ``docs/audits/2026-05-29-plan-0103-real-user-failures.md``).

Why a dedicated module (not a tuple / dict): keeping the marker as a typed
dataclass lets us add fields (status_code, elapsed_ms, reason) without breaking
any downstream ``isinstance`` checks; the orchestrator's existing
``list / None`` branches keep working untouched because ``TransportErrorMarker``
is neither.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TransportErrorMarker:
    """Sentinel returned by ``ToolExecutor.execute`` on transport-layer failures.

    Frozen + slots: cheap, immutable, hashable — safe to stash in the
    orchestrator's per-iteration cache without copy overhead.
    """

    tool_name: str
    reason: str  # ``upstream_unreachable`` | ``upstream_timeout`` | ``upstream_5xx``
    elapsed_ms: int
    status_code: int | None = None
    path: str | None = None


__all__ = ["TransportErrorMarker"]
