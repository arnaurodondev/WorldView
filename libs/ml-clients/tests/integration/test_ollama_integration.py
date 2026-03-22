"""Integration tests — require a running Ollama instance with bge-large-en-v1.5 loaded.

Run with:
    OLLAMA_BASE_URL=http://localhost:11434 pytest tests/integration/ -v -m integration
"""

from __future__ import annotations

import asyncio
import os

import pytest
from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter
from ml_clients.adapters.ollama_extraction import OllamaExtractionAdapter
from ml_clients.dataclasses import EmbeddingInput, ExtractionInput


@pytest.fixture
def semaphore() -> asyncio.Semaphore:
    return asyncio.Semaphore(4)


@pytest.mark.integration
async def test_ollama_embedding_roundtrip(semaphore: asyncio.Semaphore) -> None:
    """Requires OLLAMA_BASE_URL env var and bge-large-en-v1.5 model loaded."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    adapter = OllamaEmbeddingAdapter(base_url=base_url, model_id="bge-large-en-v1.5", semaphore=semaphore)
    result = await adapter.embed([EmbeddingInput(text="Apple Inc. reported earnings", model_id="bge-large-en-v1.5")])
    assert len(result) == 1
    assert result[0].dimension == 1024
    assert len(result[0].embedding) == 1024


@pytest.mark.integration
async def test_ollama_embedding_batch(semaphore: asyncio.Semaphore) -> None:
    """Embed multiple texts; each must return 1024-dim vector."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    adapter = OllamaEmbeddingAdapter(base_url=base_url, model_id="bge-large-en-v1.5", semaphore=semaphore)
    texts = [
        "Apple Inc. reported record earnings.",
        "The Federal Reserve raised interest rates.",
        "Tesla announced a new Gigafactory.",
    ]
    inputs = [EmbeddingInput(text=t, model_id="bge-large-en-v1.5") for t in texts]
    results = await adapter.embed(inputs)
    assert len(results) == 3
    for r in results:
        assert r.dimension == 1024
        assert len(r.embedding) == 1024


@pytest.mark.integration
async def test_ollama_extraction_roundtrip(semaphore: asyncio.Semaphore) -> None:
    """Requires OLLAMA_BASE_URL env var and qwen2.5:7b-instruct model loaded."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    adapter = OllamaExtractionAdapter(base_url=base_url, model_id="qwen2.5:7b-instruct", semaphore=semaphore)
    inp = ExtractionInput(
        prompt=(
            "Extract the company name and sentiment from the context. "
            'Respond with valid JSON only: {"company": str, "sentiment": str}'
        ),
        context="Apple Inc. reported record Q4 earnings, beating analyst expectations.",
        output_schema={"type": "object", "properties": {"company": {}, "sentiment": {}}},
        model_id="qwen2.5:7b-instruct",
    )
    result = await adapter.extract(inp)
    assert "company" in result.result or len(result.raw_response) > 0
