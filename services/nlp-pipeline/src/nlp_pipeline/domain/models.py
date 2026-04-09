"""Domain models for the NLP Pipeline service.

Pure dataclasses — NO infrastructure imports allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from common.ids import new_uuid7  # type: ignore[import-untyped]
from nlp_pipeline.domain.errors import PriceImpactError

if TYPE_CHECKING:
    from datetime import date, datetime
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
    text_key: str | None = None  # MinIO key for chunk text; set after upload


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
    embedding_text: str = ""  # text to embed on retry; populated at creation time


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


@dataclass(frozen=True)
class ArticlePriceImpact:
    """Retrospective price-impact label for a processed article (PRD-0020 §6.5).

    Represents how much the related entity's price moved in the OHLCV bar
    covering the article's publication time.  All monetary fields use
    ``Decimal`` (not ``float``) for precision.

    Factories:
      - ``compute()`` — derives ``price_delta_pct`` and ``impact_score`` from OHLCV
      - ``zero()``    — no-data sentinel (OHLCV unavailable or article < 25h old)
    """

    # Required fields (no defaults) — must come before fields with defaults
    article_id: UUID
    entity_id: UUID
    symbol: str
    published_at: datetime
    ohlcv_date: date
    price_open: Decimal
    price_close: Decimal
    price_delta_pct: Decimal
    impact_score: Decimal
    # Optional fields
    next_day_delta_pct: Decimal | None = None
    max_intraday_range_pct: Decimal | None = None
    # Auto-generated primary key (UUIDv7); override when reconstructing from DB
    id: UUID = field(default_factory=new_uuid7)

    def __post_init__(self) -> None:
        if self.published_at.tzinfo is None:  # type: ignore[union-attr]
            raise PriceImpactError("published_at must be UTC-aware (tzinfo required)")
        if not (Decimal("0.0") <= self.impact_score <= Decimal("1.0")):
            raise PriceImpactError(f"impact_score must be in [0.0, 1.0], got {self.impact_score}")
        if not (1 <= len(self.symbol.strip()) <= 20):
            raise PriceImpactError(f"symbol must be 1-20 chars, got '{self.symbol}'")
        if self.price_open < Decimal("0"):
            raise PriceImpactError(f"price_open must be >= 0, got {self.price_open}")
        if self.price_close < Decimal("0"):
            raise PriceImpactError(f"price_close must be >= 0, got {self.price_close}")

    @classmethod
    def compute(
        cls,
        article_id: UUID,
        entity_id: UUID,
        symbol: str,
        published_at: datetime,
        price_open: Decimal,
        price_close: Decimal,
        normalisation_cap_pct: Decimal = Decimal("5.0"),
        next_day_delta_pct: Decimal | None = None,
        max_intraday_range_pct: Decimal | None = None,
    ) -> ArticlePriceImpact:
        """Compute impact_score from OHLCV data (PRD-0020 §6.5).

        Raises:
            PriceImpactError: if ``published_at`` is naive or ``price_open`` is <= 0.
        """
        if published_at.tzinfo is None:  # type: ignore[union-attr]
            raise PriceImpactError("published_at must be UTC-aware")
        if price_open <= Decimal("0"):
            raise PriceImpactError(f"price_open must be > 0 in compute(), got {price_open}")
        price_delta_pct = (price_close - price_open) / price_open * Decimal("100")
        impact_score = min(Decimal("1.0"), abs(price_delta_pct) / normalisation_cap_pct)
        ohlcv_date = published_at.date()  # type: ignore[union-attr]
        return cls(
            article_id=article_id,
            entity_id=entity_id,
            symbol=symbol.strip(),
            published_at=published_at,
            ohlcv_date=ohlcv_date,
            price_open=price_open,
            price_close=price_close,
            price_delta_pct=price_delta_pct,
            impact_score=impact_score,
            next_day_delta_pct=next_day_delta_pct,
            max_intraday_range_pct=max_intraday_range_pct,
        )

    @classmethod
    def zero(
        cls,
        article_id: UUID,
        entity_id: UUID,
        symbol: str,
        published_at: datetime,
        ohlcv_date: date,
    ) -> ArticlePriceImpact:
        """No-data sentinel: OHLCV unavailable or article < 25h old (PRD-0020 §6.5)."""
        return cls(
            article_id=article_id,
            entity_id=entity_id,
            symbol=symbol.strip(),
            published_at=published_at,
            ohlcv_date=ohlcv_date,
            price_open=Decimal("0"),
            price_close=Decimal("0"),
            price_delta_pct=Decimal("0"),
            impact_score=Decimal("0.0"),
        )
