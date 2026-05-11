"""Port ABC for entity-context loading (PLAN-0074 Wave F, T-F-01).

R12: No infrastructure imports in the domain/application layer.
The concrete implementation (EntityContextClient) lives in
``infrastructure/clients/entity_context_client.py`` and is injected
at construction time via this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from rag_chat.domain.entities.entity_chat_context import EntityChatContext


class EntityContextLoaderPort(ABC):
    """Abstract port for loading enriched entity context from S7.

    The implementing class is responsible for:
    - Making parallel HTTP calls to S7's intelligence + graph endpoints.
    - Mapping the raw responses to EntityChatContext.
    - Returning ``EntityChatContext(entity_id=..., is_empty=True)`` on any
      failure (404, 5xx, timeout) instead of raising exceptions.
      This keeps the use case free from error-handling concerns.
    """

    @abstractmethod
    async def load(
        self,
        entity_id: UUID,
        tenant_id: UUID | None,
        jwt_token: str,
    ) -> EntityChatContext:
        """Load entity intelligence context from S7.

        Args:
            entity_id:  UUID of the entity whose context to load.
            tenant_id:  Optional tenant UUID forwarded to S7 for multi-tenant
                        filtering.  May be None for public (non-tenanted) entities.
            jwt_token:  RS256 internal JWT forwarded in X-Internal-JWT header.
                        Required by S7's InternalJWTMiddleware.

        Returns:
            Populated EntityChatContext on success.
            EntityChatContext with is_empty=True on any failure — callers MUST
            handle is_empty gracefully (use a generic prompt instead).
        """
