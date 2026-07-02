"""Unit tests for PrometheusAndDbCostRecorder provenance (PLAN-0117 W4, T-A-4-01).

Verifies the leaf cost path now:
  - resolves the §2.2 priority via ml_clients.resolve_cost (provider → matrix),
  - stamps ``cost_source`` on the persisted row,
  - threads the authenticated ``user_id`` through to the INSERT.

The DB session is faked; the repository is patched so we assert exactly which
kwargs reach the usage-log write without needing a live Postgres.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_USER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
_THREAD_ID = UUID("00000000-0000-0000-0000-0000000000bb")


def _fake_session_factory() -> MagicMock:
    """Return a factory yielding an AsyncMock session (execute/commit/close)."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()
    return MagicMock(return_value=session)


async def _run_record(**record_kwargs) -> AsyncMock:
    """Instantiate the recorder, patch the repo, run record(), return repo.log mock."""
    from rag_chat.infrastructure.llm.cost_recorder import PrometheusAndDbCostRecorder

    recorder = PrometheusAndDbCostRecorder(write_session_factory=_fake_session_factory())
    repo_instance = MagicMock()
    repo_instance.log = AsyncMock()
    with patch(
        "rag_chat.infrastructure.db.repositories.llm_usage_log.RagChatUsageLogRepository",
        return_value=repo_instance,
    ):
        await recorder.record(**record_kwargs)
    return repo_instance.log


async def test_provider_cost_stamps_provider_source() -> None:
    """usage.estimated_cost present → cost_source='provider', verbatim cost."""
    log_mock = await _run_record(
        thread_id=_THREAD_ID,
        model_id="Qwen/Qwen3-235B-A22B-Instruct-2507",
        tokens_in=16,
        tokens_out=3,
        call_site="tool_loop_iter",
        provider_estimated_cost=4.1e-07,
        user_id=_USER_ID,
    )
    log_mock.assert_awaited_once()
    kwargs = log_mock.await_args.kwargs
    assert kwargs["cost_source"] == "provider"
    # Provider float → Decimal verbatim, no float drift.
    assert Decimal(str(kwargs["estimated_cost_usd"])) == Decimal("0.00000041")
    assert kwargs["user_id"] == _USER_ID


async def test_missing_provider_cost_falls_back_to_matrix() -> None:
    """No provider cost → cost_source='pricematrix' via the canonical matrix."""
    log_mock = await _run_record(
        thread_id=None,
        model_id="Qwen/Qwen3-235B-A22B-Instruct-2507",
        tokens_in=1000,
        tokens_out=1000,
        call_site="synthesis",
        provider_estimated_cost=None,
    )
    kwargs = log_mock.await_args.kwargs
    assert kwargs["cost_source"] == "pricematrix"
    # A priced model with 2000 tokens must never be a silent $0.
    assert kwargs["estimated_cost_usd"] > 0
    # No authenticated user on this path → NULL user_id.
    assert kwargs["user_id"] is None


async def test_user_id_threaded_to_row() -> None:
    """The authenticated user_id reaches the usage-log write (FR-3)."""
    log_mock = await _run_record(
        thread_id=_THREAD_ID,
        model_id="Qwen/Qwen3-235B-A22B-Instruct-2507",
        tokens_in=10,
        tokens_out=10,
        call_site="tool_loop_iter",
        provider_estimated_cost=1.0e-06,
        user_id=_USER_ID,
    )
    assert log_mock.await_args.kwargs["user_id"] == _USER_ID
