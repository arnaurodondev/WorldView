"""Integration-style test: `run_embeddings_block` + the shared embedding cache.

Confirms the composition-root wiring (`CachedEmbeddingClient` wrapping the
provider adapter) prevents a repeat, paid embed call for a chunk/section
whose text was already embedded — the concrete scenario is a backfill/retry
of a document whose `chunk_embeddings` INSERT uses
``ON CONFLICT (chunk_id, model_id) DO NOTHING`` (see
``nlp_pipeline.workers.backfill_light_chunk_embeddings`` /
``nlp_pipeline.infrastructure.workers.embedding_retry_worker``): without the
cache, re-running the embedding step for the SAME text re-pays the provider
even though the eventual DB write is a guaranteed no-op.
"""

from __future__ import annotations

import uuid

import pytest
from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput  # type: ignore[import-not-found]
from ml_clients.embedding_cache import CachedEmbeddingClient  # type: ignore[import-not-found]
from nlp_pipeline.application.blocks.embeddings import run_embeddings_block
from nlp_pipeline.domain.models import Section

pytestmark = pytest.mark.unit


class _FakeValkey:
    """Same minimal in-memory Valkey stand-in used by the ml-clients unit tests."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.store.get(k) for k in keys]

    async def mset(self, mapping: dict[str, str]) -> None:
        self.store.update(mapping)

    async def expire(self, key: str, seconds: int) -> bool:
        return True


class _CountingInner:
    """Fake provider adapter — records every batch it was asked to embed."""

    def __init__(self) -> None:
        self.calls: list[list[EmbeddingInput]] = []

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        self.calls.append(inputs)
        return [EmbeddingOutput(embedding=[0.25] * 8, model_id=inp.model_id, dimension=8) for inp in inputs]


def _make_section(text: str) -> Section:
    return Section(
        section_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        section_index=0,
        char_start=0,
        char_end=len(text),
        text=text,
        section_type="body",
        speaker=None,
    )


@pytest.mark.asyncio
async def test_retrying_the_same_document_reuses_the_cached_chunk_embedding() -> None:
    """Simulates a backfill/retry re-running Block 7 for an identical section
    text (e.g. the retry worker re-claiming a stuck `embedding_pending` row,
    or a resumed backfill re-processing a doc it already embedded but whose
    write never got flushed/observed). The second pass must not re-pay."""
    inner = _CountingInner()
    cached_client = CachedEmbeddingClient(inner, _FakeValkey())

    # A short single-sentence section so section-embedding text == chunk[0]
    # text deterministically, keeping the assertion simple.
    text = "Apple reported strong quarterly earnings."
    sections = [_make_section(text)]

    first_pass = await run_embeddings_block(
        sections,
        embedding_client=cached_client,  # type: ignore[arg-type]
        model_id="bge-large",
        instruction_prefix="",
        generate_chunk_embeddings=True,
    )
    first_calls = len(inner.calls)
    assert first_calls >= 1
    assert first_pass[1]  # chunk_embeddings non-empty
    assert first_pass[2]  # section_embeddings non-empty

    # Re-run on a FRESH Section domain object with identical text (this is
    # what a retry/backfill re-processing the same doc looks like: new
    # objects, same content).
    retry_sections = [_make_section(text)]
    second_pass = await run_embeddings_block(
        retry_sections,
        embedding_client=cached_client,  # type: ignore[arg-type]
        model_id="bge-large",
        instruction_prefix="",
        generate_chunk_embeddings=True,
    )

    assert len(inner.calls) == first_calls  # no NEW paid calls on retry
    assert second_pass[1]  # still produced chunk embeddings (served from cache)
    assert second_pass[2]
