"""Unit tests for DeepInfra adapter provider-cost capture (PLAN-0117 W4, FR-1).

The adapter's ``_record_cost`` must surface DeepInfra's ``usage.estimated_cost``
to the CostRecorder as ``provider_estimated_cost`` and thread the authenticated
``user_id``. We drive ``_record_cost`` directly with a fake recorder so the test
is transport-free.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from rag_chat.infrastructure.llm.deepinfra_adapter import DeepInfraCompletionAdapter

pytestmark = pytest.mark.unit

_USER_ID = UUID("00000000-0000-0000-0000-0000000000cc")
_THREAD_ID = UUID("00000000-0000-0000-0000-0000000000dd")


def _adapter_with_recorder() -> tuple[DeepInfraCompletionAdapter, AsyncMock]:
    recorder = AsyncMock()
    adapter = DeepInfraCompletionAdapter(
        api_key="test-key",
        http_client=AsyncMock(),
        cost_recorder=recorder,
    )
    return adapter, recorder


async def test_record_cost_forwards_provider_estimated_cost() -> None:
    """usage.estimated_cost + tokens + user_id reach recorder.record()."""
    adapter, recorder = _adapter_with_recorder()
    await adapter._record_cost(
        thread_id=_THREAD_ID,
        model_id="Qwen/Qwen3-235B-A22B-Instruct-2507",
        usage={"prompt_tokens": 16, "completion_tokens": 3, "estimated_cost": 4.1e-07},
        call_site="tool_loop_iter",
        user_id=_USER_ID,
    )
    recorder.record.assert_awaited_once()
    kwargs = recorder.record.await_args.kwargs
    assert kwargs["provider_estimated_cost"] == 4.1e-07
    assert kwargs["tokens_in"] == 16
    assert kwargs["tokens_out"] == 3
    assert kwargs["user_id"] == _USER_ID
    assert kwargs["call_site"] == "tool_loop_iter"


async def test_record_cost_missing_estimated_cost_forwards_none() -> None:
    """Absent estimated_cost → provider_estimated_cost=None (recorder falls back)."""
    adapter, recorder = _adapter_with_recorder()
    await adapter._record_cost(
        thread_id=None,
        model_id="Qwen/Qwen3-235B-A22B-Instruct-2507",
        usage={"prompt_tokens": 5, "completion_tokens": 2},
        call_site="synthesis",
    )
    kwargs = recorder.record.await_args.kwargs
    assert kwargs["provider_estimated_cost"] is None
    assert kwargs["user_id"] is None


async def test_record_cost_no_recorder_is_noop() -> None:
    """No recorder wired → no crash (defence-in-depth)."""
    adapter = DeepInfraCompletionAdapter(api_key="k", http_client=AsyncMock(), cost_recorder=None)
    # Must simply return without error.
    await adapter._record_cost(
        thread_id=None,
        model_id="m",
        usage={"prompt_tokens": 1, "completion_tokens": 1, "estimated_cost": 1e-6},
        call_site="tool_loop_iter",
    )
