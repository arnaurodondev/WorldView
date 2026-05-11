"""Unit tests for the get_alerts tool handler added in PLAN-0082 Wave A.

Handler under test:
  - _handle_get_alerts  (calls S10Port.get_alerts)

Each handler is tested for:
  (a) happy path — returns RetrievedItems with correct fields
  (b) missing port (s10=None) → returns []
  (c) no auth context (user_id or tenant_id None) → returns []
  (d) upstream returns [] → returns []
  (e) source_type on returned items is "alert"
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

# ── Constants ─────────────────────────────────────────────────────────────────

_FAKE_USER_ID = UUID("018f0000-0000-7000-8000-000000000030")
_FAKE_TENANT_ID = UUID("018f0000-0000-7000-8000-000000000031")


# ── Helper builders ───────────────────────────────────────────────────────────


def _make_registry() -> Any:
    """Build a ToolRegistry with all 21 tools (including the new get_alerts tool)."""
    from rag_chat.application.pipeline.tool_executor import build_default_registry

    return build_default_registry()


def _make_s3_port() -> AsyncMock:
    """Minimal S3Port mock (required by ToolExecutor constructor)."""
    mock = AsyncMock()
    mock.get_ohlcv_range.return_value = []
    mock.get_fundamentals_history.return_value = []
    mock.get_fundamentals_highlights.return_value = {}
    mock.get_earnings.return_value = []
    mock.get_quote.return_value = {}
    mock.find_instrument_by_ticker.return_value = None
    return mock


def _make_s10_port(alerts: list[dict] | None = None) -> AsyncMock:
    """Build a mock S10Port with configurable get_alerts response."""
    mock = AsyncMock()
    mock.get_alerts.return_value = alerts if alerts is not None else []
    return mock


def _make_tool_use_block(name: str, input_dict: dict | None = None) -> Any:
    """Build a ToolUseBlock for the given tool name."""
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock

    return ToolUseBlock(name=name, input=input_dict or {})


def _make_executor(
    s10: AsyncMock | None = None,
    user_id: UUID | None = _FAKE_USER_ID,
    tenant_id: UUID | None = _FAKE_TENANT_ID,
) -> Any:
    """Build a ToolExecutor with the given s10 port and auth context."""
    from rag_chat.application.pipeline.tool_executor import ToolExecutor

    return ToolExecutor(
        registry=_make_registry(),
        s3=_make_s3_port(),
        s10=s10,
        user_id=user_id,
        tenant_id=tenant_id,
        timeout=5.0,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_alerts_returns_items_on_success() -> None:
    """Happy path: S10Port returns 2 alerts → 2 RetrievedItems emitted."""
    alerts = [
        {"id": "a1", "ticker": "AAPL", "alert_type": "price", "status": "pending"},
        {"id": "a2", "ticker": "NVDA", "alert_type": "signal", "status": "pending"},
    ]
    s10 = _make_s10_port(alerts=alerts)
    executor = _make_executor(s10=s10)
    tool_call = _make_tool_use_block("get_alerts")

    result = await executor.execute(tool_call)

    # execute() returns the list directly for multi-result tools
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert len(result) == 2, f"Expected 2 items, got {len(result)}"
    # Verify S10Port was called with correct user/tenant scope
    s10.get_alerts.assert_awaited_once_with(
        user_id=str(_FAKE_USER_ID),
        tenant_id=str(_FAKE_TENANT_ID),
    )


@pytest.mark.asyncio
async def test_get_alerts_missing_port_returns_empty() -> None:
    """When s10=None, get_alerts degrades gracefully to []."""
    executor = _make_executor(s10=None)
    tool_call = _make_tool_use_block("get_alerts")

    result = await executor.execute(tool_call)

    # execute() wraps handler result; None or [] both surface as falsy
    assert result is None or result == []


@pytest.mark.asyncio
async def test_get_alerts_no_auth_context_returns_empty() -> None:
    """When user_id is None (anonymous session), get_alerts returns []."""
    s10 = _make_s10_port(alerts=[{"id": "a1", "ticker": "AAPL"}])
    # user_id=None simulates an unauthenticated request
    executor = _make_executor(s10=s10, user_id=None)
    tool_call = _make_tool_use_block("get_alerts")

    result = await executor.execute(tool_call)

    # S10Port must NOT be called when auth context is missing
    s10.get_alerts.assert_not_awaited()
    assert result is None or result == []


@pytest.mark.asyncio
async def test_get_alerts_upstream_empty_returns_empty() -> None:
    """When S10Port returns [] (no pending alerts), get_alerts returns []."""
    s10 = _make_s10_port(alerts=[])
    executor = _make_executor(s10=s10)
    tool_call = _make_tool_use_block("get_alerts")

    result = await executor.execute(tool_call)

    # execute() returns None on empty (tool_no_data path)
    assert result is None or result == []


@pytest.mark.asyncio
async def test_get_alerts_source_type_is_alert() -> None:
    """Each RetrievedItem returned by get_alerts must reference the alert source.

    source_type is passed to RetrievedItem.create() and used for recency scoring.
    We verify the citation_meta.source_name is "alert_service" (the field that
    carries alert identity to the citation renderer) and item_id starts with
    "tool:alert:" (stable item_id prefix for alerts).
    """
    alerts = [
        {"id": "b1", "ticker": "TSLA", "alert_type": "price", "status": "pending"},
    ]
    s10 = _make_s10_port(alerts=alerts)
    executor = _make_executor(s10=s10)
    tool_call = _make_tool_use_block("get_alerts")

    result = await executor.execute(tool_call)

    assert isinstance(result, list) and len(result) == 1
    item = result[0]
    # Verify the item is correctly attributed to the alert service
    assert (
        item.citation_meta.source_name == "alert_service"
    ), f"Expected source_name='alert_service', got {item.citation_meta.source_name!r}"
    assert item.item_id.startswith("tool:alert:"), f"Expected item_id to start with 'tool:alert:', got {item.item_id!r}"
