"""Abstract repository interfaces (ports) for the Alert application layer.

Use cases depend only on these ABCs; never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from alert.domain.entities import Alert, DeadLetterEntry, EmailPreference, OutboxEvent, PendingAlert


class DLQRepositoryPort(ABC):
    """Port for DLQ admin operations (list, inspect, resolve)."""

    @abstractmethod
    async def list_failed(self, limit: int = 50, offset: int = 0) -> list[DeadLetterEntry]: ...

    @abstractmethod
    async def count_failed(self) -> int: ...

    @abstractmethod
    async def get_by_id(self, dlq_id: UUID) -> DeadLetterEntry | None: ...

    @abstractmethod
    async def resolve(self, dlq_id: UUID, resolution_note: str) -> bool: ...

    @abstractmethod
    async def commit(self) -> None: ...


class AlertRepositoryPort(ABC):
    """Port for alert reads."""

    @abstractmethod
    async def get_by_id(self, alert_id: UUID) -> Alert | None: ...


class PendingAlertRepositoryPort(ABC):
    """Port for pending alert operations."""

    @abstractmethod
    async def list_by_user(self, user_id: UUID, limit: int = 50, offset: int = 0) -> list[PendingAlert]: ...

    @abstractmethod
    async def acknowledge(self, user_id: UUID, alert_id: UUID) -> bool: ...

    @abstractmethod
    async def save(self, pending: PendingAlert) -> None: ...


class DedupRepositoryPort(ABC):
    """Port for dedup key lookups."""

    @abstractmethod
    async def exists(self, dedup_key: str) -> bool: ...


class OutboxRepositoryPort(ABC):
    """Port for outbox event appends."""

    @abstractmethod
    async def append(self, event: OutboxEvent) -> None: ...


class AlertSaveRepositoryPort(ABC):
    """Port for alert saves (includes dedup_key unique constraint)."""

    @abstractmethod
    async def save(self, alert: Alert) -> None: ...


class EmailPreferenceRepositoryPort(ABC):
    """Port for email preference read/write operations."""

    @abstractmethod
    async def get_by_user(self, user_id: UUID, tenant_id: UUID) -> EmailPreference | None: ...

    @abstractmethod
    async def upsert(self, pref: EmailPreference) -> None: ...

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def list_scheduled_users(self, day: int, hour: int) -> list[EmailPreference]: ...
