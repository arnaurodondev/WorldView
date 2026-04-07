"""HyDE (Hypothetical Document Embedding) expander for the RAG-Chat pipeline (T-E-2-02).

HyDE generates a short hypothetical answer paragraph for vector-intent queries, then
embeds it to improve semantic retrieval quality (see PRD §6.7 Step 4, AD-06).

Only activated for intents where hypothesis embedding meaningfully improves recall:
SIGNAL_INTEL, FACTUAL_LOOKUP, RELATIONSHIP, REASONING.

On any LLM or embedding error the expander degrades gracefully — returning
``(None, None)`` so the pipeline continues with direct query embedding (§9.1).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import structlog

from rag_chat.domain.enums import QueryIntent

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
    from rag_chat.application.ports.embedding import EmbeddingPort
    from rag_chat.application.ports.llm_provider import LlmStreamProvider

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_HYDE_INTENTS: frozenset[QueryIntent] = frozenset(
    {
        QueryIntent.SIGNAL_INTEL,
        QueryIntent.FACTUAL_LOOKUP,
        QueryIntent.RELATIONSHIP,
        QueryIntent.REASONING,
    }
)

_HYDE_TTL_SECONDS = 1800  # 30 minutes

_HYDE_PROMPT_TEMPLATE = (
    "Write a factual 80-120 word answer paragraph as if it appeared in a financial report:\n\n{query}"
)


def _hyde_cache_key(rephrased_query: str) -> str:
    digest = hashlib.sha256(rephrased_query.encode()).hexdigest()
    return f"rag:v1:hyde:{digest}"


class HydeExpander:
    """Generate and cache a hypothetical document embedding for eligible intents.

    Args:
        llm_provider:     Streaming LLM used to generate the hypothesis paragraph.
        embedding_client: Embedding backend (S6 HTTP adapter post Wave E-3).
        valkey:           Async Redis/Valkey client for 30-minute hypothesis cache.
    """

    def __init__(
        self,
        llm_provider: LlmStreamProvider,
        embedding_client: EmbeddingPort,
        valkey: ValkeyClient,  # type: ignore[name-defined]
    ) -> None:
        self._llm = llm_provider
        self._embedder = embedding_client
        self._valkey = valkey

    async def expand(
        self,
        rephrased_query: str,
        intent: QueryIntent,
    ) -> tuple[str | None, list[float] | None]:
        """Return ``(hypothesis_text, hypothesis_embedding)`` or ``(None, None)``.

        Returns ``(None, None)`` when:
        - *intent* is not in the HyDE-eligible set (FINANCIAL_DATA, COMPARISON, PORTFOLIO)
        - Any LLM or embedding error occurs (graceful degradation per §9.1)
        """
        if intent not in _HYDE_INTENTS:
            return None, None

        cache_key = _hyde_cache_key(rephrased_query)
        try:
            cached: str | None = await self._valkey.get(cache_key)
            if cached is not None:
                data = json.loads(cached)
                return data["text"], data["embedding"]

            # Generate hypothesis paragraph
            prompt = _HYDE_PROMPT_TEMPLATE.format(query=rephrased_query)
            hypothesis = ""
            async for chunk in self._llm.stream(prompt, max_tokens=200, temperature=0.1):
                hypothesis += chunk
            hypothesis = hypothesis.strip()

            if not hypothesis:
                return None, None

            # Embed the hypothesis
            embedding: list[float] = await self._embedder.embed(hypothesis)

            # Cache for 30 minutes
            await self._valkey.setex(
                cache_key,
                _HYDE_TTL_SECONDS,
                json.dumps({"text": hypothesis, "embedding": embedding}),
            )
            return hypothesis, embedding

        except Exception:
            log.warning(  # type: ignore[no-any-return]
                "hyde_expansion_failed",
                intent=intent,
                query_len=len(rephrased_query),
            )
            return None, None
