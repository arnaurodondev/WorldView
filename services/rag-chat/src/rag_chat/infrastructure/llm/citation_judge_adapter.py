"""Citation-judge LLM adapter — PLAN-0084 Sub-Plan A-1 T-A-1-02.

Wraps an existing completion-provider client (DeepInfra or Ollama) and exposes
the ``LLMJudgePort.score_citation`` interface required by
``ScoreCitationAccuracyUseCase``.

Key guarantees:
- Per-call timeout enforced via ``asyncio.wait_for`` (timeout_s from Settings).
- On timeout: logs ``citation_judge_timeout`` at WARNING, raises
  ``LLMJudgeTimeoutError`` — never swallowed silently.
- LLM parameters: temperature=0.0, max_tokens=2 (single digit + optional newline).
- All other provider exceptions propagate unchanged so the caller can classify them.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from rag_chat.application.ports.llm_judge import LLMJudgePort  # A-001: import port from canonical location
from rag_chat.domain.errors import LLMJudgeTimeoutError

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class CitationJudgeAdapter(LLMJudgePort):
    """Implements ``LLMJudgePort`` by delegating to an existing provider client.

    Args:
        provider_client: A provider object that exposes an async ``stream()``
            generator accepting ``prompt``, ``temperature``, and ``max_tokens``
            keyword arguments (e.g. ``DeepInfraCompletionAdapter`` or
            ``OllamaCompletionAdapter``).  The adapter collects all streamed
            chunks into a single string and returns it.
        timeout_s: Per-call wall-clock budget in seconds. Matches
            ``Settings.citation_call_timeout_s`` (default 15.0).
    """

    def __init__(self, provider_client: Any, *, timeout_s: float) -> None:
        self._provider = provider_client
        self._timeout_s = timeout_s

    async def score_citation(self, *, claim: str) -> str:
        """Return the raw LLM response string for the pre-assembled rubric prompt.

        The use case pre-assembles the full fenced prompt (rubric + claim + snippet)
        and passes it as ``claim``.  This adapter's job is purely transport +
        timeout enforcement — no prompt construction logic lives here.

        A-002: ``snippet`` parameter removed.  The full prompt is in ``claim``.

        Raises:
            LLMJudgeTimeoutError: When the provider call exceeds ``timeout_s``.
            Any provider-specific exception: propagated unchanged for the caller
                to classify.
        """
        # claim is the complete ready-to-send rubric prompt built by the use case.
        prompt = claim

        async def _call() -> str:
            chunks: list[str] = []
            async for chunk in self._provider.stream(
                prompt,
                temperature=0.0,
                max_tokens=2,
            ):
                chunks.append(chunk)
            return "".join(chunks)

        try:
            result = await asyncio.wait_for(_call(), timeout=self._timeout_s)
        except TimeoutError as exc:
            log.warning(  # type: ignore[no-any-return]
                "citation_judge_timeout",
                timeout_s=self._timeout_s,
            )
            raise LLMJudgeTimeoutError(f"Citation judge call timed out after {self._timeout_s}s") from exc
        return result
