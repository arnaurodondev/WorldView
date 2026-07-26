"""Tests for the shared content-addressed embedding cache.

Covers: cache-key construction (model/instruction/text sensitivity) and the
hit/miss decision logic of :class:`CachedEmbeddingClient` against a fake,
in-memory Valkey stand-in (no real Redis/Valkey connection needed).
"""

from __future__ import annotations

import json

import pytest
from ml_clients.dataclasses import EmbeddingInput, EmbeddingOutput
from ml_clients.embedding_cache import CachedEmbeddingClient, embedding_cache_key


class _FakeValkey:
    """Minimal in-memory stand-in for `messaging.valkey.client.ValkeyClient`.

    Implements only the subset of the surface `CachedEmbeddingClient` uses
    (mget/mset/expire), tracking call counts so tests can assert on I/O
    volume in addition to values.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.expiries: dict[str, int] = {}
        self.mget_calls = 0
        self.mset_calls = 0

    async def mget(self, keys: list[str]) -> list[str | None]:
        self.mget_calls += 1
        return [self.store.get(k) for k in keys]

    async def mset(self, mapping: dict[str, str]) -> None:
        self.mset_calls += 1
        self.store.update(mapping)

    async def expire(self, key: str, seconds: int) -> bool:
        self.expiries[key] = seconds
        return True


class _FailingValkey:
    """Simulates a Valkey outage — every call raises."""

    async def mget(self, keys: list[str]) -> list[str | None]:
        raise ConnectionError("valkey unreachable")

    async def mset(self, mapping: dict[str, str]) -> None:
        raise ConnectionError("valkey unreachable")

    async def expire(self, key: str, seconds: int) -> bool:
        raise ConnectionError("valkey unreachable")


class _CountingInner:
    """Fake underlying embedding adapter — records every batch it was asked to embed."""

    def __init__(self, vector: list[float] | None = None) -> None:
        self.calls: list[list[EmbeddingInput]] = []
        self._vector = vector or [0.1, 0.2, 0.3]

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        self.calls.append(inputs)
        return [EmbeddingOutput(embedding=self._vector, model_id=inp.model_id, dimension=3) for inp in inputs]


# ── Cache-key construction ───────────────────────────────────────────────────


def test_key_is_deterministic_for_identical_input() -> None:
    k1 = embedding_cache_key("bge-large", "Apple")
    k2 = embedding_cache_key("bge-large", "Apple")
    assert k1 == k2


def test_key_differs_by_model_id() -> None:
    k1 = embedding_cache_key("bge-large", "Apple")
    k2 = embedding_cache_key("BAAI/bge-large-en-v1.5", "Apple")
    assert k1 != k2


def test_key_differs_by_text() -> None:
    k1 = embedding_cache_key("bge-large", "Apple")
    k2 = embedding_cache_key("bge-large", "the Fed")
    assert k1 != k2


def test_key_differs_by_instruction_prefix() -> None:
    """BGE asymmetric-retrieval prefixes change the actual vector produced —
    a query-embedding must never collide with a passage-embedding cache entry
    for the same raw text."""
    k1 = embedding_cache_key("bge-large", "Apple", instruction_prefix="query: ")
    k2 = embedding_cache_key("bge-large", "Apple", instruction_prefix="passage: ")
    k3 = embedding_cache_key("bge-large", "Apple", instruction_prefix=None)
    assert len({k1, k2, k3}) == 3


def test_key_is_namespaced() -> None:
    assert embedding_cache_key("bge-large", "Apple").startswith("mlc:v1:emb:bge-large:")


# ── Hit/miss behaviour ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_input_returns_empty_without_touching_valkey_or_inner() -> None:
    valkey = _FakeValkey()
    inner = _CountingInner()
    client = CachedEmbeddingClient(inner, valkey)

    result = await client.embed([])

    assert result == []
    assert inner.calls == []
    assert valkey.mget_calls == 0


@pytest.mark.asyncio
async def test_first_call_is_a_full_miss_and_populates_cache() -> None:
    valkey = _FakeValkey()
    inner = _CountingInner(vector=[1.0, 2.0, 3.0])
    client = CachedEmbeddingClient(inner, valkey)

    inputs = [EmbeddingInput(text="Apple", model_id="bge-large")]
    outputs = await client.embed(inputs)

    assert len(inner.calls) == 1  # exactly one paid call
    assert inner.calls[0] == inputs
    assert outputs[0].embedding == [1.0, 2.0, 3.0]
    # The result was written back so a subsequent call can hit.
    assert valkey.mset_calls == 1


@pytest.mark.asyncio
async def test_second_call_with_identical_text_is_a_cache_hit_no_inner_call() -> None:
    """The core dedup guarantee: repeating the SAME (model, prefix, text) —
    e.g. the entity surface 'Apple' appearing in a second article — must
    NEVER re-invoke the underlying (paid) embedding adapter."""
    valkey = _FakeValkey()
    inner = _CountingInner(vector=[9.0, 9.0, 9.0])
    client = CachedEmbeddingClient(inner, valkey)

    inputs = [EmbeddingInput(text="Apple", model_id="bge-large")]
    await client.embed(inputs)
    assert len(inner.calls) == 1

    # Second call, same text — must be served entirely from cache.
    outputs2 = await client.embed(inputs)
    assert len(inner.calls) == 1  # STILL 1 — no new paid call
    assert outputs2[0].embedding == [9.0, 9.0, 9.0]


@pytest.mark.asyncio
async def test_partial_batch_hit_only_embeds_the_miss() -> None:
    valkey = _FakeValkey()
    inner = _CountingInner()
    client = CachedEmbeddingClient(inner, valkey)

    # Warm the cache for "Apple" only.
    await client.embed([EmbeddingInput(text="Apple", model_id="bge-large")])
    assert len(inner.calls) == 1

    # Batch of [Apple (hit), the Fed (miss)] — only the miss should be sent.
    batch = [
        EmbeddingInput(text="Apple", model_id="bge-large"),
        EmbeddingInput(text="the Fed", model_id="bge-large"),
    ]
    outputs = await client.embed(batch)

    assert len(inner.calls) == 2  # one more call, for the miss only
    assert inner.calls[1] == [EmbeddingInput(text="the Fed", model_id="bge-large")]
    assert len(outputs) == 2


@pytest.mark.asyncio
async def test_different_model_id_is_a_separate_cache_namespace() -> None:
    """Two sites embedding the SAME text under DIFFERENT model_id labels
    (e.g. nlp-pipeline's 'bge-large' vs 'BAAI/bge-large-en-v1.5') must not
    collide — they are logged as distinct model_id though physically the
    same weights; a conflation risk this cache deliberately avoids."""
    valkey = _FakeValkey()
    inner = _CountingInner()
    client = CachedEmbeddingClient(inner, valkey)

    await client.embed([EmbeddingInput(text="Apple", model_id="bge-large")])
    await client.embed([EmbeddingInput(text="Apple", model_id="BAAI/bge-large-en-v1.5")])

    assert len(inner.calls) == 2  # both are misses — different namespaces


@pytest.mark.asyncio
async def test_valkey_outage_degrades_to_always_miss_not_a_hard_failure() -> None:
    """The cache must never become a NEW source of pipeline failures — a
    Valkey outage should just disable caching for that call, not raise."""
    valkey = _FailingValkey()
    inner = _CountingInner()
    client = CachedEmbeddingClient(inner, valkey)

    outputs = await client.embed([EmbeddingInput(text="Apple", model_id="bge-large")])

    assert len(outputs) == 1
    assert len(inner.calls) == 1  # fell through to the paid call


@pytest.mark.asyncio
async def test_underlying_short_batch_truncates_result_preserving_failure_contract() -> None:
    """Callers (entity_resolution/_embed_batch) detect partial failure by
    comparing len(outputs) to len(inputs), not by scanning for None. The
    cache wrapper must preserve that contract on a miss the inner adapter
    fails to fill."""

    class _ShortInner:
        async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
            return []  # simulates total provider failure for the miss

    valkey = _FakeValkey()
    client = CachedEmbeddingClient(_ShortInner(), valkey)

    outputs = await client.embed([EmbeddingInput(text="Apple", model_id="bge-large")])

    assert outputs == []  # truncated at the gap, not padded


@pytest.mark.asyncio
async def test_corrupt_cache_entry_is_treated_as_a_miss() -> None:
    valkey = _FakeValkey()
    key = embedding_cache_key("bge-large", "Apple")
    valkey.store[key] = "not-json{{{"
    inner = _CountingInner(vector=[5.0, 5.0, 5.0])
    client = CachedEmbeddingClient(inner, valkey)

    outputs = await client.embed([EmbeddingInput(text="Apple", model_id="bge-large")])

    assert len(inner.calls) == 1
    assert outputs[0].embedding == [5.0, 5.0, 5.0]


@pytest.mark.asyncio
async def test_ttl_is_applied_to_stored_keys() -> None:
    valkey = _FakeValkey()
    client = CachedEmbeddingClient(_CountingInner(), valkey, ttl_seconds=123)

    await client.embed([EmbeddingInput(text="Apple", model_id="bge-large")])

    key = embedding_cache_key("bge-large", "Apple")
    assert valkey.expiries[key] == 123
    # sanity: the stored payload round-trips through JSON as expected.
    payload = json.loads(valkey.store[key])
    assert payload["dimension"] == 3
