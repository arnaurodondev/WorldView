"""DeepSeek extraction adapter — structured extraction via DeepSeek-compatible OpenAI endpoint."""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

import structlog

from ml_clients.dataclasses import ExtractionInput, ExtractionOutput
from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    import asyncio

    from observability.metrics import MLMetrics

logger = structlog.get_logger()

_DEFAULT_MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"
_DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"

# Extraction prompts for 8B-class models on DeepInfra typically return in 30-90s.
# The openai SDK default of 600s means a stalled request hangs the article consumer
# for up to 10 minutes before the docker restart policy triggers (BP-235 variant).
# 120s gives a 2x margin over the p99 observed latency while preventing infinite hangs.
_EXTRACTION_TIMEOUT_S = 120.0


class DeepSeekExtractionAdapter:
    """Implements ExtractionClient via DeepInfra OpenAI-compatible endpoint. Default model: DeepSeek-V4-Flash."""

    def __init__(
        self,
        api_key: str,
        model_id: str = _DEFAULT_MODEL_ID,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        semaphore: asyncio.Semaphore,
        timeout_s: float = _EXTRACTION_TIMEOUT_S,
        metrics: MLMetrics | None = None,
    ) -> None:
        try:
            import openai as _openai
        except ImportError as exc:
            raise FatalError("openai package not installed; install ml-clients[openai]") from exc

        self._model_id = model_id
        self._semaphore = semaphore
        self._metrics = metrics
        self._openai = _openai
        # Client is created once at startup so httpx maintains a persistent connection
        # pool across extraction calls. This also enables DeepInfra's server-side KV
        # prefix cache: when the system prompt bytes are identical across calls, the
        # provider reuses cached KV tensors and charges only for the new user tokens.
        self._client = _openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_openai.Timeout(connect=5.0, read=timeout_s, write=30.0, pool=5.0),
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def extract(self, inp: ExtractionInput) -> ExtractionOutput:
        start = time.perf_counter()
        status = "success"
        tokens_in = 0
        tokens_out = 0
        tokens_cached = 0
        try:
            async with self._semaphore:
                try:
                    # PLAN-0052 platform-QA round 8 (2026-05-01): adopt the
                    # JSON-mode pattern proven by sibling workers
                    # (article_relevance_scoring_worker.py:335,
                    # unresolved_resolution_worker.py:561). Without these three
                    # parameters Llama-3.1-8B is free to wrap output in markdown
                    # fences, prepend reasoning preambles, or truncate at the
                    # default token cap — all producing JSONDecodeError that
                    # the article-consumer logs as ``deep_extraction.window_failed``
                    # and silently drops. ``response_format`` forces a valid
                    # JSON object server-side, ``temperature=0`` removes
                    # sampling variance, ``max_tokens=2048`` covers the
                    # extraction schema with comfortable headroom.
                    response = await self._client.chat.completions.create(
                        model=self._model_id,
                        messages=[
                            {"role": "system", "content": inp.prompt},
                            {"role": "user", "content": inp.context},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.0,
                        max_tokens=2048,
                    )
                    # Capture actual token usage from API response when available.
                    # cached_tokens: DeepInfra KV prefix cache hit count — non-zero when
                    # the system prompt prefix bytes matched a prior call on the same connection.
                    if response.usage is not None:
                        tokens_in = response.usage.prompt_tokens or 0
                        tokens_out = response.usage.completion_tokens or 0
                        details = getattr(response.usage, "prompt_tokens_details", None)
                        tokens_cached = getattr(details, "cached_tokens", 0) or 0
                    raw_response: str = response.choices[0].message.content or ""
                    finish_reason: str | None = getattr(response.choices[0], "finish_reason", None)
                    logger.info(
                        "deepseek_extraction_completed",
                        model_id=self._model_id,
                        tokens_cached=tokens_cached,
                    )
                    # Defense-in-depth: even with response_format=json_object,
                    # strip markdown fences (` ```json ... ``` `) before parsing
                    # in case a future model variant ignores the directive.
                    try:
                        result: dict[str, object] = json.loads(raw_response)
                    except json.JSONDecodeError:
                        cleaned = re.sub(
                            r"^\s*```(?:json)?\s*|\s*```\s*$",
                            "",
                            raw_response.strip(),
                        )
                        try:
                            result = json.loads(cleaned)
                        except json.JSONDecodeError as exc:
                            # Surface the raw response prefix so the next
                            # regression of this class is debuggable.
                            logger.warning(
                                "deepseek_extraction_malformed",
                                model_id=self._model_id,
                                raw_response_prefix=raw_response[:500],
                                raw_response_len=len(raw_response),
                                finish_reason=finish_reason,
                            )
                            raise FatalError(f"malformed extraction output: {exc}") from exc
                    return ExtractionOutput(
                        result=result,
                        raw_response=raw_response,
                        model_id=self._model_id,
                    )
                except self._openai.RateLimitError as exc:
                    raise RetryableError(f"DeepSeek rate limit (429): {exc}") from exc
                except self._openai.APIConnectionError as exc:
                    raise RetryableError(f"DeepSeek connection error: {exc}") from exc
                except self._openai.APITimeoutError as exc:
                    raise RetryableError(f"DeepSeek timeout: {exc}") from exc
                except self._openai.APIStatusError as exc:
                    if exc.status_code >= 500:
                        raise RetryableError(f"DeepSeek 5xx: {exc}") from exc
                    raise FatalError(f"DeepSeek 4xx: {exc}") from exc
                except (RetryableError, FatalError):
                    raise
                except Exception as exc:
                    raise FatalError(f"Unexpected DeepSeek error: {exc}") from exc
        except (RetryableError, FatalError):
            status = "error"
            raise
        finally:
            if self._metrics:
                latency = time.perf_counter() - start
                self._metrics.ml_api_requests_total.labels(
                    model_id=self._model_id, operation="extract", status=status
                ).inc()
                self._metrics.ml_api_latency_seconds.labels(model_id=self._model_id, operation="extract").observe(
                    latency
                )
                self._metrics.ml_api_tokens_in_total.labels(model_id=self._model_id).inc(tokens_in)
                self._metrics.ml_api_tokens_out_total.labels(model_id=self._model_id).inc(tokens_out)
                from ml_clients.cost import estimate_cost  # local import avoids circular dep

                cost = estimate_cost("deepinfra", self._model_id, tokens_in, tokens_out)
                self._metrics.ml_api_estimated_cost_usd_total.labels(model_id=self._model_id).inc(cost)
