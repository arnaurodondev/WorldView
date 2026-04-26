"""Embed endpoint — expose embedding generation to downstream services (S8/rag-chat).

Endpoint:
  POST /api/v1/embed   → compute a text embedding via Ollama bge-large

This endpoint is called by rag-chat's _S6EmbeddingAdapter on every chat request
(HyDE generation + direct query embedding).  Without it, RAG retrieval returns
zero chunks because the query_embedding field in POST /api/v1/search/chunks is
always None.

Architecture note:
  The nlp-pipeline API process does NOT hold an ml_clients EmbeddingClient in
  app.state — that object lives in the separate article_consumer_main process.
  This endpoint instantiates a lightweight per-request Ollama HTTP call instead,
  matching the same truncation and model-id logic used by OllamaEmbeddingAdapter
  in libs/ml-clients.

Protected app-wide by InternalJWTMiddleware (PRD-0025). No per-route auth needed.
"""

from __future__ import annotations

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["embed"])
_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# BGE-large BERT context window = 512 tokens.  Matches OllamaEmbeddingAdapter._MAX_WORDS
# so the API and consumer embeddings are produced by identical pre-processing.
_MAX_WORDS = 384

# Default Ollama embedding timeout — generous because Ollama may be warming up on
# first request and we'd rather wait than return an empty embedding.
_OLLAMA_TIMEOUT = 30.0

# Instruction prefix applied by the consumer worker (Block 7).  The API uses the same
# prefix so query embeddings land in the same semantic space as stored chunk embeddings.
_DEFAULT_INSTRUCTION_PREFIX = "Represent this financial document passage for retrieval: "


class EmbedRequest(BaseModel):
    """Request body for POST /api/v1/embed."""

    text: str = Field(..., min_length=1, description="Text to embed (required).")
    model: str | None = Field(
        default=None,
        description="Optional Ollama model name override.  Defaults to settings.embedding_model_id.",
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
    """Compute a text embedding via Ollama and return the vector.

    Called by rag-chat's _S6EmbeddingAdapter on every chat request:
      - HyDE hypothesis generation then embedding of the hypothesis
      - Direct query embedding when HyDE is skipped or fails

    The endpoint mirrors OllamaEmbeddingAdapter (libs/ml-clients) exactly:
      1. Prepend the instruction prefix (same as Block 7 consumer).
      2. Truncate to _MAX_WORDS to avoid BERT context overflow.
      3. POST to Ollama /api/embeddings.
      4. Return the 1024-dim float vector.

    Returns 503 when Ollama is unreachable so rag-chat can degrade gracefully.
    """
    from nlp_pipeline.config import Settings

    settings: Settings = request.app.state.settings

    # Resolve model: use caller's override if provided, else the service setting.
    model_id = body.model or settings.embedding_model_id

    # Build text with instruction prefix — must match Block 7 / OllamaEmbeddingAdapter.
    instruction_prefix: str = settings.embedding_instruction_prefix
    full_text = f"{instruction_prefix} {body.text}" if instruction_prefix else body.text

    # Truncate to token limit — same word-count approximation as OllamaEmbeddingAdapter.
    words = full_text.split()
    if len(words) > _MAX_WORDS:
        full_text = " ".join(words[:_MAX_WORDS])

    ollama_url = settings.ollama_base_url.rstrip("/")

    _log.debug("embed_request", model=model_id, text_len=len(full_text))  # type: ignore[no-any-return]

    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT) as client:
            resp = await client.post(
                f"{ollama_url}/api/embeddings",
                json={"model": model_id, "prompt": full_text},
            )
            resp.raise_for_status()
            data: dict = resp.json()
            embedding: list[float] = data["embedding"]
    except httpx.TimeoutException:
        _log.warning("embed_ollama_timeout", model=model_id)  # type: ignore[no-any-return]
        # 503 so rag-chat degrades gracefully (returns empty embedding) instead of 500.
        return JSONResponse(status_code=503, content={"error": "embedding_timeout"})
    except httpx.HTTPStatusError as exc:
        _log.warning(  # type: ignore[no-any-return]
            "embed_ollama_http_error",
            model=model_id,
            status=exc.response.status_code,
        )
        return JSONResponse(status_code=503, content={"error": "embedding_unavailable"})
    except (TimeoutError, httpx.RequestError, KeyError, ValueError) as exc:
        _log.warning("embed_request_error", model=model_id, error=str(exc))  # type: ignore[no-any-return]
        return JSONResponse(status_code=503, content={"error": "embedding_unavailable"})

    _log.info("embed_ok", model=model_id, dimensions=len(embedding))  # type: ignore[no-any-return]
    return EmbedResponse(embedding=embedding, model=model_id, dimensions=len(embedding))
