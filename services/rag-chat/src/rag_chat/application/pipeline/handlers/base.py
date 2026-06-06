"""Base class for tool handlers.

Also hosts the ``filter_kwargs_to_signature`` utility — the systemic safeguard
against the silent kwarg-drop bug class (BP-622). Without it, every handler
with a fixed named-parameter signature would either:

  * raise ``TypeError`` when the LLM emits an unknown kwarg, which the outer
    ToolExecutor then swallows as ``tool_argument_error`` → the call returns
    ``None`` and the LLM sees an opaque empty result; or
  * silently forward unknown kwargs into a downstream that quietly ignores
    them (the original BP-622: ``revenue_growth_yoy_min`` dropped by
    ``_handle_screen_universe``).

The helper introspects the target handler's signature once, splits the LLM-
supplied args into ``(known, unknown)``, emits a structured ``tool_unknown_kwarg``
log + Prom counter per unknown key, and returns the known subset so the call
proceeds with what the handler can actually accept. The unknown keys are
attached to the structlog event so operators see the drift in real-time
instead of having to grep DeepSeek's tool_input traces.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import structlog

_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


def filter_kwargs_to_signature(
    handler: Callable[..., Any],
    tool_name: str,
    args: dict[str, Any],
    *,
    reserved: tuple[str, ...] = ("self", "tool_call"),
) -> tuple[dict[str, Any], list[str]]:
    """Split ``args`` into the (known, unknown) kwargs against ``handler``'s signature.

    Why a helper instead of ``**kwargs`` on every handler: keeping the named
    parameters preserves type information for mypy/ruff and lets each handler
    document its accepted contract in the signature itself. The helper just
    sanitises the LLM payload before it hits the handler so unknown kwargs
    can't either crash the call (TypeError) or be silently forwarded.

    A handler that legitimately needs to accept open-ended kwargs (e.g.
    ``_handle_create_alert`` which already absorbs LLM noise via ``**_``)
    will have ``VAR_KEYWORD`` in its signature; in that case we short-circuit
    and return ``(args, [])`` — every key is "known".

    ``reserved`` excludes parameters supplied by the dispatcher itself
    (``self`` is implicit on bound methods; ``tool_call`` is a stub the
    legacy intelligence/narrative/news handlers receive from ``execute()``).

    Side effects:
      * Each unknown kwarg increments ``rag_chat_tool_unknown_kwarg_total``.
      * A single ``tool_unknown_kwarg`` structlog event is emitted listing
        ALL unknown keys for the call (one event per call, not per key —
        keeps log volume bounded when an LLM emits a verbose payload).
    """
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):
        # Builtins or C-callables without an inspectable signature — be
        # permissive rather than dropping everything.
        return args, []

    # If the handler accepts **kwargs, every key is implicitly known.
    has_var_keyword = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if has_var_keyword:
        return args, []

    accepted = {name for name in sig.parameters if name not in reserved}
    known: dict[str, Any] = {}
    unknown: list[str] = []
    for k, v in args.items():
        if k in accepted:
            known[k] = v
        else:
            unknown.append(k)

    if unknown:
        # Defer the metrics import so unit tests that don't load prometheus_client
        # (or that monkeypatch the counter) keep working unchanged.
        try:
            from rag_chat.application.metrics.prometheus import rag_chat_tool_unknown_kwarg_total

            for key in unknown:
                rag_chat_tool_unknown_kwarg_total.labels(tool_name=tool_name, kwarg=key).inc()
        except Exception:  # noqa: S110 — metrics never crash the request path
            pass  # pragma: no cover
        _log.warning(
            "tool_unknown_kwarg",
            tool=tool_name,
            unknown_kwargs=sorted(unknown),
            accepted_kwargs=sorted(accepted),
        )

    return known, unknown


class ToolHandler(ABC):
    """Handles execution of a group of related tools.

    WHY ABC: enforces a uniform can_handle / execute contract across all domain
    handler classes. The ToolExecutor dispatcher iterates the handler list and
    delegates to the first handler that claims the tool name.
    """

    @abstractmethod
    def can_handle(self, tool_name: str) -> bool:
        """Return True if this handler handles the named tool."""
        ...

    @abstractmethod
    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Execute the tool and return the result.

        Returns:
            RetrievedItem, list[RetrievedItem], or None depending on the tool.
            Returns [] (empty list) on graceful degradation (missing port, no data).
            Returns None on hard-fail (missing auth, rate limit, invalid input).

        Implementations MUST sanitise ``args`` via ``filter_kwargs_to_signature``
        before dispatching to the per-tool ``_handle_*`` method. This guards
        against the silent kwarg-drop bug class (BP-622) where an LLM-supplied
        parameter the handler does not recognise would otherwise either crash
        the call with ``TypeError`` or be quietly forwarded into a downstream
        that ignores it.
        """
        ...
