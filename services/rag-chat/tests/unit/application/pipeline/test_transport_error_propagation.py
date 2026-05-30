"""BP-623 unit tests: transport-error propagation through executor + SSE emitter.

These pin the centralised disambiguation policy:

  1. ``ToolExecutor.execute`` catches ``UpstreamTransportError`` (a
     ``BaseException``) and returns a ``TransportErrorMarker`` sentinel —
     NOT ``None`` (which would map to ``status="error"`` in the orchestrator)
     and NOT an empty list (which would map to ``status="empty"``).

  2. ``SSEEmitter.emit_tool_result`` accepts the new
     ``status="transport_error"`` plus optional ``reason`` / ``status_code``
     / ``elapsed_ms`` fields, and emits them in the SSE payload alongside
     the legacy ``tool`` / ``status`` / ``item_count`` keys.

  3. The default SSE shape (no transport-error fields) stays byte-identical
     so frontend snapshot tests and the chat-eval harness see no regression
     for the ``ok``/``empty``/``error`` paths.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from rag_chat.application.pipeline.handlers.base import ToolHandler
from rag_chat.application.pipeline.sse_emitter import SSEEmitter
from rag_chat.application.pipeline.tool_executor import ToolExecutor, ToolUseBlock
from rag_chat.application.pipeline.transport_error import TransportErrorMarker
from rag_chat.infrastructure.clients.base import UpstreamTransportError

# ── Test doubles ─────────────────────────────────────────────────────────────


class _RaisingHandler(ToolHandler):
    """Handler stub that raises ``UpstreamTransportError`` from execute().

    We use a real ``BaseException`` subclass (not a mock) so we exercise the
    actual catch logic in ``ToolExecutor.execute`` — a MagicMock-side_effect
    setup would otherwise mask the BaseException-vs-Exception inheritance
    invariant we are explicitly testing.
    """

    def __init__(self, tool_name: str, reason: str, status_code: int | None = None) -> None:
        self._tool_name = tool_name
        self._reason = reason
        self._status_code = status_code

    def can_handle(self, tool_name: str) -> bool:
        return tool_name == self._tool_name

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        raise UpstreamTransportError(
            self._reason,
            path="/v1/upstream",
            elapsed_ms=42,
            status_code=self._status_code,
        )


def _build_executor(handler: ToolHandler, tool_name: str) -> ToolExecutor:
    """Construct a ToolExecutor with a single fake handler.

    We bypass the real registry by stubbing ``_registry.get_spec`` to return
    a truthy sentinel — that keeps execute() from short-circuiting on the
    unknown-tool guard.
    """
    executor = MagicMock(spec=ToolExecutor)
    # Re-attach the real method bindings so behaviour is the production code.
    executor.execute = ToolExecutor.execute.__get__(executor, ToolExecutor)
    executor._registry = MagicMock()
    executor._registry.get_spec = MagicMock(return_value=object())  # truthy
    executor._handlers = [handler]
    return executor


# ── Executor catches UpstreamTransportError and returns TransportErrorMarker ─


@pytest.mark.asyncio
async def test_executor_catches_transport_error_and_returns_marker() -> None:
    """The marker carries reason + path + elapsed_ms so the orchestrator can
    surface them in the SSE tool_result event and in the LLM-visible tool
    message."""
    tool = "get_fundamentals_history_batch"
    executor = _build_executor(_RaisingHandler(tool, "upstream_unreachable"), tool)
    tool_call = ToolUseBlock(name=tool, input={"tickers": ["TSLA"]})

    result = await executor.execute(tool_call)

    assert isinstance(result, TransportErrorMarker)
    assert result.tool_name == "get_fundamentals_history_batch"
    assert result.reason == "upstream_unreachable"
    # elapsed_ms is the executor's wall-clock measurement; the handler stub's
    # 42 is the per-CALL elapsed_ms (carried on the exception), but execute()
    # overwrites with its own outer measurement so the marker reflects the
    # total dispatch time. Both >=0 is the only stable assertion.
    assert result.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_executor_marker_preserves_5xx_status_code() -> None:
    """When the underlying transport-error carried an HTTP status (5xx case),
    the marker must propagate it so the LLM message can include it."""
    executor = _build_executor(_RaisingHandler("traverse_graph", "upstream_5xx", status_code=503), "traverse_graph")
    tool_call = ToolUseBlock(name="traverse_graph", input={"entity_id": "x"})

    result = await executor.execute(tool_call)

    assert isinstance(result, TransportErrorMarker)
    assert result.reason == "upstream_5xx"
    assert result.status_code == 503


# ── SSE emitter renders transport_error fields ───────────────────────────────


def test_emit_tool_result_transport_error_includes_reason_and_status_code() -> None:
    """SSE payload for a transport_error must carry the new fields so the
    frontend (and chat-eval harness) can render outage copy."""
    emitter = SSEEmitter()
    event = emitter.emit_tool_result(
        "get_fundamentals_history_batch",
        status="transport_error",
        item_count=0,
        reason="upstream_5xx",
        status_code=503,
        elapsed_ms=42,
    )
    assert event["event"] == "tool_result"
    payload = json.loads(event["data"])
    assert payload["type"] == "tool_result"
    assert payload["tool"] == "get_fundamentals_history_batch"
    assert payload["status"] == "transport_error"
    assert payload["item_count"] == 0
    assert payload["reason"] == "upstream_5xx"
    assert payload["status_code"] == 503
    assert payload["elapsed_ms"] == 42


def test_emit_tool_result_default_shape_unchanged_for_ok_status() -> None:
    """Backward-compat: the legacy ok/empty/error paths must NOT carry the
    new optional fields. Pinning this prevents accidental payload churn that
    would break frontend snapshot tests."""
    emitter = SSEEmitter()
    event = emitter.emit_tool_result("get_price_history", status="ok", item_count=3)
    payload = json.loads(event["data"])
    assert payload == {
        "type": "tool_result",
        "tool": "get_price_history",
        "status": "ok",
        "item_count": 3,
    }


def test_emit_tool_result_empty_status_unchanged() -> None:
    """Same legacy-compat guard for status=empty (the FIX-LIVE-Y case)."""
    emitter = SSEEmitter()
    event = emitter.emit_tool_result("get_contradictions", status="empty", item_count=0)
    payload = json.loads(event["data"])
    assert "reason" not in payload
    assert "status_code" not in payload
    assert "elapsed_ms" not in payload
    assert payload["status"] == "empty"
