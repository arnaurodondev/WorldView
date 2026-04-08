"""Ollama embedding adapter — bge-large-en-v1.5 (1024-dim)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import structlog

from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput
from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    import asyncio

logger = structlog.get_logger()


class OllamaEmbeddingAdapter:
    """Implements EmbeddingClient via Ollama REST API. Model: bge-large-en-v1.5 (1024-dim)."""

    EXPECTED_DIMENSION = 1024
    MODEL_ID = "bge-large-en-v1.5"

    # BGE-large BERT context window = 512 tokens.  Word-count approximation:
    # financial text tokenises at ~1.3 tokens/word (wordpiece, dense on digits).
    # 384 words * 1.3 ~= 499 tokens — safely under 512 and avoids the
    # GGML_ASSERT crash (i01 >= ne01) in llama.cpp when the position-embedding
    # matrix index goes out of bounds.
    _MAX_WORDS = 384

    def __init__(self, base_url: str, model_id: str, semaphore: asyncio.Semaphore) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._semaphore = semaphore

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        results: list[EmbeddingOutput] = []
        for inp in inputs:
            async with self._semaphore:
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        text = f"{inp.instruction_prefix} {inp.text}" if inp.instruction_prefix else inp.text
                        # Truncate to stay within the model's 512-token context window
                        # using word count as an approximation (1.3 tokens/word).
                        words = text.split()
                        if len(words) > self._MAX_WORDS:
                            text = " ".join(words[: self._MAX_WORDS])
                        resp = await client.post(
                            f"{self._base_url}/api/embeddings",
                            json={"model": self._model_id, "prompt": text},
                        )
                        resp.raise_for_status()
                        embedding: list[float] = resp.json()["embedding"]
                        if len(embedding) != self.EXPECTED_DIMENSION:
                            raise FatalError(
                                f"Unexpected embedding dimension: {len(embedding)} (expected {self.EXPECTED_DIMENSION})"
                            )
                        results.append(
                            EmbeddingOutput(
                                embedding=embedding,
                                model_id=self._model_id,
                                dimension=len(embedding),
                            )
                        )
                        logger.info(
                            "embedding_generated",
                            model_id=self._model_id,
                            dimension=len(embedding),
                        )
                except httpx.TimeoutException as exc:
                    raise RetryableError(f"Ollama embedding timeout: {exc}") from exc
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code >= 500:
                        raise RetryableError(f"Ollama 5xx: {exc}") from exc
                    raise FatalError(f"Ollama 4xx: {exc}") from exc
                except FatalError:
                    raise
                except RetryableError:
                    raise
                except Exception as exc:
                    raise FatalError(f"Unexpected embedding error: {exc}") from exc
        return results
