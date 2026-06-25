"""EmbeddingGemma adapter - google/embeddinggemma-300m on DeepInfra.

Purpose (PLAN-0111 Sub-Plan C / news-routing cascade router)
------------------------------------------------------------
This adapter produces the **classifier input vector** for the news-routing
cascade router. A short news headline (``title + subtitle/lede``) is embedded
once with EmbeddingGemma's task-specific *classification* prompt, then fed to a
small calibrated classifier head that decides the routing *tier* for the
article.

IMPORTANT - this embedding lives in its OWN vector space.
    The router vector is **never** ANN-compared against the BGE retrieval
    vectors (those come from ``DeepInfraEmbeddingAdapter`` /
    ``OllamaEmbeddingAdapter``, 1024-dim, ``BAAI/bge-large-en-v1.5``). Mixing the
    two spaces would be a silent correctness bug. We therefore keep a *separate*
    adapter, model id, and dimensionality (768d native, MRL-truncatable to
    512/256/128) so the two paths can never be confused.

Why a dedicated adapter rather than reusing ``DeepInfraEmbeddingAdapter``?
    - Different model (``google/embeddinggemma-300m``) → different dimension.
    - EmbeddingGemma is **prompt-conditioned**: it expects a task-specific
      prefix (``task: classification | query: {content}`` for classification, or
      ``title: {title} | text: {content}`` for documents/retrieval). Feeding raw
      text without the prefix degrades quality. ``DeepInfraEmbeddingAdapter``
      uses BGE's ``instruction_prefix`` convention, which is a different thing.
    - We expose a *classification-first* API (``embed_for_classification``) plus
      a Matryoshka (MRL) truncation option that the BGE adapter does not need.

Model facts (model card + DeepInfra, verified live 2026-06-12)
    - 300M params, 768-dim output, 2048-token context.
    - Matryoshka Representation Learning (MRL): the 768d vector can be truncated
      to 512 / 256 / 128 and **re-L2-normalized** with graceful quality loss.
      We default to full 768d; the router head can request 256d for a light head.
    - float32 / bfloat16 (NOT float16) - we request ``encoding_format=float``.
    - Cost is trivial (~$0.002 / 1M tokens) and headlines are ~30-60 tokens.

DeepInfra also accepts a server-side ``dimensions`` param (verified: passing
``dimensions=256`` returns a 256-d vector). We nonetheless truncate **client
side** so the renormalization semantics are explicit and deterministic and do
not depend on undocumented provider behaviour.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import httpx
import structlog

from ml_clients.errors import FatalError, RateLimitError, RetryableError, parse_retry_after

if TYPE_CHECKING:
    from observability.metrics import MLMetrics

logger = structlog.get_logger()

_DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"
_DEFAULT_MODEL_ID = "google/embeddinggemma-300m"

# Native output dimension of embeddinggemma-300m.
_NATIVE_DIMENSION = 768

# Valid MRL truncation targets per the model card. The native size (768) is a
# no-op truncation. Anything else must be one of these Matryoshka cut points.
_VALID_MRL_DIMENSIONS = frozenset({768, 512, 256, 128})

# EmbeddingGemma task-specific prompt prefixes (from the model card).
#   - classification: scoring/labelling a single short text (our router use).
#   - document/retrieval: title + body for indexing/retrieval.
_CLASSIFICATION_PREFIX = "task: classification | query: "
_DOCUMENT_PREFIX_TEMPLATE = "title: {title} | text: {content}"

# 2048-token context. A headline+subtitle is ~30-60 tokens, but guard against a
# pathological caller passing a whole article. ~4 chars/token → ~8000 chars is a
# safe ceiling well under the 2048-token limit while never clipping a headline.
_MAX_CHARS = 8000


def _l2_normalize(vector: list[float]) -> list[float]:
    """Return the L2-normalized (unit-norm) copy of *vector*.

    MRL truncation requires re-normalization: slicing a normalized 768d vector to
    256d yields a sub-unit-norm vector, so we must renormalize to restore unit
    norm before cosine comparison. A zero vector is returned unchanged (cannot be
    normalized).
    """
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return vector
    return [component / norm for component in vector]


class EmbeddingGemmaRouterAdapter:
    """EmbeddingGemma-300m client for the news-routing classifier (DeepInfra).

    This is intentionally *not* an ``EmbeddingClient`` (the shared protocol whose
    ``embed()`` returns BGE-shaped ``EmbeddingOutput``): the router consumes raw
    ``list[float]`` vectors in a separate space and needs the
    classification-prompt + MRL semantics that the generic protocol does not
    model. Keeping it off the protocol prevents it from being accidentally wired
    into the BGE retrieval path.

    Args:
        api_key:            DeepInfra API key (NEVER hardcode - injected from
                            settings, e.g. ``NLP_PIPELINE_ROUTER_EMBEDDING_API_KEY``
                            or the shared ``*_DEEPINFRA_API_KEY``).
        model_id:           Model slug (default ``google/embeddinggemma-300m``).
        base_url:           DeepInfra OpenAI-compatible base URL.
        default_dimensions: MRL output size (one of 768/512/256/128). Defaults to
                            the native 768d.
        timeout:            HTTP timeout in seconds (default 30.0). Wrapped in an
                            explicit ``httpx.Timeout`` (BP-235: never rely on the
                            httpx 5s default when an outer ``asyncio.wait_for``
                            may also be in play).
        metrics:            Optional ``MLMetrics`` for latency/cost observation.
    """

    NATIVE_DIMENSION = _NATIVE_DIMENSION

    def __init__(
        self,
        api_key: str,
        model_id: str = _DEFAULT_MODEL_ID,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        default_dimensions: int = _NATIVE_DIMENSION,
        timeout: float = 30.0,
        metrics: MLMetrics | None = None,
    ) -> None:
        if default_dimensions not in _VALID_MRL_DIMENSIONS:
            raise ValueError(
                f"default_dimensions={default_dimensions} is not a valid MRL cut point; "
                f"expected one of {sorted(_VALID_MRL_DIMENSIONS, reverse=True)}."
            )
        self._api_key = api_key
        self._model_id = model_id
        self._base_url = base_url.rstrip("/")
        self._default_dimensions = default_dimensions
        # BP-235: wrap the float timeout in an explicit httpx.Timeout so the
        # 5s httpx default can never silently fire before our intended timeout.
        self._timeout = httpx.Timeout(timeout)
        self._metrics = metrics

    async def embed_for_classification(
        self,
        texts: list[str],
        *,
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed *texts* with the *classification* prompt for the router head.

        Each text is prefixed with ``task: classification | query: `` and the
        whole batch is sent in a single DeepInfra request. Returns one vector per
        input, in input order.

        Args:
            texts:      Short classifier inputs. For the router, pass
                        ``f"{title}\\n{subtitle}"`` per article.
            dimensions: Override the adapter's ``default_dimensions`` for this
                        call (one of 768/512/256/128). ``None`` uses the default.

        Returns:
            ``list[list[float]]`` - one vector per input. If ``dimensions < 768``
            the vectors are MRL-truncated and L2-renormalized to unit norm.

        Raises:
            RetryableError / RateLimitError: 5xx, 429, timeout, or network error.
            FatalError:                      4xx, wrong dimension, or malformed body.
        """
        prefixed = [f"{_CLASSIFICATION_PREFIX}{text}" for text in texts]
        return await self._embed(prefixed, dimensions=dimensions)

    async def embed_documents(
        self,
        documents: list[tuple[str, str]],
        *,
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed (title, content) pairs with the *document/retrieval* prompt.

        Provided for completeness - the router defaults to the classification
        prompt (``embed_for_classification``) because the downstream use is a
        classifier. Each document is formatted as
        ``title: {title} | text: {content}``.
        """
        prefixed = [_DOCUMENT_PREFIX_TEMPLATE.format(title=title, content=content) for title, content in documents]
        return await self._embed(prefixed, dimensions=dimensions)

    async def _embed(self, prepared_texts: list[str], *, dimensions: int | None) -> list[list[float]]:
        """Shared HTTP path: send already-prefixed texts, return (truncated) vectors."""
        if not prepared_texts:
            return []

        target_dim = dimensions if dimensions is not None else self._default_dimensions
        if target_dim not in _VALID_MRL_DIMENSIONS:
            raise FatalError(
                f"Requested dimensions={target_dim} is not a valid MRL cut point; "
                f"expected one of {sorted(_VALID_MRL_DIMENSIONS, reverse=True)}."
            )

        start = time.perf_counter()
        status = "success"
        try:
            texts = [text[:_MAX_CHARS] if len(text) > _MAX_CHARS else text for text in prepared_texts]

            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/embeddings",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self._model_id,
                            "input": texts,
                            # bfloat16/float32 model - request float (NOT float16).
                            "encoding_format": "float",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.TimeoutException as exc:
                raise RetryableError(f"EmbeddingGemma timeout: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    retry_after = parse_retry_after(exc.response.headers)
                    raise RateLimitError(
                        f"EmbeddingGemma rate-limited (429): {exc}",
                        retry_after=retry_after,
                    ) from exc
                if exc.response.status_code >= 500:
                    raise RetryableError(f"EmbeddingGemma 5xx: {exc}") from exc
                raise FatalError(f"EmbeddingGemma 4xx: {exc}") from exc
            except httpx.RequestError as exc:
                raise RetryableError(f"EmbeddingGemma network error: {exc}") from exc

            raw_items: list[dict] = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            if len(raw_items) != len(prepared_texts):
                raise FatalError(f"EmbeddingGemma returned {len(raw_items)} results for {len(prepared_texts)} inputs")

            results: list[list[float]] = []
            for item in raw_items:
                embedding: list[float] = item["embedding"]
                if len(embedding) != _NATIVE_DIMENSION:
                    raise FatalError(
                        f"Unexpected EmbeddingGemma dimension: {len(embedding)} "
                        f"(expected native {_NATIVE_DIMENSION}). Model '{self._model_id}' "
                        f"should return 768-dim vectors before MRL truncation."
                    )
                if target_dim < _NATIVE_DIMENSION:
                    # MRL: keep the first `target_dim` components, then renormalize
                    # to unit norm (slicing breaks the unit norm of the full vector).
                    embedding = _l2_normalize(embedding[:target_dim])
                results.append(embedding)

            logger.info(
                "embeddinggemma_router_batch_ok",
                model_id=self._model_id,
                count=len(results),
                dimensions=target_dim,
            )
            return results
        except (RetryableError, FatalError):
            status = "error"
            raise
        finally:
            if self._metrics:
                latency = time.perf_counter() - start
                self._metrics.ml_api_requests_total.labels(
                    model_id=self._model_id, operation="embed", status=status
                ).inc()
                self._metrics.ml_api_latency_seconds.labels(model_id=self._model_id, operation="embed").observe(latency)
                token_count = sum(len(text.split()) for text in prepared_texts)
                self._metrics.ml_api_tokens_in_total.labels(model_id=self._model_id).inc(token_count)
                # DeepInfra google/embeddinggemma-300m: ~$0.002 per 1M tokens.
                cost = token_count * 0.000000002
                self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=self._model_id).inc(cost)
