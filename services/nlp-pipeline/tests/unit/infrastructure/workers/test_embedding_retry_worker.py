"""Unit tests for EmbeddingRetryWorker (PLAN-0057 Wave E-4).

These cover the new ``embedding_retry_abandoned`` log emission so the operations
team always has a structured signal when a row hits the retry ceiling.

structlog is not bound to stdlib ``logging`` in unit-test runs so we monkey-patch
the module-level ``logger`` and assert on its captured calls instead of using
``caplog``.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_session_factory() -> MagicMock:
    """Build a session factory that yields an AsyncMock session via async with."""

    @asynccontextmanager
    async def _ctx():
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        session.commit = AsyncMock()
        session.add = MagicMock()
        yield session

    return MagicMock(side_effect=_ctx)


def _make_failing_embedding_client() -> AsyncMock:
    client = AsyncMock()
    client.embed = AsyncMock(side_effect=RuntimeError("DeepInfra 503"))
    return client


def _make_job(retry_count: int) -> MagicMock:
    job = MagicMock()
    job.pending_id = uuid.uuid4()
    job.doc_id = uuid.uuid4()
    job.section_id = uuid.uuid4()
    job.chunk_id = None
    job.embedding_text = "Apple posted Q3 earnings."
    job.retry_count = retry_count
    return job


class TestAbandonedLogEmission:
    @pytest.mark.asyncio
    async def test_emits_abandoned_log_on_final_retry(self, monkeypatch) -> None:
        """When the failing job's incoming retry_count is _MAX_RETRIES-1 (=4),
        the resulting attempt brings the total to _MAX_RETRIES so the next
        ``claim_batch`` call will skip it.  The worker must surface this with an
        ``embedding_retry_abandoned`` warning.
        """
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        fake_logger.info = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_failing_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        await worker._process_job(_make_job(retry_count=4))

        events = [event for event, _ in warning_calls]
        assert "embedding_retry_failed" in events
        assert "embedding_retry_abandoned" in events
        # Verify the abandoned event carries diagnostic context.
        abandoned_kw = next(kw for event, kw in warning_calls if event == "embedding_retry_abandoned")
        assert abandoned_kw["retry_count"] == 5
        assert abandoned_kw["max_retries"] == 5
        assert abandoned_kw["final_error"] == "DeepInfra 503"

    @pytest.mark.asyncio
    async def test_does_not_emit_abandoned_log_on_intermediate_retry(self, monkeypatch) -> None:
        """A job with retry_count=2 -> 3 must NOT emit the abandoned signal."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        fake_logger.info = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_failing_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        await worker._process_job(_make_job(retry_count=2))

        events = [event for event, _ in warning_calls]
        assert "embedding_retry_abandoned" not in events
