"""Unit tests for the LLM relevance cascade scorer (PLAN-0111 C-7).

The cascade reuses the Llama-3.1-8B relevance model via a DeepInfra OpenAI-compat
chat-completions call. These tests stub the httpx transport so no network is hit
and assert: a well-formed response yields a clamped [0,1] score; malformed /
error responses return None (best-effort — never break routing); and the score
is clamped.
"""

from __future__ import annotations

import httpx
import pytest
from nlp_pipeline.application.blocks.relevance_cascade import RelevanceCascadeScorer

pytestmark = pytest.mark.unit


def _scorer(handler: httpx.MockTransport) -> RelevanceCascadeScorer:
    # We monkeypatch the AsyncClient inside score_relevance by patching httpx;
    # instead we inject via a transport-bearing client. Simpler: patch the
    # module's httpx.AsyncClient to use the mock transport.
    return RelevanceCascadeScorer(
        api_key="test-key",
        base_url="https://api.deepinfra.com/v1/openai",
        model_id="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        timeout_seconds=5.0,
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    """Make the module construct an AsyncClient bound to the mock transport."""
    import nlp_pipeline.application.blocks.relevance_cascade as mod

    real_client = httpx.AsyncClient

    def _factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("timeout", None)
        return real_client(transport=transport)

    monkeypatch.setattr(mod.httpx, "AsyncClient", _factory)


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.mark.asyncio
async def test_score_relevance_parses_clamped_score(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(lambda _req: _chat_response('{"score": 0.83, "sentiment": "positive"}'))
    _patch_client(monkeypatch, transport)
    scorer = _scorer(transport)
    score = await scorer.score_relevance(title="Apple beats earnings", subtitle="Record sales")
    assert score == pytest.approx(0.83)


@pytest.mark.asyncio
async def test_score_relevance_clamps_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(lambda _req: _chat_response('{"score": 1.7}'))
    _patch_client(monkeypatch, transport)
    scorer = _scorer(transport)
    score = await scorer.score_relevance(title="t", subtitle="s")
    assert score == 1.0


@pytest.mark.asyncio
async def test_score_relevance_returns_none_on_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(lambda _req: _chat_response("not json at all"))
    _patch_client(monkeypatch, transport)
    scorer = _scorer(transport)
    score = await scorer.score_relevance(title="t", subtitle="s")
    assert score is None


@pytest.mark.asyncio
async def test_score_relevance_returns_none_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(lambda _req: httpx.Response(500, text="boom"))
    _patch_client(monkeypatch, transport)
    scorer = _scorer(transport)
    score = await scorer.score_relevance(title="t", subtitle="s")
    assert score is None


@pytest.mark.asyncio
async def test_score_relevance_strips_think_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """A <think>…</think>-wrapped response is salvaged, not dropped."""
    content = '<think>let me reason</think>{"score": 0.42}'
    transport = httpx.MockTransport(lambda _req: _chat_response(content))
    _patch_client(monkeypatch, transport)
    scorer = _scorer(transport)
    score = await scorer.score_relevance(title="t", subtitle="s")
    assert score == pytest.approx(0.42)


def _scorer_with_logger(logger: object) -> RelevanceCascadeScorer:
    return RelevanceCascadeScorer(
        api_key="test-key",
        base_url="https://api.deepinfra.com/v1/openai",
        model_id="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        timeout_seconds=5.0,
        usage_logger=logger,  # type: ignore[arg-type]
    )


def _chat_response_with_usage(content: str, estimated_cost: float | None) -> httpx.Response:
    usage: dict[str, object] = {"prompt_tokens": 16, "completion_tokens": 3}
    if estimated_cost is not None:
        usage["estimated_cost"] = estimated_cost
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": usage})


@pytest.mark.asyncio
async def test_cascade_logs_provider_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLAN-0117 W3: DeepInfra usage.estimated_cost → cost_source='provider', verbatim cost."""
    from unittest.mock import AsyncMock

    logger = AsyncMock()
    transport = httpx.MockTransport(lambda _req: _chat_response_with_usage('{"score": 0.5}', 4.1e-07))
    _patch_client(monkeypatch, transport)
    scorer = _scorer_with_logger(logger)
    await scorer.score_relevance(title="t", subtitle="s")

    logger.log.assert_awaited_once()
    kwargs = logger.log.await_args.kwargs
    assert kwargs["cost_source"] == "provider"
    # Verbatim provider cost, not the price-matrix estimate.
    assert kwargs["estimated_cost_usd"] == pytest.approx(4.1e-07)
    assert kwargs["estimated_cost_usd"] != 0.0


@pytest.mark.asyncio
async def test_cascade_falls_back_to_pricematrix(monkeypatch: pytest.MonkeyPatch) -> None:
    """No provider cost → matrix path (cost_source='pricematrix'), never a hardcoded $0."""
    from unittest.mock import AsyncMock

    logger = AsyncMock()
    transport = httpx.MockTransport(lambda _req: _chat_response_with_usage('{"score": 0.5}', None))
    _patch_client(monkeypatch, transport)
    scorer = _scorer_with_logger(logger)
    await scorer.score_relevance(title="Apple beats", subtitle="strong quarter")

    kwargs = logger.log.await_args.kwargs
    assert kwargs["cost_source"] == "pricematrix"
    # Turbo 8B is priced → non-zero cost for non-zero tokens.
    assert kwargs["estimated_cost_usd"] > 0.0
