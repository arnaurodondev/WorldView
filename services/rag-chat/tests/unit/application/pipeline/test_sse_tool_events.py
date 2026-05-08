"""Unit tests for SSEEmitter tool progress events (PLAN-0066 Wave H T-W10-H-04).

Updated in PLAN-0067 W11-3:
- emit_tool_call signature changed: tool_input → input_summary, added label field
- emit_tool_result signature changed: success: bool → status: str, added item_count

Tests:
- test_sse_tool_call_event_emitted_before_execute
- test_sse_tool_call_has_label_field (W11-3 new)
- test_sse_tool_result_ok_emitted_on_success
- test_sse_tool_result_error_status (W11-3: status string not bool)
- test_sse_tool_result_empty_status (W11-3 new)
- test_sse_tool_result_has_item_count (W11-3 new)
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
            input_summary={"ticker": "AAPL", "from_date": "2026-02-01", "to_date": "2026-05-01"},
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

    def test_sse_tool_call_has_label_field(self) -> None:
        """emit_tool_call() must include a user-friendly 'label' field (PLAN-0067 W11-3).

        WHY: raw tool names ("get_price_history") are not suitable for display in the UI.
        The label ("Fetching price history...") is shown in the chat spinner.
        """
        emitter = SSEEmitter()

        event = emitter.emit_tool_call("get_price_history", {"ticker": "AAPL"})
        data = json.loads(event["data"])

        assert "label" in data
        # Must be a non-empty string
        assert isinstance(data["label"], str) and len(data["label"]) > 0

    def test_sse_tool_call_unknown_tool_has_fallback_label(self) -> None:
        """Unknown tool names must have a fallback label (not raise KeyError)."""
        emitter = SSEEmitter()

        event = emitter.emit_tool_call("unknown_tool_xyz", {})
        data = json.loads(event["data"])

        # Fallback label should contain the tool name
        assert "label" in data
        assert "unknown_tool_xyz" in data["label"]


class TestSSEToolResultEvent:
    def test_sse_tool_result_ok_emitted_on_success(self) -> None:
        """emit_tool_result(status='ok') must emit status='ok'."""
        emitter = SSEEmitter()

        event = emitter.emit_tool_result(tool_name="get_price_history", status="ok", item_count=5)

        assert event["event"] == "tool_result"
        data = json.loads(event["data"])
        assert data["type"] == "tool_result"
        assert data["tool"] == "get_price_history"
        assert data["status"] == "ok"

    def test_sse_tool_result_error_status(self) -> None:
        """emit_tool_result(status='error') must emit status='error'.

        WHY: when ToolExecutor raises an exception, the SSE result signals the
        failure so the frontend spinner closes.
        """
        emitter = SSEEmitter()

        event = emitter.emit_tool_result(tool_name="get_fundamentals_history", status="error")

        assert event["event"] == "tool_result"
        data = json.loads(event["data"])
        assert data["status"] == "error"
        assert data["tool"] == "get_fundamentals_history"

    def test_sse_tool_result_empty_status(self) -> None:
        """emit_tool_result(status='empty') must emit status='empty'.

        WHY: 'empty' differentiates 'ran successfully but found nothing' from 'error'
        so the frontend can show "No data found" vs "Tool failed".
        """
        emitter = SSEEmitter()

        event = emitter.emit_tool_result(tool_name="search_claims", status="empty", item_count=0)

        data = json.loads(event["data"])
        assert data["status"] == "empty"
        assert data["item_count"] == 0

    def test_sse_tool_result_has_item_count(self) -> None:
        """emit_tool_result() must include item_count in the payload (PLAN-0067 W11-3).

        WHY: item_count lets the frontend show 'Found N results' inline without
        waiting for the full token stream.
        """
        emitter = SSEEmitter()

        event = emitter.emit_tool_result(tool_name="get_price_history", status="ok", item_count=42)
        data = json.loads(event["data"])

        assert "item_count" in data
        assert data["item_count"] == 42

    def test_sse_tool_result_item_count_defaults_to_zero(self) -> None:
        """item_count defaults to 0 if not supplied."""
        emitter = SSEEmitter()

        event = emitter.emit_tool_result(tool_name="get_price_history", status="error")
        data = json.loads(event["data"])

        assert data["item_count"] == 0

    def test_sse_tool_result_always_has_tool_field(self) -> None:
        """emit_tool_result() must always include the tool name for frontend routing."""
        emitter = SSEEmitter()

        for tool_name in ["get_price_history", "get_fundamentals_history"]:
            event = emitter.emit_tool_result(tool_name=tool_name, status="ok")
            data = json.loads(event["data"])
            assert data["tool"] == tool_name
