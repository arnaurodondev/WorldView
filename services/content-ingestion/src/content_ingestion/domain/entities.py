"""Domain entities for the Content Ingestion service."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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


# ── Prediction Market entities ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class OutcomeSnapshot:
    """A single binary outcome of a prediction market (e.g. "Yes" or "No").

    Invariants:
        - ``name`` and ``token_id`` must be non-empty strings.
        - ``price`` must be in the closed interval [0.0, 1.0].
    """

    name: str
    token_id: str
    price: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("OutcomeSnapshot.name must not be empty")
        if not self.token_id:
            raise ValueError("OutcomeSnapshot.token_id must not be empty")
        if not (0.0 <= self.price <= 1.0):
            raise ValueError(f"OutcomeSnapshot.price must be in [0.0, 1.0], got {self.price}")


@dataclass(frozen=True, slots=True)
class PredictionMarketFetchResult:
    """Immutable result of fetching one prediction market from Polymarket.

    This is a pure domain object — no infrastructure imports.  The adapter
    constructs instances via :meth:`from_gamma_response` and may attach the
    MinIO key via ``dataclasses.replace()`` after upload.

    Invariants:
        - ``fetched_at`` must be UTC-aware.
        - ``outcomes`` must contain at least 2 entries.
    """

    source_type: SourceType
    market_id: str
    question: str
    outcomes: list[OutcomeSnapshot]
    raw_bytes: bytes
    fetched_at: datetime
    description: str | None = None
    volume_24h: float | None = None
    liquidity: float | None = None
    close_time: datetime | None = None
    resolution_status: str = "open"
    resolved_answer: str | None = None
    minio_bronze_key: str | None = None
    id: UUID = field(default_factory=common.ids.new_uuid7)

    def __post_init__(self) -> None:
        if self.fetched_at.tzinfo is None:
            raise ValueError("PredictionMarketFetchResult.fetched_at must be UTC-aware")
        if len(self.outcomes) < 2:
            raise ValueError("PredictionMarketFetchResult.outcomes must have at least 2 entries")

    @classmethod
    def from_gamma_response(
        cls,
        raw: dict,
        fetched_at: datetime,
    ) -> PredictionMarketFetchResult:
        """Construct from a Polymarket Gamma API market dict.

        Maps Gamma API field names to domain attributes.  All optional fields
        use defensive ``.get()`` with None defaults to tolerate absent keys.
        """
        tokens: list[dict] = raw.get("tokens") or []
        outcomes = [
            OutcomeSnapshot(
                name=t.get("outcome", ""),
                token_id=t.get("token_id", ""),
                price=float(t.get("price", 0.0)),
            )
            for t in tokens
        ]

        # Map Gamma "closed" status → domain "cancelled" (R15: stable values)
        raw_status = raw.get("status", "active")
        if raw_status == "closed":
            resolution_status = "cancelled"
        elif raw_status == "resolved":
            resolution_status = "resolved"
        else:
            resolution_status = "open"

        close_time: datetime | None = None
        raw_end_date = raw.get("endDate")
        if raw_end_date:
            try:
                close_time = datetime.fromisoformat(raw_end_date.replace("Z", "+00:00")).astimezone(UTC)
            except (ValueError, AttributeError):
                close_time = None

        return cls(
            source_type=SourceType.POLYMARKET,
            market_id=raw.get("conditionId", ""),
            question=raw.get("question", ""),
            description=raw.get("description"),
            outcomes=outcomes,
            volume_24h=float(raw["volume24hr"]) if raw.get("volume24hr") is not None else None,
            liquidity=float(raw["liquidity"]) if raw.get("liquidity") is not None else None,
            close_time=close_time,
            resolution_status=resolution_status,
            resolved_answer=raw.get("resolvedAnswer"),
            raw_bytes=json.dumps(raw).encode(),
            fetched_at=fetched_at,
            minio_bronze_key=None,
        )
