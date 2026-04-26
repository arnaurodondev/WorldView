"""Unit tests for ArticleRelevanceScoringWorker (PRD-0026 Wave 5)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from nlp_pipeline.infrastructure.workers.article_relevance_scoring_worker import (
    ArticleRelevanceScoringWorker,
)

pytestmark = pytest.mark.unit

_DOC_ID = uuid.uuid4()
_PATCH_HTTPX = "nlp_pipeline.infrastructure.workers.article_relevance_scoring_worker.httpx.AsyncClient"


def _make_session_factory(
    articles: list[tuple] | None = None,
) -> tuple[MagicMock, AsyncMock]:
    """Build a session factory that returns mocked DB results."""
    session = AsyncMock()
    session.commit = AsyncMock()

    # Simulate Phase 1 query result
    if articles is not None:
        rows = [MagicMock(doc_id=str(doc_id), title=title, source_type=st) for doc_id, title, st in articles]
        result_mock = MagicMock()
        result_mock.fetchall.return_value = rows
        session.execute = AsyncMock(return_value=result_mock)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=ctx)
    return factory, session


@contextmanager
def _mock_http_client(response_body: str | None = None, side_effect: Exception | None = None) -> Generator:
    """Context manager that patches httpx.AsyncClient.post with the given response."""
    resp_mock = MagicMock()
    resp_mock.text = response_body or ""

    if side_effect is not None:
        post_mock = AsyncMock(side_effect=side_effect)
    else:
        post_mock = AsyncMock(return_value=resp_mock)

    client_mock = AsyncMock()
    client_mock.post = post_mock

    ctx_manager = MagicMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=client_mock)
    ctx_manager.__aexit__ = AsyncMock(return_value=False)

    with patch(_PATCH_HTTPX, return_value=ctx_manager):
        yield client_mock


def _make_worker(factory: MagicMock) -> ArticleRelevanceScoringWorker:
    return ArticleRelevanceScoringWorker(
        nlp_session_factory=factory,
        ollama_url="http://ollama:11434",
        model="qwen3:0.6b",
        batch_size=10,
        timeout_seconds=5,
        cycle_seconds=1,
    )


# ── Ollama response parsing tests ─────────────────────────────────────────────


class TestOllamaResponseParsing:
    @pytest.mark.asyncio
    async def test_parses_valid_json_score(self) -> None:
        """Ollama returns {"score": 0.75, "reason": "CEO change"} → stored as 0.75."""
        articles = [(_DOC_ID, "Tesla CEO resigns", "NEWS")]
        factory, session = _make_session_factory(articles)

        # Ollama wraps model output in "response" field
        body = json.dumps({"response": json.dumps({"score": 0.75, "reason": "CEO change"})})

        with _mock_http_client(body):
            worker = _make_worker(factory)
            count = await worker.scoring_cycle()

        assert count == 1
        # Verify write was called with correct score
        write_call = session.execute.call_args_list[-1]
        params = write_call[0][1]
        assert abs(params["score"] - 0.75) < 1e-9

    @pytest.mark.asyncio
    async def test_clamps_score_above_1(self) -> None:
        """Score > 1.0 is clamped to 1.0."""
        articles = [(_DOC_ID, "Mega crash", "NEWS")]
        factory, session = _make_session_factory(articles)

        body = json.dumps({"response": json.dumps({"score": 1.5, "reason": "too high"})})

        with _mock_http_client(body):
            worker = _make_worker(factory)
            count = await worker.scoring_cycle()

        assert count == 1
        write_call = session.execute.call_args_list[-1]
        params = write_call[0][1]
        assert params["score"] == 1.0

    @pytest.mark.asyncio
    async def test_clamps_score_below_0(self) -> None:
        """Score < 0.0 is clamped to 0.0."""
        articles = [(_DOC_ID, "Irrelevant news", "BLOG")]
        factory, session = _make_session_factory(articles)

        body = json.dumps({"response": json.dumps({"score": -0.2, "reason": "negative"})})

        with _mock_http_client(body):
            worker = _make_worker(factory)
            count = await worker.scoring_cycle()

        assert count == 1
        write_call = session.execute.call_args_list[-1]
        params = write_call[0][1]
        assert params["score"] == 0.0

    @pytest.mark.asyncio
    async def test_skips_article_on_json_decode_error(self) -> None:
        """Invalid JSON from Ollama → article skipped, no DB write, no exception."""
        articles = [(_DOC_ID, "Bad JSON article", "NEWS")]
        factory, _session = _make_session_factory(articles)

        with _mock_http_client("not valid json at all"):
            worker = _make_worker(factory)
            count = await worker.scoring_cycle()

        # Article skipped — Phase 3 should not run (scored list is empty)
        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_article_on_missing_score_key(self) -> None:
        """JSON without 'score' key → article skipped."""
        articles = [(_DOC_ID, "Some article", "NEWS")]
        factory, _session = _make_session_factory(articles)

        body = json.dumps({"response": json.dumps({"reason": "no score key"})})

        with _mock_http_client(body):
            worker = _make_worker(factory)
            count = await worker.scoring_cycle()

        assert count == 0


# ── Tier filtering tests ───────────────────────────────────────────────────────


class TestTierFiltering:
    @pytest.mark.asyncio
    async def test_empty_batch_returns_zero(self) -> None:
        """No MEDIUM/DEEP articles → returns 0 without HTTP calls."""
        factory, _session = _make_session_factory(articles=[])

        with _mock_http_client() as client_mock:
            worker = _make_worker(factory)
            count = await worker.scoring_cycle()

        assert count == 0
        client_mock.post.assert_not_called()  # No Ollama calls


# ── R24 compliance tests ───────────────────────────────────────────────────────


class TestR24Compliance:
    @pytest.mark.asyncio
    async def test_db_session_closed_before_ollama_call(self) -> None:
        """R24: DB session must be released BEFORE any Ollama HTTP call."""
        events: list[str] = []

        # Session factory that records open/close
        session = AsyncMock()
        session.commit = AsyncMock()
        rows = [MagicMock(doc_id=str(_DOC_ID), title="T", source_type="NEWS")]
        result_mock = MagicMock()
        result_mock.fetchall.return_value = rows
        session.execute = AsyncMock(return_value=result_mock)

        async def _enter(*_: object) -> AsyncMock:
            events.append("session_open")
            return session

        async def _exit(*_: object) -> bool:
            events.append("session_close")
            return False

        ctx = AsyncMock()
        ctx.__aenter__ = _enter
        ctx.__aexit__ = _exit
        factory = MagicMock(return_value=ctx)

        # HTTP call recorder
        body = json.dumps({"response": json.dumps({"score": 0.5, "reason": "ok"})})
        resp_mock = MagicMock()
        resp_mock.text = body

        async def _post(*_: object, **__: object) -> MagicMock:
            events.append("http_call")
            return resp_mock

        client_mock = AsyncMock()
        client_mock.post = _post
        ctx_http = MagicMock()
        ctx_http.__aenter__ = AsyncMock(return_value=client_mock)
        ctx_http.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_HTTPX, return_value=ctx_http):
            worker = _make_worker(factory)
            await worker.scoring_cycle()

        # Phase 1 session must close BEFORE first HTTP call
        first_close = next(i for i, e in enumerate(events) if e == "session_close")
        first_http = next(i for i, e in enumerate(events) if e == "http_call")
        assert first_close < first_http, f"Session not closed before HTTP: {events}"


# ── Error handling tests ───────────────────────────────────────────────────────


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_handles_ollama_connect_error(self) -> None:
        """httpx.ConnectError → skip cycle, log warning, return 0 (no exception raised)."""
        articles = [(_DOC_ID, "Some article", "NEWS")]
        factory, _session = _make_session_factory(articles)

        with _mock_http_client(side_effect=httpx.ConnectError("Connection refused")):
            worker = _make_worker(factory)
            count = await worker.scoring_cycle()  # must not raise

        assert count == 0

    @pytest.mark.asyncio
    async def test_handles_ollama_timeout(self) -> None:
        """httpx.TimeoutException → skip cycle, return 0."""
        articles = [(_DOC_ID, "Timeout article", "NEWS")]
        factory, _session = _make_session_factory(articles)

        with _mock_http_client(side_effect=httpx.ReadTimeout("Timed out")):
            worker = _make_worker(factory)
            count = await worker.scoring_cycle()

        assert count == 0
