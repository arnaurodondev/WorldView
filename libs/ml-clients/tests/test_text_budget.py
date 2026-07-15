"""Unit tests for ml_clients.text_budget (BGE token-budget truncation, task #4).

These tests pin the two safety invariants that fix the embedding 400 backlog:
  1. After truncation, the ESTIMATED token count is always <= MAX_TOKENS, which is
     itself safely below BGE's hard 512-token limit.  This is what stops the
     "513 input tokens > 512" HTTP 400 the retry worker could never drain.
  2. The estimator is CONSERVATIVE (over-counts vs a real tokenizer) and dense
     JSON text is cut more aggressively than sparse prose — so the same budget
     keeps more useful content for normal text while still protecting the limit.
"""

from __future__ import annotations

from ml_clients.text_budget import (
    MAX_CHARS,
    MAX_TOKENS,
    estimate_bert_tokens,
    truncate_for_bge,
)


class TestEstimateBertTokens:
    """The conservative WordPiece upper-bound estimator."""

    def test_empty_text_is_two_special_tokens(self) -> None:
        # Even empty input carries [CLS] + [SEP].
        assert estimate_bert_tokens("") == 2

    def test_dense_json_scores_higher_than_prose_of_same_length(self) -> None:
        # Per character, JSON-envelope text is far more token-dense than English —
        # this is exactly why the old flat char cap failed for chunk-0 envelopes.
        n = 400
        dense = ('{"k":1,"v":2}' * n)[:n]
        prose = ("apple reported strong quarterly earnings " * n)[:n]
        assert estimate_bert_tokens(dense) > estimate_bert_tokens(prose)

    def test_unicode_escapes_score_heavier_than_their_ascii_chars(self) -> None:
        # A JSON \uXXXX escape decodes to a non-Latin codepoint that BGE tokenises
        # into several tokens — far more than the ~3 its 6 ASCII chars would score
        # via the alnum rule.  This is what fixed the residual Hebrew/CJK 400s after
        # the first task #4 deploy.  An escape-dense string must out-score the same
        # number of plain ASCII chars.
        # Literal backslash-u escapes, exactly as the JSON envelope stores Hebrew
        # (ensure_ascii=True). Built from a backslash + "uXXXX" so the source file
        # contains the 6-char escape token, NOT a decoded Hebrew glyph.
        escaped = "\\u05e8" * 20  # 120 chars, 20 escapes
        # Same character count, but plain ASCII letters (no escapes).
        plain = "x" * len(escaped)
        assert estimate_bert_tokens(escaped) > estimate_bert_tokens(plain)

    def test_raw_cjk_scores_heavier_than_ascii_of_same_length(self) -> None:
        # Regression: some sources (e.g. Korean GLOBE NEWSWIRE press releases) store
        # embedding_text as RAW UTF-8, not \uXXXX escapes. Each raw Hangul/CJK
        # codepoint byte-splits into ~2-6 BGE WordPiece tokens, so it must out-score
        # the same number of ASCII letters — otherwise a "truncated" Korean row still
        # exceeds 512 real tokens and DeepInfra 400s (the residual embedding-retry
        # failures observed 2026-07-15 after the 480→360 budget fix).
        korean = "미국 캘리포니아주 새너제이 지능형 시스템" * 5  # raw, no escapes
        ascii_same = "x" * len(korean.replace(" ", ""))
        assert estimate_bert_tokens(korean) > estimate_bert_tokens(ascii_same)

    def test_monotonic_in_prefix_length(self) -> None:
        # A longer prefix never has fewer estimated tokens — required for the
        # binary search in truncate_for_bge to be correct.
        text = '{"ticker":"AAPL","revenue":383285000000}' * 50
        prev = -1
        for cut in range(0, len(text), 37):
            cur = estimate_bert_tokens(text[:cut])
            assert cur >= prev
            prev = cur


class TestTruncateForBge:
    """The token-budget truncation used by every embedding path."""

    def test_short_text_returned_unchanged(self) -> None:
        text = "Apple Q3 revenue beat estimates."
        assert truncate_for_bge(text) == text

    def test_dense_json_truncated_under_token_budget(self) -> None:
        # The audit's failing case: a long dense JSON envelope. Post-truncation the
        # estimate must be <= MAX_TOKENS (well under BGE's 512), guaranteeing 200.
        dense = '{"ticker":"AAPL","isin":"US0378331005","revenue":383285000000}' * 80
        out = truncate_for_bge(dense)
        assert estimate_bert_tokens(out) <= MAX_TOKENS
        assert len(out) <= MAX_CHARS
        # Dense text is cut aggressively — well below the proven-safe 1100-char boundary.
        assert len(out) < 1100

    def test_raw_cjk_truncated_under_token_budget(self) -> None:
        # The residual failing case: a long RAW (un-escaped) Korean row. Post-truncation
        # the estimate must be <= MAX_TOKENS so the real BGE token count stays under 512
        # and DeepInfra returns 200 instead of a fatal 400.
        korean = (
            "미국 캘리포니아주 새너제이, 어떤 데이터 환경에서도 최적화된 성능을 제공하는 지능형 시스템입니다. " * 40
        )
        out = truncate_for_bge(korean)
        assert estimate_bert_tokens(out) <= MAX_TOKENS
        assert len(out) <= MAX_CHARS

    def test_long_prose_keeps_more_than_dense_at_same_budget(self) -> None:
        # Sparse English packs fewer tokens/char, so the SAME token budget keeps a
        # longer prefix — the win over a flat char cap.
        prose = "Apple reported strong quarterly earnings driven by services growth. " * 80
        dense = '{"k":1,"v":2,"x":3}' * 200
        out_prose = truncate_for_bge(prose)
        out_dense = truncate_for_bge(dense)
        assert estimate_bert_tokens(out_prose) <= MAX_TOKENS
        assert estimate_bert_tokens(out_dense) <= MAX_TOKENS
        assert len(out_prose) > len(out_dense)

    def test_hard_char_cap_is_respected(self) -> None:
        # A pathological low-token-density run (spaces) must still be bounded by the
        # hard char backstop so the request body cannot grow unbounded.
        spaced = "a " * 5000  # ~10k chars, very low token density
        out = truncate_for_bge(spaced)
        assert len(out) <= MAX_CHARS

    def test_custom_budget_is_honoured(self) -> None:
        text = "word " * 2000
        out = truncate_for_bge(text, max_tokens=50, max_chars=10_000)
        assert estimate_bert_tokens(out) <= 50
