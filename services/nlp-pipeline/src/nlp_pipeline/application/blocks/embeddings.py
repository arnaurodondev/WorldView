"""Block 7 — Sentence-aware chunked embeddings (PRD §6.7 Block 7).

Produces:
  - Section embeddings for ALL routing tiers.
  - Chunk embeddings for MEDIUM/DEEP only (via should_generate_chunk_embeddings).
  - Chunk text uploads to MinIO (ALL tiers, best-effort via ChunkTextStorePort).
  - Failed embeddings → EmbeddingPendingEntry (never raises on partial failure).
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
from typing import TYPE_CHECKING

import structlog  # type: ignore[import-untyped]

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from nlp_pipeline.domain.models import Chunk, EmbeddingPendingEntry

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

if TYPE_CHECKING:
    from uuid import UUID

    from ml_clients.protocols import EmbeddingClient  # type: ignore[import-not-found]

    from nlp_pipeline.application.ports.repositories import ChunkTextStorePort
    from nlp_pipeline.domain.models import Section


# ── Chunking constants (PRD §6.7 Block 7) ────────────────────────────────────

#: Maximum tokens per chunk (approximate word count)
CHUNK_MAX_TOKENS: int = 512

#: Overlap in tokens between consecutive chunks
CHUNK_OVERLAP_TOKENS: int = 64

#: Sentence boundary pattern
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


# ── Sentence-aware chunking ───────────────────────────────────────────────────


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence units using punctuation boundaries."""
    parts = _SENTENCE_END_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _word_count(text: str) -> int:
    """Approximate token count via whitespace-split word count."""
    return len(text.split())


