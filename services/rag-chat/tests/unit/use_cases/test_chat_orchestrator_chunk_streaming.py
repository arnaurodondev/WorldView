"""Unit tests for the SSE chunk-streaming helper.

PLAN-0099 W1 / BP-595: the orchestrator's "LLM answered directly" branch
used to emit one large ``emit_token`` event holding the entire response,
giving chat-eval TPS ≈ 0.087 tok/s. We now slice the buffered text into
word groups and emit one ``token`` SSE frame per slice. These tests pin
the chunker contract — round-trip fidelity and frame count — so any
future tweak to chunk size or whitespace handling fails loudly here.
"""

from __future__ import annotations

import pytest
from rag_chat.application.use_cases.chat_orchestrator import (
    _STREAM_WORDS_PER_CHUNK,
    _chunk_text_for_streaming,
)

pytestmark = pytest.mark.unit


def test_chunk_text_round_trips_exactly() -> None:
    """Concatenating chunks must reconstruct the input character-for-character.

    Downstream grounding validation reads the accumulated answer back from
    the streamed text; any whitespace drift would silently corrupt the
    captured response and could miss numeric-grounding violations.
    """
    text = "Apple's main competitors include Samsung, Google, and Microsoft in the smartphone and OS space."
    chunks = _chunk_text_for_streaming(text)
    assert "".join(chunks) == text


def test_chunk_text_emits_multiple_frames_for_long_answer() -> None:
    """A paragraph-length answer must produce ≥2 chunks so TTFT is real."""
    # 24 words → with the default 8-per-chunk groupage we expect exactly 3 frames.
    text = " ".join(f"word{i}" for i in range(24))
    chunks = _chunk_text_for_streaming(text)
    assert len(chunks) == 3
    assert "".join(chunks) == text


def test_chunk_text_empty_returns_empty_list() -> None:
    """Empty / whitespace input returns [] so the caller emits nothing.

    Avoids a zero-byte SSE frame which the harness's TTFT detector would
    incorrectly latch onto as first-content arrival.
    """
    assert _chunk_text_for_streaming("") == []


def test_chunk_text_invalid_words_per_chunk_falls_back_to_default() -> None:
    """Misconfigured group size degrades to the default, not ZeroDivisionError."""
    text = "one two three four five six seven eight nine ten"
    # Negative + zero should both fall back to ``_STREAM_WORDS_PER_CHUNK``.
    expected = _chunk_text_for_streaming(text, words_per_chunk=_STREAM_WORDS_PER_CHUNK)
    assert _chunk_text_for_streaming(text, words_per_chunk=0) == expected
    assert _chunk_text_for_streaming(text, words_per_chunk=-3) == expected


def test_chunk_text_no_whitespace_returns_single_chunk() -> None:
    """A whitespace-free token (URL, long identifier) must not be split mid-word."""
    text = "https://example.com/very/long/path/that/has/no/spaces"
    chunks = _chunk_text_for_streaming(text)
    assert chunks == [text]


def test_chunk_text_preserves_internal_whitespace_runs() -> None:
    """Multi-space / newline runs are preserved on the trailing edge of chunks."""
    text = "line one\n\nline two with    extra     spaces"
    chunks = _chunk_text_for_streaming(text)
    assert "".join(chunks) == text


def test_chunk_text_small_group_size_produces_many_frames() -> None:
    """A 2-word group size yields one frame per word pair — proves the knob works."""
    text = "alpha beta gamma delta epsilon zeta"
    chunks = _chunk_text_for_streaming(text, words_per_chunk=2)
    assert len(chunks) == 3
    assert "".join(chunks) == text


def test_chunk_text_single_word_returns_single_chunk() -> None:
    """A one-word answer still produces one frame, not zero."""
    chunks = _chunk_text_for_streaming("ok")
    assert chunks == ["ok"]
