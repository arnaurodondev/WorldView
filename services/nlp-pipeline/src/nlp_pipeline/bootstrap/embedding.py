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


def current_embedding_model_ids(settings: Settings) -> list[str]:
    """The set of ``model_id`` labels that denote the CURRENTLY configured model.

    A single physical embedding model is written under DIFFERENT ``model_id``
    labels depending on which provider produced the vector:

      * ``deepinfra`` writes ``settings.embedding_api_model_id`` (e.g.
        ``"BAAI/bge-large-en-v1.5"``) — see :func:`build_embedding_client` and
        ``embedding_retry_worker_main``.
      * ``ollama`` / the ``POST /api/v1/embed`` endpoint write
        ``settings.embedding_model_id`` (e.g. ``"bge-large"``).

    Both labels name the SAME 1024-dim bge-large model, so BOTH are "current".
    ``_expire_stale_embeddings`` must treat the whole set as current: comparing
    against only ``embedding_model_id`` flagged every DeepInfra-written row
    (~half the live corpus) as stale, which is the PRE-1 boot timeout root cause
    (the UPDATE tried to expire ~13k rows, each forcing an HNSW re-insert, and
    ran past the 10-min statement_timeout on every boot).

    A GENUINELY different model (e.g. switching to ``embeddinggemma-300m`` or
    ``jina-embeddings-v3``) carries a label in NEITHER config field, so its old
    vectors are still correctly expired once both config values are updated.

    Empty strings are dropped (unset optional labels must not match every row's
    NULL-ish/empty ``model_id``). The list is sorted for deterministic SQL params
    and log output.
    """
    return sorted({settings.embedding_model_id, settings.embedding_api_model_id} - {""})


def build_embedding_client(settings: Settings) -> Any:
    """Instantiate the embedding adapter selected by ``settings.embedding_provider``.

    Returns a client exposing ``embed(inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]``.
    The Ollama fallback (used when the chosen provider is misconfigured) wraps a
    :class:`asyncio.Semaphore` of size 1 to serialise local inference.
    """
    provider = settings.embedding_provider.lower()
    _embedding_api_key = settings.embedding_api_key.get_secret_value()  # DEF-019
    if provider == "deepinfra" and _embedding_api_key:
        from ml_clients.adapters.deepinfra_embedding import (  # type: ignore[import-not-found]
            DeepInfraEmbeddingAdapter,
        )

        return DeepInfraEmbeddingAdapter(
            api_key=_embedding_api_key,
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
    _jina_api_key = settings.jina_api_key.get_secret_value()  # DEF-019
    if provider == "jina" and _jina_api_key:
        from ml_clients.adapters.jina_embedding import JinaEmbeddingAdapter  # type: ignore[import-not-found]

        return JinaEmbeddingAdapter(api_key=_jina_api_key)

    from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter  # type: ignore[import-not-found]

    return OllamaEmbeddingAdapter(
        base_url=settings.ollama_base_url,
        model_id=settings.embedding_model_id,
        semaphore=asyncio.Semaphore(1),
    )
