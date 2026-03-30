"""Abstract repository interfaces (ports) for the Alert application layer.

Use cases depend only on these ABCs; never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from alert.domain.entities import DeadLetterEntry


class DLQRepositoryPort(ABC):
    """Port for DLQ admin operations (list, inspect, resolve)."""

    @abstractmethod
    async def list_failed(self, limit: int = 50, offset: int = 0) -> list[DeadLetterEntry]: ...

    @abstractmethod
    async def get_by_id(self, dlq_id: UUID) -> DeadLetterEntry | None: ...

    @abstractmethod
    async def resolve(self, dlq_id: UUID, resolution_note: str) -> bool: ...

    @abstractmethod
    async def commit(self) -> None: ...
