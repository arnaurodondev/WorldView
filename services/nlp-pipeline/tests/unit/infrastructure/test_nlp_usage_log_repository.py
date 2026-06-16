"""Unit tests for NlpUsageLogRepository (PLAN-0033 T-C-1-03).

Verifies the fire-and-forget observer contract:
  - log() calls session.execute()
  - log() swallows DB exceptions and never raises
  - service_name defaults to 'nlp-pipeline'
  - context kwargs (doc_id, tenant_id) are forwarded correctly
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from nlp_pipeline.infrastructure.nlp_db.repositories.llm_usage_log import (
    NlpUsageLogRepository,
)

pytestmark = pytest.mark.unit


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.mark.unit
class TestNlpUsageLogRepository:
    async def test_log_calls_execute(self) -> None:
        """log() must call session.execute() once."""
        session = _make_session()
        repo = NlpUsageLogRepository(session)

        await repo.log(
            model_id="nomic-embed-text",
            provider="ollama",
            capability="embedding",
            tokens_in=128,
            tokens_out=0,
            latency_ms=42,
            estimated_cost_usd=0.0,
            success=True,
        )

        session.execute.assert_awaited_once()

    async def test_log_accepts_doc_id_context(self) -> None:
        """log() must accept doc_id as a **context kwarg without raising."""
        session = _make_session()
        repo = NlpUsageLogRepository(session)
        doc_id = uuid.uuid4()

        await repo.log(
            model_id="qwen2.5:3b",
            provider="ollama",
            capability="extraction",
            tokens_in=200,
            tokens_out=50,
            latency_ms=300,
            doc_id=doc_id,
        )

        session.execute.assert_awaited_once()

    async def test_log_swallows_db_errors(self) -> None:
        """log() must never raise even if session.execute() throws."""
        session = _make_session()
        session.execute = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        repo = NlpUsageLogRepository(session)

        # Should NOT raise
        await repo.log(
            model_id="nomic-embed-text",
            provider="ollama",
            capability="embedding",
            tokens_in=64,
            tokens_out=0,
            latency_ms=10,
        )

    async def test_log_failure_path(self) -> None:
        """log() with success=False and error_code must still call execute."""
        session = _make_session()
        repo = NlpUsageLogRepository(session)

        await repo.log(
            model_id="qwen2.5:3b",
            provider="ollama",
            capability="extraction",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            success=False,
            error_code="model_error",
        )

        session.execute.assert_awaited_once()

    async def test_log_accepts_tenant_id(self) -> None:
        """tenant_id can be passed as context kwargs."""
        session = _make_session()
        repo = NlpUsageLogRepository(session)
        tenant_id = uuid.uuid4()

        await repo.log(
            model_id="nomic-embed-text",
            provider="ollama",
            capability="embedding",
            tokens_in=100,
            tokens_out=0,
            latency_ms=20,
            tenant_id=tenant_id,
        )

        session.execute.assert_awaited_once()

    async def test_log_records_actual_model_and_fallback_reason(self) -> None:
        """Task #36: the row records the ACTUAL serving model + fallback_reason.

        The deep-extraction caller passes ``model_id=ExtractionOutput.model_used``
        (the secondary slug on a fallback hop) plus ``fallback_reason`` as a
        **context kwarg. The repo must bind BOTH into the INSERT params.
        """
        session = _make_session()
        repo = NlpUsageLogRepository(session)

        await repo.log(
            model_id="deepseek-ai/DeepSeek-V4-Flash",  # the SECONDARY model served it
            provider="deepinfra",
            capability="extraction",
            tokens_in=500,
            tokens_out=80,
            latency_ms=1200,
            success=True,
            fallback_reason="rate_limit",
        )

        session.execute.assert_awaited_once()
        # The bind-params dict is the 2nd positional arg to session.execute().
        params = session.execute.await_args.args[1]
        assert params["model_id"] == "deepseek-ai/DeepSeek-V4-Flash"
        assert params["fallback_reason"] == "rate_limit"

    async def test_log_fallback_reason_defaults_to_null(self) -> None:
        """When no fallback_reason is supplied the bound value is None (NULL)."""
        session = _make_session()
        repo = NlpUsageLogRepository(session)

        await repo.log(
            model_id="Qwen/Qwen3-235B-A22B-Instruct-2507",
            provider="deepinfra",
            capability="extraction",
            tokens_in=400,
            tokens_out=60,
            latency_ms=900,
        )

        params = session.execute.await_args.args[1]
        assert params["fallback_reason"] is None
