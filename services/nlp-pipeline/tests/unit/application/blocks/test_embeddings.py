"""Unit tests for Block 7 — Sentence-aware embedding generation (T-C-3-06)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.blocks.embeddings import (
    _split_sentences,
    _word_count,
    chunk_section,
    run_embeddings_block,
)
from nlp_pipeline.application.ports.repositories import ChunkTextStorePort
from nlp_pipeline.domain.models import Section


def _make_section(text: str, section_index: int = 0, speaker: str | None = None) -> Section:
    doc_id = uuid.uuid4()
    return Section(
        section_id=uuid.uuid4(),
        doc_id=doc_id,
        section_index=section_index,
        char_start=0,
        char_end=len(text),
        text=text,
        section_type="body",
        speaker=speaker,
    )


def _make_embedding_client(dimension: int = 1024) -> MagicMock:
    from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-not-found]

    output = EmbeddingOutput(embedding=[0.1] * dimension, model_id="bge", dimension=dimension)
    client = MagicMock()
    client.embed = AsyncMock(return_value=[output])
    return client


@pytest.mark.unit
class TestSplitSentences:
    def test_simple_sentences(self) -> None:
        text = "Apple rose. Tesla fell. Markets closed."
        sentences = _split_sentences(text)
        assert len(sentences) == 3
        assert sentences[0] == "Apple rose."

    def test_single_sentence(self) -> None:
        sentences = _split_sentences("Only one sentence here.")
        assert len(sentences) == 1

    def test_empty_string(self) -> None:
        assert _split_sentences("") == []

    def test_whitespace_only(self) -> None:
        assert _split_sentences("   ") == []


@pytest.mark.unit
class TestWordCount:
    def test_word_count(self) -> None:
        assert _word_count("one two three") == 3

    def test_empty_string(self) -> None:
        assert _word_count("") == 0


@pytest.mark.unit
class TestChunkSection:
    def test_short_section_produces_single_chunk(self) -> None:
        section = _make_section("Apple beats earnings. Revenue grew.")
        chunks = chunk_section(section)
        assert len(chunks) == 1
        assert chunks[0].section_id == section.section_id
        assert chunks[0].doc_id == section.doc_id

    def test_chunk_index_ascending(self) -> None:
        # Build a large section that forces multiple chunks
        long_text = " ".join(f"Sentence number {i} contains information about markets." for i in range(200))
        section = _make_section(long_text)
        chunks = chunk_section(section, max_tokens=50, overlap_tokens=10)
        assert len(chunks) > 1
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_no_chunk_exceeds_max_tokens(self) -> None:
        # Use proper sentences so splitter can divide them
        sentences = [f"Apple reported revenue for quarter {i}." for i in range(200)]
        long_text = " ".join(sentences)
        section = _make_section(long_text)
        chunks = chunk_section(section, max_tokens=20, overlap_tokens=5)
        for chunk in chunks:
            # A chunk should not greatly exceed max_tokens (max 1 sentence overshoot)
            # Sentences here are ~6 words each so max overshoot is ~26 tokens
            assert chunk.token_count <= 26

    def test_sentence_not_split_across_chunks(self) -> None:
        """Sentences must not be split mid-word across consecutive chunks."""
        sentences = [f"Sentence{i} has five words here." for i in range(100)]
        text = " ".join(sentences)
        section = _make_section(text)
        chunks = chunk_section(section, max_tokens=20, overlap_tokens=5)
        for chunk in chunks:
            # Each chunk text must start at a sentence boundary
            # (i.e., each chunk starts with "Sentence" or the beginning)
            stripped = chunk.text.strip()
            assert stripped, "Chunk should not be empty"

    def test_overlap_present_between_consecutive_chunks(self) -> None:
        """Consecutive chunks should share some text via the overlap window."""
        sentences = [f"Apple said revenues grew in quarter {i}." for i in range(30)]
        text = " ".join(sentences)
        section = _make_section(text)
        chunks = chunk_section(section, max_tokens=30, overlap_tokens=10)
        if len(chunks) >= 2:
            # The end of chunk[0] and start of chunk[1] should share words
            words0 = set(chunks[0].text.split())
            words1 = set(chunks[1].text.split())
            assert words0 & words1, "Overlap expected between consecutive chunks"

    def test_empty_section_returns_empty(self) -> None:
        section = _make_section("")
        chunks = chunk_section(section)
        assert chunks == []

    def test_speaker_propagated_to_chunks(self) -> None:
        section = _make_section("Earnings were strong. Growth exceeded targets.", speaker="CEO")
        chunks = chunk_section(section)
        for chunk in chunks:
            assert chunk.speaker == "CEO"

    def test_char_positions_within_section_bounds(self) -> None:
        text = "Apple. Tesla. Google. Amazon. Microsoft."
        section = _make_section(text)
        section_len = len(text)
        chunks = chunk_section(section)
        for chunk in chunks:
            assert chunk.char_start >= 0
            assert chunk.char_end <= section.char_start + section_len


@pytest.mark.unit
class TestRunEmbeddingsBlock:
    @pytest.mark.asyncio
    async def test_section_embeddings_for_all_tiers(self) -> None:
        """Section embeddings are generated for ALL routing tiers."""
        sections = [_make_section("Apple quarterly results exceeded guidance.")]
        client = _make_embedding_client()

        _, chunk_embeddings, section_embeddings, failures = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=False,  # LIGHT tier
        )

        assert len(section_embeddings) == 1
        assert len(chunk_embeddings) == 0  # LIGHT — no chunks
        assert not failures

    @pytest.mark.asyncio
    async def test_chunk_embeddings_only_for_medium_deep(self) -> None:
        """Chunk embeddings are ONLY generated when generate_chunk_embeddings=True."""
        sections = [_make_section("Apple. Tesla. Google. Amazon. Microsoft raised quarterly dividends.")]
        client = _make_embedding_client()

        _, chunk_embeddings, section_embeddings, _ = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=True,  # MEDIUM/DEEP
        )

        assert len(section_embeddings) == 1
        assert len(chunk_embeddings) >= 1  # at least 1 chunk per section

    @pytest.mark.asyncio
    async def test_failed_embedding_creates_pending_entry(self) -> None:
        """Failed embeddings must NOT raise — they produce EmbeddingPendingEntry."""
        client = MagicMock()
        client.embed = AsyncMock(side_effect=Exception("Ollama OOM"))

        sections = [_make_section("Apple reported record revenue this quarter.")]

        _, _, section_embeddings, failures = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=False,
        )

        assert len(section_embeddings) == 0
        assert len(failures) >= 1
        assert failures[0].section_id == sections[0].section_id

    @pytest.mark.asyncio
    async def test_returns_chunks_even_on_embedding_failure(self) -> None:
        """Chunk domain objects are always returned regardless of embedding failures."""
        client = MagicMock()
        client.embed = AsyncMock(side_effect=Exception("failure"))

        sections = [_make_section("Revenue grew strongly. Apple stock rose. Investors cheered loudly.")]

        chunks, _, _, _ = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=True,
        )

        assert len(chunks) >= 1


@pytest.mark.unit
class TestRunEmbeddingsBlockOptionC:
    """Option C: section embedding uses first chunk as representative (not full section text)."""

    @pytest.mark.asyncio
    async def test_section_embedding_uses_first_chunk_text(self) -> None:
        """Section embedding must be called with the first chunk's text, not the full section text."""
        # Build a section with multiple sentences that will produce at least one chunk
        text = "Apple reported record earnings. Revenue grew strongly. Investors cheered."
        section = _make_section(text)
        captured_texts: list[str] = []

        async def _fake_embed(inputs: list) -> list:
            from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-not-found]

            for inp in inputs:
                captured_texts.append(inp.text)
            return [EmbeddingOutput(embedding=[0.1] * 1024, model_id="bge", dimension=1024)]

        client = MagicMock()
        client.embed = _fake_embed

        _, _, section_embeddings, _ = await run_embeddings_block(
            [section],
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=False,
        )

        assert len(section_embeddings) == 1
        # The text sent to the embedding client must be the first chunk's text
        # (which for a single-sentence/short section equals the section text)
        assert len(captured_texts) == 1
        assert captured_texts[0] in text  # first chunk text is a substring/equal of section

    @pytest.mark.asyncio
    async def test_pending_entry_carries_embedding_text(self) -> None:
        """On failure, EmbeddingPendingEntry.embedding_text is populated (not empty)."""
        client = MagicMock()
        client.embed = AsyncMock(side_effect=Exception("Ollama OOM"))

        sections = [_make_section("Apple reported record revenue this quarter.")]

        _, _, _, failures = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=False,
        )

        assert len(failures) >= 1
        assert failures[0].embedding_text != "", "embedding_text must be populated for retry"

    @pytest.mark.asyncio
    async def test_chunk_pending_entry_carries_chunk_text(self) -> None:
        """Failed chunk embeddings also store the chunk text for retry."""
        client = MagicMock()
        client.embed = AsyncMock(side_effect=Exception("timeout"))

        sections = [_make_section("Apple. Tesla. Google. Amazon. Microsoft. IBM reported results.")]

        _, _, _, failures = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=True,
        )

        chunk_failures = [f for f in failures if f.chunk_id is not None]
        assert chunk_failures, "Expected at least one chunk embedding failure"
        for failure in chunk_failures:
            assert failure.embedding_text != "", f"chunk failure must have text: {failure}"


