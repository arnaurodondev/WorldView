"""Unit tests for the Content Ingestion domain layer."""

from __future__ import annotations

from datetime import timedelta

import pytest
from content_ingestion.domain.entities import RawArticle, SourceType
from content_ingestion.domain.value_objects import TokenBucket

import common.ids
import common.time

pytestmark = pytest.mark.unit


def _make_bucket(capacity: int = 10, tokens: float = 10.0, refill_rate: float = 1.0) -> TokenBucket:
    return TokenBucket(
        capacity=capacity,
        tokens=tokens,
        refill_rate=refill_rate,
        last_refill=common.time.utc_now(),
    )


class TestTokenBucketConsume:
    def test_consume_deducts_tokens(self) -> None:
        bucket = _make_bucket(tokens=5.0)
        result = bucket.consume(1)
        assert result is True
        assert bucket.tokens == pytest.approx(4.0, abs=1e-2)

    def test_consume_returns_false_when_empty(self) -> None:
        bucket = _make_bucket(tokens=0.0)
        result = bucket.consume(1)
        assert result is False

    def test_consume_multiple_drains_correctly(self) -> None:
        bucket = _make_bucket(tokens=3.0)
        assert bucket.consume(3) is True
        assert bucket.consume(1) is False

    def test_refill_over_time(self) -> None:
        past = common.time.utc_now() - timedelta(seconds=5)
        bucket = TokenBucket(capacity=10, tokens=0.0, refill_rate=2.0, last_refill=past)
        # 5 seconds * 2 tokens/s = 10 tokens, capped at capacity=10
        result = bucket.consume(1)
        assert result is True

    def test_refill_capped_at_capacity(self) -> None:
        past = common.time.utc_now() - timedelta(seconds=100)
        bucket = TokenBucket(capacity=5, tokens=0.0, refill_rate=10.0, last_refill=past)
        bucket._refill()
        assert bucket.tokens == pytest.approx(5.0)


class TestTokenBucketWaitTime:
    def test_wait_time_zero_when_sufficient(self) -> None:
        bucket = _make_bucket(tokens=5.0)
        assert bucket.wait_time(3) == pytest.approx(0.0)

    def test_wait_time_positive_when_insufficient(self) -> None:
        bucket = _make_bucket(tokens=0.0, refill_rate=1.0)
        wt = bucket.wait_time(1)
        assert wt > 0.0

    def test_wait_time_correct_value(self) -> None:
        # 0 tokens, need 2, refill_rate=1 → wait = 2s
        bucket = _make_bucket(tokens=0.0, refill_rate=1.0)
        wt = bucket.wait_time(2)
        assert wt == pytest.approx(2.0)


class TestRawArticle:
    def test_byte_size_from_raw_bytes(self) -> None:
        payload = b"hello world"
        article = RawArticle(
            source_type=SourceType.EODHD,
            url="https://example.com/news",
            url_hash="abc123",
            raw_bytes=payload,
            fetched_at=common.time.utc_now(),
            byte_size=len(payload),
        )
        assert article.byte_size == len(payload)

    def test_default_uuid7_id_assigned(self) -> None:
        article = RawArticle(
            source_type=SourceType.FINNHUB,
            url="https://example.com/a",
            url_hash="hash1",
            raw_bytes=b"data",
            fetched_at=common.time.utc_now(),
            byte_size=4,
        )
        assert article.id.version == 7

    def test_frozen_immutable(self) -> None:
        article = RawArticle(
            source_type=SourceType.NEWSAPI,
            url="https://example.com/b",
            url_hash="hash2",
            raw_bytes=b"data",
            fetched_at=common.time.utc_now(),
            byte_size=4,
        )
        with pytest.raises(AttributeError):
            article.url = "https://other.com"  # type: ignore[misc]
