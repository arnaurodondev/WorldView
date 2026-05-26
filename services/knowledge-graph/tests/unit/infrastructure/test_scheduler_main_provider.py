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

    @pytest.mark.unit()
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

    @pytest.mark.unit()
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
        # SecretStr migration: compare unwrapped value, not the SecretStr wrapper.
        assert s.embedding_api_key.get_secret_value() == ""

    @pytest.mark.unit()
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

    @pytest.mark.unit()
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

    @pytest.mark.unit()
    def test_deepinfra_extraction_config_fields_present(self) -> None:
        """Config has all four DeepInfra extraction fields with correct defaults."""
        from knowledge_graph.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
        )
        assert s.deepinfra_api_key.get_secret_value() == ""  # SecretStr migration
        assert s.deepinfra_extraction_model_id == "Qwen/Qwen3-235B-A22B-Instruct-2507"
        assert s.deepinfra_extraction_base_url == "https://api.deepinfra.com/v1/openai"
        assert s.deepinfra_extraction_concurrency == 5

    @pytest.mark.unit()
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
        assert s.deepinfra_api_key.get_secret_value() == "test-extraction-key"  # SecretStr migration
        assert s.deepinfra_extraction_model_id == "deepseek-ai/DeepSeek-V4-Flash"
        assert s.deepinfra_extraction_concurrency == 3


class TestBuildDescriptionClientDeepInfra:
    """Tests for _build_description_client() with DeepInfra provider (BP-092 regression guard)."""

    @pytest.mark.unit()
    def test_deepinfra_provider_returns_chained_adapter_with_deepinfra_primary(self) -> None:
        """description_provider='deepinfra' → ChainedDescriptionAdapter with DeepInfra as first adapter.

        Since the description client now supports a Gemini fallback, _build_description_client
        returns a ChainedDescriptionAdapter.  When only DEEPINFRA_API_KEY is set (no Gemini
        key), the chain contains a single DeepInfraDescriptionAdapter as the primary.
        """
        from unittest.mock import MagicMock, patch

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

            # Now returns ChainedDescriptionAdapter wrapping DeepInfra (+ optional Gemini)
            assert type(client).__name__ == "ChainedDescriptionAdapter"
            assert type(client).__module__ == "ml_clients.adapters.chained_description"
            # Primary adapter in the chain must be DeepInfraDescriptionAdapter
            primary = client._adapters[0]  # type: ignore[attr-defined]
            assert type(primary).__name__ == "DeepInfraDescriptionAdapter"

    @pytest.mark.unit()
    def test_deepinfra_provider_empty_key_returns_null_adapter(self) -> None:
        """description_provider='deepinfra' + BOTH keys empty → NullDescriptionAdapter (fail-safe).

        PLAN-0095 W4 T-W4-03 added a Gemini fallback when the DeepInfra key is empty.
        This test pins the terminal Null case: DeepInfra empty AND Gemini empty.
        See test_deepinfra_empty_key_falls_back_to_gemini for the new fallback path.
        """
        from knowledge_graph.config import Settings
        from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
            description_provider="deepinfra",
            deepinfra_api_key="",  # empty → no DeepInfra
            gemini_api_key="",  # empty → no Gemini fallback either
        )
        client = _build_description_client(s)

        assert type(client).__name__ == "NullDescriptionAdapter"

    @pytest.mark.unit()
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

    @pytest.mark.unit()
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
        # F-A04: fallback aligned to Meta-Llama-3.1-8B-Instruct-Turbo per ADR-0073-006.
        # Qwen/Qwen3-32B is not on the project's DeepInfra account allow-list.
        assert s.description_deepinfra_fallback_model_id == "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
        assert s.description_deepinfra_concurrency == 4


class TestBuildDescriptionClientFallbacksPLAN0095W4:
    """PLAN-0095 W4 T-W4-03 — cross-provider key fallback behaviour.

    The audit found that ``DefinitionRefreshWorker`` produced 59.5% NULL
    company descriptions because the deployed env had
    ``description_provider=gemini`` but the Gemini key was unset and
    ``_build_description_client`` went straight to ``NullDescriptionAdapter``
    instead of cascading to the available DeepInfra key.  These tests pin the
    new cascading behaviour in both directions so a future refactor cannot
    silently re-introduce the same gap.
    """

    @pytest.mark.unit()
    def test_definition_refresh_falls_back_to_deepinfra_when_gemini_unset(self) -> None:
        """provider='gemini' + GEMINI key empty + DEEPINFRA key set → DeepInfra chain.

        This is the canonical T-W4-03 acceptance test from the plan: when
        operators set the Gemini provider but the Gemini secret is rotated /
        absent, we must still emit descriptions via DeepInfra rather than
        falling silently to the deterministic stub.
        """
        from unittest.mock import MagicMock, patch

        # openai SDK is imported lazily inside DeepInfraDescriptionAdapter; mock
        # it so the test runs without network or pip-install requirements.
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
                description_provider="gemini",
                gemini_api_key="",  # empty → must cascade to DeepInfra
                deepinfra_api_key="real-deepinfra-key",
            )
            client = _build_description_client(s)

            # Cascade returns a ChainedDescriptionAdapter whose first (only)
            # adapter is the DeepInfra one — NOT NullDescriptionAdapter.
            assert type(client).__name__ == "ChainedDescriptionAdapter"
            primary = client._adapters[0]  # type: ignore[attr-defined]
            assert type(primary).__name__ == "DeepInfraDescriptionAdapter"

    @pytest.mark.unit()
    def test_deepinfra_provider_empty_key_falls_back_to_gemini(self) -> None:
        """provider='deepinfra' + DEEPINFRA key empty + GEMINI key set → Gemini chain.

        Symmetric to the above: if the operator picked DeepInfra but its key
        is missing, fall through to Gemini if that key IS configured.
        """
        from knowledge_graph.config import Settings
        from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
            description_provider="deepinfra",
            deepinfra_api_key="",
            gemini_api_key="real-gemini-key",
        )
        client = _build_description_client(s)

        assert type(client).__name__ == "ChainedDescriptionAdapter"
        primary = client._adapters[0]  # type: ignore[attr-defined]
        assert type(primary).__name__ == "GeminiDescriptionAdapter"

    @pytest.mark.unit()
    def test_gemini_provider_with_both_keys_unset_returns_null(self) -> None:
        """provider='gemini' + both keys empty → NullDescriptionAdapter (terminal fail-safe)."""
        from knowledge_graph.config import Settings
        from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client

        s = Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
            database_url_read="",
            storage_access_key="test",
            storage_secret_key="test",
            description_provider="gemini",
            gemini_api_key="",
            deepinfra_api_key="",
        )
        client = _build_description_client(s)

        assert type(client).__name__ == "NullDescriptionAdapter"
