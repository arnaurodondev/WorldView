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


class UpstreamTransportError(BaseException):
    """Raised by upstream HTTP clients when a call fails at the transport layer.

    Lives in the application layer (rather than ``infrastructure/clients/base``)
    so the orchestrator and ``ToolExecutor`` can ``except`` it without crossing
    the LAYER-APP-ISOLATION boundary (R12 / IG-LAYER-002). The infrastructure
    layer re-exports the symbol from ``infrastructure/clients/base.py`` so
    existing call sites that ``raise UpstreamTransportError(...)`` keep
    working unchanged.

    BaseException (not Exception) — per-handler ``except Exception: return []``
    guards must NOT swallow this; the orchestrator's ``except
    UpstreamTransportError`` branch must see it untouched so it can render
    ``status="transport_error"`` instead of a silently empty tool result
    (BP-623, PLAN-0103 W2).

    Attributes:
        reason: machine-readable classification — one of
            ``upstream_unreachable`` (DNS / connect refused / RemoteProtocolError)
            ``upstream_timeout``     (read / write / connect timeout)
            ``upstream_5xx``         (HTTP 5xx response)
        status_code: HTTP status when applicable (5xx only); None for connect/timeout.
        elapsed_ms: wall-clock time spent on the failed call.
        path: request path for logging / debug surfacing.
    """

    __slots__ = ("reason", "status_code", "elapsed_ms", "path")

    def __init__(
        self,
        reason: str,
        *,
        path: str,
        elapsed_ms: int,
        status_code: int | None = None,
    ) -> None:
        super().__init__(f"upstream transport error: {reason} ({path})")
        self.reason = reason
        self.path = path
        self.elapsed_ms = elapsed_ms
        self.status_code = status_code


__all__ = ["TransportErrorMarker", "UpstreamTransportError"]
