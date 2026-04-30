"""Unit tests for SessionScopedNlpUsageLogger (PLAN-0057 T-A-5-01).

Verifies the fire-and-forget contract closing audit finding F-CRIT-03:
  - log() opens a short-lived session, calls NlpUsageLogRepository.log,
    commits, and closes.
  - Internal exceptions (DB unreachable, schema drift, etc.) are swallowed
    and emitted as a structlog WARN — never re-raised.
  - The wrapper structurally satisfies LlmUsageLogProtocol so adapters can
    accept it without explicit subclassing.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.usage_log_factory import (
    SessionScopedNlpUsageLogger,
)

pytestmark = pytest.mark.unit


# Helper: build an async-context-manager session_factory that yields a mock session.
def _make_factory() -> tuple[MagicMock, AsyncMock]:
    """Return (factory, session) where calling factory() yields the session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=cm)
    return factory, session


@pytest.mark.asyncio
async def test_log_opens_session_and_calls_repository() -> None:
    """log() must open a session, delegate to NlpUsageLogRepository.log, and commit.

    We patch the repository class so we can assert log() was called with the
    forwarded kwargs without exercising raw SQL.
    """
    factory, session = _make_factory()
    logger_obj = SessionScopedNlpUsageLogger(factory)

    fake_repo = MagicMock()
    fake_repo.log = AsyncMock()
    repo_cls = MagicMock(return_value=fake_repo)

    doc_id = uuid.uuid4()

    with patch(
        "nlp_pipeline.infrastructure.nlp_db.repositories.llm_usage_log.NlpUsageLogRepository",
        repo_cls,
    ):
        await logger_obj.log(
            model_id="qwen3:0.6b",
            provider="ollama",
            capability="classification",
            tokens_in=42,
            tokens_out=12,
            latency_ms=350,
            estimated_cost_usd=0.0,
            success=True,
            error_code=None,
            doc_id=doc_id,
        )

    # Factory called once → one session opened.
    assert factory.call_count == 1
    # Repo instantiated with the session.
    repo_cls.assert_called_once_with(session)
    # Repo.log invoked with our kwargs (context kwargs included).
    fake_repo.log.assert_awaited_once()
    kwargs = fake_repo.log.await_args.kwargs
    assert kwargs["model_id"] == "qwen3:0.6b"
    assert kwargs["provider"] == "ollama"
    assert kwargs["capability"] == "classification"
    assert kwargs["tokens_in"] == 42
    assert kwargs["tokens_out"] == 12
    assert kwargs["latency_ms"] == 350
    assert kwargs["success"] is True
    assert kwargs["doc_id"] == doc_id
    # Commit invoked exactly once.
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_swallows_internal_exceptions() -> None:
    """log() must NEVER raise even when the underlying repo raises.

    The fire-and-forget contract says a logging failure cannot disrupt the
    main processing path — we assert no exception propagates and that the
    structlog warn fires.
    """
    factory, _session = _make_factory()
    logger_obj = SessionScopedNlpUsageLogger(factory)

    fake_repo = MagicMock()
    fake_repo.log = AsyncMock(side_effect=RuntimeError("DB down"))
    repo_cls = MagicMock(return_value=fake_repo)

    with (
        patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.llm_usage_log.NlpUsageLogRepository",
            repo_cls,
        ),
        patch("nlp_pipeline.infrastructure.nlp_db.usage_log_factory.logger") as mock_log,
    ):
        # Must not raise — observer must never affect the subject.
        await logger_obj.log(
            model_id="x",
            provider="ollama",
            capability="extraction",
            tokens_in=1,
            tokens_out=1,
            latency_ms=10,
        )

    # Warning emitted with the expected event name.
    mock_log.warning.assert_called_once()
    args, kwargs = mock_log.warning.call_args
    assert args[0] == "nlp_usage_log_session_scoped_failed"
    # exc_info=True ensures the traceback is preserved for ops.
    assert kwargs.get("exc_info") is True


def test_satisfies_llm_usage_log_protocol() -> None:
    """SessionScopedNlpUsageLogger must structurally satisfy LlmUsageLogProtocol.

    LlmUsageLogProtocol is @runtime_checkable; isinstance() returns True when
    the class exposes an async log() with the matching keyword signature.  This
    is what lets FallbackChainClient and adapters accept the wrapper without
    importing the service-specific concrete class.
    """
    factory, _ = _make_factory()
    logger_obj = SessionScopedNlpUsageLogger(factory)
    assert isinstance(logger_obj, LlmUsageLogProtocol)
