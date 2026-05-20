"""Unit tests for deduplication stages A, B, and MinHash computation."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from content_store.application.deduplication.minhash_compute import (
    compute_minhash,
    compute_shingles,
    normalize_financial_text,
)
from content_store.application.deduplication.stage_a_raw import (
    check_stage_a,
    compute_raw_hash,
)
from content_store.application.deduplication.stage_b_normalized import (
    check_stage_b,
    compute_normalized_hash,
    normalize_url,
)
from content_store.domain.enums import DedupOutcome

pytestmark = pytest.mark.unit


# ── Stage A: raw hash ────────────────────────────────────────────────────────


class TestStageARawHash:
    def test_compute_raw_hash_deterministic(self) -> None:
        data = b"Hello World"
        h1 = compute_raw_hash(data)
        h2 = compute_raw_hash(data)
        assert h1 == h2
        assert h1 == hashlib.sha256(data).hexdigest()

    def test_different_content_different_hash(self) -> None:
        assert compute_raw_hash(b"a") != compute_raw_hash(b"b")

    async def test_stage_a_unique(self) -> None:
        repo = AsyncMock()
        repo.check_exists.return_value = None
        raw_hash, decision = await check_stage_a(b"content", repo)
        assert decision is None
        assert raw_hash == compute_raw_hash(b"content")
        # PLAN-0086 Wave C-1: check_exists now accepts optional tenant_id kwarg.
        # Default (no tenant_id passed) → tenant_id=None (public content namespace).
        repo.check_exists.assert_called_once_with("raw_sha256", raw_hash, tenant_id=None)

    async def test_stage_a_duplicate(self) -> None:
        existing_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        repo = AsyncMock()
        repo.check_exists.return_value = existing_id
        _raw_hash, decision = await check_stage_a(b"content", repo)
        assert decision is not None
        assert decision.outcome == DedupOutcome.DUPLICATE_EXACT
        assert decision.matched_doc_id == existing_id
        assert decision.stage == "stage_a"
        assert decision.is_suppressed is True


# ── Stage B: normalized hash ─────────────────────────────────────────────────


class TestNormalizeURL:
    def test_strips_utm_params(self) -> None:
        url = "https://example.com/article?utm_source=twitter&utm_medium=social&id=42"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "id=42" in result

    def test_sorts_query_params(self) -> None:
        url = "https://example.com/page?z=1&a=2"
        result = normalize_url(url)
        assert result == "https://example.com/page?a=2&z=1"

    def test_lowercases_host(self) -> None:
        url = "HTTPS://EXAMPLE.COM/Path"
        result = normalize_url(url)
        assert result.startswith("https://example.com/Path")

    def test_removes_trailing_slash(self) -> None:
        url = "https://example.com/path/"
        result = normalize_url(url)
        assert result == "https://example.com/path"

    def test_removes_fragment(self) -> None:
        url = "https://example.com/page#section"
        result = normalize_url(url)
        assert "#section" not in result

    def test_empty_url(self) -> None:
        assert normalize_url("") == ""

    def test_strips_fbclid(self) -> None:
        url = "https://example.com/article?fbclid=abc123&title=test"
        result = normalize_url(url)
        assert "fbclid" not in result
        assert "title=test" in result

    # ── BUG-006 / TASK-W2-01 — extended tracking-param strip list ────────────
    #
    # Each of these URLs differs from the canonical form ONLY by one of the
    # newly-added tracking parameters (ClearURLs source list). They MUST all
    # normalize to the same string as the bare canonical URL so that Stage B
    # dedup catches socially-shared near-duplicates.
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/article?_ga=2.123456789.987654321.0-1234567890",
            "https://example.com/article?_gl=1*abc123*_ga*XYZ",
            "https://example.com/article?_hsenc=p2ANqtz-abcDEF",
            "https://example.com/article?_hsmi=12345678",
            "https://example.com/article?igshid=abcdef1234567890",
            "https://example.com/article?oly_anon_id=anon-abc-123",
            "https://example.com/article?oly_enc_id=enc-xyz-789",
            "https://example.com/article?wickedid=wkd-abc",
            "https://example.com/article?vero_id=user%40example.com",
            "https://example.com/article?vero_conv=conv-42",
            "https://example.com/article?yclid=987654321",
            "https://example.com/article?s_cid=adobe-camp-1",
        ],
    )
    def test_strips_extended_tracking_params(self, url: str) -> None:
        # Canonical form: same URL with no query string and no trailing slash.
        # `normalize_url` collapses an empty query to "" and drops the "?".
        expected = "https://example.com/article"
        assert normalize_url(url) == expected


class TestStageBNormalizedHash:
    def test_compute_normalized_hash_deterministic(self) -> None:
        h1 = compute_normalized_hash("https://example.com", "hello")
        h2 = compute_normalized_hash("https://example.com", "hello")
        assert h1 == h2

    def test_case_insensitive_text(self) -> None:
        h1 = compute_normalized_hash("https://example.com", "Hello World")
        h2 = compute_normalized_hash("https://example.com", "hello world")
        assert h1 == h2

    def test_different_url_different_hash(self) -> None:
        h1 = compute_normalized_hash("https://a.com", "text")
        h2 = compute_normalized_hash("https://b.com", "text")
        assert h1 != h2

    async def test_stage_b_unique(self) -> None:
        repo = AsyncMock()
        repo.check_exists.return_value = None
        norm_hash, decision = await check_stage_b("https://example.com", "text", repo)
        assert decision is None
        assert norm_hash  # non-empty hash

    async def test_stage_b_duplicate(self) -> None:
        existing_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
        repo = AsyncMock()
        repo.check_exists.return_value = existing_id
        _norm_hash, decision = await check_stage_b("https://example.com", "text", repo)
        assert decision is not None
        assert decision.outcome == DedupOutcome.DUPLICATE_NORMALIZED
        assert decision.matched_doc_id == existing_id
        assert decision.stage == "stage_b"
        assert decision.is_suppressed is True


# ── MinHash: normalize_financial_text ─────────────────────────────────────────


class TestNormalizeFinancialText:
    def test_lowercases(self) -> None:
        tokens = normalize_financial_text("Hello WORLD Test")
        assert all(t == t.lower() for t in tokens)

    def test_strips_punctuation(self) -> None:
        tokens = normalize_financial_text("Hello, world! How are you?")
        assert all("," not in t and "!" not in t and "?" not in t for t in tokens)

    def test_removes_stopwords(self) -> None:
        tokens = normalize_financial_text("the quick brown fox is running")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "quick" in tokens

    def test_removes_short_tokens(self) -> None:
        tokens = normalize_financial_text("a b cd ef ghi")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "cd" in tokens

    def test_removes_financial_boilerplate(self) -> None:
        tokens = normalize_financial_text("disclaimer forward-looking statements about risks")
        # "disclaimer", "statements", "risks" are stopwords
        assert "disclaimer" not in tokens
        assert "risks" not in tokens

    def test_nfc_normalization(self) -> None:
        # Combining é -> single codepoint
        tokens = normalize_financial_text("cafe\u0301 data")
        assert "café" in tokens or "cafe" in tokens  # NFC should merge

    def test_empty_text(self) -> None:
        assert normalize_financial_text("") == []

    def test_only_stopwords(self) -> None:
        assert normalize_financial_text("the a an is are") == []


# ── MinHash: compute_shingles ─────────────────────────────────────────────────


class TestComputeShingles:
    def test_word_bigrams_present(self) -> None:
        shingles = compute_shingles("Apple stock price increased significantly today")
        # Should have word bigrams prefixed with "w:"
        word_shingles = {s for s in shingles if s.startswith("w:")}
        assert len(word_shingles) > 0

    def test_char_trigrams_present(self) -> None:
        shingles = compute_shingles("Apple stock price")
        char_shingles = {s for s in shingles if s.startswith("c:")}
        assert len(char_shingles) > 0

    def test_union_of_both(self) -> None:
        shingles = compute_shingles("Apple stock price went up today after earnings")
        word_shingles = {s for s in shingles if s.startswith("w:")}
        char_shingles = {s for s in shingles if s.startswith("c:")}
        assert len(shingles) == len(word_shingles) + len(char_shingles)

    def test_deterministic(self) -> None:
        s1 = compute_shingles("test text here")
        s2 = compute_shingles("test text here")
        assert s1 == s2

    def test_empty_text_returns_empty(self) -> None:
        # Text of only stopwords produces no tokens → no word bigrams
        # But char trigrams may still exist
        shingles = compute_shingles("the a an")
        word_shingles = {s for s in shingles if s.startswith("w:")}
        assert len(word_shingles) == 0


# ── MinHash: compute_minhash ─────────────────────────────────────────────────


class TestComputeMinHash:
    def test_returns_list_of_int(self) -> None:
        result = compute_minhash("Apple stock price went up significantly after earnings report")
        assert isinstance(result, list)
        assert len(result) == 128
        # CRITICAL: each element must be a plain Python int, not numpy
        assert all(isinstance(v, int) for v in result)

    def test_custom_num_perm(self) -> None:
        result = compute_minhash(
            "Apple stock price went up significantly after earnings report",
            num_perm=64,
        )
        assert len(result) == 64
        assert all(isinstance(v, int) for v in result)

    def test_deterministic(self) -> None:
        text = "Apple stock price increased significantly today"
        h1 = compute_minhash(text)
        h2 = compute_minhash(text)
        assert h1 == h2

    def test_identical_texts_identical_hashes(self) -> None:
        text = "Apple announces new quarterly earnings beating expectations"
        h1 = compute_minhash(text)
        h2 = compute_minhash(text)
        assert h1 == h2

    def test_different_texts_different_hashes(self) -> None:
        h1 = compute_minhash("Apple stock price went up significantly after earnings report")
        h2 = compute_minhash("Bitcoin drops sharply as regulatory concerns mount globally")
        assert h1 != h2

    def test_similar_texts_high_jaccard(self) -> None:
        h1 = compute_minhash("Apple stock price went up significantly after quarterly earnings report")
        h2 = compute_minhash("Apple stock price rose significantly following quarterly earnings report")
        # Compute Jaccard from signatures
        jaccard = sum(1 for a, b in zip(h1, h2, strict=False) if a == b) / len(h1)
        # Similar texts should have reasonably high Jaccard
        assert jaccard > 0.2  # Conservative threshold for similar financial text

    def test_raises_on_empty_shingles(self) -> None:
        # Single short token produces no word bigrams but may have char trigrams
        # Use something that truly produces no shingles
        with pytest.raises(ValueError, match="no shingles"):
            compute_minhash("")
