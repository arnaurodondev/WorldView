"""Unit tests for POST /api/v1/embed (provider-agnostic embedding endpoint).

Covers:
  - Happy path: valid text → 200 with {embedding, model, dimensions}
  - Empty text fails Pydantic min_length=1 → 422
  - RetryableError from provider → 503 (safe degradation for rag-chat caller)
  - FatalError from provider → 503
  - Unexpected exception from provider → 503
  - Instruction prefix is prepended before calling the embedding client
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput  # type: ignore[import-not-found]
from ml_clients.errors import FatalError, RetryableError  # type: ignore[import-not-found]
from nlp_pipeline.api.routes.embed import router
from nlp_pipeline.config import Settings

pytestmark = pytest.mark.unit


def _make_app(settings: Settings | None = None, embedding_client: Any = None) -> FastAPI:
    """Build a minimal FastAPI app with the embed router, mock settings, and mock embedding client."""
    app = FastAPI()
    app.include_router(router)

    s = settings or Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/nlp_db",
        intelligence_database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
        database_url_read="",
        intelligence_database_url_read="",
    )
    app.state.settings = s

    # The embed endpoint reads app.state.embedding_client (set in lifespan in production).
    # In tests, we provide a mock to avoid real network calls.
    app.state.embedding_client = embedding_client or _make_mock_embedding_client()
    return app


def _make_mock_embedding_client(
    embedding: list[float] | None = None,
    model_id: str = "bge-large",
) -> Any:
    """Return a mock embedding client that produces the given embedding on embed()."""
    mock = MagicMock()
    out = EmbeddingOutput(
        embedding=embedding or [0.1] * 1024,
        model_id=model_id,
        dimension=len(embedding) if embedding else 1024,
    )
    mock.embed = AsyncMock(return_value=[out])
    return mock


_DUMMY_EMBEDDING = [0.1] * 1024


@pytest.mark.unit
class TestEmbedEndpoint:
    """Tests for POST /api/v1/embed."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_embedding(self) -> None:
        """Valid text → 200 with {embedding, model, dimensions}."""
        app = _make_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/embed", json={"text": "Apple Q3 revenue"})

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["embedding"], list)
        assert len(body["embedding"]) == 1024
        assert body["dimensions"] == 1024
        assert body["model"] == "bge-large"

    @pytest.mark.asyncio
    async def test_embedding_client_receives_preprocessed_text(self) -> None:
        """The embedding client receives the instruction-prefix-prepended + truncated text."""
        mock_client = _make_mock_embedding_client()
        app = _make_app(embedding_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/api/v1/embed", json={"text": "Apple Q3 revenue"})

        # embed() was called once with a single EmbeddingInput
        mock_client.embed.assert_called_once()
        inputs: list[EmbeddingInput] = mock_client.embed.call_args[0][0]
        assert len(inputs) == 1
        # instruction_prefix is None (already prepended to .text in the route handler)
        assert inputs[0].instruction_prefix is None
        # The text contains the instruction prefix prepended by the route handler
        assert "Apple Q3 revenue" in inputs[0].text

    @pytest.mark.asyncio
    async def test_empty_text_field_returns_422(self) -> None:
        """Empty string text fails Pydantic min_length=1 validation → 422."""
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/embed", json={"text": ""})

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_retryable_error_returns_503(self) -> None:
        """RetryableError from provider → 503 (safe degradation; rag-chat degrades gracefully)."""
        mock_client = MagicMock()
        mock_client.embed = AsyncMock(side_effect=RetryableError("Ollama timeout"))

        app = _make_app(embedding_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/embed", json={"text": "test text"})

        assert resp.status_code == 503
        assert resp.json()["error"] == "embedding_unavailable"

    @pytest.mark.asyncio
    async def test_fatal_error_returns_503(self) -> None:
        """FatalError from provider (e.g. dimension mismatch, 4xx) → 503."""
        mock_client = MagicMock()
        mock_client.embed = AsyncMock(side_effect=FatalError("Unexpected dimension"))

        app = _make_app(embedding_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/embed", json={"text": "Apple earnings"})

        assert resp.status_code == 503
        assert resp.json()["error"] == "embedding_unavailable"

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_503(self) -> None:
        """Unexpected exception from provider → 503 (never propagates to caller)."""
        mock_client = MagicMock()
        mock_client.embed = AsyncMock(side_effect=RuntimeError("connection refused"))

        app = _make_app(embedding_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/embed", json={"text": "NVDA revenue"})

        assert resp.status_code == 503
        assert resp.json()["error"] == "embedding_unavailable"

    @pytest.mark.asyncio
    async def test_instruction_prefix_prepended(self) -> None:
        """The instruction_prefix from settings is prepended to the text before embedding."""
        mock_client = _make_mock_embedding_client()
        app = _make_app(embedding_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/embed", json={"text": "TSLA quarterly results"})

        assert resp.status_code == 200
        inputs: list[EmbeddingInput] = mock_client.embed.call_args[0][0]
        assert len(inputs) == 1
        # Default instruction prefix is non-empty and prepended
        assert "TSLA quarterly results" in inputs[0].text
        assert "Represent this financial document" in inputs[0].text

    @pytest.mark.asyncio
    async def test_empty_output_from_client_returns_503(self) -> None:
        """Empty outputs list from provider → 503 (defensive guard)."""
        mock_client = MagicMock()
        mock_client.embed = AsyncMock(return_value=[])  # empty list, no outputs

        app = _make_app(embedding_client=mock_client)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/embed", json={"text": "test text"})

        assert resp.status_code == 503
        assert resp.json()["error"] == "embedding_unavailable"
