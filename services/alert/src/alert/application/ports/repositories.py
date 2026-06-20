"""Abstract repository interfaces (ports) for the Alert application layer.

Use cases depend only on these ABCs; never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from datetime import datetime

    from alert.domain.entities import Alert, AlertRule, DeadLetterEntry, EmailPreference, OutboxEvent, PendingAlert
    from alert.domain.enums import AlertSeverity, RuleType


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
    """Port for alert reads + ack/snooze writes (PLAN-0051 T-D-4-02)."""

    @abstractmethod
    async def get_by_id(self, alert_id: UUID) -> Alert | None: ...

    @abstractmethod
    async def acknowledge(
        self,
        alert_id: UUID,
        user_id: UUID,
        ack_time: datetime | None = None,
    ) -> bool:
        """Mark an alert acknowledged. Idempotent — returns False if already acked."""

    @abstractmethod
    async def snooze(self, alert_id: UUID, snooze_until: datetime) -> bool:
        """Set ``snooze_until``. Returns True iff a row was updated."""

    @abstractmethod
    async def list_history(
        self,
        tenant_id: UUID,
        *,
        status: str = "all",
        severity: AlertSeverity | None = None,
        entity_id: UUID | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Alert]:
        """Return alerts in tenant history matching filters, newest first."""

    @abstractmethod
    async def count_history(
        self,
        tenant_id: UUID,
        *,
        status: str = "all",
        severity: AlertSeverity | None = None,
        entity_id: UUID | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> int:
        """Return the count of alerts in tenant history matching the filters.

        Used to back canonical pagination — the API needs the universe size to
        decide whether more pages exist (QA-iter1 C-3). Mirrors the same
        WHERE-clause semantics as ``list_history`` (sans LIMIT/OFFSET).
        """


class PendingAlertRepositoryPort(ABC):
    """Port for pending alert operations."""

    @abstractmethod
    async def list_by_user(
        self,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
        min_severities: list[str] | None = None,
    ) -> list[PendingAlert]: ...

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


class IAlertRuleRepository(ABC):
    """Port for ``alert_rules`` persistence (PLAN-0113, R25 ABC).

    Use cases depend only on this interface; the concrete ``AlertRuleRepository``
    is wired in the DI factory layer.
    """

    @abstractmethod
    async def save(self, rule: AlertRule) -> None:
        """Insert a new rule row (flush, no commit — route/UoW owns the txn)."""

    @abstractmethod
    async def get_by_id(self, rule_id: UUID, tenant_id: UUID, user_id: UUID) -> AlertRule | None:
        """Fetch a rule scoped to its owner; None if missing or not owned."""

    @abstractmethod
    async def list_by_owner(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        enabled: bool | None = None,
        rule_type: RuleType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AlertRule]:
        """List the owner's rules with optional filters, newest first."""

    @abstractmethod
    async def count_by_owner(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        enabled: bool | None = None,
        rule_type: RuleType | None = None,
    ) -> int:
        """Count the owner's rules matching the same filters as ``list_by_owner``."""

    @abstractmethod
    async def update(self, rule: AlertRule) -> bool:
        """Persist a mutated rule (owner-scoped). Returns True iff a row updated."""

    @abstractmethod
    async def delete(self, rule_id: UUID, tenant_id: UUID, user_id: UUID) -> bool:
        """Delete an owned rule. Returns True iff a row was removed."""

    @abstractmethod
    async def list_enabled_by_type(self, rule_type: RuleType) -> list[AlertRule]:
        """All enabled rules of a type across all owners (poller scan)."""


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
