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
import time
from typing import TYPE_CHECKING, Any

import structlog

from rag_chat.application.ports.llm_judge import LLMJudgePort  # A-001: import port from canonical location
from rag_chat.domain.errors import LLMJudgeTimeoutError

if TYPE_CHECKING:
    from observability.metrics import MLMetrics  # type: ignore[import-untyped]

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

    def __init__(
        self,
        provider_client: Any,
        *,
        timeout_s: float,
        metrics: MLMetrics | None = None,
    ) -> None:
        self._provider = provider_client
        self._timeout_s = timeout_s
        # MLMetrics is optional — when None the score_citation path skips
        # Prometheus updates.  When wired, citation-judge calls increment
        # ``rag_chat_ml_api_requests_total{operation="citation_judge"}`` so the
        # daily cron's failure rate shows up on the rag-chat dashboard.
        self._metrics = metrics

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

        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(_call(), timeout=self._timeout_s)
        except TimeoutError as exc:
            self._record_ml_call("citation_judge", "timeout", time.perf_counter() - start)
            log.warning(  # type: ignore[no-any-return]
                "citation_judge_timeout",
                timeout_s=self._timeout_s,
            )
            raise LLMJudgeTimeoutError(f"Citation judge call timed out after {self._timeout_s}s") from exc
        except Exception:
            self._record_ml_call("citation_judge", "error", time.perf_counter() - start)
            raise
        self._record_ml_call("citation_judge", "success", time.perf_counter() - start)
        return result

    def _record_ml_call(self, operation: str, status: str, latency_s: float) -> None:
        """Best-effort Prometheus update; no-op when metrics is None.

        Uses the underlying provider's model_id so the dashboard breaks down
        judge latency by the actual model (e.g. Llama-3.1-8B-Instruct).
        """
        if self._metrics is None:
            return
        # Inspect the provider for its model id; fall back to "unknown" so the
        # series still increments rather than silently dropping.
        model_id: str = getattr(self._provider, "model_id", None) or getattr(self._provider, "_model", "unknown")
        try:
            self._metrics.ml_api_requests_total.labels(model_id=model_id, operation=operation, status=status).inc()
            self._metrics.ml_api_latency_seconds.labels(model_id=model_id, operation=operation).observe(latency_s)
        except Exception:  # pragma: no cover — defensive
            log.debug("ml_metrics_record_failed", operation=operation, status=status)  # type: ignore[no-any-return]
