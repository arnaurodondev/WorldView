"""Unit tests for RagChatUsageLogRepository (PLAN-0033 T-E-1-01).

Verifies the fire-and-forget observer contract:
  - log() calls session.execute()
  - log() swallows DB exceptions and never raises
  - context kwargs (session_id, chat_thread_id, tenant_id) are forwarded
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from rag_chat.infrastructure.db.repositories.llm_usage_log import (
    RagChatUsageLogRepository,
)


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.mark.unit
class TestRagChatUsageLogRepository:
    async def test_log_calls_execute(self) -> None:
        """log() must call session.execute() once."""
        session = _make_session()
        repo = RagChatUsageLogRepository(session)

        await repo.log(
            model_id="deepseek-r1-distill-qwen-32b",
            provider="deepinfra",
            capability="chat_completion",
            tokens_in=512,
            tokens_out=256,
            latency_ms=1800,
            estimated_cost_usd=0.00093,
            success=True,
        )

        session.execute.assert_awaited_once()

    async def test_log_accepts_session_context(self) -> None:
        """session_id and chat_thread_id can be passed as **context."""
        session = _make_session()
        repo = RagChatUsageLogRepository(session)
        session_id = uuid.uuid4()
        thread_id = uuid.uuid4()

        await repo.log(
            model_id="deepseek-r1-distill-qwen-32b",
            provider="deepinfra",
            capability="chat_completion",
            tokens_in=300,
            tokens_out=100,
            latency_ms=900,
            session_id=session_id,
            chat_thread_id=thread_id,
        )

        session.execute.assert_awaited_once()

    async def test_log_swallows_db_errors(self) -> None:
        """log() must never raise even if session.execute() throws."""
        session = _make_session()
        session.execute = AsyncMock(side_effect=RuntimeError("connection lost"))
        repo = RagChatUsageLogRepository(session)

        # Should NOT raise
        await repo.log(
            model_id="deepseek-r1-distill-qwen-32b",
            provider="deepinfra",
            capability="chat_completion",
            tokens_in=100,
            tokens_out=50,
            latency_ms=500,
        )

    async def test_log_failure_path(self) -> None:
        """log() with success=False and error_code must call execute."""
        session = _make_session()
        repo = RagChatUsageLogRepository(session)

        await repo.log(
            model_id="unknown",
            provider="unknown",
            capability="chat_completion",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            success=False,
            error_code="model_error",
        )

        session.execute.assert_awaited_once()

    async def test_log_accepts_tenant_id(self) -> None:
        """tenant_id can be passed as context kwarg."""
        session = _make_session()
        repo = RagChatUsageLogRepository(session)

        await repo.log(
            model_id="deepseek-r1-distill-qwen-32b",
            provider="deepinfra",
            capability="chat_completion",
            tokens_in=200,
            tokens_out=80,
            latency_ms=700,
            tenant_id=uuid.uuid4(),
        )

        session.execute.assert_awaited_once()
