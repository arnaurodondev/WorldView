"""Domain entities for the Content Store service.

Entities are plain dataclasses with no infrastructure dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from content_store.domain.enums import DedupOutcome, DocumentStatus, SourceType

# ── Dedup thresholds (per-source) ──────────────────────────────────────────────


@dataclass(frozen=True)
class DedupThresholds:
    """Hard and soft Jaccard thresholds for a source type."""

    hard: float
    soft: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.soft <= self.hard <= 1.0:
            msg = f"Invalid thresholds: soft={self.soft}, hard={self.hard} (need 0 <= soft <= hard <= 1)"
            raise ValueError(msg)


# PRD §6.7 Block 2 — per-source thresholds
SOURCE_THRESHOLDS: dict[str, DedupThresholds] = {
    SourceType.EODHD: DedupThresholds(hard=0.72, soft=0.55),
    SourceType.NEWSAPI: DedupThresholds(hard=0.72, soft=0.55),
    SourceType.SEC_EDGAR: DedupThresholds(hard=0.85, soft=0.70),
    SourceType.FINNHUB: DedupThresholds(hard=0.75, soft=0.60),
    SourceType.MANUAL: DedupThresholds(hard=0.70, soft=0.55),
}


def get_thresholds(source_type: str) -> DedupThresholds:
    """Return dedup thresholds for a source type, defaulting to NEWS thresholds."""
    return SOURCE_THRESHOLDS.get(source_type, DedupThresholds(hard=0.72, soft=0.55))


# ── Corroboration policy ───────────────────────────────────────────────────────


class CorroborationPolicy:
    """Classifies a Jaccard similarity result into a DedupOutcome.

    Decision matrix (PRD §6.7 Block 2):
      J >= hard + same source    -> SAME_SOURCE_DUPLICATE (suppress)
      J >= hard + diff source    -> CORROBORATING (retain both, link)
      soft <= J < hard           -> SEMANTIC_NEAR_DUPLICATE
      J < soft                   -> UNIQUE
    """

    @staticmethod
    def classify(
        jaccard: float,
        same_source: bool,
        thresholds: DedupThresholds,
    ) -> DedupOutcome:
        """Classify a candidate pair by Jaccard similarity."""
        if jaccard >= thresholds.hard:
            if same_source:
                return DedupOutcome.SAME_SOURCE_DUPLICATE
            return DedupOutcome.CORROBORATING
        if jaccard >= thresholds.soft:
            return DedupOutcome.SEMANTIC_NEAR_DUPLICATE
        return DedupOutcome.UNIQUE


# ── Deduplication decision ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class DeduplicationDecision:
    """Immutable result of the 3-stage dedup pipeline for a single article."""

    outcome: DedupOutcome
    jaccard_score: float | None = None
    matched_doc_id: UUID | None = None
    stage: str = "unknown"

    @property
    def is_suppressed(self) -> bool:
        """Whether this article should be suppressed (not stored in silver)."""
        return self.outcome in {
            DedupOutcome.DUPLICATE_EXACT,
            DedupOutcome.DUPLICATE_NORMALIZED,
            DedupOutcome.SAME_SOURCE_DUPLICATE,
        }


# ── Canonical document ─────────────────────────────────────────────────────────


@dataclass
class CanonicalDocument:
    """A deduplicated, canonical document in the content store."""

    id: UUID = field(default_factory=common.ids.new_uuid7)
    source_type: str = ""
    source_url: str | None = None
    title: str | None = None
    published_at: datetime | None = None
    ingested_at: datetime = field(default_factory=common.time.utc_now)
    content_hash: str = ""
    normalized_hash: str = ""
    status: str = DocumentStatus.PROCESSING
    dedup_result: str = DedupOutcome.UNIQUE
    minio_silver_key: str | None = None
    word_count: int | None = None
    language: str = "en"
    corroborates_doc_id: UUID | None = None
    is_backfill: bool = False
    # PLAN-0086 Wave C-1: tenant isolation — None = public/global news;
    # non-None = private tenant content uploaded via TENANT_UPLOAD source.
    tenant_id: UUID | None = None


# ── MinHash signature ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MinHashSignature:
    """128-element MinHash signature for a document.

    CRITICAL: signature must be list[int], never numpy array or bytes.
    Stored as INTEGER[] in PostgreSQL.
    """

    id: UUID = field(default_factory=common.ids.new_uuid7)
    doc_id: UUID = field(default_factory=common.ids.new_uuid7)
    signature: list[int] = field(default_factory=list)
    shingle_type: str = "word_bigram_char3gram"
    created_at: datetime = field(default_factory=common.time.utc_now)

    def __post_init__(self) -> None:
        if self.signature and not all(isinstance(v, int) for v in self.signature):
            msg = "MinHash signature must contain only int values"
            raise TypeError(msg)


# ── Entity mention ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EntityMention:
    """An entity mention extracted from a document's text.

    entity_id is a logical FK to intelligence_db — NO Postgres constraint.
    """

    sig_id: UUID = field(default_factory=common.ids.new_uuid7)
    mention_text_hash: int = 0
    mention_text: str | None = None
    entity_id: UUID | None = None
    resolution_status: str = "UNRESOLVED"
    resolved_at: datetime | None = None
