"""Domain models for the NLP Pipeline service.

Pure dataclasses — NO infrastructure imports allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from nlp_pipeline.domain.enums import DataQuality, WindowType  # needed at runtime for default arg values
from nlp_pipeline.domain.errors import PriceImpactError

if TYPE_CHECKING:
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
    ner_model_id: str | None = None
    # Set by UnresolvedResolutionWorker (PLAN-0033 Wave 3)
    resolution_noise_reason: str | None = None  # LLM reason when outcome=noise
    resolution_processed_at: datetime | None = None  # UTC timestamp when worker processed


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

    PRD-0026 additions: ``llm_relevance_score`` and ``llm_scored_at`` are
    populated by ``ArticleRelevanceScoringWorker`` for MEDIUM/DEEP-tier articles.
    Both are null until the worker runs; LIGHT tier articles are never scored.
    """

    doc_id: UUID
    created_at: datetime
    title: str | None = None
    url: str | None = None
    published_at: datetime | None = None  # UTC-aware
    source_name: str | None = None  # e.g. "SEC EDGAR", "Finnhub"
    source_type: str | None = None  # e.g. "sec_10q", "eodhd_news"
    word_count: int | None = None
    # PRD-0026: LLM relevance scoring (populated by ArticleRelevanceScoringWorker)
    llm_relevance_score: Decimal | None = None  # 0.0-1.0; null until scored
    llm_scored_at: datetime | None = None  # UTC; null until scored


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


# ── PRD-0026: Multi-window price-impact + LLM relevance scoring ───────────────


@dataclass(frozen=True)
class ArticleImpactWindow:
    """One price-impact measurement for a (article_id, entity_id, window_type) triple.

    Replaces ``ArticlePriceImpact`` with a multi-window design so the system can
    track sustained vs transient price moves and build richer ML features.

    Invariants:
      - ``window_end > window_start``
      - ``impact_score ∈ [0.0, 1.0]``
      - ``price_start > 0`` and ``price_end > 0``

    See PRD-0026 §6.5 for the full spec.
    """

    # Required identity fields (no defaults)
    id: UUID
    article_id: UUID  # logical FK to document_source_metadata.doc_id
    entity_id: UUID  # canonical entity used for OHLCV lookup
    symbol: str  # ticker symbol, 1-20 chars

    # Time fields
    published_at: datetime  # UTC-aware article publication time
    window_type: WindowType
    window_start: datetime  # UTC-aware; day_t0 = midnight of OHLCV date
    window_end: datetime  # UTC-aware; must be > window_start

    # Price data
    price_start: Decimal  # open price at window start (>0)
    price_end: Decimal  # close price at window end (>0)
    delta_pct: Decimal  # (price_end - price_start) / price_start * 100; signed

    # Derived score
    impact_score: Decimal  # min(1.0, abs(delta_pct) / normalisation_cap_pct)
    normalisation_cap_pct: Decimal  # per-window configurable cap (>0)

    # Quality flag
    data_quality: DataQuality  # all current rows = DAILY_PROXY

    # Optional OHLCV fields (None for cumulative windows that only have close prices)
    high_pct: Decimal | None = None  # max intraday high relative to price_start
    low_pct: Decimal | None = None  # max intraday low relative to price_start
    volume: Decimal | None = None  # OHLCV volume in the window

    # Set by Postgres server_default; None when constructed in application code
    computed_at: datetime | None = None

    @classmethod
    def compute(
        cls,
        article_id: UUID,
        entity_id: UUID,
        symbol: str,
        published_at: datetime,
        window_type: WindowType,
        window_start: datetime,
        window_end: datetime,
        price_start: Decimal,
        price_end: Decimal,
        cap_pct: Decimal,
        high_pct: Decimal | None = None,
        low_pct: Decimal | None = None,
        volume: Decimal | None = None,
        data_quality: DataQuality = DataQuality.DAILY_PROXY,  # type: ignore[assignment]
    ) -> ArticleImpactWindow:
        """Compute ``delta_pct`` and ``impact_score`` from raw open/close prices.

        Args:
            article_id: Logical FK to document_source_metadata.
            entity_id:  Canonical entity whose OHLCV was fetched.
            symbol:     Ticker symbol (1-20 chars).
            published_at: Article publication UTC timestamp.
            window_type: Which window (day_t0 / day_t1 / day_t2 / day_t5).
            window_start: UTC start of the price window.
            window_end:   UTC end; must be strictly after window_start.
            price_start:  Open price (>0); for cumulative windows, this is close_t0.
            price_end:    Close price (>0).
            cap_pct:      Normalisation cap for this window type.
            high_pct:     Optional daily OHLCV high relative to price_start.
            low_pct:      Optional daily OHLCV low relative to price_start.
            volume:       Optional OHLCV volume.
            data_quality: Source quality; defaults to DAILY_PROXY.

        Raises:
            ValueError: if ``window_end <= window_start`` or ``price_start <= 0``.
        """
        if window_end <= window_start:
            raise ValueError(f"window_end must be after window_start; got {window_end} <= {window_start}")
        if price_start <= Decimal("0"):
            raise ValueError(f"price_start must be > 0, got {price_start}")
        delta = (price_end - price_start) / price_start * Decimal("100")
        score = min(Decimal("1.0"), abs(delta) / cap_pct)
        return cls(
            id=new_uuid7(),
            article_id=article_id,
            entity_id=entity_id,
            symbol=symbol,
            published_at=published_at,
            window_type=window_type,
            window_start=window_start,
            window_end=window_end,
            price_start=price_start,
            price_end=price_end,
            delta_pct=delta,
            impact_score=score,
            normalisation_cap_pct=cap_pct,
            data_quality=data_quality,
            high_pct=high_pct,
            low_pct=low_pct,
            volume=volume,
        )


