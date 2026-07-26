"""Integration-style test: `_batch_embed_stage4` + the shared embedding cache.

Confirms the composition-root wiring (`CachedEmbeddingClient` wrapping the
provider adapter — see `nlp_pipeline.infrastructure.messaging.consumers.
article_consumer_main` / `nlp_pipeline.bootstrap.embedding.build_embedding_client`)
actually prevents a repeat call for an IDENTICAL mention surface, which is
the concrete cost problem this cache exists to fix: the same entity mention
text (e.g. "Apple") is re-embedded on every article that mentions it.
"""

from __future__ import annotations

import uuid

import pytest
from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput  # type: ignore[import-not-found]
from ml_clients.embedding_cache import CachedEmbeddingClient  # type: ignore[import-not-found]
from nlp_pipeline.application.blocks.entity_resolution import _batch_embed_stage4
from nlp_pipeline.domain.enums import MentionClass
from nlp_pipeline.domain.models import EntityMention

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
        return [EmbeddingOutput(embedding=[0.5] * 8, model_id=inp.model_id, dimension=8) for inp in inputs]


def _mention(text: str) -> EntityMention:
    return EntityMention(
        mention_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        section_id=None,
        mention_text=text,
        mention_class=MentionClass.ORGANIZATION,
        confidence=0.9,
        char_start=0,
        char_end=len(text),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_identical_mention_surface_across_two_articles_embeds_once() -> None:
    """The audit's motivating scenario: "Apple" appears in article A, then
    again (as its own unresolved candidate) in article B — the SECOND
    article's Stage-4 batch-embed call must be served from cache, not
    re-paid, when the shared adapter is wrapped in `CachedEmbeddingClient`.
    """
    inner = _CountingInner()
    cached_client = CachedEmbeddingClient(inner, _FakeValkey())

    # Article A: one unresolved candidate mention of "Apple".
    article_a_candidates = [_mention("Apple")]
    vectors_a = await _batch_embed_stage4(
        article_a_candidates,
        cached_client,  # type: ignore[arg-type]
        model_id="bge-large",
        instruction_prefix="",
    )
    assert len(inner.calls) == 1  # first sighting — a real, paid embed call
    assert vectors_a[0] is not None

    # Article B: same surface text, independent EntityMention instance.
    article_b_candidates = [_mention("Apple")]
    vectors_b = await _batch_embed_stage4(
        article_b_candidates,
        cached_client,  # type: ignore[arg-type]
        model_id="bge-large",
        instruction_prefix="",
    )

    assert len(inner.calls) == 1  # STILL 1 — article B's call was a cache hit
    assert vectors_b[0] == vectors_a[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mixed_batch_only_pays_for_the_new_surface() -> None:
    """A batch with one previously-seen mention ("Apple") and one new one
    ("the Fed") must only send the new one to the provider."""
    inner = _CountingInner()
    cached_client = CachedEmbeddingClient(inner, _FakeValkey())

    await _batch_embed_stage4(
        [_mention("Apple")],
        cached_client,  # type: ignore[arg-type]
        model_id="bge-large",
        instruction_prefix="",
    )
    assert len(inner.calls) == 1

    vectors = await _batch_embed_stage4(
        [_mention("Apple"), _mention("the Fed")],
        cached_client,  # type: ignore[arg-type]
        model_id="bge-large",
        instruction_prefix="",
    )

    assert len(inner.calls) == 2
    assert len(inner.calls[1]) == 1  # only "the Fed" was sent
    assert inner.calls[1][0].text == "the Fed"
    assert all(v is not None for v in vectors)
