"""Unit tests for contracts.canonical.article."""

from __future__ import annotations

import dataclasses

import pytest

from contracts.canonical.article import CanonicalArticle
from contracts.versions import ARTICLE_SCHEMA_VERSION


class TestCanonicalArticle:
    def _make_article(self) -> CanonicalArticle:
        return CanonicalArticle(
            article_id="01JPXYZ123ABC",
            source_domain="reuters.com",
            title="Apple Reports Record Earnings",
            url="https://reuters.com/apple-earnings",
        )

    def _make_full_article(self) -> CanonicalArticle:
        return CanonicalArticle(
            article_id="01JPXYZ123ABC",
            source_domain="reuters.com",
            title="Apple Reports Record Earnings",
            url="https://reuters.com/apple-earnings",
            language="en",
            word_count=850,
            is_duplicate=False,
            duplicate_of=None,
            published_at="2025-01-15T10:00:00.000000Z",
            body_text="Apple Inc. reported record earnings...",
        )

    def test_schema_version(self) -> None:
        assert self._make_article().schema_version == ARTICLE_SCHEMA_VERSION

    def test_schema_version_is_1(self) -> None:
        assert ARTICLE_SCHEMA_VERSION == 1

    def test_roundtrip_minimal(self) -> None:
        article = self._make_article()
        restored = CanonicalArticle.from_dict(article.to_dict())
        assert restored.article_id == article.article_id
        assert restored.source_domain == article.source_domain
        assert restored.title == article.title
        assert restored.url == article.url

    def test_roundtrip_full(self) -> None:
        article = self._make_full_article()
        restored = CanonicalArticle.from_dict(article.to_dict())
        assert restored.language == "en"
        assert restored.word_count == 850
        assert restored.is_duplicate is False
        assert restored.published_at == "2025-01-15T10:00:00.000000Z"
        assert restored.body_text == "Apple Inc. reported record earnings..."

    def test_frozen(self) -> None:
        article = self._make_article()
        with pytest.raises(dataclasses.FrozenInstanceError):
            article.title = "Modified"  # type: ignore[misc]

    def test_defaults(self) -> None:
        article = self._make_article()
        assert article.language == "en"
        assert article.word_count == 0
        assert article.is_duplicate is False
        assert article.duplicate_of is None
        assert article.published_at is None
        assert article.body_text == ""

    def test_duplicate_article(self) -> None:
        article = CanonicalArticle(
            article_id="01JPXYZ999",
            source_domain="bloomberg.com",
            title="Apple Earnings (Duplicate)",
            url="https://bloomberg.com/apple",
            is_duplicate=True,
            duplicate_of="01JPXYZ123ABC",
        )
        d = article.to_dict()
        assert d["is_duplicate"] is True
        assert d["duplicate_of"] == "01JPXYZ123ABC"
        restored = CanonicalArticle.from_dict(d)
        assert restored.duplicate_of == "01JPXYZ123ABC"

    def test_to_dict_keys_match_avro_schema(self) -> None:
        """to_dict() fields align with content.article.stored.v1.avsc."""
        d = self._make_full_article().to_dict()
        avro_aligned_keys = {
            "article_id", "source_domain", "title", "url",
            "language", "word_count", "is_duplicate", "duplicate_of",
            "published_at",
        }
        for key in avro_aligned_keys:
            assert key in d, f"Missing Avro-aligned key: {key}"
