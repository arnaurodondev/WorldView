"""Port (Protocol) for entity-mention persistence.

PLAN-0053 platform-stability iter-1 F-PLATFORM-02: api/dependencies.py
previously imported the concrete ``EntityMentionRepository`` from the
infrastructure layer at module level so that ``Annotated[Repo, Depends(...)]``
could resolve. That violates LAYER-API-NO-MODULE-LEVEL-INFRA. By defining
a structural Protocol here the API layer can declare ``Annotated[Port, ...]``
without ever touching infrastructure — the concrete repository lives in
``infrastructure/nlp_db/repositories/entity_mention.py`` and structurally
implements this Protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from uuid import UUID

    from nlp_pipeline.domain.models import EntityMention


@runtime_checkable
class EntityMentionRepositoryPort(Protocol):
    """Persistence contract for entity mentions.

    Only the public methods used by the API layer are defined here. Adding
    new repository methods does NOT require changing this protocol unless
    the API needs them — the protocol is intentionally narrow.
    """

    async def add(self, mention: EntityMention) -> None: ...

    async def add_batch(self, mentions: list[EntityMention]) -> None: ...

    async def get_by_doc(self, doc_id: UUID) -> list: ...

    async def get_articles_for_entity(
        self,
        entity_id: UUID,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...
