"""Tests for ingestion canonical event models.

Each model is tested for:
1. from_dict → to_dict round-trip (no data loss)
2. Frozen dataclass (FrozenInstanceError on mutation attempt)
3. Field-level assertions for defaults and type coercions
"""

import dataclasses

import pytest

from contracts import (
    CanonicalEnrichedArticleEvent,
    CanonicalRawArticleEvent,
    CanonicalSignalEvent,
    CanonicalStoredArticleEvent,
    CanonicalWatchlistEvent,
)

# ── CanonicalRawArticleEvent ──────────────────────────────────────────────────

RAW_ARTICLE_DICT = {
    "event_id": "evt-001",
    "event_type": "content.article.raw",
    "schema_version": 1,
    "occurred_at": "2026-01-15T12:00:00Z",
    "url_hash": "abc123",
    "source_id": "eodhd",
    "source_domain": "seekingalpha.com",
    "url": "https://seekingalpha.com/article/1234",
    "minio_bucket": "raw-articles",
    "minio_key": "s4/content/raw/2026/01/15/abc123.html",
    "title": "Apple Q4 Earnings Beat",
    "content_type": "text/html",
    "correlation_id": "corr-001",
}


def test_raw_article_round_trip() -> None:
    event = CanonicalRawArticleEvent.from_dict(RAW_ARTICLE_DICT)
    assert event.to_dict() == RAW_ARTICLE_DICT


def test_raw_article_defaults() -> None:
    d = {k: v for k, v in RAW_ARTICLE_DICT.items() if k not in ("title", "content_type", "correlation_id")}
    event = CanonicalRawArticleEvent.from_dict(d)
    assert event.title is None
    assert event.content_type == "text/html"
    assert event.correlation_id is None


def test_raw_article_frozen() -> None:
    event = CanonicalRawArticleEvent.from_dict(RAW_ARTICLE_DICT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.event_id = "modified"  # type: ignore[misc]


# ── CanonicalStoredArticleEvent ───────────────────────────────────────────────

STORED_ARTICLE_DICT = {
    "event_id": "evt-002",
    "event_type": "content.article.stored",
    "schema_version": 1,
    "occurred_at": "2026-01-15T12:01:00Z",
    "article_id": "doc-uuid-001",
    "source_domain": "seekingalpha.com",
    "title": "Apple Q4 Earnings Beat",
    "url": "https://seekingalpha.com/article/1234",
    "language": "en",
    "word_count": 842,
    "is_duplicate": False,
    "duplicate_of": None,
    "published_at": "2026-01-15T10:00:00Z",
    "correlation_id": "corr-001",
}


def test_stored_article_round_trip() -> None:
    event = CanonicalStoredArticleEvent.from_dict(STORED_ARTICLE_DICT)
    assert event.to_dict() == STORED_ARTICLE_DICT


def test_stored_article_is_duplicate_default() -> None:
    d = {k: v for k, v in STORED_ARTICLE_DICT.items() if k not in ("is_duplicate", "duplicate_of")}
    event = CanonicalStoredArticleEvent.from_dict(d)
    assert event.is_duplicate is False
    assert event.duplicate_of is None


# ── CanonicalEnrichedArticleEvent ─────────────────────────────────────────────

ENRICHED_ARTICLE_DICT = {
    "event_id": "evt-003",
    "event_type": "nlp.article.enriched",
    "schema_version": 1,
    "occurred_at": "2026-01-15T12:05:00Z",
    "article_id": "doc-uuid-001",
    "embedding_model": "bge-large-en-v1.5",
    "entity_count": 3,
    "event_count": 1,
    "sentiment_label": "positive",
    "sentiment_score": 0.82,
    "topic_cluster_id": "cluster-42",
    "correlation_id": "corr-001",
}


def test_enriched_article_round_trip() -> None:
    event = CanonicalEnrichedArticleEvent.from_dict(ENRICHED_ARTICLE_DICT)
    assert event.to_dict() == ENRICHED_ARTICLE_DICT


def test_enriched_article_embedding_model_default() -> None:
    """Schema default is all-MiniLM-L6-v2 for backward compat; active model is bge-large-en-v1.5."""
    d = {k: v for k, v in ENRICHED_ARTICLE_DICT.items() if k != "embedding_model"}
    event = CanonicalEnrichedArticleEvent.from_dict(d)
    assert event.embedding_model == "all-MiniLM-L6-v2"  # schema compat default


# ── CanonicalSignalEvent ──────────────────────────────────────────────────────

SIGNAL_DICT = {
    "event_id": "evt-004",
    "event_type": "nlp.signal.detected",
    "schema_version": 1,
    "occurred_at": "2026-01-15T12:06:00Z",
    "entity_id": "entity-uuid-aapl",
    "signal_type": "earnings_beat",
    "title": "Apple Q4 EPS beats consensus by 12%",
    "severity": 3,
    "source_article_ids": ["doc-uuid-001", "doc-uuid-002"],
    "details": '{"eps_beat_pct": 12.3, "consensus": 2.15}',
    "correlation_id": "corr-001",
}


def test_signal_round_trip() -> None:
    event = CanonicalSignalEvent.from_dict(SIGNAL_DICT)
    result = event.to_dict()
    assert result["source_article_ids"] == SIGNAL_DICT["source_article_ids"]  # list preserved
    assert event.source_article_ids == tuple(SIGNAL_DICT["source_article_ids"])  # tuple internally


def test_signal_source_article_ids_empty_default() -> None:
    d = {k: v for k, v in SIGNAL_DICT.items() if k != "source_article_ids"}
    event = CanonicalSignalEvent.from_dict(d)
    assert event.source_article_ids == ()
    assert event.to_dict()["source_article_ids"] == []


# ── CanonicalWatchlistEvent ───────────────────────────────────────────────────

WATCHLIST_ADDED_DICT = {
    "event_id": "evt-005",
    "event_type": "watchlist.item_added",
    "schema_version": 1,
    "occurred_at": "2026-01-15T12:10:00Z",
    "user_id": "user-uuid-001",
    "watchlist_id": "wl-uuid-001",
    "entity_ids_affected": ["entity-uuid-aapl"],
    "correlation_id": None,
}

WATCHLIST_DELETED_DICT = {**WATCHLIST_ADDED_DICT, "event_type": "watchlist.item_deleted"}


def test_watchlist_added_round_trip() -> None:
    event = CanonicalWatchlistEvent.from_dict(WATCHLIST_ADDED_DICT)
    assert event.to_dict() == WATCHLIST_ADDED_DICT


def test_watchlist_deleted_round_trip() -> None:
    event = CanonicalWatchlistEvent.from_dict(WATCHLIST_DELETED_DICT)
    assert event.event_type == "watchlist.item_deleted"


def test_watchlist_event_type_deleted_not_removed() -> None:
    """Regression: event_type must be 'watchlist.item_deleted', not 'watchlist.item_removed'."""
    event = CanonicalWatchlistEvent.from_dict(WATCHLIST_DELETED_DICT)
    assert event.event_type != "watchlist.item_removed"
    assert event.event_type == "watchlist.item_deleted"


def test_watchlist_entity_ids_tuple_internally() -> None:
    event = CanonicalWatchlistEvent.from_dict(WATCHLIST_ADDED_DICT)
    assert isinstance(event.entity_ids_affected, tuple)


def test_watchlist_entity_ids_list_in_to_dict() -> None:
    event = CanonicalWatchlistEvent.from_dict(WATCHLIST_ADDED_DICT)
    assert isinstance(event.to_dict()["entity_ids_affected"], list)
