"""Repository port interfaces for the market-ingestion bounded context.

These are application-layer contracts. Infrastructure implements them.
Do NOT import SQLAlchemy or any DB library here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Sequence

    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.domain.entities.polling_policy import PollingPolicy
    from market_ingestion.domain.entities.provider_budget import ProviderBudget
    from market_ingestion.domain.entities.watermark import Watermark
    from market_ingestion.domain.enums import DatasetType, Provider
    from market_ingestion.domain.events import DomainEvent

# ---------------------------------------------------------------------------
# Shared DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    """Minimal representation of a persisted outbox message.

    Infrastructure-agnostic: does not depend on Kafka or SQLAlchemy.
    The payload is stored as bytes for serialization independence.
    """

    id: str | UUID
    topic: str
    key: bytes | None
    payload: bytes
    headers: dict[str, str]
    event_type: str
    created_at: datetime
    correlation_id: str | None
    attempt: int


# ---------------------------------------------------------------------------
# Repository ABCs
# ---------------------------------------------------------------------------


class TaskRepository(ABC):
    """Persistence port for IngestionTask entities."""

    @abstractmethod
    async def get(self, task_id: str) -> IngestionTask | None:
        """Get a task by ID. Returns None if not found."""

    @abstractmethod
    async def add(self, task: IngestionTask) -> None:
        """Add a new task (idempotent via dedupe_key ON CONFLICT DO NOTHING)."""

    @abstractmethod
    async def add_many(self, tasks: Sequence[IngestionTask]) -> int:
        """Add multiple tasks idempotently. Returns count actually inserted."""

    @abstractmethod
    async def save(self, task: IngestionTask, *, original_lease_owner: str | None = None) -> None:
        """Persist changes to an existing task.

        ``original_lease_owner`` should be set to the worker-id that held the
        lease *before* the domain transition (retry/fail/succeed) cleared it.
        The WHERE clause uses this value so that the update succeeds even after
        ``task.lease_owner`` has been cleared by the state-machine method.
        """

    @abstractmethod
    async def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> list[IngestionTask]:
        """Atomically claim a batch of eligible tasks (PENDING or RETRY).

        Uses SELECT … FOR UPDATE SKIP LOCKED semantics.
        Sets status → RUNNING, assigns worker_id, sets lease expiry.
        """

    @abstractmethod
    async def has_active_task(
        self,
        *,
        provider: Provider,
        dataset_type: DatasetType,
        symbol: str,
        exchange: str | None,
        timeframe: str | None,
        variant: str | None,
    ) -> bool:
        """Return True if a non-terminal task exists for this data stream."""

    @abstractmethod
    async def list_by_status(
        self,
        status: str,
        limit: int = 100,
    ) -> list[IngestionTask]:
        """List tasks by status (for monitoring)."""

    @abstractmethod
    async def count_by_status(self) -> dict[str, int]:
        """Return task counts grouped by status (for metrics)."""


class WatermarkRepository(ABC):
    """Persistence port for Watermark entities."""

    @abstractmethod
    async def get(
        self,
        *,
        provider: str,
        dataset_type: str,
        symbol: str,
        exchange: str | None = None,
        timeframe: str | None = None,
        variant: str | None = None,
    ) -> Watermark | None:
        """Get watermark by its 6-tuple natural key."""

    @abstractmethod
    async def get_or_create(
        self,
        *,
        provider: str,
        dataset_type: str,
        symbol: str,
        exchange: str | None = None,
        timeframe: str | None = None,
        variant: str | None = None,
    ) -> Watermark:
        """Get existing watermark or create a new default one."""

    @abstractmethod
    async def get_for_update(
        self,
        *,
        provider: str,
        dataset_type: str,
        symbol: str,
        exchange: str | None = None,
        timeframe: str | None = None,
        variant: str | None = None,
    ) -> Watermark | None:
        """Get watermark with a row-level lock (SELECT FOR UPDATE).

        Returns None if the row does not exist. Must be called inside an open
        DB transaction to prevent concurrent workers racing on the same watermark.
        """

    @abstractmethod
    async def save(self, watermark: Watermark) -> None:
        """Persist changes to an existing watermark."""

    @abstractmethod
    async def list_by_provider(
        self,
        provider: str,
        dataset_type: str | None = None,
    ) -> list[Watermark]:
        """List watermarks for a provider, optionally filtered by dataset_type."""


class PollingPolicyRepository(ABC):
    """Persistence port for PollingPolicy entities."""

    @abstractmethod
    async def get(self, policy_id: str) -> PollingPolicy | None:
        """Get a policy by ID."""

    @abstractmethod
    async def list_enabled(self) -> list[PollingPolicy]:
        """List all enabled policies (used by scheduler)."""

    @abstractmethod
    async def find_matching(
        self,
        *,
        provider: Provider,
        dataset_type: DatasetType,
        symbol: str | None = None,
        exchange: str | None = None,
        timeframe: str | None = None,
        variant: str | None = None,
    ) -> PollingPolicy | None:
        """Find the most specific matching policy (most-specific-wins semantics)."""

    @abstractmethod
    async def add(self, policy: PollingPolicy) -> None:
        """Persist a new policy."""

    @abstractmethod
    async def save(self, policy: PollingPolicy) -> None:
        """Persist changes to an existing policy."""


class ProviderBudgetRepository(ABC):
    """Persistence port for ProviderBudget entities."""

    @abstractmethod
    async def get(self, provider: Provider) -> ProviderBudget | None:
        """Get the budget for a provider."""

    @abstractmethod
    async def get_for_update(self, provider: Provider) -> ProviderBudget | None:
        """Load budget with a row-level lock (SELECT FOR UPDATE).

        Must be called inside an open DB transaction to prevent concurrent workers
        from over-consuming the token bucket (BP-036).
        """

    @abstractmethod
    async def get_or_create(self, provider: Provider) -> ProviderBudget:
        """Get existing budget or create with provider defaults."""

    @abstractmethod
    async def save(self, budget: ProviderBudget) -> None:
        """Persist budget changes (e.g., after consuming tokens)."""

    @abstractmethod
    async def list_all(self) -> list[ProviderBudget]:
        """List all provider budgets."""


class OutboxRepository(ABC):
    """Persistence port for the transactional outbox.

    Stores integration events atomically with business writes.
    The outbox dispatcher reads and publishes these to Kafka.
    """

    @abstractmethod
    async def add(self, *, events: Sequence[DomainEvent]) -> None:
        """Persist domain events into the outbox within the current UoW."""

    @abstractmethod
    async def claim_batch(
        self,
        *,
        batch_size: int,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> list[OutboxRecord]:
        """Atomically claim a batch of eligible outbox records for dispatch."""

    @abstractmethod
    async def mark_published(
        self,
        *,
        outbox_id: str | UUID,
        published_at: datetime,
        worker_id: str,
    ) -> bool:
        """Mark a record as successfully published. Returns True on success."""

    @abstractmethod
    async def mark_failed(
        self,
        *,
        outbox_id: str | UUID,
        error: str,
        worker_id: str,
        now: datetime,
        max_attempts: int,
        backoff_seconds: int,
    ) -> bool:
        """Mark a record as failed for this attempt. Implements retry backoff."""
