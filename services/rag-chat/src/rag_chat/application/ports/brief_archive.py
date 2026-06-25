"""BriefArchivePort — application-layer interface for brief persistence (PLAN-0066 Wave A T-W10-A-03).

WHY Protocol (not ABC): the worldview convention for ports that need structural
subtyping is typing.Protocol (see PLAN-0076 §9.1, R25). Protocol lets the
infrastructure layer implement the interface without importing from the
application layer, keeping the dependency arrow pointing inward.

WHY @runtime_checkable: the DI container (or tests) can use isinstance() checks
to verify that a registered adapter actually satisfies the port before startup.
This catches misconfiguration at boot rather than at runtime.

WHY UserBriefRecord as a frozen dataclass (not a Pydantic model): the domain
convention is frozen dataclasses (see PLAN-0083, BP-405). Pydantic is strictly
an API-layer tool; the domain and application layers are Pydantic-free.

WHY NullBriefArchive: provides a safe no-op default when brief persistence is
not configured (e.g. during unit tests that don't need a real DB). The DI
container registers NullBriefArchive by default; production wires in
SqlBriefArchive (PLAN-0066 Wave B).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, kw_only=True)
class UserBriefRecord:
    """Immutable application-layer representation of a persisted brief.

    WHY frozen: the record is a read/write DTO between use cases and the archive
    adapter. Making it frozen prevents accidental in-place mutation after
    retrieval, which would otherwise create a subtle divergence between the
    in-memory object and the persisted row.

    WHY kw_only: forces callers to name every field explicitly, making future
    field additions non-breaking (callers use keyword syntax, so adding a new
    field with a default does not break existing instantiation sites).

    Field notes:
      generated_at  — must be UTC-aware (R11); the use case must pass
                      ``common.time.utc_now()`` or an explicit ``timezone.utc``
                      datetime. The ORM adapter stores it as TIMESTAMPTZ.
      sections_json — list[dict] round-tripped from list[BriefSection.to_dict()]
      citations_json — list[dict] round-tripped from list[BriefCitation.to_dict()]
      source_version — pipeline version tag, used for cache invalidation logic.
    """

    id: UUID
    user_id: UUID
    tenant_id: UUID
    # WHY str not Enum: brief_type is extensible without a schema migration;
    # the Protocol contract is the only enforcement boundary.
    brief_type: str
    entity_id: UUID | None
    generated_at: datetime  # UTC-aware (R11)
    headline: str
    lead: str | None
    sections_json: list[dict]
    citations_json: list[dict]
    confidence: float
    source_version: str


@runtime_checkable
class BriefArchivePort(Protocol):
    """Port for storing and retrieving generated briefs.

    Implementations (SqlBriefArchive, NullBriefArchive) live in
    rag_chat.infrastructure and are wired by the DI container.

    WHY get_latest vs get_history: callers that need the current brief use
    get_latest(limit=2) — fast index-only scan on (user_id, generated_at DESC).
    Callers that need paginated history (e.g. history panel) use get_history,
    which returns a (rows, total) tuple matching the standard worldview
    pagination contract.
    """

    async def save(self, brief: UserBriefRecord) -> None:
        """Persist a new brief record.

        The caller is responsible for supplying a UUIDv7 id (via
        common.ids.new_uuid7()) and a UTC-aware generated_at timestamp
        (via common.time.utc_now()). Raises on DB error.
        """
        ...

    async def get_latest(
        self,
        user_id: UUID,
        tenant_id: UUID,
        brief_type: str,
        limit: int = 2,
    ) -> list[UserBriefRecord]:
        """Return the most-recent ``limit`` briefs for a user+tenant+type combo.

        Used by the morning brief cache check: fetch the newest 2 rows and
        decide whether a fresh generation is needed. Returns [] when no rows
        exist — callers must handle the empty case.
        """
        ...

    async def get_history(
        self,
        user_id: UUID,
        tenant_id: UUID,
        brief_type: str,
        page: int,
        page_size: int,
    ) -> tuple[list[UserBriefRecord], int]:
        """Return paginated brief history and total row count.

        Follows the standard worldview pagination contract:
          page      — 1-based page number
          page_size — rows per page
          returns   — (rows_for_this_page, total_matching_rows)
        """
        ...

    async def get_by_id(self, brief_id: UUID) -> UserBriefRecord | None:
        """Return a single brief by its primary key, or None if not found."""
        ...

    async def get_latest_entity_brief(
        self,
        entity_id: UUID,
        limit: int = 1,
    ) -> list[UserBriefRecord]:
        """Return the most-recent entity-scoped briefs for ``entity_id``.

        WHY this exists (AI-brief-flag fix, 2026-06-19): the on-demand and
        pre-gen instrument-brief paths need a CROSS-USER freshness/idempotency
        check keyed by ``(brief_type='entity', entity_id)`` — the same key the
        ``GetAiBriefFlagUseCase`` (and therefore the screener ``has_ai_brief``
        column) queries by. ``get_latest`` keys on ``(user_id, tenant_id,
        brief_type)`` and so cannot answer "has ANYONE generated a brief for
        this instrument recently?". This method answers exactly that question.

        Note: ``entity_id`` here is the value the flag matches on — i.e. the
        market-data ``instrument_id`` the screener uses, NOT necessarily the KG
        entity id (see BriefingContext.resolved_instrument_id).

        Returns [] when no entity brief exists for the id.
        """
        ...


class NullBriefArchive:
    """No-op implementation of BriefArchivePort.

    WHY exists: the DI container registers this as the default archive adapter
    so that services that have not yet configured brief persistence (e.g. during
    unit tests or local dev without a DB) still start successfully. All methods
    are safe to call — they silently discard writes and return empty results.

    Production wires SqlBriefArchive (PLAN-0066 Wave B) in its place.
    """

    async def save(self, brief: UserBriefRecord) -> None:
        # WHY silent no-op: NullBriefArchive is a deliberate opt-out, not an
        # error. Tests that need to verify saves use a mock or SqlBriefArchive.
        return

    async def get_latest(
        self,
        user_id: UUID,
        tenant_id: UUID,
        brief_type: str,
        limit: int = 2,
    ) -> list[UserBriefRecord]:
        return []

    async def get_history(
        self,
        user_id: UUID,
        tenant_id: UUID,
        brief_type: str,
        page: int,
        page_size: int,
    ) -> tuple[list[UserBriefRecord], int]:
        return [], 0

    async def get_by_id(self, brief_id: UUID) -> UserBriefRecord | None:
        return None

    async def get_latest_entity_brief(
        self,
        entity_id: UUID,
        limit: int = 1,
    ) -> list[UserBriefRecord]:
        return []
