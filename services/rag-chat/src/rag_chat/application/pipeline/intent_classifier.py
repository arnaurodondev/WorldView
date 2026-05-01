"""Intent classifier for the RAG-Chat pipeline (T-E-2-01).

Three-tier classification strategy:
  1. ``DeepInfraIntentClassifier`` — primary when ``deepinfra_api_key`` is set;
     calls meta-llama/Meta-Llama-3.2-3B-Instruct via DeepInfra (~100-200ms GPU).
  2. ``OllamaIntentClassifier`` — secondary, calls local qwen3:0.6b via Ollama
     (used as primary when no DeepInfra key; ~2-5s on warm CPU).
  3. ``KeywordHeuristicClassifier`` — final fallback; pure in-memory, no I/O.

All return ``(intent, sub_questions, rephrased_query)`` so callers are agnostic to
which tier was used.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from rag_chat.domain.enums import QueryIntent

if TYPE_CHECKING:
    from rag_chat.domain.entities.chat import ResolvedEntity

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# ── Keyword heuristic lookup ───────────────────────────────────────────────────

# Ordered by specificity: more specific intents are checked first.
_INTENT_KEYWORDS: dict[QueryIntent, list[str]] = {
    QueryIntent.PORTFOLIO: ["portfolio", "holdings", "my stocks", "my shares", "watchlist"],
    QueryIntent.COMPARISON: ["compare", " vs ", "versus", "difference between", "better than"],
    QueryIntent.REASONING: ["why", "reason", "explain", "cause", "because", "how come"],
    QueryIntent.RELATIONSHIP: ["supply chain", "subsidiaries", "owns", "acquired", "parent company"],
    QueryIntent.FINANCIAL_DATA: ["price", "p/e", "revenue", "earnings", "ratio", "ebitda"],
    QueryIntent.SIGNAL_INTEL: ["news", "announced", "filed", "reported", "allegations"],
    QueryIntent.GENERAL: ["what is", "define", "how does", "tell me about", "explain what"],
    # FACTUAL_LOOKUP is the default — no keywords needed
}

# ── Classification prompt ──────────────────────────────────────────────────────

_CLASSIFICATION_PROMPT = (
    "You are a query intent classifier for a financial intelligence system.\n"
    "Classify the query into exactly one of: FACTUAL_LOOKUP, RELATIONSHIP, SIGNAL_INTEL,\n"
    "FINANCIAL_DATA, COMPARISON, REASONING, PORTFOLIO, GENERAL.\n"
    "\n"
    "Use GENERAL for ambiguous, educational, or open-ended questions not tied to a specific\n"
    "entity or financial metric. Use FACTUAL_LOOKUP when a specific named entity is targeted.\n"
    "For COMPARISON queries with multiple entities, extract sub_questions (one per entity).\n"
    "For REASONING queries, rephrase as a standalone question using conversation context.\n"
    "\n"
    "Examples:\n"
    '- "Who is Apple\'s CEO?" ->'
    ' {{"intent":"FACTUAL_LOOKUP","sub_questions":[],'
    '"rephrased_query":"Who is the CEO of Apple Inc.?"}}\n'
    '- "Why is Apple\'s margin declining?" ->'
    ' {{"intent":"REASONING","sub_questions":[],'
    '"rephrased_query":"Why is Apple\'s gross margin declining?"}}\n'
    '- "Compare TSLA vs RIVN margins" ->'
    ' {{"intent":"COMPARISON","sub_questions":["What are Tesla\'s margins?",'
    '"What are Rivian\'s margins?"],"rephrased_query":"Compare TSLA and RIVN margins."}}\n'
    '- "What risks affect my holdings?" ->'
    ' {{"intent":"PORTFOLIO","sub_questions":[],'
    '"rephrased_query":"What risks affect my portfolio holdings?"}}\n'
    '- "What is Apple\'s relationship with TSMC?" ->'
    ' {{"intent":"RELATIONSHIP","sub_questions":[],'
    '"rephrased_query":"What is Apple\'s supply chain relationship with TSMC?"}}\n'
    '- "Latest news on Nvidia?" ->'
    ' {{"intent":"SIGNAL_INTEL","sub_questions":[],'
    '"rephrased_query":"What are recent news and announcements about Nvidia?"}}\n'
    '- "What is TSLA\'s current P/E ratio?" ->'
    ' {{"intent":"FINANCIAL_DATA","sub_questions":[],'
    '"rephrased_query":"What is Tesla\'s current price-to-earnings ratio?"}}\n'
    '- "How do interest rates affect stock prices?" ->'
    ' {{"intent":"GENERAL","sub_questions":[],'
    '"rephrased_query":"How do interest rate changes affect equity valuations?"}}\n'
    "\n"
    "Query: {message}\n"
    "Conversation context: {history}\n"
    "Resolved entities: {entities}\n"
    'Respond with JSON only: {{"intent": "...", "sub_questions": [...], "rephrased_query": "..."}}\n'
)

_VALID_INTENTS: frozenset[str] = frozenset(q.value for q in QueryIntent)

# ── DeepInfra API constants ────────────────────────────────────────────────────

_DEEPINFRA_API_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
# PLAN-0052 platform-QA round 5 (2026-05-01): default 8B → 1B. The 1B
# completes a single-token intent decision in ~1.2s at ~1/6 the cost;
# on DeepInfra the lowercase `llama` path unlocks the 3.2-1B/3B
# variants. The 8B remains valid via env override for installs that
# need higher accuracy on ambiguous multi-intent queries.
_DEEPINFRA_DEFAULT_MODEL = "meta-llama/Llama-3.2-1B-Instruct"

# ── Keyword heuristic classifier ───────────────────────────────────────────────


class KeywordHeuristicClassifier:
    """Keyword-based intent classifier used as fallback when Ollama is unavailable.

    Operates entirely in memory — no I/O, no external calls.
    Falls back to ``FACTUAL_LOOKUP`` if no keyword matches.
    """

    def classify(self, message: str) -> tuple[QueryIntent, list[str], str]:
        """Return ``(intent, sub_questions, rephrased_query)`` via keyword matching.

        ``sub_questions`` and ``rephrased_query`` are empty/identity on the keyword
        path — the pipeline will use the original message for retrieval.
        """
        lower = message.lower()
        for intent, keywords in _INTENT_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                return intent, [], message
        return QueryIntent.FACTUAL_LOOKUP, [], message


# ── Ollama-backed classifier ───────────────────────────────────────────────────


class OllamaIntentClassifier:
    """Two-tier intent classifier: Ollama primary, keyword heuristic fallback.

    On any error from Ollama (timeout, HTTP error, invalid JSON) the keyword
    heuristic is used transparently and a warning is logged. Callers always
    receive a valid ``(intent, sub_questions, rephrased_query)`` triple.

    Args:
        ollama_base_url: Base URL for the Ollama API (e.g. ``http://localhost:11434``).
        model:           Ollama model name (default: ``qwen3:0.6b``).
        http_client:     Optional pre-configured ``httpx.AsyncClient`` — injected
                         in tests to avoid real network calls.
    """

    def __init__(
        self,
        ollama_base_url: str,
        model: str = "qwen3:0.6b",
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._ollama_url = ollama_base_url.rstrip("/")
        self._model = model
        self._client = http_client or httpx.AsyncClient()
        self._fallback = KeywordHeuristicClassifier()

    async def classify(
        self,
        message: str,
        conversation_history: list[dict[str, Any]],
        resolved_entities: list[ResolvedEntity],
    ) -> tuple[QueryIntent, list[str], str]:
        """Classify *message* into a ``QueryIntent``.

        Returns ``(intent, sub_questions, rephrased_query)``.
        Falls back to the keyword heuristic if Ollama is unavailable.
        """
        prompt = _CLASSIFICATION_PROMPT.format(
            message=message,
            history=json.dumps(conversation_history[-6:]),
            entities=json.dumps(
                [{"canonical_name": e.canonical_name, "type": e.entity_type} for e in resolved_entities]
            ),
        )
        try:
            response = await self._client.post(
                f"{self._ollama_url}/api/generate",
                # BP-231: qwen3:0.6b is a thinking model — in thinking mode it emits reasoning
                # tokens first, pushing CPU inference to 90-146s (always times out).
                # "think": False disables the reasoning block, dropping latency to ~2-5s warm.
                # This is a native Ollama parameter (added in v0.21.x) — no system prompt hack.
                json={"model": self._model, "prompt": prompt, "stream": False, "format": "json", "think": False},
                timeout=20.0,
            )
            response.raise_for_status()
            return _parse_intent_response(response.json().get("response", ""))
        except Exception:
            log.warning(  # type: ignore[no-any-return]
                "ollama_intent_classifier_fallback",
                model=self._model,
                msg_len=len(message),
            )
            return self._fallback.classify(message)


# ── DeepInfra-backed classifier ───────────────────────────────────────────────


class DeepInfraIntentClassifier:
    """Primary intent classifier backed by DeepInfra GPU inference.

    Uses ``meta-llama/Meta-Llama-3.2-3B-Instruct`` via DeepInfra's
    OpenAI-compatible ``/v1/openai/chat/completions`` endpoint.
    Expected latency: ~100-200ms (GPU, always warm).

    This replaces the local ``qwen3:0.6b`` which runs on CPU and takes 2-20s
    depending on Ollama model-swap contention, causing the system to always
    fall back to the keyword heuristic and lose sub_questions/rephrased_query.

    Falls back to ``KeywordHeuristicClassifier`` on any API error so the
    pipeline is never blocked by classification.

    Args:
        api_key:     DeepInfra API key.
        model:       DeepInfra model ID (default: meta-llama/Meta-Llama-3.2-3B-Instruct).
        http_client: Optional pre-configured httpx.AsyncClient (injected in tests).
        timeout:     Request timeout in seconds (default: 10.0).
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEEPINFRA_DEFAULT_MODEL,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = http_client or httpx.AsyncClient()
        self._timeout = timeout
        self._fallback = KeywordHeuristicClassifier()

    async def classify(
        self,
        message: str,
        conversation_history: list[dict[str, Any]],
        resolved_entities: list[ResolvedEntity],
    ) -> tuple[QueryIntent, list[str], str]:
        """Classify *message* into a ``QueryIntent`` via DeepInfra API.

        Returns ``(intent, sub_questions, rephrased_query)``.
        Falls back to keyword heuristic if DeepInfra is unavailable.
        """
        prompt = _CLASSIFICATION_PROMPT.format(
            message=message,
            history=json.dumps(conversation_history[-6:]),
            entities=json.dumps(
                [{"canonical_name": e.canonical_name, "type": e.entity_type} for e in resolved_entities]
            ),
        )
        try:
            response = await self._client.post(
                _DEEPINFRA_API_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a financial query intent classifier. "
                                "Always respond with valid JSON matching the requested schema."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    # response_format: json_object forces the model to emit valid JSON.
                    # Not all DeepInfra models support this; _parse_intent_response()
                    # handles the fallback if parsing fails.
                    "response_format": {"type": "json_object"},
                    "temperature": 0.0,
                    "max_tokens": 256,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return _parse_intent_response(content)
        except Exception:
            log.warning(  # type: ignore[no-any-return]
                "deepinfra_intent_classifier_fallback",
                model=self._model,
                msg_len=len(message),
            )
            return self._fallback.classify(message)


# ── Response parser ────────────────────────────────────────────────────────────


def _parse_intent_response(raw: str) -> tuple[QueryIntent, list[str], str]:
    """Parse the Ollama JSON response into ``(intent, sub_questions, rephrased_query)``.

    Returns ``(FACTUAL_LOOKUP, [], "")`` on any parse failure — callers will use
    the original message for retrieval.
    """
    try:
        data = json.loads(raw)
        intent_str = str(data.get("intent", "FACTUAL_LOOKUP")).upper()
        if intent_str not in _VALID_INTENTS:
            intent_str = "FACTUAL_LOOKUP"
        intent = QueryIntent(intent_str)
        sub_questions: list[str] = [str(q) for q in data.get("sub_questions", [])]
        rephrased: str = str(data.get("rephrased_query", ""))
        return intent, sub_questions, rephrased
    except (json.JSONDecodeError, KeyError, ValueError):
        return QueryIntent.FACTUAL_LOOKUP, [], ""
