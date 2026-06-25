"""ML clients configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class MLClientsSettings(BaseSettings):
    model_config = {"env_prefix": ""}  # No prefix — shared across services

    ollama_base_url: str = "http://ollama:11434"
    embedding_model_id: str = "bge-large-en-v1.5"
    extraction_model_id: str = "qwen2.5:7b-instruct"
    ner_model_path: str = "urchade/gliner_large-v2.1"
    max_ollama_concurrent: int = 4  # asyncio.Semaphore value

    # Task #36: SECONDARY deep-extraction model used when the PRIMARY (configured by
    # the service, e.g. Qwen3-235B) returns HTTP 429 (rate-limit / engine_overloaded)
    # or persistently fails.  Verified DeepInfra slug: ``deepseek-ai/DeepSeek-V4-Flash``
    # (OpenAI-compatible, accepts the same JSON-mode extraction request).  Empty =
    # fallback disabled (behaviour unchanged: exhaust the primary's retries then raise).
    # Env: ML_CLIENTS_EXTRACTION_FALLBACK_MODEL_ID
    extraction_fallback_model_id: str = ""

    # News-routing cascade router embedding (PLAN-0111 Sub-Plan C).
    # EmbeddingGemma lives in its OWN vector space (classifier input only) — it is
    # NEVER ANN-compared against the BGE retrieval vectors. The API key is read
    # from the environment, never hardcoded.
    router_embedding_model_id: str = "google/embeddinggemma-300m"
    router_embedding_base_url: str = "https://api.deepinfra.com/v1/openai"
    router_embedding_dimensions: int = 768  # MRL cut point: 768/512/256/128
    router_embedding_api_key: str = ""  # injected via env (e.g. *_DEEPINFRA_API_KEY)
