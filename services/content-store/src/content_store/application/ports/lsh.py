"""LSH client port interface for the Content Store application layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from content_store.domain.entities import DeduplicationDecision


class LSHClientPort(ABC):
    """Port for Valkey-backed LSH near-duplicate detection (Stage C)."""

    @abstractmethod
    async def query(
        self,
        signature: list[int],
        source_type: str,
        source_name: str | None = None,
        fetch_signature: Callable[[str], Awaitable[list[int] | None]] | None = None,
    ) -> DeduplicationDecision: ...

    @abstractmethod
    async def index(
        self,
        doc_id: UUID,
        signature: list[int],
        source_type: str,
        source_name: str = "",
    ) -> None: ...
