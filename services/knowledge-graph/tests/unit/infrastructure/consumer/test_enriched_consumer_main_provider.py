"""Unit tests for embedding provider selection in enriched_consumer_main.

Regression guard for the 2026-07-06 Ollama drop: the enriched consumer used to
hardcode ``OllamaEmbeddingAdapter`` ("required — exits if unavailable"), which
made the KG enrichment hot path depend on a local Ollama server. It now honours
``KNOWLEDGE_GRAPH_EMBEDDING_PROVIDER`` via ``_build_embedding_adapter`` so prod
(deepinfra) runs without Ollama. Both providers return 1024-dim bge-large.
"""

from __future__ import annotations

import pytest
from knowledge_graph.config import Settings
from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer_main import (
    _build_embedding_adapter,
)

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
        "database_url_read": "",
        "storage_access_key": "test",
        "storage_secret_key": "test",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestEnrichedConsumerEmbeddingProviderSelection:
    @pytest.mark.unit
    def test_deepinfra_selected_when_provider_and_key_set(self) -> None:
        """provider=deepinfra + api_key → DeepInfraEmbeddingAdapter, DeepInfra model id."""
        s = _settings(embedding_provider="deepinfra", embedding_api_key="real-key")

        adapter, model_id = _build_embedding_adapter(s)

        assert type(adapter).__name__ == "DeepInfraEmbeddingAdapter"
        assert type(adapter).__module__ == "ml_clients.adapters.deepinfra_embedding"
        assert model_id == "BAAI/bge-large-en-v1.5"
        # Must match the vector(1024) column so DeepInfra vectors are drop-in.
        assert adapter.EXPECTED_DIMENSION == 1024

    @pytest.mark.unit
    def test_falls_back_to_ollama_when_provider_default(self) -> None:
        """Default provider (ollama) → OllamaEmbeddingAdapter, Ollama model id."""
        s = _settings()  # embedding_provider defaults to "ollama"

        adapter, model_id = _build_embedding_adapter(s)

        assert type(adapter).__name__ == "OllamaEmbeddingAdapter"
        assert model_id == "bge-large:latest"

    @pytest.mark.unit
    def test_falls_back_to_ollama_when_deepinfra_key_missing(self) -> None:
        """provider=deepinfra but empty key → Ollama fallback (never a hard crash)."""
        s = _settings(embedding_provider="deepinfra", embedding_api_key="")

        adapter, _model_id = _build_embedding_adapter(s)

        assert type(adapter).__name__ == "OllamaEmbeddingAdapter"
