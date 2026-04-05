"""Domain models for the NLP Pipeline service.

Pure dataclasses — NO infrastructure imports allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from nlp_pipeline.domain.enums import MentionClass, ResolutionOutcome, RoutingTier


@dataclass(frozen=True)
class Section:
    """A structural section of a document (PRD §6.4.3)."""

    section_id: UUID
    doc_id: UUID
    section_index: int
    char_start: int
    char_end: int
    text: str
    section_type: str | None = None  # body | heading | footnote | speaker_turn | disclaimer
    title: str | None = None
    speaker: str | None = None  # transcripts only
    token_count: int | None = None


@dataclass(frozen=True)
class Chunk:
    """A sentence-aware chunk of a section (PRD §6.7 Block 7)."""

    chunk_id: UUID
    doc_id: UUID
    section_id: UUID
    chunk_index: int
    char_start: int
    char_end: int
    token_count: int
    text: str
    sentence_start_idx: int | None = None
    sentence_end_idx: int | None = None
    speaker: str | None = None  # transcripts only
    heading_path: str | None = None  # e.g. "Item 1A > Risk Factors"


@dataclass
class EntityMention:
    """A named entity mention extracted by GLiNER (PRD §6.7 Block 4)."""

    mention_id: UUID
    doc_id: UUID
    section_id: UUID | None
    mention_text: str
    mention_class: MentionClass
    confidence: float
    char_start: int
    char_end: int
    # Set by Block 9 entity resolution
    resolved_entity_id: UUID | None = None
    resolution_confidence: float | None = None
    resolution_stage: int | None = None  # 1=exact, 2=ticker, 3=fuzzy, 4=ANN
    resolution_outcome: ResolutionOutcome | None = None


@dataclass
class MentionResolution:
    """Audit trail entry for a single resolution cascade stage (PRD §6.4.3)."""

    mention_id: UUID
    stage: int  # 1=exact, 2=ticker, 3=fuzzy, 4=ANN
    score: float
    is_winner: bool = False
    candidate_entity_id: UUID | None = None
    metadata: dict[str, object] | None = None  # stage-specific details


@dataclass
class DocumentEntityStats:
    """Aggregate NER stats for a document (PRD §6.4.3)."""

    doc_id: UUID
    distinct_mention_count: int = 0
    high_conf_mention_count: int = 0  # confidence >= 0.70
    type_distribution: dict[str, int] = field(default_factory=dict)  # {class: count}


@dataclass
class RoutingDecision:
    """Routing score and tier assignment for a document (PRD §6.7 Block 5)."""

    decision_id: UUID
    doc_id: UUID
    routing_tier: RoutingTier
    composite_score: float
    feature_scores: dict[str, float]  # all 7 signal values for audit/training
    final_routing_tier: RoutingTier | None = None  # after Stage 2 novelty correction


@dataclass
class NLPDocument:
    """In-memory processing state for a document passing through S6 blocks."""

    doc_id: UUID
    source_type: str
    published_at: datetime | None
    extracted_at: datetime
    sections: list[Section] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    mentions: list[EntityMention] = field(default_factory=list)
    routing_decision: RoutingDecision | None = None
    # Set after Block 7
    embedding_failures: list[UUID] = field(default_factory=list)  # chunk_ids that failed


@dataclass(frozen=True)
class SignalEvent:
    """High-confidence financial signal detected from an article (PRD §6.7 Block 10)."""

    signal_id: UUID
    doc_id: UUID
    entity_id: UUID
    signal_type: str
    confidence: float
    evidence_text: str
    detected_at: datetime


@dataclass
class EmbeddingPendingEntry:
    """Record of a chunk or section whose embedding failed and needs retry."""

    doc_id: UUID
    chunk_id: UUID | None
    section_id: UUID | None
    error_detail: str
    created_at: datetime


@dataclass(frozen=True)
class DocumentSourceMetadata:
    """Cached citation metadata for a stored article (PRD §6 Wave B-1).

    Populated by S6 consumer from ``content.article.stored.v1`` events.
    Accessed by S8 RAG pipeline to return inline citation data without
    a round-trip to S5.
    """

    doc_id: UUID
    created_at: datetime
    title: str | None = None
    url: str | None = None
    published_at: datetime | None = None  # UTC-aware
    source_name: str | None = None  # e.g. "SEC EDGAR", "Finnhub"
    source_type: str | None = None  # e.g. "sec_10q", "eodhd_news"
    word_count: int | None = None
