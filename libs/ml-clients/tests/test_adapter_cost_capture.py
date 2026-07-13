"""Adapter provider-cost capture tests (PLAN-0117 W1, T-A-1-02).

Verifies FR-1: the DeepInfra adapters read ``usage.estimated_cost`` verbatim and
feed it (as the authoritative cost) into ``ml_api_estimated_cost_usd_total``,
falling back to the price matrix — never a silent $0 — when the provider omits
the cost, and never raising on a malformed cost value (NFR-1).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Extraction adapter ────────────────────────────────────────────────────────


def _make_extraction_adapter(**kwargs: Any) -> Any:
    from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter

    return DeepSeekExtractionAdapter(
        api_key="test-key",
        semaphore=asyncio.Semaphore(1),
        **kwargs,
    )


def _extraction_input() -> Any:
    from ml_clients.dataclasses import ExtractionInput

    return ExtractionInput(prompt="sys", context="ctx", output_schema={}, model_id="m")


def _ok_response_with_usage(*, estimated_cost: Any, tokens_in: int = 100, tokens_out: int = 50) -> MagicMock:
    """openai-shaped chat response whose ``usage`` carries an estimated_cost."""
    msg = MagicMock()
    msg.content = json.dumps({"relations": [{"a": 1}]})
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    usage = MagicMock()
    usage.prompt_tokens = tokens_in
    usage.completion_tokens = tokens_out
    # Explicit None — a bare MagicMock attribute would otherwise be a truthy mock.
    usage.prompt_tokens_details = None
    usage.estimated_cost = estimated_cost
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _cost_inc_value(metrics: MagicMock) -> float:
    """Extract the value passed to ``ml_api_estimated_cost_usd_total…inc(x)``."""
    inc = metrics.ml_api_estimated_cost_usd_total.labels.return_value.inc
    assert inc.call_args is not None, "cost metric .inc() was never called"
    return float(inc.call_args.args[0])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extraction_captures_estimated_cost_scientific_notation() -> None:
    """FR-1: provider ``estimated_cost`` (scientific notation) is used verbatim."""
    metrics = MagicMock()
    adapter = _make_extraction_adapter(model_id="openai/gpt-oss-120b", metrics=metrics)
    adapter._client.chat.completions.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_ok_response_with_usage(estimated_cost=4.1e-07)
    )

    await adapter.extract(_extraction_input())

    # 4.1e-07 captured verbatim (no float drift, no matrix override).
    assert _cost_inc_value(metrics) == pytest.approx(4.1e-07, rel=1e-9)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extraction_missing_cost_falls_back_to_matrix() -> None:
    """FR-1: absent provider cost → price-matrix compute_cost (never silent $0)."""
    from ml_clients.pricing import compute_cost

    metrics = MagicMock()
    # Qwen3-32B IS priced → matrix fallback must be non-zero.
    adapter = _make_extraction_adapter(model_id="Qwen/Qwen3-32B", metrics=metrics)
    adapter._client.chat.completions.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_ok_response_with_usage(estimated_cost=None, tokens_in=1000, tokens_out=500)
    )

    await adapter.extract(_extraction_input())

    expected = float(compute_cost("Qwen/Qwen3-32B", 1000, 500))
    assert expected > 0
    assert _cost_inc_value(metrics) == pytest.approx(expected, rel=1e-9)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extraction_never_raises_on_malformed_cost() -> None:
    """NFR-1: a malformed ``estimated_cost`` degrades to matrix, does not raise."""
    metrics = MagicMock()
    adapter = _make_extraction_adapter(model_id="Qwen/Qwen3-32B", metrics=metrics)
    adapter._client.chat.completions.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_ok_response_with_usage(estimated_cost="not-a-number", tokens_in=1000, tokens_out=500)
    )

    # Must complete normally (no exception leaks from cost parsing).
    out = await adapter.extract(_extraction_input())
    assert out.result == {"relations": [{"a": 1}]}
    # Fell back to the matrix (non-zero for the priced model).
    assert _cost_inc_value(metrics) > 0


# ── Embedding adapter ─────────────────────────────────────────────────────────


def _embedding_response(embeddings: list[list[float]], *, usage: dict[str, Any] | None) -> MagicMock:
    body: dict[str, Any] = {
        "data": [{"embedding": emb, "index": i} for i, emb in enumerate(embeddings)],
        "model": "BAAI/bge-large-en-v1.5",
        "object": "list",
    }
    if usage is not None:
        body["usage"] = usage
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body
    return resp


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embedding_prefers_provider_estimated_cost() -> None:
    """FR-1: /embeddings ``usage.estimated_cost`` is used verbatim when present."""
    from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
    from ml_clients.dataclasses import EmbeddingInput

    metrics = MagicMock()
    resp = _embedding_response([[0.1] * 1024], usage={"estimated_cost": 2.5e-08})
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=resp)

        adapter = DeepInfraEmbeddingAdapter(api_key="test-key", metrics=metrics)
        await adapter.embed([EmbeddingInput(text="Apple Inc.", model_id="BAAI/bge-large-en-v1.5")])

    assert _cost_inc_value(metrics) == pytest.approx(2.5e-08, rel=1e-9)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embedding_falls_back_to_matrix_without_usage() -> None:
    """FR-1: no ``usage`` block → matrix compute_cost for BAAI/bge-large."""
    from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
    from ml_clients.dataclasses import EmbeddingInput
    from ml_clients.pricing import compute_cost

    metrics = MagicMock()
    resp = _embedding_response([[0.1] * 1024], usage=None)
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=resp)

        adapter = DeepInfraEmbeddingAdapter(api_key="test-key", metrics=metrics)
        # "Apple Inc." → 2 words → matrix cost for 2 input tokens, 0 output.
        await adapter.embed([EmbeddingInput(text="Apple Inc.", model_id="BAAI/bge-large-en-v1.5")])

    expected = float(compute_cost("BAAI/bge-large-en-v1.5", 2, 0))
    assert _cost_inc_value(metrics) == pytest.approx(expected, rel=1e-9)
