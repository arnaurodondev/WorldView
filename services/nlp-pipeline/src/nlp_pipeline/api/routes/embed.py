"""Embed endpoint — expose embedding generation to downstream services (S8/rag-chat).

Endpoint:
  POST /api/v1/embed   → compute a text embedding via the configured provider

This endpoint is called by rag-chat's _S6EmbeddingAdapter on every chat request
(HyDE generation + direct query embedding).  Without it, RAG retrieval returns
zero chunks because the query_embedding field in POST /api/v1/search/chunks is
always None.

Embedding provider selection:
  The provider is controlled by NLP_PIPELINE_EMBEDDING_PROVIDER (and its related
  API key/model env vars).  The embedding_client is instantiated once in the
  lifespan (app.py) and stored on app.state.embedding_client.  Switching providers
  here automatically applies to both ingestion (article consumer) and queries, so
  ingestion and query embeddings always share the same vector space.

  "ollama"    → local bge-large via OllamaEmbeddingAdapter (default)
  "deepinfra" → BAAI/bge-large-en-v1.5 on DeepInfra GPU (~50-150ms)
  "jina"      → jina-embeddings-v3 on Jina AI REST API (~100-300ms)

Protected app-wide by InternalJWTMiddleware (PRD-0025). No per-route auth needed.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["embed"])
_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# BGE-large BERT context window = 512 tokens. Character-based truncation to match
# OllamaEmbeddingAdapter._MAX_CHARS -- ensures query embeddings use the same
# pre-processing as stored chunk embeddings (both 1500-char limit).
_MAX_CHARS = 1500

# Instruction prefix applied by the consumer worker (Block 7).  The API uses the same
# prefix so query embeddings land in the same semantic space as stored chunk embeddings.
_DEFAULT_INSTRUCTION_PREFIX = "Represent this financial document passage for retrieval: "


class EmbedRequest(BaseModel):
    """Request body for POST /api/v1/embed."""

    text: str = Field(..., min_length=1, description="Text to embed (required).")
    model: str | None = Field(
        default=None,
        description="Optional model name override.  Defaults to the configured embedding model.",
    )


class EmbedResponse(BaseModel):
    """Response from POST /api/v1/embed."""

    embedding: list[float]
    model: str
    dimensions: int


@router.post("/embed", response_model=EmbedResponse)
async def embed_text(
    body: EmbedRequest,
    request: Request,
) -> EmbedResponse | JSONResponse:
    """Compute a text embedding via the configured provider and return the vector.

    Called by rag-chat's _S6EmbeddingAdapter on every chat request:
      - HyDE hypothesis generation then embedding of the hypothesis
      - Direct query embedding when HyDE is skipped or fails

    The endpoint applies the same pre-processing as the article consumer (Block 7):
      1. Prepend the instruction prefix (same as OllamaEmbeddingAdapter / DeepInfraEmbeddingAdapter).
      2. Truncate to _MAX_CHARS to avoid BERT context overflow.
      3. Delegate to app.state.embedding_client (provider-agnostic).
      4. Return the 1024-dim float vector.

    Returns 503 when the embedding provider is unreachable so rag-chat degrades gracefully.
    """
    from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]
    from ml_clients.errors import FatalError, RetryableError  # type: ignore[import-not-found]

    from nlp_pipeline.config import Settings

    settings: Settings = request.app.state.settings

    # Resolve instruction prefix from settings (same value used by the consumer).
    instruction_prefix: str = settings.embedding_instruction_prefix

    # Build text with instruction prefix — must match Block 7 / consumer worker.
    full_text = f"{instruction_prefix} {body.text}" if instruction_prefix else body.text

    # Truncate to character limit -- matches OllamaEmbeddingAdapter / DeepInfraEmbeddingAdapter._MAX_CHARS.
    # 1500 chars ~= 500 tokens for financial text (2.0-2.2 tok/word); safe under 512.
    if len(full_text) > _MAX_CHARS:
        full_text = full_text[:_MAX_CHARS]

    _log.debug("embed_request", provider=settings.embedding_provider, text_len=len(full_text))  # type: ignore[no-any-return]

    # Retrieve the pre-built embedding client from app.state (created in lifespan).
    embedding_client = request.app.state.embedding_client

    try:
        outputs = await embedding_client.embed(
            # instruction_prefix=None: we already prepended the prefix to full_text above.
            # Passing None (falsy) prevents the adapter from prepending it a second time.
            [EmbeddingInput(text=full_text, model_id=settings.embedding_model_id, instruction_prefix=None)]
        )
    except RetryableError as exc:
        _log.warning("embed_retryable_error", error=str(exc))  # type: ignore[no-any-return]
        return JSONResponse(status_code=503, content={"error": "embedding_unavailable"})
    except FatalError as exc:
        _log.error("embed_fatal_error", error=str(exc))  # type: ignore[no-any-return]
        return JSONResponse(status_code=503, content={"error": "embedding_unavailable"})
    except Exception as exc:
        _log.error("embed_unexpected_error", error=str(exc))  # type: ignore[no-any-return]
        return JSONResponse(status_code=503, content={"error": "embedding_unavailable"})

    if not outputs:
        return JSONResponse(status_code=503, content={"error": "embedding_unavailable"})

    embedding = outputs[0].embedding
    model_id = outputs[0].model_id

    _log.info("embed_ok", provider=settings.embedding_provider, model=model_id, dimensions=len(embedding))  # type: ignore[no-any-return]
    return EmbedResponse(embedding=embedding, model=model_id, dimensions=len(embedding))