@dataclass(frozen=True)
class DisplayRelevanceScore:
    """Composite relevance score for user-facing article ranking (PRD-0026 §6.5).

    Combines three signals using a weighted formula with four branches based on
    which signals are available. ``None`` means "data not yet available", NOT zero.
    A zero market_impact means the market genuinely did not move — that is distinct
    from a missing measurement and must not be treated identically to None (AD-5).

    Signal priority:
      market_impact (0.50): retrospective ground truth — did the market react?
      llm_relevance (0.40): forward-looking expert estimate
      routing_score (0.10): system heuristic; always available; weakest signal

    Articles with only routing_score (LIGHT tier) are penalised to 0.40x of
    routing_score - they are genuinely less informative than MEDIUM/DEEP articles.
    """

    market_impact: float | None  # MAX(day_t0, day_t1) impact_score; None = not labelled yet
    llm_relevance: float | None  # LLM score; None for LIGHT tier or unscored article
    routing_score: float | None  # composite_score from routing_decisions; None if JOIN miss

    @property
    def value(self) -> float:
        """Compute the weighted composite display score.

        Four branches depending on which signals are available:
          1. All signals:  0.50*market + 0.40*llm + 0.10*routing
          2. Market only:  0.70*market + 0.30*routing
          3. LLM only:     0.60*llm    + 0.40*routing
          4. Routing only: 0.40*routing
        """
        mi = self.market_impact  # None ≠ 0.0 — see class docstring
        llm = self.llm_relevance
        rs = self.routing_score or 0.0  # None routing becomes 0.0

        if mi is not None and mi > 0 and llm is not None:
            # Branch 1: all three signals available
            return 0.50 * mi + 0.40 * llm + 0.10 * rs
        if mi is not None and mi > 0:
            # Branch 2: market confirmed but LLM not yet scored
            return 0.70 * mi + 0.30 * rs
        if llm is not None:
            # Branch 3: LLM scored but market data not yet available (or mi == 0.0)
            # mi == 0.0 means genuinely no market movement → LLM estimate dominates
            return 0.60 * llm + 0.40 * rs
        # Branch 4: LIGHT tier or no scoring available; routing_score only
        return rs * 0.40
