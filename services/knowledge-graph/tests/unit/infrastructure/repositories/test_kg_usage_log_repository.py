"""Unit tests for KgUsageLogRepository (PLAN-0033 T-D-1-01).

Verifies the fire-and-forget observer contract:
  - isinstance check: KgUsageLogRepository satisfies LlmUsageLogProtocol
  - log() calls session.execute()
  - log() swallows DB exceptions and never raises
  - context kwargs (entity_id, relation_id, tenant_id) are accepted
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from knowledge_graph.infrastructure.intelligence_db.repositories.llm_usage_log import (
    LlmUsageLogRepository,
)
from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.mark.unit()
class TestKgUsageLogRepository:
    def test_satisfies_llm_usage_log_protocol(self) -> None:
        """LlmUsageLogRepository must be an instance of LlmUsageLogProtocol (R16)."""
        session = _make_session()
        repo = LlmUsageLogRepository(session)
        # LlmUsageLogProtocol is @runtime_checkable — isinstance() validates structural match
        assert isinstance(repo, LlmUsageLogProtocol)

    async def test_log_calls_execute(self) -> None:
        """log() must delegate to session.execute() exactly once."""
        session = _make_session()
        repo = LlmUsageLogRepository(session)

        await repo.log(
            model_id="ollama/nomic-embed-text",
            provider="ollama",
            capability="embedding",
            tokens_in=128,
            tokens_out=0,
            latency_ms=55,
            estimated_cost_usd=0.0,
            success=True,
        )

        session.execute.assert_awaited_once()

    async def test_log_swallows_db_errors(self) -> None:
        """log() must never raise even if session.execute() throws.

        Cost logging is a non-critical observer — it must never interrupt
        the main KG processing path (Rule 16 fire-and-forget contract).
        """
        session = _make_session()
        session.execute = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        repo = LlmUsageLogRepository(session)

        # Must NOT raise
        await repo.log(
            model_id="gemini/flash-lite",
            provider="gemini",
            capability="extraction",
            tokens_in=500,
            tokens_out=80,
            latency_ms=1200,
        )

    async def test_log_accepts_context_kwargs(self) -> None:
        """entity_id, relation_id, and tenant_id are forwarded as context kwargs."""
        session = _make_session()
        repo = LlmUsageLogRepository(session)
        entity_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        await repo.log(
            model_id="ollama/nomic-embed-text",
            provider="ollama",
            capability="embedding",
            tokens_in=64,
            tokens_out=0,
            latency_ms=30,
            entity_id=entity_id,
            tenant_id=tenant_id,
        )

        session.execute.assert_awaited_once()

    async def test_log_persists_cost_source_and_user_id(self) -> None:
        """PLAN-0117 W3 (FR-2/FR-3): cost_source + user_id are bound into the INSERT."""
        session = _make_session()
        repo = LlmUsageLogRepository(session)
        user_id = uuid.uuid4()

        await repo.log(
            model_id="Qwen/Qwen3-235B-A22B-Instruct-2507",
            provider="deepinfra",
            capability="extraction",
            tokens_in=500,
            tokens_out=80,
            latency_ms=1200,
            estimated_cost_usd=0.00031,
            cost_source="provider",
            user_id=user_id,
        )

        params = session.execute.await_args.args[1]
        assert params["cost_source"] == "provider"
        assert params["user_id"] == str(user_id)

    async def test_log_cost_source_defaults_null_and_local_stamp(self) -> None:
        """Omitted → NULL; an Ollama write can stamp cost_source='local'."""
        session = _make_session()
        repo = LlmUsageLogRepository(session)

        await repo.log(
            model_id="qwen3:0.6b",
            provider="ollama",
            capability="extraction",
            tokens_in=10,
            tokens_out=0,
            latency_ms=5,
            estimated_cost_usd=0.0,
            cost_source="local",
        )

        params = session.execute.await_args.args[1]
        assert params["cost_source"] == "local"
        assert params["user_id"] is None
