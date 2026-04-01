"""Domain entities for the Content Ingestion service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

import common.ids
import common.time
from content_ingestion.domain.exceptions import InvalidStateTransition
from contracts.enums import (  # type: ignore[import-untyped]
    ContentSourceType as SourceType,
)
from contracts.enums import (  # type: ignore[import-untyped]
    IngestionTaskStatus as IngestionTaskStatus,
)


@dataclass
class Source:
    """A configured polling source."""

    name: str
    source_type: SourceType
    enabled: bool
    config: dict[str, Any]
    id: UUID = field(default_factory=common.ids.new_uuid7)
    created_at: datetime = field(default_factory=common.time.utc_now)


@dataclass(frozen=True)
class FetchResult:
    """Raw result of a single HTTP fetch attempt.

    Attributes:
        published_at: Publication datetime as reported by the source API, or None if not
            available. This is the article's *editorial* date, distinct from ``fetched_at``
            (when our crawler pulled it). Used as ``evidence_date`` when writing
            ``relation_evidence`` rows in S7 — critical for correct temporal decay.
        is_backfill: True when this result was produced during a boot-time historical
            backfill run (i.e. ``BACKFILL_ENABLED=true``).  Propagated through the
            pipeline so that S10 can suppress alert fan-out for historical documents.
    """

    source_id: UUID
    url: str
    url_hash: str
    raw_bytes: bytes
    fetched_at: datetime
    http_status: int
    content_type: str
    published_at: datetime | None = None
    is_backfill: bool = False


@dataclass(frozen=True)
class RawArticle:
    """A raw article ready for storage and Kafka publish.

    Attributes:
        published_at: Source-reported publication datetime, or None.  When present, S7
            MUST use this as ``relation_evidence.evidence_date`` so the temporal decay
            formula reflects the article's *actual* age, not when it was ingested.
        is_backfill: True for documents ingested during a historical backfill run.
            Propagated through the Kafka event so S10 can suppress alert fan-out.
    """

    source_type: SourceType
    url: str
    url_hash: str
    raw_bytes: bytes
    fetched_at: datetime
    byte_size: int
    published_at: datetime | None = None
    is_backfill: bool = False
    id: UUID = field(default_factory=common.ids.new_uuid7)


# ── Scheduler-Worker task entity ──────────────────────────────────────────────


_CLAIMABLE_STATUSES = frozenset({IngestionTaskStatus.PENDING, IngestionTaskStatus.RETRY})


@dataclass
class ContentIngestionTask:
    """A unit of work representing a single fetch cycle for one content source.

    State machine::

        PENDING ──→ CLAIMED ──→ RUNNING ──→ SUCCEEDED
                                        ├──→ RETRY  (attempt_count < max_attempts)
                                        └──→ FAILED (attempt_count >= max_attempts, or immediate)
    """

    # Identity
    source_id: UUID
    source_name: str
    source_type: SourceType

    # State machine
    status: IngestionTaskStatus = IngestionTaskStatus.PENDING

    # Lease
    worker_id: str | None = None
    leased_at: datetime | None = None
    lease_expires: datetime | None = None

    # Retry
    attempt_count: int = 0
    max_attempts: int = 5
    error_detail: str | None = None

    # Scheduling
    is_backfill: bool = False
    window_start: datetime | None = None

    # Audit
    id: UUID = field(default_factory=common.ids.new_uuid7)
    created_at: datetime = field(default_factory=common.time.utc_now)
    updated_at: datetime = field(default_factory=common.time.utc_now)

    # ── State transitions ─────────────────────────────────────────────────

    def claim(self, worker_id: str, lease_seconds: int) -> None:
        """Transition PENDING/RETRY → CLAIMED, set worker lease."""
        if self.status not in _CLAIMABLE_STATUSES:
            raise InvalidStateTransition(f"Cannot claim task in status {self.status!r}; must be PENDING or RETRY")
        self.status = IngestionTaskStatus.CLAIMED
        self.worker_id = worker_id
        self.leased_at = common.time.utc_now()
        self.lease_expires = self.leased_at + timedelta(seconds=lease_seconds)
        self.updated_at = common.time.utc_now()

    def start(self) -> None:
        """Transition CLAIMED → RUNNING."""
        if self.status != IngestionTaskStatus.CLAIMED:
            raise InvalidStateTransition(f"Cannot start task in status {self.status!r}; must be CLAIMED")
        self.status = IngestionTaskStatus.RUNNING
        self.attempt_count += 1
        self.updated_at = common.time.utc_now()

    def succeed(self) -> None:
        """Transition RUNNING → SUCCEEDED."""
        if self.status != IngestionTaskStatus.RUNNING:
            raise InvalidStateTransition(f"Cannot succeed task in status {self.status!r}; must be RUNNING")
        self.status = IngestionTaskStatus.SUCCEEDED
        self.worker_id = None
        self.lease_expires = None
        self.updated_at = common.time.utc_now()

    def fail(self, error: str) -> None:
        """Transition RUNNING → FAILED or RETRY depending on attempts remaining."""
        if self.status != IngestionTaskStatus.RUNNING:
            raise InvalidStateTransition(f"Cannot fail task in status {self.status!r}; must be RUNNING")
        self.error_detail = error
        self.worker_id = None
        self.lease_expires = None
        if self.attempt_count >= self.max_attempts:
            self.status = IngestionTaskStatus.FAILED
        else:
            self.status = IngestionTaskStatus.RETRY
        self.updated_at = common.time.utc_now()

    # ── Queries ───────────────────────────────────────────────────────────

    @property
    def is_claimable(self) -> bool:
        """True if the task can be claimed by a worker."""
        return self.status in _CLAIMABLE_STATUSES

    def is_lease_expired(self, now: datetime) -> bool:
        """True if the current lease has passed its expiry time."""
        if self.lease_expires is None:
            return False
        return now > self.lease_expires

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    def create_for_source(
        cls,
        source: Source,
        *,
        is_backfill: bool = False,
        window_start: datetime | None = None,
    ) -> ContentIngestionTask:
        """Create a new task from a Source entity."""
        return cls(
            source_id=source.id,
            source_name=source.name,
            source_type=source.source_type,
            is_backfill=is_backfill,
            window_start=window_start,
        )
