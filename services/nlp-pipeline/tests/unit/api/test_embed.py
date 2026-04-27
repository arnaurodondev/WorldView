"""Unit tests for POST /api/v1/embed (Bug fix: missing embed endpoint).

Covers:
  - Happy path: valid text → 200 with list[float] embedding
  - Empty embedding from Ollama is returned as-is (edge case: empty model response)
  - Ollama timeout → 503 (safe degradation for rag-chat caller)
  - Ollama 5xx → 503
  - Ollama connection refused → 503
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.routes.embed import router
from nlp_pipeline.config import Settings


def _make_app(settings: Settings | None = None) -> FastAPI:
    """Build a minimal FastAPI app with the embed router and mock settings."""
    app = FastAPI()
    app.include_router(router)

    # Attach settings to app.state as the router reads settings from there.
    s = settings or Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/nlp_db",
        intelligence_database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
        database_url_read="",
        intelligence_database_url_read="",
    )
    app.state.settings = s
    return app


def _mock_ollama_response(embedding: list[float]) -> Any:
    """Build a mock httpx.Response with the given embedding."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"embedding": embedding})
    return mock_resp


_DUMMY_EMBEDDING = [0.1] * 1024
# nomic-embed-text produces 768-dim vectors — must match expected_dims validation in embed.py
_DUMMY_EMBEDDING_768 = [0.1] * 768


@pytest.mark.unit
class TestEmbedEndpoint:
    """Tests for POST /api/v1/embed."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_embedding(self) -> None:
        """Valid text → 200 with {embedding, model, dimensions}."""
        app = _make_app()

        # Patch httpx.AsyncClient.post to return a mock Ollama response.
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_mock_ollama_response(_DUMMY_EMBEDDING))

        with patch("nlp_pipeline.api.routes.embed.httpx.AsyncClient", return_value=mock_client):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/embed", json={"text": "Apple Q3 revenue"})

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["embedding"], list)
        assert len(body["embedding"]) == 1024
        assert body["dimensions"] == 1024
        # model must match settings.embedding_model_id default ("bge-large")
        assert body["model"] == "bge-large"

    @pytest.mark.asyncio
    async def test_model_override_is_used(self) -> None:
        """Optional model field is forwarded to Ollama when provided.

        Uses a 768-dim mock embedding because nomic-embed-text produces 768-dim
        vectors — the dimension validation added to embed.py rejects embeddings
        whose dimension does not match the model's expected size (1024 for bge-large,
        768 for nomic-embed-text).  Using _DUMMY_EMBEDDING (1024-dim) here would
        cause the endpoint to return 503 with 'embedding_unavailable'.
        """
        app = _make_app()

        call_args: dict = {}

        async def _fake_post(url: str, *, json: dict, **_: Any) -> Any:
            call_args["model"] = json.get("model")
            # Return 768-dim vector so dimension validation passes for nomic-embed-text.
            return _mock_ollama_response(_DUMMY_EMBEDDING_768)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = _fake_post

        with patch("nlp_pipeline.api.routes.embed.httpx.AsyncClient", return_value=mock_client):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/embed", json={"text": "hello", "model": "nomic-embed-text"})

        assert resp.status_code == 200
        assert call_args["model"] == "nomic-embed-text"
        assert resp.json()["model"] == "nomic-embed-text"
        # Dimension must match nomic-embed-text's 768-dim output.
        assert resp.json()["dimensions"] == 768

    @pytest.mark.asyncio
    async def test_empty_text_field_returns_422(self) -> None:
        """Empty string text fails Pydantic min_length=1 validation → 422."""
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/embed", json={"text": ""})

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_ollama_timeout_returns_503(self) -> None:
        """Ollama timeout → 503 (safe degradation; rag-chat returns empty embedding)."""
        import httpx

        app = _make_app()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("nlp_pipeline.api.routes.embed.httpx.AsyncClient", return_value=mock_client):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/embed", json={"text": "test text"})

        assert resp.status_code == 503
        # All fallback models also timeout → embedding_unavailable (not embedding_timeout)
        assert resp.json()["error"] == "embedding_unavailable"

    @pytest.mark.asyncio
    async def test_ollama_5xx_returns_503(self) -> None:
        """Ollama HTTP 500 → 503 with error field."""
        import httpx

        app = _make_app()

        error_resp = MagicMock()
        error_resp.status_code = 500
        http_err = httpx.HTTPStatusError("500 Internal Server Error", request=MagicMock(), response=error_resp)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=http_err)

        with patch("nlp_pipeline.api.routes.embed.httpx.AsyncClient", return_value=mock_client):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/embed", json={"text": "Apple earnings"})

        assert resp.status_code == 503
        assert resp.json()["error"] == "embedding_unavailable"

    @pytest.mark.asyncio
    async def test_ollama_connection_refused_returns_503(self) -> None:
        """Connection refused to Ollama → 503."""
        import httpx

        app = _make_app()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("nlp_pipeline.api.routes.embed.httpx.AsyncClient", return_value=mock_client):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/embed", json={"text": "NVDA revenue"})

        assert resp.status_code == 503
        assert resp.json()["error"] == "embedding_unavailable"

    @pytest.mark.asyncio
    async def test_instruction_prefix_prepended(self) -> None:
        """The instruction_prefix from settings is prepended to the text before embedding."""
        app = _make_app()

        captured_prompt: list[str] = []

        async def _fake_post(url: str, *, json: dict, **_: Any) -> Any:
            captured_prompt.append(json.get("prompt", ""))
            return _mock_ollama_response(_DUMMY_EMBEDDING)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = _fake_post

        with patch("nlp_pipeline.api.routes.embed.httpx.AsyncClient", return_value=mock_client):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post("/api/v1/embed", json={"text": "TSLA quarterly results"})

        # The default instruction prefix is prepended
        assert len(captured_prompt) == 1
        assert "TSLA quarterly results" in captured_prompt[0]
        # Instruction prefix must be present (default is non-empty)
        assert "Represent this financial document" in captured_prompt[0]
