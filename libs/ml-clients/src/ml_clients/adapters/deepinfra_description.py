"""DeepInfra description adapter — entity description generation via OpenAI-compatible endpoint.

Primary model : Qwen/Qwen3-235B-A22B-Instruct-2507
Fallback model: Qwen/Qwen3-32B

Both Qwen3 models can emit <think>…</think> reasoning blocks; the adapter strips
these before returning the plain-text description.

Cost cap: same atomic Valkey INCRBYFLOAT-then-check pattern as GeminiDescriptionAdapter
(G-005 fix). The monthly budget key is shared with the gemini adapter key prefix so
the combined description spend is tracked under one counter.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from ml_clients.errors import FatalError

if TYPE_CHECKING:
    import asyncio

    from ml_clients.description_client import CostTrackerProtocol
    from ml_clients.usage_log import LlmUsageLogProtocol

logger = structlog.get_logger()

_DEFAULT_PRIMARY_MODEL_ID = "Qwen/Qwen3-235B-A22B-Instruct-2507"
_DEFAULT_FALLBACK_MODEL_ID = "Qwen/Qwen3-32B"
_DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"
_DEFAULT_MAX_MONTHLY_USD = 10.0
_DEFAULT_TIMEOUT_S = 60.0  # description calls are simpler than extraction; 60 s is generous

# Monthly cost key in Valkey (shared namespace with gemini adapter)
_COST_KEY_PREFIX = "s7:desc:cost"

# Default estimated output tokens for pre-call cost reservation
_DEFAULT_ESTIMATED_OUTPUT_TOKENS = 120

# Regex to strip Qwen3 thinking blocks
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _month_key() -> str:
    now = datetime.now(tz=UTC)
    return f"{_COST_KEY_PREFIX}:{now.strftime('%Y-%m')}"


def _estimate_cost_local(model_id: str, tokens_in: int, tokens_out: int) -> float:
    """Local cost estimation (avoids circular import with cost.py)."""
    from ml_clients.cost import estimate_cost

    return estimate_cost("deepinfra", model_id, tokens_in, tokens_out)


def _strip_think_blocks(text: str) -> str:
    """Remove Qwen3 <think>…</think> reasoning blocks from the output."""
    return _THINK_RE.sub("", text).strip()


class DeepInfraDescriptionAdapter:
    """Generates entity descriptions via DeepInfra (Qwen3-235B-A22B primary, Qwen3-32B fallback).

    Args:
    ----
        api_key:          DeepInfra API key.
        primary_model_id: Primary model (default: Qwen/Qwen3-235B-A22B-Instruct-2507).
        fallback_model_id: Fallback model (default: Qwen/Qwen3-32B).
        base_url:         OpenAI-compatible base URL (default: DeepInfra).
        semaphore:        Concurrency limiter (keyword-only, required).
        cost_tracker:     Valkey client for monthly cost cap (optional; fail-open when None).
        max_monthly_usd:  Monthly spend cap in USD (default: $10.0).
        usage_logger:     Optional LLM usage logger (fire-and-forget).
        timeout_s:        Per-request HTTP timeout in seconds (default: 60).

    """

    def __init__(
        self,
        api_key: str,
        primary_model_id: str = _DEFAULT_PRIMARY_MODEL_ID,
        fallback_model_id: str = _DEFAULT_FALLBACK_MODEL_ID,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        semaphore: asyncio.Semaphore,
        cost_tracker: CostTrackerProtocol | None = None,
        max_monthly_usd: float = _DEFAULT_MAX_MONTHLY_USD,
        usage_logger: LlmUsageLogProtocol | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        try:
            import openai as _openai
        except ImportError as exc:
            raise FatalError("openai package not installed; install ml-clients[openai]") from exc

        self._primary_model_id = primary_model_id
        self._fallback_model_id = fallback_model_id
        self._semaphore = semaphore
        self._cost_tracker = cost_tracker
        self._max_monthly_usd = max_monthly_usd
        self._usage_logger = usage_logger
        self._openai = _openai
        # Persistent client enables connection pool reuse and DeepInfra KV prefix caching.
        self._client = _openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_openai.Timeout(connect=5.0, read=timeout_s, write=30.0, pool=5.0),
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def generate_description(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str,
        context_hints: dict[str, str],
    ) -> str | None:
        """Generate a world-knowledge description using Qwen3 via DeepInfra.

        Tries the primary model first; falls back to the secondary model on any error.
        Returns None (without calling the API) when the monthly cost cap is exceeded.
        """
        prompt = _build_prompt(canonical_name, entity_type, context_hints)

        # Atomic cost-cap reserve before any API call
        reserved, estimated_cost = await self._reserve_cost(prompt)
        if not reserved:
            logger.warning(
                "deepinfra_description_cost_cap_exceeded",
                entity_id=entity_id,
                max_monthly_usd=self._max_monthly_usd,
            )
            return None

        # Try primary, then fallback
        for model_id in (self._primary_model_id, self._fallback_model_id):
            result = await self._call_model(model_id, prompt, entity_id, entity_type)
            if result is not None:
                await self._adjust_cost(estimated_cost, model_id, result[1], result[2])
                return result[0]

        # Both models failed — undo reservation
        await self._undo_reservation(estimated_cost)
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _call_model(
        self,
        model_id: str,
        prompt: str,
        entity_id: str,
        entity_type: str,
    ) -> tuple[str, int, int] | None:
        """Call one model; return (description_text, tokens_in, tokens_out) or None on error."""
        start = time.perf_counter()
        status = "success"
        tokens_in = 0
        tokens_out = 0
        try:
            async with self._semaphore:
                response = await self._client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=256,
                )
                raw: str = response.choices[0].message.content or ""
                if response.usage is not None:
                    tokens_in = response.usage.prompt_tokens or 0
                    tokens_out = response.usage.completion_tokens or 0

                description = _strip_think_blocks(raw)
                if not description:
                    logger.warning(
                        "deepinfra_description_empty",
                        entity_id=entity_id,
                        model_id=model_id,
                    )
                    return None

                logger.info(
                    "deepinfra_description_generated",
                    entity_id=entity_id,
                    entity_type=entity_type,
                    model_id=model_id,
                )
                return description, tokens_in, tokens_out

        except (self._openai.RateLimitError, self._openai.APIConnectionError, self._openai.APITimeoutError) as exc:
            status = "error"
            logger.warning("deepinfra_description_retryable", model_id=model_id, error=str(exc))
            return None
        except self._openai.APIStatusError as exc:
            status = "error"
            logger.warning("deepinfra_description_api_error", model_id=model_id, status_code=exc.status_code)
            return None
        except Exception as exc:
            status = "error"
            logger.warning("deepinfra_description_unexpected", model_id=model_id, error=str(exc))
            return None
        finally:
            if status == "error" and self._usage_logger is not None:
                import asyncio as _asyncio

                _asyncio.create_task(  # noqa: RUF006
                    self._usage_logger.log(
                        model_id=model_id,
                        provider="deepinfra",
                        capability="description",
                        tokens_in=0,
                        tokens_out=0,
                        latency_ms=int((time.perf_counter() - start) * 1000),
                        estimated_cost_usd=0.0,
                        success=False,
                        error_code="model_error",
                    ),
                )

    async def _reserve_cost(self, prompt: str) -> tuple[bool, float]:
        if self._cost_tracker is None:
            return True, 0.0
        estimated = _estimate_cost_local(
            self._primary_model_id,
            len(prompt) // 4,
            _DEFAULT_ESTIMATED_OUTPUT_TOKENS,
        )
        if estimated == 0.0:
            # Model pricing not in cost.py yet — allow call, don't track
            return True, 0.0
        key = _month_key()
        cap_threshold = self._max_monthly_usd * 0.95
        try:
            new_total = await self._cost_tracker.incrbyfloat(key, estimated)
            if new_total >= cap_threshold:
                await self._cost_tracker.incrbyfloat(key, -estimated)
                return False, estimated
            return True, estimated
        except Exception as exc:
            logger.warning("deepinfra_desc_cost_reserve_failed", error=str(exc))
            return True, 0.0

    async def _adjust_cost(
        self,
        estimated: float,
        model_id: str,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        actual = _estimate_cost_local(model_id, tokens_in, tokens_out)
        if self._usage_logger is not None:
            import asyncio as _asyncio

            _asyncio.create_task(  # noqa: RUF006
                self._usage_logger.log(
                    model_id=model_id,
                    provider="deepinfra",
                    capability="description",
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=0,
                    estimated_cost_usd=actual,
                    success=True,
                ),
            )
        if self._cost_tracker is None or estimated == 0.0:
            return
        delta = actual - estimated
        if abs(delta) < 0.000001:
            return
        try:
            await self._cost_tracker.incrbyfloat(_month_key(), delta)
        except Exception as exc:
            logger.warning("deepinfra_desc_cost_adjust_failed", error=str(exc))

    async def _undo_reservation(self, estimated_cost: float) -> None:
        if self._cost_tracker is None or estimated_cost == 0.0:
            return
        try:
            await self._cost_tracker.incrbyfloat(_month_key(), -estimated_cost)
        except Exception as exc:
            logger.warning("deepinfra_desc_cost_undo_failed", error=str(exc))


def _build_prompt(canonical_name: str, entity_type: str, context_hints: dict[str, str]) -> str:
    """Build the entity description prompt (XML-wrapped inputs prevent injection)."""
    safe_name = canonical_name[:256]
    safe_type = entity_type[:64]
    hints_str = "; ".join(f"{k[:64]}: {str(v)[:256]}" for k, v in context_hints.items()) if context_hints else "none"
    return (
        f"Write a concise 2-3 sentence factual description of "
        f"<entity_name>{safe_name}</entity_name> "
        f"(entity type: <entity_type>{safe_type}</entity_type>). "
        f"Additional context: {hints_str}. "
        "Focus on what this entity is, its significance, and its primary domain. "
        "Do not include opinions or speculation. "
        "Respond with only the description text — no JSON, no markdown, no preamble."
    )
