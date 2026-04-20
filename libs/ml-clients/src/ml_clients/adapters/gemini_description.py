"""Gemini description adapter — entity description generation (PRD-0017 §6.5).

Uses gemini-3.1-flash-lite via Google AI Studio.  Checks a Valkey monthly cost
counter before each call; skips API call and returns None if cap is exceeded.

**Atomicity (G-005 / PLAN-0031 C-2)**: Cost cap enforcement uses an atomic
INCRBYFLOAT-then-check pattern.  The estimated call cost is *reserved* (atomically
incremented) BEFORE the API call.  If the post-increment total meets or exceeds
the cap, the reservation is immediately undone.  After the API call completes,
the reserved amount is adjusted to the actual cost.  This prevents the race
condition where two concurrent callers both pass a non-atomic GET check and
both proceed past the cap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from ml_clients.errors import FatalError, RetryableError

if TYPE_CHECKING:
    import asyncio

    from ml_clients.description_client import CostTrackerProtocol

logger = structlog.get_logger()

_DEFAULT_MODEL_ID = "gemini-3.1-flash-lite"
_DEFAULT_MAX_MONTHLY_USD = 10.0

# Approximate pricing for gemini-3.1-flash-lite (as of 2026-04)
# $0.000075 / 1K input tokens  +  $0.0003 / 1K output tokens
_INPUT_COST_PER_TOKEN = 0.000075 / 1000
_OUTPUT_COST_PER_TOKEN = 0.0003 / 1000

# Cost key prefix (Valkey); full key: s7:desc:cost:{YYYY-MM}
_COST_KEY_PREFIX = "s7:desc:cost"

# Transient error type names from google-genai SDK
_RETRYABLE_GEMINI_ERRORS = frozenset(
    {
        "ResourceExhausted",
        "ServiceUnavailable",
        "DeadlineExceeded",
        "InternalServerError",
        "TooManyRequests",
    }
)

# Default output token estimate for pre-reservation cost calculation
_DEFAULT_ESTIMATED_OUTPUT_TOKENS = 150


def _month_key() -> str:
    """Return current UTC month as YYYY-MM string."""
    now = datetime.now(tz=UTC)
    return f"{_COST_KEY_PREFIX}:{now.strftime('%Y-%m')}"


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost from token counts."""
    return (input_tokens * _INPUT_COST_PER_TOKEN) + (output_tokens * _OUTPUT_COST_PER_TOKEN)


