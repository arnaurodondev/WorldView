"""Integration-style test: `canonicalize_relation_type` Step 2 + the shared
embedding cache.

Mirrors the real composition-root wiring in
``knowledge_graph.infrastructure.messaging.consumers.enriched_consumer_main``:
the raw batch ``EmbeddingClient`` adapter is wrapped in
``CachedEmbeddingClient`` BEFORE being bridged to the block's
``embed(text) -> list[float]`` protocol via a thin singular-string adapter
(the same shape as ``_EmbeddingBridgeClient``).

Confirms the concrete cost problem this cache exists to fix at this site:
relation-type label strings (e.g. "acquired") are drawn from a small,
highly-repeated vocabulary, so the SAME raw_type reaching Step 2 (ANN
soft-map) on a second extraction must not re-pay the provider.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from knowledge_graph.application.blocks.canonicalization import (
    canonicalize_relation_type,
)
from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput  # type: ignore[import-not-found]
from ml_clients.embedding_cache import CachedEmbeddingClient  # type: ignore[import-not-found]

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


class _CountingBatchAdapter:
    """Fake raw batch provider adapter — records every batch it embeds."""

    def __init__(self) -> None:
        self.calls: list[list[EmbeddingInput]] = []

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        self.calls.append(inputs)
        return [EmbeddingOutput(embedding=[0.1, 0.2, 0.3], model_id=inp.model_id, dimension=3) for inp in inputs]


class _SingularBridge:
    """Bridges the batch `CachedEmbeddingClient` to the block's `embed(str)
    -> list[float]` protocol — same shape as `_EmbeddingBridgeClient` in
    `enriched_consumer_main.py`."""

    def __init__(self, batch_client: CachedEmbeddingClient, model_id: str) -> None:
        self._batch_client = batch_client
        self._model_id = model_id

    async def embed(self, text: str) -> list[float]:
        outputs = await self._batch_client.embed([EmbeddingInput(text=text, model_id=self._model_id)])
        return outputs[0].embedding


def _make_registry_repo() -> AsyncMock:
    """No exact match, no soft match — Step 3 (propose) always fires, but
    Step 2's embed() call still happens first, which is all this test needs."""
    repo = AsyncMock()
    repo.find_exact = AsyncMock(return_value=None)
    repo.find_by_embedding = AsyncMock(return_value=None)
    return repo


def _make_outbox_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.append = AsyncMock(return_value=uuid4())
    return repo


def test_repeated_raw_type_across_two_extractions_embeds_once() -> None:
    """ "acquired" is proposed by one extraction, then encountered again by a
    LATER extraction (still not in the registry) — the second call's Step-2
    embed() must be served from cache, not re-paid."""
    batch_adapter = _CountingBatchAdapter()
    cached_batch_client = CachedEmbeddingClient(batch_adapter, _FakeValkey())
    bridge = _SingularBridge(cached_batch_client, model_id="bge-large")

    registry = _make_registry_repo()
    outbox = _make_outbox_repo()

    result_1 = asyncio.run(
        canonicalize_relation_type(
            raw_type="acquired",
            semantic_mode_hint="RELATION_STATE",
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            source_doc_id=uuid4(),
            registry_repo=registry,
            outbox_repo=outbox,
            embedding_client=bridge,  # type: ignore[arg-type]
        )
    )
    assert result_1.step == "proposed"
    assert len(batch_adapter.calls) == 1  # first sighting — a real, paid embed call

    result_2 = asyncio.run(
        canonicalize_relation_type(
            raw_type="acquired",
            semantic_mode_hint="RELATION_STATE",
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            source_doc_id=uuid4(),
            registry_repo=registry,
            outbox_repo=outbox,
            embedding_client=bridge,  # type: ignore[arg-type]
        )
    )
    assert result_2.step == "proposed"
    assert len(batch_adapter.calls) == 1  # STILL 1 — second call was a cache hit


def test_different_raw_type_is_a_separate_cache_entry() -> None:
    batch_adapter = _CountingBatchAdapter()
    cached_batch_client = CachedEmbeddingClient(batch_adapter, _FakeValkey())
    bridge = _SingularBridge(cached_batch_client, model_id="bge-large")

    registry = _make_registry_repo()
    outbox = _make_outbox_repo()

    asyncio.run(
        canonicalize_relation_type(
            raw_type="acquired",
            semantic_mode_hint="RELATION_STATE",
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            source_doc_id=uuid4(),
            registry_repo=registry,
            outbox_repo=outbox,
            embedding_client=bridge,  # type: ignore[arg-type]
        )
    )
    asyncio.run(
        canonicalize_relation_type(
            raw_type="partnered_with",
            semantic_mode_hint="RELATION_STATE",
            subject_entity_id=uuid4(),
            object_entity_id=uuid4(),
            source_doc_id=uuid4(),
            registry_repo=registry,
            outbox_repo=outbox,
            embedding_client=bridge,  # type: ignore[arg-type]
        )
    )

    assert len(batch_adapter.calls) == 2  # both are misses — different raw_type
