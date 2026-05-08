"""TriggerNarrativeGenerationUseCase — rate-limited manual narrative trigger.

R25 compliance: wraps Valkey + GenerateNarrativeUseCase so the API route never
imports from the infrastructure layer.
BP-200: uses set_nx() — NOT set(..., nx=True) — to avoid the kwargs signature mismatch
that silently disables rate-limiting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from knowledge_graph.application.use_cases.generate_narrative import GenerateNarrativeUseCase
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Rate-limit window: one manual generation per entity+tenant+user per hour.
_RATE_LIMIT_TTL_S = 3600


class TriggerNarrativeGenerationUseCase:
    """Rate-limited manual narrative generation trigger.

    Args:
        valkey:          ValkeyClient for rate-limit state.
        generate_uc:     GenerateNarrativeUseCase to actually run generation.

    The rate limit key is:
        ``narrative_gen:{tenant_id}:{entity_id}:{user_id}``
    Set with NX + EX=3600 so the key auto-expires after one hour.
    """

    def __init__(
        self,
        valkey: ValkeyClient,
        generate_uc: GenerateNarrativeUseCase,
    ) -> None:
        self._valkey = valkey
        self._generate_uc = generate_uc

    async def execute(
        self,
        entity_id: UUID,
        tenant_id: UUID | None,
        user_id: str,
    ) -> bool:
        """Attempt to queue narrative generation.

        Returns:
            True  — generation was queued (rate limit key was newly set).
            False — rate limit hit (key already exists; caller should 429).

        BP-200: uses ``set_nx(key, val, ex=N)`` explicitly — never ``set(..., nx=True)``
        which uses a different kwargs signature on ValkeyClient that does NOT pass nx=True
        to the underlying redis-py call (BP-200 pattern).
        """
        tenant_str = str(tenant_id) if tenant_id else "global"
        rate_key = f"narrative_gen:{tenant_str}:{entity_id}:{user_id}"

        # set_nx returns True when the key was newly created (not rate-limited),
        # False when the key already existed (rate-limited).
        allowed = await self._valkey.set_nx(rate_key, "1", ex=_RATE_LIMIT_TTL_S)

        if not allowed:
            logger.info(  # type: ignore[no-any-return]
                "narrative_generation_rate_limited",
                entity_id=str(entity_id),
                tenant_id=tenant_str,
                user_id=user_id,
            )
            return False

        # Fire-and-forget: asyncio.create_task so the response is immediate (202).
        import asyncio

        from knowledge_graph.domain.narrative import NarrativeGenerationReason

        asyncio.create_task(  # noqa: RUF006 — intentional fire-and-forget for manual trigger
            self._generate_uc.execute(
                entity_id=entity_id,
                tenant_id=tenant_id,
                reason=NarrativeGenerationReason.MANUAL_TRIGGER.value,
            )
        )

        logger.info(  # type: ignore[no-any-return]
            "narrative_generation_queued",
            entity_id=str(entity_id),
            tenant_id=tenant_str,
            user_id=user_id,
        )
        return True
