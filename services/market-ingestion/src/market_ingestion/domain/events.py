"""Domain events for the Market Ingestion service.

All events follow the worldview envelope standard (AGENTS.md §9):
    event_id, event_type, schema_version, occurred_at, correlation_id, causation_id.

MarketDatasetFetched implements the AvroDictable protocol with to_dict()/from_dict()
that flatten ObjectRef claim-check fields into 27 top-level Avro-compatible keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, cast

from common.ids import new_ulid  # type: ignore[import-untyped]
from common.time import to_iso8601, utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.value_objects import ObjectRef


def _new_event_id() -> str:
    return new_ulid()  # type: ignore[no-any-return]


def _now_iso() -> str:
    return to_iso8601(utc_now())  # type: ignore[no-any-return]


# ── Base ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Immutable base for all Market Ingestion domain events.

    Envelope fields are auto-populated on construction:
    - event_id: ULID (time-sortable unique identifier)
    - occurred_at: ISO-8601 UTC timestamp string
    - correlation_id / causation_id: optional tracing fields

    Subclasses declare EVENT_TYPE and SCHEMA_VERSION as ClassVar.
    """

    EVENT_TYPE: ClassVar[str] = ""
    SCHEMA_VERSION: ClassVar[int] = 1

    event_id: str = field(default_factory=_new_event_id)
    occurred_at: str = field(default_factory=_now_iso)
    correlation_id: str | None = None
    causation_id: str | None = None


# ── External event ────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class MarketDatasetFetched(DomainEvent):
    """Emitted when a complete dataset has been fetched and stored in object storage.

    This is a claim-check event: consumers follow the bronze_ref / canonical_ref
    pointers to retrieve the actual data from MinIO/S3.

    The to_dict() method flattens ObjectRef fields into 27 top-level keys that
    map directly to the market.dataset.fetched Avro schema.
    """

    EVENT_TYPE: ClassVar[str] = "market.dataset.fetched"
    SCHEMA_VERSION: ClassVar[int] = 1

    # Dataset metadata
    provider: str
    dataset_type: str
    symbol: str
    exchange: str | None = None
    timeframe: str | None = None
    variant: str | None = None

    # Date range (YYYY-MM-DD strings for Avro compatibility)
    range_start: str = ""
    range_end: str = ""

    # Claim-check references (flattened to 5 fields each in to_dict)
    bronze_ref: ObjectRef = field(default=ObjectRef(bucket="", key="", sha256="", byte_length=0, mime_type=""))
    canonical_ref: ObjectRef = field(default=ObjectRef(bucket="", key="", sha256="", byte_length=0, mime_type=""))

    # Canonical metadata
    canonical_schema_version: int = 1
    row_count: int = 0
    task_id: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialize to a flat dict with all 27 Avro-compatible fields."""
        return {
            # Envelope (6)
            "event_id": self.event_id,
            "event_type": self.EVENT_TYPE,
            "schema_version": self.SCHEMA_VERSION,
            "occurred_at": self.occurred_at,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            # Task + dataset identity (7)
            "task_id": self.task_id,
            "provider": self.provider,
            "dataset_type": self.dataset_type,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timeframe": self.timeframe,
            "variant": self.variant,
            # Date range (2)
            "range_start": self.range_start or None,
            "range_end": self.range_end or None,
            # Bronze ref — ObjectRef flattened (5)
            "bronze_ref_bucket": self.bronze_ref.bucket,
            "bronze_ref_key": self.bronze_ref.key,
            "bronze_ref_sha256": self.bronze_ref.sha256,
            "bronze_ref_byte_length": self.bronze_ref.byte_length,
            "bronze_ref_mime_type": self.bronze_ref.mime_type,
            # Canonical ref — ObjectRef flattened (5)
            "canonical_ref_bucket": self.canonical_ref.bucket,
            "canonical_ref_key": self.canonical_ref.key,
            "canonical_ref_sha256": self.canonical_ref.sha256,
            "canonical_ref_byte_length": self.canonical_ref.byte_length,
            "canonical_ref_mime_type": self.canonical_ref.mime_type,
            # Metadata (2)
            "canonical_schema_version": self.canonical_schema_version,
            "row_count": self.row_count if self.row_count else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> MarketDatasetFetched:
        """Reconstruct from a flat dict produced by to_dict()."""
        bronze_ref = ObjectRef(
            bucket=str(d["bronze_ref_bucket"]),
            key=str(d["bronze_ref_key"]),
            sha256=str(d["bronze_ref_sha256"]),
            byte_length=cast("int", d["bronze_ref_byte_length"]),
            mime_type=str(d["bronze_ref_mime_type"]),
        )
        canonical_ref = ObjectRef(
            bucket=str(d["canonical_ref_bucket"]),
            key=str(d["canonical_ref_key"]),
            sha256=str(d["canonical_ref_sha256"]),
            byte_length=cast("int", d["canonical_ref_byte_length"]),
            mime_type=str(d["canonical_ref_mime_type"]),
        )
        return cls(
            event_id=str(d.get("event_id") or _new_event_id()),
            occurred_at=str(d.get("occurred_at") or _now_iso()),
            correlation_id=str(d["correlation_id"]) if d.get("correlation_id") else None,
            causation_id=str(d["causation_id"]) if d.get("causation_id") else None,
            provider=str(d["provider"]),
            dataset_type=str(d["dataset_type"]),
            symbol=str(d["symbol"]),
            exchange=str(d["exchange"]) if d.get("exchange") else None,
            timeframe=str(d["timeframe"]) if d.get("timeframe") else None,
            variant=str(d["variant"]) if d.get("variant") else None,
            range_start=str(d.get("range_start", "")),
            range_end=str(d.get("range_end", "")),
            bronze_ref=bronze_ref,
            canonical_ref=canonical_ref,
            canonical_schema_version=cast("int", d.get("canonical_schema_version", 1)),
            row_count=cast("int", d.get("row_count", 0)),
            task_id=str(d.get("task_id", "")),
        )


# ── Internal events ───────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class IngestionTaskCompleted(DomainEvent):
    """Internal event: fired when an ingestion task finishes successfully."""

    EVENT_TYPE: ClassVar[str] = "market.task.completed"
    SCHEMA_VERSION: ClassVar[int] = 1

    task_id: str = ""
    provider: str = ""
    dataset_type: str = ""
    symbol: str = ""


@dataclass(frozen=True, kw_only=True)
class IngestionTaskScheduled(DomainEvent):
    """Internal event: fired when a new ingestion task is scheduled."""

    EVENT_TYPE: ClassVar[str] = "market.task.scheduled"
    SCHEMA_VERSION: ClassVar[int] = 1

    task_id: str = ""
    provider: str = ""
    dataset_type: str = ""
    symbol: str = ""
