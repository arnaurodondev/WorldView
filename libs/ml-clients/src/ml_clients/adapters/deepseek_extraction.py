"""DeepSeek extraction adapter — structured extraction via DeepSeek-compatible OpenAI endpoint."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import TYPE_CHECKING

import structlog

from ml_clients.dataclasses import ExtractionInput, ExtractionOutput
from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    from observability.metrics import MLMetrics

logger = structlog.get_logger()

_DEFAULT_MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"
_DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"

# Extraction prompts for 8B-class models on DeepInfra typically return in 30-90s.
# The openai SDK default of 600s means a stalled request hangs the article consumer
# for up to 10 minutes before the docker restart policy triggers (BP-235 variant).
# 90s wall-clock cap via asyncio.wait_for prevents DLQ storms when DeepInfra is
# under queue pressure (root cause of 93 DLQ timeouts seen 2026-05-10..21).
# The httpx read=90s provides a secondary per-chunk guard.
_EXTRACTION_TIMEOUT_S = 90.0


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
        max_connections: int = 64,
        max_keepalive_connections: int = 32,
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
        self._timeout_s = timeout_s
        # Task #14: deep extraction is I/O-bound (12-22s DeepInfra network wait per
        # article).  When the article consumer processes many articles concurrently,
        # an equal number of extraction calls hit this client at once.  httpx's
        # default Limits (max_connections=100, max_keepalive=20) silently *queue*
        # connections beyond the keepalive pool, adding hidden latency under load.
        # We pass an explicit httpx.AsyncClient with Limits sized for the configured
        # concurrency (default 64 conns / 32 keepalive ~ 50 concurrent + headroom).
        # A wide keepalive pool also keeps warm TCP+TLS connections so DeepInfra's
        # server-side KV prefix cache (same system prompt) stays hot across calls.
        import httpx  # local import: httpx ships transitively with the openai SDK

        http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            ),
            timeout=httpx.Timeout(connect=5.0, read=timeout_s, write=30.0, pool=5.0),
        )
        # Client is created once at startup so httpx maintains a persistent connection
        # pool across extraction calls. This also enables DeepInfra's server-side KV
        # prefix cache: when the system prompt bytes are identical across calls, the
        # provider reuses cached KV tensors and charges only for the new user tokens.
        self._client = _openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_openai.Timeout(connect=5.0, read=timeout_s, write=30.0, pool=5.0),
            http_client=http_client,
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
                    # sampling variance, ``max_tokens=4096`` covers the
                    # extraction schema with comfortable headroom even for
                    # articles with many relations/events/claims.
                    # extra_body (DeepInfra extensions):
                    # reasoning_effort=none — disables Qwen3.x chain-of-thought so the
                    #   answer goes to content (not reasoning_content), saving latency
                    #   and tokens on extraction tasks where reasoning adds no value.
                    # prompt_cache_key — DeepInfra caches the system-prompt prefix KV
                    #   tensors across requests sharing the same key; only new (user-role)
                    #   tokens are billed after the initial cache-miss call.
                    # asyncio.wait_for enforces a wall-clock total timeout so
                    # a stalled DeepInfra request (high TTFT under queue pressure)
                    # cannot consume the article consumer's 300s watchdog budget.
                    response = await asyncio.wait_for(
                        self._client.chat.completions.create(
                            model=self._model_id,
                            messages=[
                                {"role": "system", "content": inp.prompt},
                                {"role": "user", "content": inp.context},
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.0,
                            max_tokens=4096,
                            extra_body={
                                "reasoning_effort": "none",
                                "prompt_cache_key": "kg_extraction_v1",
                            },
                        ),
                        timeout=self._timeout_s,
                    )
                    # Capture actual token usage from API response when available.
                    # cached_tokens: DeepInfra KV prefix cache hit count — non-zero when
                    # the system prompt prefix bytes matched a prior call on the same connection.
                    if response.usage is not None:
                        tokens_in = response.usage.prompt_tokens or 0
                        tokens_out = response.usage.completion_tokens or 0
                        details = getattr(response.usage, "prompt_tokens_details", None)
                        tokens_cached = getattr(details, "cached_tokens", 0) or 0
                    # With reasoning_effort=none the answer must be in content.
                    # Do NOT fall back to reasoning_content: when reasoning_effort=none fails
                    # the model puts its full thinking chain there (~6 kB of prose) which
                    # will always fail JSON parsing and trigger an incorrect Ollama fallback.
                    msg = response.choices[0].message
                    raw_response: str = msg.content or ""
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
                            # Partial-JSON recovery for finish_reason=length: small models
                            # (0.8B) repeat list items until the token limit is hit,
                            # truncating mid-array. Since canonical_name / ticker / isin
                            # always appear before the aliases array, strip the incomplete
                            # aliases tail and inject [] so the core fields are preserved.
                            recovered: dict[str, object] | None = None
                            if finish_reason == "length":
                                stripped = re.sub(
                                    r',\s*"aliases"\s*:.*$',
                                    "",
                                    cleaned,
                                    flags=re.DOTALL,
                                )
                                try:
                                    _r: dict[str, object] = json.loads(stripped + "}")
                                    _r.setdefault("aliases", [])
                                    recovered = _r
                                    logger.warning(
                                        "deepseek_extraction_aliases_truncated_recovered",
                                        model_id=self._model_id,
                                        finish_reason=finish_reason,
                                    )
                                except json.JSONDecodeError:
                                    pass
                            if recovered is not None:
                                result = recovered
                            else:
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
                except TimeoutError as exc:
                    raise RetryableError(f"DeepSeek wall-clock timeout after {self._timeout_s}s") from exc
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
