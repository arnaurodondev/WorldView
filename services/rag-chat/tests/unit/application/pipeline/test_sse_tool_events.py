"""Unit tests for SSEEmitter tool progress events (PLAN-0066 Wave H T-W10-H-04).

Tests:
- test_sse_tool_call_event_emitted_before_execute
- test_sse_tool_result_ok_emitted_on_success
- test_sse_tool_result_error_emitted_on_none
"""

from __future__ import annotations

import json

import pytest
from rag_chat.application.pipeline.sse_emitter import SSEEmitter

pytestmark = pytest.mark.unit


class TestSSEToolCallEvent:
    def test_sse_tool_call_event_emitted_before_execute(self) -> None:
        """emit_tool_call() must return an event with type='tool_call' and status='running'."""
        emitter = SSEEmitter()

        event = emitter.emit_tool_call(
            tool_name="get_price_history",
            tool_input={"ticker": "AAPL", "from_date": "2026-02-01", "to_date": "2026-05-01"},
        )

        assert event["event"] == "tool_call"
        data = json.loads(event["data"])
        assert data["type"] == "tool_call"
        assert data["tool"] == "get_price_history"
        assert data["status"] == "running"
        assert data["input"]["ticker"] == "AAPL"

    def test_sse_tool_call_event_structure(self) -> None:
        """emit_tool_call() must contain all required fields for the streaming UI."""
        emitter = SSEEmitter()

        event = emitter.emit_tool_call("get_fundamentals_history", {"ticker": "MSFT", "periods": 8})

        data = json.loads(event["data"])
        assert "type" in data
        assert "tool" in data
        assert "input" in data
        assert "status" in data
        assert data["tool"] == "get_fundamentals_history"


class TestSSEToolResultEvent:
    def test_sse_tool_result_ok_emitted_on_success(self) -> None:
        """emit_tool_result(success=True) must emit status='ok'."""
        emitter = SSEEmitter()

        event = emitter.emit_tool_result(tool_name="get_price_history", success=True)

        assert event["event"] == "tool_result"
        data = json.loads(event["data"])
        assert data["type"] == "tool_result"
        assert data["tool"] == "get_price_history"
        assert data["status"] == "ok"

    def test_sse_tool_result_error_emitted_on_none(self) -> None:
        """emit_tool_result(success=False) must emit status='error'.

        WHY: when ToolExecutor returns None (tool failed or empty data),
        the SSE result must signal the failure so the frontend spinner closes.
        """
        emitter = SSEEmitter()

        event = emitter.emit_tool_result(tool_name="get_fundamentals_history", success=False)

        assert event["event"] == "tool_result"
        data = json.loads(event["data"])
        assert data["status"] == "error"
        assert data["tool"] == "get_fundamentals_history"

    def test_sse_tool_result_always_has_tool_field(self) -> None:
        """emit_tool_result() must always include the tool name for frontend routing."""
        emitter = SSEEmitter()

        for tool_name in ["get_price_history", "get_fundamentals_history"]:
            event = emitter.emit_tool_result(tool_name=tool_name, success=True)
            data = json.loads(event["data"])
            assert data["tool"] == tool_name
