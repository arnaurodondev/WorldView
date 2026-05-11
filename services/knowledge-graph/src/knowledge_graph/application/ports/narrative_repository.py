"""Port interface for entity narrative version reads and writes (PRD-0074 §9.1).

Use cases depend only on this ABC — never on infrastructure classes directly.
No infrastructure imports are permitted in this module (R12).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from knowledge_graph.domain.narrative import EntityNarrativeVersion


class NarrativeRepositoryPort(ABC):
    """Read and write access to ``entity_narrative_versions``.

    All mutating operations accept an :class:`AsyncSession` (passed in from the
    use case) so the caller controls the transaction boundary (R27).
    Read-only operations use an injected session-factory internally.
    """

    @abstractmethod
    async def find_current(
        self,
        entity_id: UUID,
        tenant_id: UUID | None = None,
    ) -> EntityNarrativeVersion | None:
        """Return the current (``is_current=True``) narrative version for an entity.

        Returns ``None`` when no current version exists (entity has never had a
        narrative generated, or all versions have been superseded without promotion).

        Args:
        ----
            entity_id: Target canonical entity UUID.
            tenant_id: Optional tenant filter; when ``None`` all tenants match.

        """

    @abstractmethod
    async def find_by_input_snapshot(
        self,
        entity_id: UUID,
        snapshot_hash: str,
    ) -> EntityNarrativeVersion | None:
        """Idempotency check — find a version whose input snapshot matches *snapshot_hash*.

        *snapshot_hash* is computed by the caller as
        ``sha256(json.dumps(input_snapshot, sort_keys=True, default=str))``.

        Returns ``None`` when no matching version exists, which means the caller
        should proceed with generation (inputs have changed or no prior version).

        Args:
        ----
            entity_id:      Target canonical entity UUID.
            snapshot_hash:  SHA-256 hex digest of the canonical JSON-serialised
                            ``input_snapshot`` dict.

        """

    @abstractmethod
    async def list_versions(
        self,
        entity_id: UUID,
        tenant_id: UUID | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[EntityNarrativeVersion], str | None]:
        """Return paginated version history for an entity, newest first.

        Cursor-based pagination: *cursor* is a base64-encoded string of the form
        ``"<generated_at_iso>|<version_id>"``.  When ``None``, pagination starts
        from the most recent version.

        Returns a ``(versions, next_cursor)`` tuple where ``next_cursor`` is
        ``None`` when there are no more pages.

        Args:
        ----
            entity_id:  Target canonical entity UUID.
            tenant_id:  Optional tenant filter.
            limit:      Maximum versions to return (1-100).
            cursor:     Opaque pagination token from the previous page.

        """

    @abstractmethod
    async def insert_and_promote(
        self,
        version: EntityNarrativeVersion,
        session: AsyncSession,
        health_score: float | None = None,
    ) -> None:
        """Persist a new narrative version and promote it to ``is_current=True``.

        Sequence (all within the caller-supplied *session* transaction):
          1. INSERT new row with ``is_current=False``.
          2. UPDATE the existing ``is_current=True`` row → ``is_current=False``
             (for the same ``entity_id``).
          3. UPDATE the newly inserted row → ``is_current=True``.
          4. UPDATE ``canonical_entities SET current_narrative_version_id=?,
             health_score=?`` for the entity.

        The caller is responsible for committing the session.

        Args:
        ----
            version:      The new narrative version to persist and promote.
            session:      Open :class:`AsyncSession` (caller owns the transaction).
            health_score: Optional updated health score to set on the canonical entity.

        """
