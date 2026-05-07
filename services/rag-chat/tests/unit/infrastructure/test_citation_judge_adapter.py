"""Unit tests for CitationJudgeAdapter — PLAN-0084 A-1 T-A-1-02."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_provider(chunks: list[str]) -> MagicMock:
    """Build a fake provider whose stream() yields the given chunks."""

    async def _stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        for chunk in chunks:
            yield chunk

    provider = MagicMock()
    provider.stream = MagicMock(side_effect=_stream)
    return provider


@pytest.mark.asyncio
async def test_score_citation_happy_path() -> None:
    """Provider returns '2' → adapter returns '2' unchanged."""
    from rag_chat.infrastructure.llm.citation_judge_adapter import CitationJudgeAdapter

    provider = _make_provider(["2"])
    adapter = CitationJudgeAdapter(provider, timeout_s=10.0)
    result = await adapter.score_citation(claim="test prompt", snippet="unused")
    assert result == "2"


@pytest.mark.asyncio
async def test_score_citation_timeout_raises_LLMJudgeTimeoutError() -> None:
    """Provider never yields → asyncio.wait_for fires → LLMJudgeTimeoutError raised."""
    from rag_chat.domain.errors import LLMJudgeTimeoutError
    from rag_chat.infrastructure.llm.citation_judge_adapter import CitationJudgeAdapter

    async def _slow_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        await asyncio.sleep(999)  # will never complete within the tiny timeout
        yield "never"

    provider = MagicMock()
    provider.stream = MagicMock(side_effect=_slow_stream)

    adapter = CitationJudgeAdapter(provider, timeout_s=0.001)
    with pytest.raises(LLMJudgeTimeoutError):
        await adapter.score_citation(claim="claim", snippet="snippet")


@pytest.mark.asyncio
async def test_score_citation_propagates_provider_errors() -> None:
    """Provider raises RuntimeError → adapter propagates it unchanged."""
    from rag_chat.infrastructure.llm.citation_judge_adapter import CitationJudgeAdapter

    async def _failing_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider down")
        yield  # make it a generator

    provider = MagicMock()
    provider.stream = MagicMock(side_effect=_failing_stream)

    adapter = CitationJudgeAdapter(provider, timeout_s=10.0)
    with pytest.raises(RuntimeError, match="provider down"):
        await adapter.score_citation(claim="claim", snippet="snippet")


@pytest.mark.asyncio
async def test_score_citation_uses_temperature_zero() -> None:
    """Adapter always passes temperature=0.0 and max_tokens=2 to the provider."""
    from rag_chat.infrastructure.llm.citation_judge_adapter import CitationJudgeAdapter

    captured_kwargs: dict = {}

    async def _recording_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured_kwargs.update(kwargs)
        yield "3"

    provider = MagicMock()
    provider.stream = MagicMock(side_effect=_recording_stream)

    adapter = CitationJudgeAdapter(provider, timeout_s=10.0)
    await adapter.score_citation(claim="prompt text", snippet="unused")

    assert captured_kwargs.get("temperature") == 0.0
    assert captured_kwargs.get("max_tokens") == 2


@pytest.mark.asyncio
async def test_score_citation_multi_chunk_response() -> None:
    """Multiple chunks are joined into a single return value."""
    from rag_chat.infrastructure.llm.citation_judge_adapter import CitationJudgeAdapter

    provider = _make_provider(["", "2", "\n"])
    adapter = CitationJudgeAdapter(provider, timeout_s=10.0)
    result = await adapter.score_citation(claim="prompt", snippet="unused")
    assert result == "2\n"
    # Callers strip() the result before parsing, so this is fine.