def chunk_section(
    section: Section,
    max_tokens: int = CHUNK_MAX_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Produce sentence-aware chunks from a section.

    Invariants (PRD §6.7 Block 7):
      - Chunks are at most max_tokens tokens (approximate).
      - Consecutive chunks overlap by overlap_tokens tokens.
      - Sentence boundaries are NEVER split — a sentence always ends in the
        chunk it starts in.
      - If a single sentence exceeds max_tokens it becomes its own chunk.

    Args:
        section: Source section to chunk.
        max_tokens: Target upper bound on chunk size (word count).
        overlap_tokens: Overlap window between consecutive chunks.

    Returns:
        Ordered list of Chunk domain objects.
    """
    sentences = _split_sentences(section.text)
    if not sentences:
        return []

    chunks: list[Chunk] = []
    chunk_index = 0
    i = 0  # sentence pointer

    # Track char offset within the section text for char_start/char_end
    # We rebuild position by searching from previous end.
    section_text = section.text
    search_offset = 0

    # Carry-over sentences from the overlap window
    overlap_sentences: list[str] = []

    while i < len(sentences):
        # Start new chunk with the overlap tail
        current_sentences: list[str] = list(overlap_sentences)
        current_tokens = sum(_word_count(s) for s in current_sentences)

        # Add sentences until we would exceed max_tokens
        while i < len(sentences):
            s_tokens = _word_count(sentences[i])
            if current_tokens + s_tokens > max_tokens and current_sentences:
                # Would overflow — flush
                break
            current_sentences.append(sentences[i])
            current_tokens += s_tokens
            i += 1

        if not current_sentences:
            # Single sentence that alone exceeds max_tokens — emit as-is
            current_sentences = [sentences[i]]
            i += 1

        chunk_text = " ".join(current_sentences)

        # Locate char_start / char_end within the section text
        char_start = section_text.find(current_sentences[0], search_offset)
        if char_start == -1:
            char_start = 0  # fallback
        last_sentence = current_sentences[-1]
        char_end_raw = section_text.find(last_sentence, char_start)
        char_end = len(section_text) if char_end_raw == -1 else char_end_raw + len(last_sentence)

        # Clamp
        char_end = min(char_end, len(section_text))
        search_offset = max(0, char_end - len(last_sentence))

        chunk = Chunk(
            chunk_id=common.ids.new_uuid7(),
            doc_id=section.doc_id,
            section_id=section.section_id,
            chunk_index=chunk_index,
            char_start=char_start + section.char_start,
            char_end=char_end + section.char_start,
            token_count=current_tokens,
            text=chunk_text,
            sentence_start_idx=None,
            sentence_end_idx=None,
            speaker=section.speaker,
            heading_path=None,
        )
        chunks.append(chunk)
        chunk_index += 1

        # Build overlap window for the next chunk
        # Take the trailing sentences that total ≤ overlap_tokens
        overlap_sentences = []
        overlap_tokens_acc = 0
        for sent in reversed(current_sentences):
            w = _word_count(sent)
            if overlap_tokens_acc + w > overlap_tokens:
                break
            overlap_sentences.insert(0, sent)
            overlap_tokens_acc += w

    return chunks


# ── Embedding generation ──────────────────────────────────────────────────────


async def _embed_text(
    text: str,
    model_id: str,
    instruction_prefix: str,
    embedding_client: EmbeddingClient,
) -> list[float] | None:
    """Embed a single text. Returns None on failure (caller logs pending entry)."""
    from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]

    inp = EmbeddingInput(text=text, model_id=model_id, instruction_prefix=instruction_prefix)
    try:
        outputs = await embedding_client.embed([inp])
        if outputs:
            return outputs[0].embedding
    except Exception as exc:
        logger.debug("embeddings.embed_failed", error=str(exc))
    return None


async def _upload_chunk_texts(
    chunks: list[Chunk],
    chunk_text_store: ChunkTextStorePort,
) -> list[Chunk]:
    """Upload chunk texts to MinIO in parallel (best-effort).

    For each chunk, attempts ``chunk_text_store.put()`` and returns an updated
    Chunk with ``text_key`` set.  Individual failures are logged and swallowed —
    the chunk is returned unchanged (``text_key=None``).
    """

    async def _upload_one(chunk: Chunk) -> Chunk:
        if not chunk.text:
            return chunk
        try:
            key = await chunk_text_store.put(chunk.chunk_id, chunk.doc_id, chunk.text)
            return dataclasses.replace(chunk, text_key=key)
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "chunk_text_upload_failed",
                chunk_id=str(chunk.chunk_id),
                error=str(exc),
            )
            return chunk

    return list(await asyncio.gather(*[_upload_one(c) for c in chunks]))


async def run_embeddings_block(
    sections: list[Section],
    *,
    embedding_client: EmbeddingClient,
    model_id: str,
    instruction_prefix: str,
    generate_chunk_embeddings: bool,
    max_tokens: int = CHUNK_MAX_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
    chunk_text_store: ChunkTextStorePort | None = None,
) -> tuple[
    list[Chunk],
    list[tuple[UUID, list[float]]],  # (chunk_id, embedding)
    list[tuple[UUID, list[float]]],  # (section_id, embedding)
    list[EmbeddingPendingEntry],
]:
    """Run Block 7: chunk + section embedding generation.

    Section embeddings are produced for ALL routing tiers.
    Chunk embeddings are produced only when ``generate_chunk_embeddings=True``
    (MEDIUM/DEEP tiers — determined by the caller via suppression gate).

    When ``chunk_text_store`` is provided, chunk text is uploaded to MinIO
    for ALL routing tiers (best-effort; failures do not raise).

    Failed embeddings are recorded as EmbeddingPendingEntry entries; they are
    never re-raised to the caller.

    Returns:
        (chunks, chunk_embeddings, section_embeddings, pending_failures)
    """
    all_chunks: list[Chunk] = []
    chunk_embeddings: list[tuple[UUID, list[float]]] = []
    section_embeddings: list[tuple[UUID, list[float]]] = []
    pending_failures: list[EmbeddingPendingEntry] = []

    now = common.time.utc_now()  # type: ignore[no-any-return]

    for section in sections:
        # ── Section embedding (ALL tiers) ─────────────────────────────────
        sec_vec = await _embed_text(
            section.text,
            model_id=model_id,
            instruction_prefix=instruction_prefix,
            embedding_client=embedding_client,
        )
        if sec_vec is not None:
            section_embeddings.append((section.section_id, sec_vec))
        else:
            pending_failures.append(
                EmbeddingPendingEntry(
                    doc_id=section.doc_id,
                    chunk_id=None,
                    section_id=section.section_id,
                    error_detail="section embedding failed",
                    created_at=now,
                ),
            )

        # ── Chunk splitting ───────────────────────────────────────────────
        section_chunks = chunk_section(section, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        all_chunks.extend(section_chunks)

        if not generate_chunk_embeddings:
            continue

        # ── Chunk embeddings (MEDIUM/DEEP only) ───────────────────────────
        for chunk in section_chunks:
            chunk_vec = await _embed_text(
                chunk.text,
                model_id=model_id,
                instruction_prefix=instruction_prefix,
                embedding_client=embedding_client,
            )
            if chunk_vec is not None:
                chunk_embeddings.append((chunk.chunk_id, chunk_vec))
            else:
                pending_failures.append(
                    EmbeddingPendingEntry(
                        doc_id=chunk.doc_id,
                        chunk_id=chunk.chunk_id,
                        section_id=chunk.section_id,
                        error_detail="chunk embedding failed",
                        created_at=now,
                    ),
                )

    # ── Chunk text upload (ALL tiers, best-effort) ────────────────────────
    if chunk_text_store is not None and all_chunks:
        all_chunks = await _upload_chunk_texts(all_chunks, chunk_text_store)

    return all_chunks, chunk_embeddings, section_embeddings, pending_failures
