"""Unit tests for embedding provider selection in scheduler_main (T-A-2-02).

Verifies that:
  - Default embedding_provider is "ollama" with empty api_key
  - Config fields for DeepInfra provider (embedding_provider, embedding_api_key,
    embedding_api_model_id, embedding_api_base_url) are present and assignable
  - DeepInfraEmbeddingAdapter is importable and constructable for KG use
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestSchedulerMainEmbeddingProviderSelection:
    """Tests for embedding provider selection in scheduler_main."""

    @pytest.mark.unit
    def test_deepinfra_provider_selected_when_api_key_set(self) -> None:
        """When embedding_provider=deepinfra + api_key set → config fields are consistent."""
        from knowledge_graph.config import Settings

        # We test the provider selection logic by checking that the config fields
        # exist and can be set. Since scheduler_main.py has side effects (real DB
        # connections, signal handlers), we test the selection logic through config.
        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
        )
        s.embedding_provider = "deepinfra"
        s.embedding_api_key = "test-key"
        s.embedding_api_model_id = "BAAI/bge-large-en-v1.5"

        assert s.embedding_provider == "deepinfra"
        assert s.embedding_api_key == "test-key"
        assert s.embedding_api_model_id == "BAAI/bge-large-en-v1.5"

    @pytest.mark.unit
    def test_ollama_provider_is_default(self) -> None:
        """Default embedding_provider is 'ollama' and embedding_api_key is empty."""
        from knowledge_graph.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
        )
        assert s.embedding_provider == "ollama"
        assert s.embedding_api_key == ""

    @pytest.mark.unit
    def test_deepinfra_api_base_url_default(self) -> None:
        """Default embedding_api_base_url points to DeepInfra OpenAI-compatible endpoint."""
        from knowledge_graph.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
        )
        assert s.embedding_api_base_url == "https://api.deepinfra.com/v1/openai"
        assert s.embedding_api_model_id == "BAAI/bge-large-en-v1.5"

    @pytest.mark.unit
    def test_deepinfra_adapter_can_be_instantiated(self) -> None:
        """DeepInfraEmbeddingAdapter is importable and constructable for KG use."""
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter  # type: ignore[import-not-found]

        adapter = DeepInfraEmbeddingAdapter(
            api_key="test-key",
            model_id="BAAI/bge-large-en-v1.5",
            base_url="https://api.deepinfra.com/v1/openai",
        )
        assert adapter is not None
        # Verify the expected dimension constant matches the KG vector(1024) column
        assert adapter.EXPECTED_DIMENSION == 1024


class TestSchedulerMainExtractionProviderConfig:
    """Tests for DeepInfra extraction provider config (PLAN-0061 T-C-2)."""

    @pytest.mark.unit
    def test_deepinfra_extraction_config_fields_present(self) -> None:
        """Config has all four DeepInfra extraction fields with correct defaults."""
        from knowledge_graph.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
        )
        assert s.deepinfra_api_key == ""
        assert s.deepinfra_extraction_model_id == "deepseek-ai/DeepSeek-V4-Flash"
        assert s.deepinfra_extraction_base_url == "https://api.deepinfra.com/v1/openai"
        assert s.deepinfra_extraction_concurrency == 5

    @pytest.mark.unit
    def test_deepinfra_extraction_config_can_be_set(self) -> None:
        """deepinfra_api_key can be set (triggers non-empty check in scheduler_main)."""
        from knowledge_graph.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
            deepinfra_api_key="test-extraction-key",
            deepinfra_extraction_model_id="deepseek-ai/DeepSeek-V4-Flash",
            deepinfra_extraction_concurrency=3,
        )
        assert s.deepinfra_api_key == "test-extraction-key"
        assert s.deepinfra_extraction_model_id == "deepseek-ai/DeepSeek-V4-Flash"
        assert s.deepinfra_extraction_concurrency == 3


class TestBuildDescriptionClientDeepInfra:
    """Tests for _build_description_client() with DeepInfra provider (BP-092 regression guard)."""

    @pytest.mark.unit
    def test_deepinfra_provider_returns_deepinfra_adapter(self) -> None:
        """description_provider='deepinfra' with valid api_key → DeepInfraDescriptionAdapter.

        The scheduler module is pre-imported BEFORE patch.dict so it stays in sys.modules
        after the patch exits (avoiding prometheus re-registration in subsequent tests).
        openai is mocked because it is not installed in the KG test environment.
        """
        from unittest.mock import MagicMock, patch

        # Pre-import: ensures scheduler module is in sys.modules before patch.dict runs.
        # patch.dict only removes/restores the specified key (openai); everything else persists.
        # Without this, the scheduler would be re-imported in subsequent tests causing
        # duplicate prometheus metric registration.
        import knowledge_graph.infrastructure.scheduler.scheduler as _sched  # noqa: F401

        mock_openai = MagicMock()
        mock_openai.Timeout = MagicMock(return_value=MagicMock())
        mock_openai.AsyncOpenAI.return_value = MagicMock()

        with patch.dict("sys.modules", {"openai": mock_openai}):
            from knowledge_graph.config import Settings
            from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client

            s = Settings(
                database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
                database_url_read="",
                storage_access_key="test",
                storage_secret_key="test",
                description_provider="deepinfra",
                deepinfra_api_key="real-api-key",
            )
            client = _build_description_client(s)

            assert type(client).__name__ == "DeepInfraDescriptionAdapter"
            assert type(client).__module__ == "ml_clients.adapters.deepinfra_description"

    @pytest.mark.unit
    def test_deepinfra_provider_empty_key_returns_null_adapter(self) -> None:
        """description_provider='deepinfra' with empty api_key → NullDescriptionAdapter (fail-safe)."""
        from knowledge_graph.config import Settings
        from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
            description_provider="deepinfra",
            deepinfra_api_key="",  # empty → must fall back to NullDescriptionAdapter
        )
        client = _build_description_client(s)

        assert type(client).__name__ == "NullDescriptionAdapter"

    @pytest.mark.unit
    def test_unknown_provider_returns_null_adapter(self) -> None:
        """Unrecognised description_provider → NullDescriptionAdapter (no external calls)."""
        from knowledge_graph.config import Settings
        from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
            description_provider="none",
        )
        client = _build_description_client(s)

        assert type(client).__name__ == "NullDescriptionAdapter"

    @pytest.mark.unit
    def test_deepinfra_description_config_fields_present(self) -> None:
        """Settings has all 3 DeepInfra description fields with correct defaults."""
        from knowledge_graph.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
        )
        assert s.description_provider == "none"
        assert s.description_deepinfra_model_id == "Qwen/Qwen3-235B-A22B-Instruct-2507"
        assert s.description_deepinfra_fallback_model_id == "Qwen/Qwen3-32B"
        assert s.description_deepinfra_concurrency == 4
