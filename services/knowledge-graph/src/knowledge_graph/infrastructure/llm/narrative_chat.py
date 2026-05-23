"""Narrative chat client (PLAN-0088 P0-7, 2026-05-10).

Direct DeepInfra chat-completion call for the GenerateNarrativeUseCase. The
fallback-chain extraction adapter cannot serve narrative prompts because it
hard-codes ``response_format={"type": "json_object"}``, which causes the model
to emit hallucinated ``{"error": ...}`` envelopes for free-form prose tasks.

This module exposes a minimal, stateful callable that does an OpenAI-compatible
chat-completions request against DeepInfra (or any OpenAI-compatible base URL)
WITHOUT JSON mode, using temperature ``0.2`` and a generous ``max_tokens`` so the
model has room for a 2-4 sentence narrative.

Wiring:
- ``services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py``
  passes the configured client into ``GenerateNarrativeUseCase`` so the periodic
  ``NarrativeRefreshWorker`` and on-demand ``NarrativeGenerationWorker`` can both
  produce real LLM narratives instead of falling back to the template-v1 stub.
- ``services/knowledge-graph/src/knowledge_graph/api/narratives.py`` constructs
  the same client from settings so the manual trigger endpoint also benefits.
"""

from __future__ import annotations

from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


class DeepInfraNarrativeChatClient:
    """Minimal OpenAI-compatible chat-completion client for narrative prose.

    Why a fresh class instead of reusing ``DeepSeekExtractionAdapter``: the
    extraction adapter is intentionally locked into JSON-mode + low temperature
    + extraction-shaped prompt assumptions. Trying to flip those flags per call
    would couple two unrelated pipelines.
    """

    def __init__(
        self,
        api_key: str,
        model_id: str,
        base_url: str = "https://api.deepinfra.com/v1/openai",
        timeout_s: float = 30.0,
    ) -> None:
        # Lazy-import openai so test environments without the package can still
        # import this module via the type-checker path.
        import openai as _openai  # type: ignore[import-not-found]

        self._openai = _openai
        self._model_id = model_id
        # AsyncOpenAI handles connection pooling + retries at the transport
        # layer; we layer use-case-level retries on top with exponential backoff.
        self._client = _openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_openai.Timeout(connect=5.0, read=timeout_s, write=10.0, pool=5.0),
        )

    async def __call__(self, prompt: str) -> str:
        """Run a chat-completion request and return the assistant's text output."""
        response = await self._client.chat.completions.create(
            model=self._model_id,
            messages=[
                # System message anchors the model in a journalistic-prose voice.
                # Without this anchor the 8B model occasionally emits JSON or
                # repeats the prompt header verbatim.
                {
                    "role": "system",
                    "content": (
                        "You are a financial intelligence analyst. Given a structured "
                        "entity profile, write a concise factual narrative of 100-120 words. "
                        "Output ONLY the narrative prose — no JSON, no preamble, no headers. "
                        "IMPORTANT: Only describe facts directly supported by the provided "
                        "relations and claims. Do not invent acquisition events, funding rounds, "
                        "product launches, or leadership changes not present in the data. "
                        "If the entity is not well-known or has limited data, write a "
                        "conservative description based only on what is provided. "
                        "Prefer a shorter, accurate description over a longer, speculative one."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            # NOT json_object: narrative prose is plain text.
            # max_tokens capped at 180 to enforce the 100-120 word target and
            # reduce padding-induced hallucination in low-data entities.
            temperature=0.2,
            max_tokens=180,
        )
        msg = response.choices[0].message
        text: str = msg.content or ""
        return text.strip()

    async def aclose(self) -> None:
        await self._client.close()
