"""GenerateBriefingUseCase — internal briefing endpoint logic (T-B-2-04, PRD-0016 §6.2).

Called by S10 email scheduler to generate a portfolio risk narrative for digest emails.

Auth:       X-Internal-Token validated via hmac.compare_digest (constant-time).
Rate limit: 100 requests/day per user_id (Valkey counter with midnight-aligned key).
LLM:        EMAIL_DEEP_BRIEF_PROMPT via LLMProviderChain (collects full stream).
"""

from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from rag_chat.application.pipeline.prompts.intent_prompts import EMAIL_DEEP_BRIEF_PROMPT
from rag_chat.domain.errors import BriefingAuthError, RateLimitExceededError

if TYPE_CHECKING:
    from uuid import UUID

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
    from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_DAILY_RATE_LIMIT = 100
_BRIEFING_RL_PREFIX = "rag:v1:briefing:rl"
_BRIEFING_RL_TTL = 90_000  # 25 hours — covers DST edge cases


class GenerateBriefingUseCase:
    """Generate an AI-narrative portfolio risk brief for email delivery.

    Args:
        llm_chain:              LLM provider chain (DeepInfra → OpenRouter → Ollama).
        internal_service_token: Expected value of the X-Internal-Token header.
        valkey:                 Valkey client for daily rate-limit counters.
    """

    def __init__(
        self,
        llm_chain: LLMProviderChain,
        internal_service_token: str,
        valkey: ValkeyClient,  # type: ignore[name-defined]
    ) -> None:
        self._llm_chain = llm_chain
        self._token = internal_service_token
        self._valkey = valkey

    async def execute(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        portfolio_context: dict[str, Any],
        market_snapshots: list[dict[str, Any]],
        active_signals: list[dict[str, Any]],
        lookback_days: int,
        token: str,
    ) -> dict[str, Any]:
        """Run the briefing pipeline.

        Returns a dict with keys: narrative, risk_summary, citations, generated_at.

        Raises:
            BriefingAuthError:      Token missing or incorrect.
            RateLimitExceededError: User has exceeded 100 briefings today.
            ProviderUnavailableError: All LLM providers failed.
        """
        # ── 1. Auth ───────────────────────────────────────────────────────────
        if not self._token or not hmac.compare_digest(token, self._token):
            raise BriefingAuthError("Invalid or missing X-Internal-Token")

        # ── 2. Daily rate limit (100/day per user_id) ─────────────────────────
        await self._check_daily_rate_limit(user_id)

        # ── 3. Build prompt ───────────────────────────────────────────────────
        prompt = self._build_prompt(
            user_id=user_id,
            tenant_id=tenant_id,
            portfolio_context=portfolio_context,
            market_snapshots=market_snapshots,
            active_signals=active_signals,
            lookback_days=lookback_days,
        )

        # ── 4. LLM completion (collect streaming tokens) ─────────────────────
        chunks: list[str] = []
        async for chunk in self._llm_chain.stream(
            prompt,
            max_tokens=6000,
            temperature=0.1,
        ):
            chunks.append(chunk)
        narrative = "".join(chunks)

        # ── 5. Derive risk_summary from input signals ─────────────────────────
        risk_summary = self._build_risk_summary(
            portfolio_context=portfolio_context,
            active_signals=active_signals,
        )

        generated_at = datetime.now(tz=UTC).isoformat()

        log.info(  # type: ignore[no-any-return]
            "briefing_generated",
            user_id=str(user_id),
            tenant_id=str(tenant_id),
            narrative_chars=len(narrative),
        )

        return {
            "narrative": narrative,
            "risk_summary": risk_summary,
            "citations": [],
            "generated_at": generated_at,
        }

    async def _check_daily_rate_limit(self, user_id: UUID) -> None:
        """Increment the daily briefing counter and raise if over limit.

        Key format: ``rag:v1:briefing:rl:{user_id}:{YYYY-MM-DD}`` (UTC date).
        TTL is 25 hours to cover DST transitions.
        """
        today = datetime.now(tz=UTC).date().isoformat()
        key = f"{_BRIEFING_RL_PREFIX}:{user_id}:{today}"

        count = await self._valkey.incr(key)
        if count == 1:
            # First request today — set expiry
            await self._valkey.expire(key, _BRIEFING_RL_TTL)

        if count > _DAILY_RATE_LIMIT:
            raise RateLimitExceededError(
                f"Briefing rate limit exceeded: {count} requests today (limit: {_DAILY_RATE_LIMIT})"
            )

    def _build_prompt(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        portfolio_context: dict[str, Any],
        market_snapshots: list[dict[str, Any]],
        active_signals: list[dict[str, Any]],
        lookback_days: int,
    ) -> str:
        """Assemble the EMAIL_DEEP_BRIEF prompt with XML-wrapped context."""
        context_block = (
            f"<portfolio_context>\n{json.dumps(portfolio_context, indent=2)}\n</portfolio_context>\n\n"
            f"<market_snapshots lookback_days='{lookback_days}'>\n"
            f"{json.dumps(market_snapshots, indent=2)}\n</market_snapshots>\n\n"
        )
        if active_signals:
            context_block += f"<active_signals>\n{json.dumps(active_signals, indent=2)}\n</active_signals>\n\n"

        return (
            f"{EMAIL_DEEP_BRIEF_PROMPT}\n\n"
            f"<context>\n{context_block}</context>\n\n"
            f"Generate the portfolio risk brief for user {user_id} (tenant {tenant_id})."
        )

    def _build_risk_summary(
        self,
        *,
        portfolio_context: dict[str, Any],
        active_signals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Derive a structured risk summary from input data (no extra LLM call).

        Computes a simple concentration score from portfolio positions if available.
        """
        positions: list[dict[str, Any]] = portfolio_context.get("positions", [])

        # Concentration score: 1.0 = fully concentrated in one position
        concentration_score: float = 0.0
        sector_breakdown: dict[str, float] = {}
        if positions:
            total_value = sum(float(p.get("value", 0)) for p in positions)
            if total_value > 0:
                weights = [float(p.get("value", 0)) / total_value for p in positions]
                # Herfindahl-Hirschman Index normalised to [0, 1]
                concentration_score = round(sum(w * w for w in weights), 4)

            for pos in positions:
                sector = str(pos.get("sector", "unknown"))
                value = float(pos.get("value", 0))
                sector_breakdown[sector] = round(
                    sector_breakdown.get(sector, 0.0) + (value / total_value if total_value > 0 else 0.0),
                    4,
                )

        top_risk_signals = [
            {"signal_id": str(s.get("id", "")), "description": str(s.get("description", ""))}
            for s in active_signals[:5]  # cap at 5 top signals
        ]

        return {
            "concentration_score": concentration_score,
            "top_risk_signals": top_risk_signals,
            "sector_breakdown": sector_breakdown,
        }
