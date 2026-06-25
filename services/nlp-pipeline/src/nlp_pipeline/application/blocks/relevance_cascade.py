"""LLM relevance cascade tiebreaker (PLAN-0111 C-7).

WHAT THIS IS
------------
A FrugalGPT / learning-to-defer *cascade* stage for the learned router. The
cheap EmbeddingGemma classifier (``LearnedRouter``) emits a calibrated
``P(yield)``. When that probability lands in the AMBIGUOUS band around the
extract threshold (``[thr_extract-0.10, thr_extract+0.10]``) the cheap model is
genuinely uncertain — its decision there is close to a coin-flip. Instead of
committing, we DEFER that uncertain slice to a slightly more expensive but still
small generative model for a tiebreak.

WHY REUSE THE EXISTING Llama-8B RELEVANCE SCORER (no new model)
---------------------------------------------------------------
The platform already runs a small generative relevance scorer:
``ArticleRelevanceScoringWorker`` calls ``meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo``
on DeepInfra with the ``ARTICLE_RELEVANCE_SCORER`` prompt (title-only) to emit a
0.0-1.0 market-relevance score. PLAN-0111 C-7 explicitly reuses *that* model and
*that* prompt for the tiebreak — we do NOT introduce a new model. This keeps the
cascade's "expensive" leg cheap (~100-200ms, ~$0.02/M tokens) and its semantics
identical to the relevance signal already understood elsewhere in the pipeline.

THE COMBINE RULE (documented + explainable)
-------------------------------------------
The router calls this scorer ONLY for in-band articles. The rule is deliberately
simple so it is auditable:

    in-band → LLM relevance probability >= cutoff  → MEDIUM (extract)
              LLM relevance probability <  cutoff  → LIGHT  (embed only)

Out-of-band articles never reach this code (the whole point of a cascade —
cheap majority, LLM only on the uncertain minority).

FAILURE POLICY
--------------
This is a best-effort enhancement. ANY failure (network error, malformed JSON,
empty content) returns ``None``; the caller then falls back to the cheap
classifier's own ``map_p_yield_to_tier`` decision for that article. A cascade
outage must never break routing — it only forfeits the tiebreak.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

import httpx
import structlog
from prompts.classification.article_relevance import ARTICLE_RELEVANCE_SCORER  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]

logger = structlog.get_logger()

# Resolve the static instruction block ONCE (no parameters) so the hot path is a
# single string concat — byte-identical to the ArticleRelevanceScoringWorker.
_SYSTEM_PROMPT = ARTICLE_RELEVANCE_SCORER.render()


def _extract_relevance_json(content: str | None) -> dict[str, object]:
    """Strip ``<think>`` blocks + markdown fences, then parse JSON.

    Mirrors ``article_relevance_scoring_worker._extract_relevance_json``: small
    instruct models occasionally wrap the JSON in a hidden chain-of-thought or a
    ```json fence even with ``response_format=json_object`` set. We salvage the
    object rather than silently dropping the tiebreak.
    """
    if not content:
        raise ValueError("empty_content")
    content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL)
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
    if fence_match:
        content = fence_match.group(1)
    else:
        brace_match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if brace_match:
            content = brace_match.group(0)
    return json.loads(content)  # type: ignore[no-any-return]


class RelevanceCascadeScorer:
    """Calls the reused Llama-8B relevance scorer for an in-band tiebreak.

    Args:
        api_key:    DeepInfra API key (the SAME key the rest of the pipeline
                    uses; the router is only constructed when it is present).
        base_url:   OpenAI-compatible base URL.
        model_id:   the relevance model id — reused verbatim from
                    ``relevance_scoring_api_model_id``
                    (``meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo``).
        timeout_seconds: per-call httpx timeout; the cascade fires on a small
                    slice so a slow call must not stall the pipeline.
        usage_logger: optional shared llm_usage_log sink so cascade calls are
                    auditable alongside extraction spend.

    The scorer is constructed once and reused; it opens a short-lived httpx
    client per call (the call rate is low — only the in-band slice).
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_id: str,
        timeout_seconds: float = 15.0,
        usage_logger: LlmUsageLogProtocol | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._timeout = float(timeout_seconds)
        self._usage_logger = usage_logger

    async def score_relevance(self, *, title: str | None, subtitle: str | None) -> float | None:
        """Return the LLM relevance probability in [0,1], or None on any failure.

        Uses the SAME prompt shape as ArticleRelevanceScoringWorker so the score
        is comparable to the relevance signal stored elsewhere. The dynamic
        trailer carries the title (and the lede as Source context) exactly like
        the worker's per-article suffix.
        """
        # The worker appends "\nUser: Title: ...\nSource: ..." — we keep the same
        # shape. The lede goes in as additional context after the title so the
        # 8B model has the same headline+lede the embedding router saw.
        title_str = (title or "Unknown").strip() or "Unknown"
        subtitle_str = (subtitle or "").strip()
        user_trailer = f"\nUser: Title: {title_str}"
        if subtitle_str:
            user_trailer += f"\nLede: {subtitle_str}"
        user_content = _SYSTEM_PROMPT + user_trailer

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model_id,
                        "messages": [{"role": "user", "content": user_content}],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.0,
                        # Disable hidden thinking + give headroom (mirrors the worker).
                        "chat_template_kwargs": {"enable_thinking": False},
                        "max_tokens": 512,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
            parsed = _extract_relevance_json(content)
            score = float(parsed["score"])  # type: ignore[arg-type]
            score = max(0.0, min(1.0, score))
            await self._record_usage(
                latency_ms=int((time.perf_counter() - t0) * 1000),
                success=True,
                tokens_in=len(user_content.split()),
                tokens_out=len(str(content).split()),
            )
            return score
        except Exception as exc:  # cascade is best-effort — never break routing
            logger.warning("relevance_cascade_failed", error=str(exc))  # type: ignore[no-any-return]
            await self._record_usage(
                latency_ms=int((time.perf_counter() - t0) * 1000),
                success=False,
                tokens_in=len(user_content.split()),
                tokens_out=0,
                error_code="model_error",
            )
            return None

    async def _record_usage(
        self,
        *,
        latency_ms: int,
        success: bool,
        tokens_in: int,
        tokens_out: int,
        error_code: str | None = None,
    ) -> None:
        """Append one llm_usage_log row per cascade call (best-effort)."""
        if self._usage_logger is None:
            return
        try:
            await self._usage_logger.log(
                model_id=self._model_id,
                provider="deepinfra",
                capability="classification",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                estimated_cost_usd=0.0,
                success=success,
                error_code=error_code,
            )
        except Exception as exc:  # protocol forbids raising
            logger.warning("relevance_cascade_usage_log_failed", error=str(exc))  # type: ignore[no-any-return]
