"""Core request/response domain entities for the RAG-Chat pipeline (T-D-1-01)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from rag_chat.domain.enums import ItemType, QueryIntent
    from rag_chat.domain.value_objects import DateRange

# ── Recency score helper ───────────────────────────────────────────────────────

# Decay rate per source type: score = exp(-rate * days_old). Higher rate = faster decay.
# Calibrated so SEC filings retain >0.83 after 365 days; news drops below 0.55 after 30 days.
_RECENCY_DECAY_RATES: dict[str, float] = {
    "sec_filing": 0.0005,  # 10-K/10-Q stay relevant for years
    "earnings_transcript": 0.001,
    "press_release": 0.01,
    "eodhd_news": 0.02,
    "finnhub_news": 0.02,
    "newsapi": 0.025,
    "default": 0.005,  # unchanged from pre-W5-4 uniform constant
}

# Source-quality floor multiplier — applied AFTER recency decay so primary sources
# (filings, transcripts) dominate over transient news on tied lexical relevance.
# WHY: eodhd_news decays 40x faster than sec_filing, so a 14-day-old transcript
# would rank near zero against a 1-day-old blurb without this lift.
# Wired to RetrievedItem fusion_score in F-W5-9 follow-up after 30d of telemetry.
_SOURCE_QUALITY_FLOOR: dict[str, float] = {
    "sec_filing": 1.4,
    "earnings_transcript": 1.3,
    "press_release": 1.0,
    "eodhd_news": 0.9,
    "finnhub_news": 0.9,
    "newsapi": 0.85,
    "default": 1.0,
}


def compute_recency_score(
    published_at: datetime | None,
    source_type: str | None = None,
) -> float:
    """Temporal decay weight for a retrieved item, source-aware.

    Returns exp(-rate * days_old) where rate is looked up from
    _RECENCY_DECAY_RATES by source_type (default 0.005 if unknown).
    Returns 0.5 when published_at is None (matches pre-W5-4 behaviour).
    Future dates are clamped to days_old=0 (returns 1.0).
    Naive datetimes are treated as UTC.
    """
    if published_at is None:
        return 0.5
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    days_old = max(0, (datetime.now(tz=UTC) - published_at).days)
    rate = _RECENCY_DECAY_RATES.get(source_type or "default", _RECENCY_DECAY_RATES["default"])
    return math.exp(-rate * days_old)


# ── Request context ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChatContext:
    """Optional filters attached to a chat request."""

    entity_ids: tuple[UUID, ...] = ()
    date_range: DateRange | None = None

    def __post_init__(self) -> None:
        if len(self.entity_ids) > 5:
            raise ValueError(f"ChatContext.entity_ids exceeds maximum of 5 (got {len(self.entity_ids)})")


@dataclass(frozen=True)
class ChatRequest:
    """Validated, HTML-stripped user query with routing metadata.

    Callers are responsible for stripping HTML before constructing this entity.
    Length is validated in __post_init__ (1-2000 characters).
    """

    message: str
    context: ChatContext
    tenant_id: UUID
    user_id: UUID
    thread_id: UUID | None = None

    def __post_init__(self) -> None:
        if not (1 <= len(self.message) <= 2000):
            raise ValueError(f"ChatRequest.message length must be 1-2000 chars (got {len(self.message)})")


# ── Resolution ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedEntity:
    """An entity resolved from the user query via NER + alias lookup."""

    entity_id: UUID
    canonical_name: str
    entity_type: str
    confidence: float
    matched_text: str
    ticker: str | None = None


# ── Retrieved items ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CitationMeta:
    """Bibliographic metadata for a single retrieved item."""

    title: str | None
    url: str | None
    source_name: str | None
    published_at: datetime | None
    entity_name: str | None


@dataclass(frozen=True)
class RetrievedItem:
    """Unified retrieval result from any source (chunks, relations, claims, etc.).

    Invariant: fusion_score == score * recency_score * trust_weight (tolerance 1e-9).
    Use the ``create()`` factory to compute fusion_score automatically.
    """

    item_id: str
    item_type: ItemType
    text: str
    score: float
    recency_score: float
    trust_weight: float
    fusion_score: float
    citation_meta: CitationMeta
    entity_id: UUID | None = None
    doc_id: UUID | None = None
    published_at: datetime | None = None
    graph_enrichment: tuple[dict, ...] = field(default_factory=tuple)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        expected = self.score * self.recency_score * self.trust_weight
        if abs(self.fusion_score - expected) >= 1e-9:
            raise ValueError(
                f"RetrievedItem fusion_score invariant violated: "
                f"{self.fusion_score!r} != {self.score!r} * {self.recency_score!r} "
                f"* {self.trust_weight!r} = {expected!r}"
            )

    @classmethod
    def create(
        cls,
        item_id: str,
        item_type: ItemType,
        text: str,
        score: float,
        trust_weight: float,
        citation_meta: CitationMeta | None = None,
        entity_id: UUID | None = None,
        doc_id: UUID | None = None,
        published_at: datetime | None = None,
        graph_enrichment: tuple[dict, ...] = (),
        source_type: str | None = None,
    ) -> RetrievedItem:
        """Factory that computes recency_score and fusion_score automatically."""
        recency_score = compute_recency_score(published_at, source_type=source_type)
        fusion_score = score * recency_score * trust_weight
        return cls(
            item_id=item_id,
            item_type=item_type,
            text=text,
            score=score,
            recency_score=recency_score,
            trust_weight=trust_weight,
            fusion_score=fusion_score,
            citation_meta=citation_meta
            or CitationMeta(
                title=None,
                url=None,
                source_name=None,
                published_at=None,
                entity_name=None,
            ),
            entity_id=entity_id,
            doc_id=doc_id,
            published_at=published_at,
            graph_enrichment=graph_enrichment,
        )


# ── Query resolution + retrieval planning ─────────────────────────────────────


@dataclass(frozen=True)
class ResolvedQuery:
    """Output of entity resolution + intent classification (pipeline step 3)."""

    intent: QueryIntent
    rephrased_query: str
    sub_questions: tuple[str, ...] = ()
    resolved_entities: tuple[ResolvedEntity, ...] = ()
    hyde_hypothesis: str | None = None


@dataclass(frozen=True)
class RetrievalPlan:
    """Which retrieval sources to activate for this query (pipeline step 3 output)."""

    use_chunks: bool
    use_relations: bool
    use_graph: bool
    use_claims: bool
    use_events: bool
    use_contradictions: bool
    use_financial: bool
    use_portfolio: bool
    use_cypher: bool
    entity_ids: tuple[UUID, ...]
    date_filter: DateRange | None = None