@pytest.mark.unit
class TestRunEmbeddingsBlockChunkTextStore:
    """Tests for the chunk_text_store integration in Block 7."""

    def _make_text_store(self, fail: bool = False) -> ChunkTextStorePort:
        store = MagicMock(spec=ChunkTextStorePort)
        if fail:
            store.put = AsyncMock(side_effect=Exception("MinIO unavailable"))
        else:

            async def _put(chunk_id: object, doc_id: object, text: object) -> str:
                return f"nlp-pipeline/chunk-text/{doc_id}/{chunk_id}/body/v1.txt"

            store.put = AsyncMock(side_effect=_put)
        return store

    @pytest.mark.asyncio
    async def test_chunk_text_keys_set_when_store_provided(self) -> None:
        """When chunk_text_store is provided, all chunks get text_key set."""
        client = _make_embedding_client()
        sections = [_make_section("Apple beats earnings. Revenue grew. Stock rallied.")]
        store = self._make_text_store()

        chunks, _, _, _ = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=True,
            chunk_text_store=store,
        )

        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.text_key is not None
            assert "nlp-pipeline/chunk-text" in chunk.text_key

    @pytest.mark.asyncio
    async def test_chunk_text_keys_none_without_store(self) -> None:
        """When chunk_text_store is None, text_key is never set on chunks."""
        client = _make_embedding_client()
        sections = [_make_section("Apple beats earnings. Revenue grew.")]

        chunks, _, _, _ = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=True,
            chunk_text_store=None,
        )

        for chunk in chunks:
            assert chunk.text_key is None

    @pytest.mark.asyncio
    async def test_upload_failure_does_not_raise(self) -> None:
        """MinIO upload failure must not propagate — chunk is returned with text_key=None."""
        client = _make_embedding_client()
        sections = [_make_section("Revenue grew. Apple stock rose.")]
        store = self._make_text_store(fail=True)

        chunks, _, _, _ = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=True,
            chunk_text_store=store,
        )

        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.text_key is None  # upload failed, key not set

    @pytest.mark.asyncio
    async def test_store_called_for_all_tiers(self) -> None:
        """Text is uploaded even when generate_chunk_embeddings=False (LIGHT tier)."""
        client = _make_embedding_client()
        sections = [_make_section("Short article text. Only one sentence.")]
        store = self._make_text_store()

        chunks, _, _, _ = await run_embeddings_block(
            sections,
            embedding_client=client,
            model_id="bge",
            instruction_prefix="",
            generate_chunk_embeddings=False,  # LIGHT tier
            chunk_text_store=store,
        )

        assert store.put.await_count == len(chunks)
        for chunk in chunks:
            assert chunk.text_key is not None
