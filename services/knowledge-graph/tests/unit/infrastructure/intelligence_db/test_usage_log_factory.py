"""Unit tests for SessionScopedKgUsageLogger (PLAN-0057 T-A-5-03).

Mirror of the NLP-side test suite.  Verifies the fire-and-forget contract
closing audit finding F-CRIT-03 (KG side):
  - log() opens a short-lived session, calls LlmUsageLogRepository.log,
    commits, and closes.
  - Internal exceptions are swallowed and emitted as a structlog WARN —
    never re-raised.
  - The wrapper structurally satisfies LlmUsageLogProtocol so adapters can
    accept it without explicit subclassing.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from knowledge_graph.infrastructure.intelligence_db.usage_log_factory import (
    SessionScopedKgUsageLogger,
)
from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


def _make_factory() -> tuple[MagicMock, AsyncMock]:
    """Return (factory, session) where calling factory() yields the session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=cm)
    return factory, session


@pytest.mark.asyncio()
async def test_log_opens_session_and_calls_repository() -> None:
    """log() must open a session, delegate to LlmUsageLogRepository.log, and commit."""
    factory, session = _make_factory()
    logger_obj = SessionScopedKgUsageLogger(factory)

    fake_repo = MagicMock()
    fake_repo.log = AsyncMock()
    repo_cls = MagicMock(return_value=fake_repo)

    entity_id = uuid.uuid4()

    with patch(
        "knowledge_graph.infrastructure.intelligence_db.repositories.llm_usage_log.LlmUsageLogRepository",
        repo_cls,
    ):
        await logger_obj.log(
            model_id="ollama/nomic-embed-text",
            provider="ollama",
            capability="embedding",
            tokens_in=64,
            tokens_out=0,
            latency_ms=120,
            estimated_cost_usd=0.0,
            success=True,
            error_code=None,
            entity_id=entity_id,
        )

    assert factory.call_count == 1
    repo_cls.assert_called_once_with(session)
    fake_repo.log.assert_awaited_once()
    kwargs = fake_repo.log.await_args.kwargs
    assert kwargs["model_id"] == "ollama/nomic-embed-text"
    assert kwargs["provider"] == "ollama"
    assert kwargs["capability"] == "embedding"
    assert kwargs["tokens_in"] == 64
    assert kwargs["latency_ms"] == 120
    assert kwargs["success"] is True
    assert kwargs["entity_id"] == entity_id
    session.commit.assert_awaited_once()


@pytest.mark.asyncio()
async def test_log_swallows_internal_exceptions() -> None:
    """log() must NEVER raise even when the underlying repo raises."""
    factory, _session = _make_factory()
    logger_obj = SessionScopedKgUsageLogger(factory)

    fake_repo = MagicMock()
    fake_repo.log = AsyncMock(side_effect=RuntimeError("DB down"))
    repo_cls = MagicMock(return_value=fake_repo)

    with (
        patch(
            "knowledge_graph.infrastructure.intelligence_db.repositories.llm_usage_log.LlmUsageLogRepository",
            repo_cls,
        ),
        patch("knowledge_graph.infrastructure.intelligence_db.usage_log_factory.logger") as mock_log,
    ):
        await logger_obj.log(
            model_id="x",
            provider="ollama",
            capability="extraction",
            tokens_in=1,
            tokens_out=1,
            latency_ms=10,
        )

    mock_log.warning.assert_called_once()
    args, kwargs = mock_log.warning.call_args
    assert args[0] == "kg_usage_log_session_scoped_failed"
    assert kwargs.get("exc_info") is True


def test_satisfies_llm_usage_log_protocol() -> None:
    """SessionScopedKgUsageLogger must structurally satisfy LlmUsageLogProtocol."""
    factory, _ = _make_factory()
    logger_obj = SessionScopedKgUsageLogger(factory)
    assert isinstance(logger_obj, LlmUsageLogProtocol)