class GeminiDescriptionAdapter:
    """Generates entity descriptions via Google Gemini AI Studio (gemini-3.1-flash-lite).

    Args:
        api_key:          Google AI Studio API key.
        model_id:         Model ID override (default: gemini-3.1-flash-lite).
        semaphore:        Concurrency limiter (must be provided, keyword-only).
        cost_tracker:     Valkey client for monthly cost tracking (optional).
        max_monthly_usd:  Monthly spend cap in USD (default: $10.0).
    """

    def __init__(
        self,
        api_key: str,
        model_id: str = _DEFAULT_MODEL_ID,
        *,
        semaphore: asyncio.Semaphore,
        cost_tracker: CostTrackerProtocol | None = None,
        max_monthly_usd: float = _DEFAULT_MAX_MONTHLY_USD,
    ) -> None:
        self._api_key = api_key
        self._model_id = model_id
        self._semaphore = semaphore
        self._cost_tracker = cost_tracker
        self._max_monthly_usd = max_monthly_usd
        self._genai_client: object | None = None  # Lazy: initialized on first generate call

    async def generate_description(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str,
        context_hints: dict[str, str],
    ) -> str | None:
        """Generate a world-knowledge description for a non-company entity.

        Returns None (without calling the API) if the monthly cost cap is exceeded.

        Cost cap uses an atomic reserve-then-check pattern (G-005 fix):
        1. INCRBYFLOAT atomically reserves estimated cost
        2. If post-increment total >= cap → undo reservation, return None
        3. After API call → adjust reservation to actual cost
        """
        # Build prompt first — needed for cost estimation
        prompt = self._build_prompt(canonical_name, entity_type, context_hints)

        # ---- Atomic cost-cap reserve ----
        reserved, estimated_cost = await self._reserve_cost(prompt)
        if not reserved:
            logger.warning(
                "gemini_description_cost_cap_exceeded",
                entity_id=entity_id,
                max_monthly_usd=self._max_monthly_usd,
            )
            return None

        if self._genai_client is None:
            try:
                from google import genai
            except ImportError as exc:
                # Undo reservation on fatal init error
                await self._undo_reservation(estimated_cost)
                raise FatalError("google-genai package not installed; install ml-clients[gemini]") from exc
            self._genai_client = genai.Client(api_key=self._api_key)

        async with self._semaphore:
            try:
                response = await self._genai_client.aio.models.generate_content(  # type: ignore[union-attr]
                    model=self._model_id,
                    contents=prompt,
                )
                description: str = response.text.strip()

                # ---- Adjust reservation to actual cost ----
                await self._adjust_cost(estimated_cost, response, prompt)

                logger.info(
                    "gemini_description_generated",
                    entity_id=entity_id,
                    entity_type=entity_type,
                    model_id=self._model_id,
                )
                return description or None

            except (RetryableError, FatalError):
                # Undo reservation — the API call failed, no cost incurred
                await self._undo_reservation(estimated_cost)
                raise
            except Exception as exc:
                # Undo reservation — the API call failed
                await self._undo_reservation(estimated_cost)
                if type(exc).__name__ in _RETRYABLE_GEMINI_ERRORS:
                    raise RetryableError(f"Gemini transient error: {exc}") from exc
                raise FatalError(f"Gemini error: {exc}") from exc

    # ------------------------------------------------------------------
    # Internals — atomic cost cap (G-005 / PLAN-0031 C-2)
    # ------------------------------------------------------------------

    async def _reserve_cost(self, prompt: str) -> tuple[bool, float]:
        """Atomically reserve estimated call cost via INCRBYFLOAT.

        Returns ``(allowed, estimated_cost)``.  If the post-increment total
        meets or exceeds the cap (with 5 % safety margin), the reservation
        is immediately undone and ``allowed`` is False.

        INCRBYFLOAT is atomic in Redis/Valkey — the returned value reflects
        the exact post-increment state, so concurrent callers each see their
        own incremented total and make correct cap decisions.
        """
        if self._cost_tracker is None:
            return True, 0.0

        estimated = _estimate_cost(len(prompt) // 4, _DEFAULT_ESTIMATED_OUTPUT_TOKENS)
        key = _month_key()
        cap_threshold = self._max_monthly_usd * 0.95  # 5 % safety margin

        try:
            new_total = await self._cost_tracker.incrbyfloat(key, estimated)
            if new_total >= cap_threshold:
                # Over cap — undo the reservation atomically
                await self._cost_tracker.incrbyfloat(key, -estimated)
                return False, estimated
            return True, estimated
        except Exception as exc:
            # Valkey unavailable — fail-open (allow the call)
            logger.warning("gemini_cost_reserve_failed", error=str(exc))
            return True, 0.0

    async def _adjust_cost(self, estimated: float, response: object, prompt: str) -> None:
        """Adjust the reserved amount to reflect actual API cost.

        If the actual cost differs from the pre-reserved estimate, a
        corrective INCRBYFLOAT is applied (positive or negative delta).
        """
        if self._cost_tracker is None or estimated == 0.0:
            return

        try:
            usage = getattr(response, "usage_metadata", None)
            input_tokens: int = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens: int = getattr(usage, "candidates_token_count", 0) or 0
        except Exception:
            input_tokens = len(prompt) // 4
            output_tokens = _DEFAULT_ESTIMATED_OUTPUT_TOKENS

        actual = _estimate_cost(input_tokens, output_tokens)
        delta = actual - estimated
        if abs(delta) < 0.000001:
            return
        try:
            await self._cost_tracker.incrbyfloat(_month_key(), delta)
        except Exception as exc:
            logger.warning("gemini_cost_adjust_failed", error=str(exc))

    async def _undo_reservation(self, estimated_cost: float) -> None:
        """Undo a pre-reserved cost (e.g. on API call failure)."""
        if self._cost_tracker is None or estimated_cost == 0.0:
            return
        try:
            await self._cost_tracker.incrbyfloat(_month_key(), -estimated_cost)
        except Exception as exc:
            logger.warning("gemini_cost_undo_failed", error=str(exc))

    @staticmethod
    def _build_prompt(canonical_name: str, entity_type: str, context_hints: dict[str, str]) -> str:
        """Build the entity description prompt.

        ``canonical_name`` and context values are XML-wrapped to prevent prompt
        injection (PRD-0017 §8 security requirement).
        """
        # Truncate inputs to safe bounds before interpolation
        safe_name = canonical_name[:256]
        safe_type = entity_type[:64]
        hints_str = (
            "; ".join(f"{k[:64]}: {str(v)[:256]}" for k, v in context_hints.items()) if context_hints else "none"
        )
        return (
            f"Write a concise 2-3 sentence factual description of "
            f"<entity_name>{safe_name}</entity_name> "
            f"(entity type: <entity_type>{safe_type}</entity_type>). "
            f"Additional context: {hints_str}. "
            "Focus on what this entity is, its significance, and its primary domain. "
            "Do not include opinions or speculation. "
            "Respond with only the description text, no JSON, no markdown."
        )
