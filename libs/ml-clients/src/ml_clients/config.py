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
