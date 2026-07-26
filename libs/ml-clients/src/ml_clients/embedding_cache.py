"""Shared content-addressed embedding cache (Valkey-backed).

Motivation (2026-07 embedding-cost audit): three independent embedding call
sites re-embed identical text on every call with no cross-call dedup:

  1. ``nlp_pipeline.application.blocks.entity_resolution._batch_embed_stage4``
     — entity mention surfaces (e.g. "Apple", "the Fed") are re-embedded on
     EVERY article that mentions them.
  2. ``nlp_pipeline.application.blocks.embeddings.run_embeddings_block`` —
     chunk/section embeddings; the DB write is ``ON CONFLICT DO NOTHING``,
     so a backfill/retry of an already-embedded chunk pays for the embed
     call again even though the write is a safe no-op.
  3. ``knowledge_graph.application.blocks.canonicalization.canonicalize_relation_type``
     — relation-type label strings (e.g. "acquired", "partnered_with") are
     drawn from a small, highly-repeated vocabulary across extractions.

All three sites embed with the SAME physical model family (BAAI bge-large,
1024-dim — see ``docs/BUG_PATTERNS.md`` / service configs), a BERT-style
encoder with no sampling/dropout at inference time, so identical
``(model_id, instruction_prefix, text)`` ALWAYS produces the identical
vector — a textbook case for a content-addressed cache. This module
provides ONE shared, reusable wrapper instead of three ad-hoc caches so any
future embedding call site gets the same dedup for free.

Design:
  - Cache key: ``mlc:v1:emb:<model_id>:sha256(instruction_prefix + "\\x00" + text)``
    (exact-match only — no fuzzy/near-duplicate matching in this first
    version; deliberately conservative).
  - Value: JSON-encoded ``{"embedding": [...], "dimension": N}``.
  - TTL: 60 days by default (embeddings for a fixed, versioned model do not
    go stale the way LLM completions do — the existing ``entity_embedding_state``
    HNSW-indexed table already owns *staleness*/*refresh* semantics for
    entity description/narrative/fundamentals vectors; THIS cache is a pure
    latency/cost optimization for the mention-surface and chunk-text
    embedding calls that table does not cover, and is safe to expire
    independently since a cache miss just re-embeds).
  - Wraps the ``ml_clients.protocols.EmbeddingClient`` batch protocol
    (``embed(list[EmbeddingInput]) -> list[EmbeddingOutput]``) so it is a
    drop-in decorator around any adapter (DeepInfra/Ollama/Jina/fallback
    chain) — callers construct it ONCE at the composition root and every
    existing call site benefits without internal changes.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import structlog

from ml_clients.dataclasses import EmbeddingOutput

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
    from ml_clients.dataclasses import EmbeddingInput
    from ml_clients.protocols import EmbeddingClient

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

#: Default TTL for cached embeddings — 60 days. Long-lived because a fixed
#: model version's output for a given text never changes; the only reason to
#: expire at all is to bound Valkey memory growth and to let a future model
#: swap (which changes ``model_id`` and therefore the cache key namespace
#: anyway) naturally age out orphaned keys.
DEFAULT_TTL_SECONDS = 60 * 24 * 60 * 60

_KEY_PREFIX = "mlc:v1:emb"


def embedding_cache_key(model_id: str, text: str, instruction_prefix: str | None = None) -> str:
    """Build the content-addressed cache key for one ``(model_id, text)`` pair.

    ``instruction_prefix`` is folded into the hash (not just appended to the
    key) because BGE-style asymmetric retrieval prefixes ("query: " vs
    "passage: ") change the ACTUAL vector produced for the same raw text —
    conflating them would silently serve a query-embedding as a
    document-embedding cache hit (or vice versa), a correctness bug that
    would otherwise only surface as pgvector cosine-distance drift.
    """
    digest = hashlib.sha256(f"{instruction_prefix or ''}\x00{text}".encode()).hexdigest()
    return f"{_KEY_PREFIX}:{model_id}:{digest}"


class CachedEmbeddingClient:
    """Decorator that adds a content-addressed Valkey cache in front of an
    :class:`~ml_clients.protocols.EmbeddingClient`.

    Implements the same batch ``embed(inputs) -> outputs`` protocol as the
    wrapped client, so it can be substituted anywhere an ``EmbeddingClient``
    is expected (nlp-pipeline's ``build_embedding_client`` composition root,
    knowledge-graph's ``_build_embedding_adapter``, etc.) with no changes to
    the call sites that consume it.

    Args:
        inner: The underlying embedding adapter (DeepInfra/Ollama/Jina/
            fallback-chain) that performs the actual (paid) embed call.
        valkey: Shared Valkey client for the cache store.
        ttl_seconds: Cache entry TTL. Defaults to :data:`DEFAULT_TTL_SECONDS`.
    """

    def __init__(
        self,
        inner: EmbeddingClient,
        valkey: ValkeyClient,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._inner = inner
        self._valkey = valkey
        self._ttl_seconds = ttl_seconds

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        """Embed *inputs*, serving exact-match cache hits and only paying for misses.

        Preserves input order in the returned list on the full-success path.
        Mirrors the wrapped adapters' existing "returned fewer than
        requested == some entries failed" contract (see
        ``entity_resolution._batch_embed_stage4`` / ``embeddings._embed_batch``
        docstrings): if the underlying adapter cannot produce a vector for a
        miss, the returned list is truncated at that gap rather than padded
        with a placeholder, so callers' existing length-comparison failure
        handling keeps working unchanged.

        Cache reads/writes are best-effort: a Valkey error degrades to
        "treat as a miss" / "skip the write" rather than failing the embed
        call — this cache must never become a new source of pipeline
        failures.
        """
        if not inputs:
            return []

        keys = [embedding_cache_key(inp.model_id, inp.text, inp.instruction_prefix) for inp in inputs]

        try:
            cached_raw = await self._valkey.mget(keys)
        except Exception as exc:  # pragma: no cover - defensive, Valkey outage
            logger.warning("embedding_cache.mget_failed", error=str(exc))
            cached_raw = [None] * len(keys)

        outputs: list[EmbeddingOutput | None] = [None] * len(inputs)
        miss_indices: list[int] = []
        hits = 0
        for idx, raw in enumerate(cached_raw):
            if raw is None:
                miss_indices.append(idx)
                continue
            try:
                payload = json.loads(raw)
                outputs[idx] = EmbeddingOutput(
                    embedding=payload["embedding"],
                    model_id=inputs[idx].model_id,
                    dimension=payload["dimension"],
                )
                hits += 1
            except (ValueError, KeyError, TypeError) as exc:
                # Corrupt cache entry (should not happen) — treat as a miss.
                logger.warning("embedding_cache.corrupt_entry", error=str(exc))
                miss_indices.append(idx)

        if miss_indices:
            miss_inputs = [inputs[i] for i in miss_indices]
            miss_outputs = await self._inner.embed(miss_inputs)
            to_store: dict[str, str] = {}
            for offset, idx in enumerate(miss_indices):
                if offset >= len(miss_outputs):
                    # Underlying adapter returned fewer outputs than requested
                    # (transient provider failure) — leave this slot None so
                    # the length-truncation below reproduces the existing
                    # "short batch == partial failure" signal callers rely on.
                    continue
                out = miss_outputs[offset]
                outputs[idx] = out
                to_store[keys[idx]] = json.dumps({"embedding": out.embedding, "dimension": out.dimension})
            if to_store:
                try:
                    # mset has no per-key TTL, so set the TTL on each key with a
                    # follow-up EXPIRE. A crash between mset and expire just
                    # leaves that key without a TTL (never expires) — a slow
                    # memory-growth risk, not a correctness bug, and self-heals
                    # on the next successful write cycle for the same text.
                    await self._valkey.mset(to_store)
                    for key in to_store:
                        await self._valkey.expire(key, self._ttl_seconds)
                except Exception as exc:  # pragma: no cover - defensive, Valkey outage
                    logger.warning("embedding_cache.write_failed", error=str(exc))

        logger.debug(
            "embedding_cache.batch",
            requested=len(inputs),
            hits=hits,
            misses=len(miss_indices),
        )

        # Truncate at the first gap (mirrors the wrapped adapters' existing
        # "len(outputs) < len(inputs) == partial failure" contract).
        result: list[EmbeddingOutput] = []
        for maybe_out in outputs:
            if maybe_out is None:
                break
            result.append(maybe_out)
        return result
