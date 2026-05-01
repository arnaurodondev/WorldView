"""Single source of truth for embedding-client construction.

PLAN-0057 QA A-004: previously this provider-selection logic was duplicated
in ``nlp_pipeline.app:_build_embedding_client`` AND
``nlp_pipeline.workers.embedding_retry_worker_main:_build_embedding_client``.
The two copies had to be kept in sync as new providers landed (Groq, OpenAI,
Jina, …) — exactly the kind of silent drift the audit was meant to eliminate.

Both call sites now import :func:`build_embedding_client` from here.

Provider selection is driven by :attr:`Settings.embedding_provider`:
  * ``"deepinfra"`` (with ``embedding_api_key``) → DeepInfra-hosted bge-large
  * ``"jina"`` (with ``jina_api_key``)            → Jina cloud embeddings
  * ``"ollama"`` / default / any fallback         → local Ollama bge-large

The Ollama fallback uses ``Semaphore(1)`` because both the API process and
the standalone worker share a single Ollama instance — concurrent embed
requests slow each other down on CPU inference.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nlp_pipeline.config import Settings


def build_embedding_client(settings: Settings) -> Any:
    """Instantiate the embedding adapter selected by ``settings.embedding_provider``.

    Returns a client exposing ``embed(inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]``.
    The Ollama fallback (used when the chosen provider is misconfigured) wraps a
    :class:`asyncio.Semaphore` of size 1 to serialise local inference.
    """
    provider = settings.embedding_provider.lower()
    if provider == "deepinfra" and settings.embedding_api_key:
        from ml_clients.adapters.deepinfra_embedding import (  # type: ignore[import-not-found]
            DeepInfraEmbeddingAdapter,
        )

        return DeepInfraEmbeddingAdapter(
            api_key=settings.embedding_api_key,
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
    if provider == "jina" and settings.jina_api_key:
        from ml_clients.adapters.jina_embedding import JinaEmbeddingAdapter  # type: ignore[import-not-found]

        return JinaEmbeddingAdapter(api_key=settings.jina_api_key)

    from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter  # type: ignore[import-not-found]

    return OllamaEmbeddingAdapter(
        base_url=settings.ollama_base_url,
        model_id=settings.embedding_model_id,
        semaphore=asyncio.Semaphore(1),
    )
