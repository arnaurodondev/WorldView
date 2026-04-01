"""Integration test fixtures for nlp-pipeline service.

These tests require a running PostgreSQL instance (via testcontainers or external).
All ML clients are replaced with lightweight mock adapters that return deterministic
responses so tests run without GPU/Ollama infrastructure.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Mock ML adapters ──────────────────────────────────────────────────────────


class _MockNERClient:
    """Returns one organization mention per document, deterministically."""

    async def predict(self, texts: list[str], labels: list[str], threshold: float = 0.35) -> list[list[dict[str, Any]]]:
        return [
            [{"text": "TestCorp", "label": "organization", "score": 0.95, "start": 0, "end": 8}] if text else []
            for text in texts
        ]


class _MockZeroNERClient:
    """Returns no mentions — used for the zero-NER scenario."""

    async def predict(self, texts: list[str], labels: list[str], threshold: float = 0.35) -> list[list[dict[str, Any]]]:
        return [[] for _ in texts]


class _MockEmbeddingClient:
    """Returns fixed-dimension zero vectors."""

    _DIM = 32

    async def embed(self, texts: list[str], instruction_prefix: str = "") -> list[list[float]]:
        return [[0.0] * self._DIM for _ in texts]


class _MockExtractionClient:
    """Returns an empty extraction result."""

    async def extract(self, prompt: str, model_id: str) -> dict[str, Any]:
        return {"events": [], "claims": [], "relations": []}


# ── Shared fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_ner_client() -> _MockNERClient:
    return _MockNERClient()


@pytest.fixture
def mock_zero_ner_client() -> _MockZeroNERClient:
    return _MockZeroNERClient()


@pytest.fixture
def mock_embedding_client() -> _MockEmbeddingClient:
    return _MockEmbeddingClient()


@pytest.fixture
def mock_extraction_client() -> _MockExtractionClient:
    return _MockExtractionClient()


@pytest.fixture
def mock_storage() -> MagicMock:
    """Storage that returns a fixed article text."""
    storage = MagicMock()
    storage.get_object_bytes = MagicMock(
        return_value=b"Apple Inc. reported record earnings this quarter. "
        b"The technology giant posted revenue of $120 billion. "
        b"CEO Tim Cook cited strong iPhone sales as the primary driver."
    )
    return storage


@pytest.fixture
def mock_watchlist_cache() -> MagicMock:
    cache = MagicMock()
    cache.get_all_watched = AsyncMock(return_value=frozenset())
    cache._client = AsyncMock()  # raw valkey client for novelty gate
    return cache


@pytest.fixture
def mock_backpressure() -> MagicMock:
    bp = MagicMock()
    bp.__aenter__ = AsyncMock(return_value=None)
    bp.__aexit__ = AsyncMock(return_value=None)
    return bp
