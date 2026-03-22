"""Canonical event dataclasses for the ingestion pipeline.

These models mirror the Avro schemas in infra/kafka/schemas/ and provide
a typed Python interface for producers and consumers. Each model implements
from_dict() and to_dict() for Avro payload interop.

Field names match the Avro schema field names exactly. Do NOT rename fields
to match Python conventions — parity with the schema is the contract.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class CanonicalRawArticleEvent:
    """Mirrors content.article.raw.v1.avsc — produced by S4, consumed by S5."""

    event_id: str
    event_type: str  # always "content.article.raw"
    schema_version: int
    occurred_at: str  # ISO-8601 string; TIMESTAMPTZ at the DB level
    url_hash: str
    source_id: str
    source_domain: str
    url: str
    minio_bucket: str
    minio_key: str
    title: str | None = None
    content_type: str = "text/html"
    correlation_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalRawArticleEvent:
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            schema_version=d["schema_version"],
            occurred_at=d["occurred_at"],
            url_hash=d["url_hash"],
            source_id=d["source_id"],
            source_domain=d["source_domain"],
            url=d["url"],
            minio_bucket=d["minio_bucket"],
            minio_key=d["minio_key"],
            title=d.get("title"),
            content_type=d.get("content_type", "text/html"),
            correlation_id=d.get("correlation_id"),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "url_hash": self.url_hash,
            "source_id": self.source_id,
            "source_domain": self.source_domain,
            "url": self.url,
            "minio_bucket": self.minio_bucket,
            "minio_key": self.minio_key,
            "title": self.title,
            "content_type": self.content_type,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True)
class CanonicalStoredArticleEvent:
    """Mirrors content.article.stored.v1.avsc — produced by S5, consumed by S6."""

    event_id: str
    event_type: str  # always "content.article.stored"
    schema_version: int
    occurred_at: str
    article_id: str  # maps to doc_id in content_store_db; field name preserved for schema compat
    source_domain: str
    title: str
    url: str
    language: str = "en"
    word_count: int = 0
    is_duplicate: bool = False
    duplicate_of: str | None = None
    published_at: str | None = None
    correlation_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalStoredArticleEvent:
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            schema_version=d["schema_version"],
            occurred_at=d["occurred_at"],
            article_id=d["article_id"],
            source_domain=d["source_domain"],
            title=d["title"],
            url=d["url"],
            language=d.get("language", "en"),
            word_count=d.get("word_count", 0),
            is_duplicate=d.get("is_duplicate", False),
            duplicate_of=d.get("duplicate_of"),
            published_at=d.get("published_at"),
            correlation_id=d.get("correlation_id"),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "article_id": self.article_id,
            "source_domain": self.source_domain,
            "title": self.title,
            "url": self.url,
            "language": self.language,
            "word_count": self.word_count,
            "is_duplicate": self.is_duplicate,
            "duplicate_of": self.duplicate_of,
            "published_at": self.published_at,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True)
class CanonicalEnrichedArticleEvent:
    """Mirrors nlp.article.enriched.v1.avsc — produced by S6, consumed by S7.

    Note: embedding_model field default is "all-MiniLM-L6-v2" in the schema for
    backward compatibility. The active model in production is bge-large-en-v1.5.
    Do NOT change the schema default — this is a compatibility artifact.
    Always check the actual embedding_model value in the event payload.
    """

    event_id: str
    event_type: str  # always "nlp.article.enriched"
    schema_version: int
    occurred_at: str
    article_id: str  # logical FK to content_store_db documents; field name preserved
    embedding_model: str = "all-MiniLM-L6-v2"  # backward-compat default; actual = bge-large-en-v1.5
    entity_count: int = 0
    event_count: int = 0
    sentiment_label: str | None = None
    sentiment_score: float | None = None
    topic_cluster_id: str | None = None
    correlation_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalEnrichedArticleEvent:
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            schema_version=d["schema_version"],
            occurred_at=d["occurred_at"],
            article_id=d["article_id"],
            embedding_model=d.get("embedding_model", "all-MiniLM-L6-v2"),
            entity_count=d.get("entity_count", 0),
            event_count=d.get("event_count", 0),
            sentiment_label=d.get("sentiment_label"),
            sentiment_score=d.get("sentiment_score"),
            topic_cluster_id=d.get("topic_cluster_id"),
            correlation_id=d.get("correlation_id"),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "article_id": self.article_id,
            "embedding_model": self.embedding_model,
            "entity_count": self.entity_count,
            "event_count": self.event_count,
            "sentiment_label": self.sentiment_label,
            "sentiment_score": self.sentiment_score,
            "topic_cluster_id": self.topic_cluster_id,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True)
class CanonicalSignalEvent:
    """Mirrors nlp.signal.detected.v1.avsc — produced by S6, consumed by S10."""

    event_id: str
    event_type: str  # always "nlp.signal.detected"
    schema_version: int
    occurred_at: str
    entity_id: str
    signal_type: str
    title: str
    severity: int = 1
    source_article_ids: tuple[str, ...] = ()  # tuple for frozen immutability; from_dict converts list
    details: str | None = None  # JSON-encoded detail payload
    correlation_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalSignalEvent:
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            schema_version=d["schema_version"],
            occurred_at=d["occurred_at"],
            entity_id=d["entity_id"],
            signal_type=d["signal_type"],
            title=d["title"],
            severity=d.get("severity", 1),
            source_article_ids=tuple(d.get("source_article_ids", [])),
            details=d.get("details"),
            correlation_id=d.get("correlation_id"),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "entity_id": self.entity_id,
            "signal_type": self.signal_type,
            "title": self.title,
            "severity": self.severity,
            "source_article_ids": list(self.source_article_ids),  # Avro array requires list
            "details": self.details,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True)
class CanonicalWatchlistEvent:
    """Mirrors portfolio.watchlist.updated.v1.avsc envelope — produced by S1, consumed by S10.

    The event_type field discriminates the two event subtypes:
      - "watchlist.item_added"   — entity added to a watchlist
      - "watchlist.item_deleted" — entity removed from a watchlist (PRD §1.5 rule 5)

    Never construct this with event_type = "watchlist.item_removed" — that string was
    deprecated in Wave 01 (T-F-001) and is a bug if it appears.
    """

    event_id: str
    event_type: str  # "watchlist.item_added" or "watchlist.item_deleted"
    schema_version: int
    occurred_at: str
    user_id: str
    watchlist_id: str
    entity_ids_affected: tuple[str, ...] = ()  # always non-empty for valid events
    correlation_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalWatchlistEvent:
        return cls(
            event_id=d["event_id"],
            event_type=d["event_type"],
            schema_version=d["schema_version"],
            occurred_at=d["occurred_at"],
            user_id=d["user_id"],
            watchlist_id=d["watchlist_id"],
            entity_ids_affected=tuple(d.get("entity_ids_affected", [])),
            correlation_id=d.get("correlation_id"),
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "user_id": self.user_id,
            "watchlist_id": self.watchlist_id,
            "entity_ids_affected": list(self.entity_ids_affected),
            "correlation_id": self.correlation_id,
        }
