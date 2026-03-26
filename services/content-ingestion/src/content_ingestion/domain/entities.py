"""Domain entities for the Content Ingestion service."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

import common.ids
import common.time


class SourceType(StrEnum):
    """Supported ingestion sources."""

    EODHD = "eodhd"
    SEC_EDGAR = "sec_edgar"
    FINNHUB = "finnhub"
    NEWSAPI = "newsapi"
    MANUAL = "manual"


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
