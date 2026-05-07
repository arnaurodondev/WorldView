"""Enhanced chunk search use case (PLAN-0015-B Wave B-3).

Combines HNSW ANN vector search on chunk/section embeddings with:
  - Full chunk text fetched from MinIO via ``ChunkTextStorePort``
    (Valkey-cached; key: ``nlp:v1:chunk_text:{chunk_id}``, TTL 1h)
  - Inline entity annotations from chunk_entity_mentions → entity_mentions
  - Citation metadata from document_source_metadata
  - Embedding caching via Valkey (key: s6:v1:emb:{sha256(text)}, TTL 1h)

Chunk results include full text when ``chunk_text_key`` is populated in the
DB (set by Block 7 during document processing via ``MinIOChunkTextStore``).
Section results return ``title`` (heading_path) or ``""`` — sections are not
stored as MinIO objects.
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

from nlp_pipeline.application.blocks.rare_token import analyze as _analyze_rare_tokens
from nlp_pipeline.application.use_cases._rrf import DEFAULT_K as _RRF_K
from nlp_pipeline.application.use_cases._rrf import reciprocal_rank_fuse
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.protocols import EmbeddingClient  # type: ignore[import-not-found]

    from nlp_pipeline.application.ports.canonical_entity import CanonicalEntityPort
    from nlp_pipeline.application.ports.chunk_search import ChunkSearchPort
    from nlp_pipeline.application.ports.repositories import (
        ChunkTextStorePort,
        DocumentSourceMetadataRepository,
    )

_log = get_logger(__name__)  # type: ignore[no-any-return]

_EMBED_CACHE_TTL = 3600  # 1 hour
_ENTITY_MIN_CONFIDENCE = 0.45

# PLAN-0063 W5-3 §0-bis.7 — when the query is too short the lexical leg has
# almost no signal (one-token FTS queries return everything that contains
# the token, which is noise). Below this threshold we silently fall back to
# pure ANN.
_HYBRID_MIN_TOKENS = 3

# ── Domain types ──────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class SourceMetadata:
    """Citation metadata for a retrieved chunk."""

    title: str | None = None
    url: str | None = None
    published_at: Any | None = None  # datetime | None — avoid runtime import
    source_name: str | None = None
    source_type: str | None = None


@dataclasses.dataclass(frozen=True)
class ChunkEntityAnnotation:
    """An entity mention resolved within a retrieved chunk."""

    entity_id: UUID
    canonical_name: str
    entity_type: str
    confidence: float


@dataclasses.dataclass(frozen=True)
class EnrichedChunkResult:
    """A single ANN search result enriched with entity annotations and source metadata."""

    chunk_id: UUID
    doc_id: UUID
    section_id: UUID | None
    granularity: str  # "chunk" | "section"
    text: str  # full chunk text from MinIO; falls back to heading_path or ""
    score: float
    source_metadata: SourceMetadata
    entities: list[ChunkEntityAnnotation]
    section_type: str | None = None
    heading_path: str | None = None


# ── Use case ──────────────────────────────────────────────────────────────────


def _embed_cache_key(text: str) -> str:
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"s6:v1:emb:{digest}"


def _chunk_text_cache_key(chunk_id: UUID) -> str:
    return f"nlp:v1:chunk_text:{chunk_id}"


class EnhancedChunkSearchUseCase:
    """Search chunks/sections via HNSW ANN with entity + citation enrichment.

    Designed for S8 RAG pipeline retrieval — a single call returns everything
    needed for context assembly without extra round trips.

    Dependency injection pattern follows :class:`QueryEntityResolverUseCase`:
    the embedding_client is optional — when absent, ``query_embedding`` MUST be
    provided in :meth:`execute` (pre-computed by the caller).

    When ``chunk_text_store`` is provided, full chunk text is fetched from MinIO
    for each result (Valkey-cached at ``nlp:v1:chunk_text:{chunk_id}``).
    """

    def __init__(
        self,
        chunk_ann_repo: ChunkSearchPort,
        source_metadata_repo: DocumentSourceMetadataRepository,
        canonical_entity_repo: CanonicalEntityPort,
        valkey: Any | None = None,  # redis.asyncio.Redis
        embedding_client: EmbeddingClient | None = None,
        chunk_text_store: ChunkTextStorePort | None = None,
        lexical_boost: float = 1.5,
    ) -> None:
        self._ann = chunk_ann_repo
        self._meta = source_metadata_repo
        self._canon = canonical_entity_repo
        self._valkey = valkey
        self._emb = embedding_client
        self._chunk_text_store = chunk_text_store
        # PLAN-0063 W5-3 L9: tunable adaptive lexical boost factor. Default
        # 1.5 from §0-bis.7; the eval harness's --mode hybrid_boost_sweep
        # picks the optimum value per dataset.
        self._lexical_boost = lexical_boost

    async def execute(
        self,
        *,
        query_text: str | None,
        query_embedding: list[float] | None,
        granularity: str = "chunk",
        top_k: int = 20,
        min_score: float = 0.0,
        include_entities: bool = True,
        date_from: date | None = None,
        date_to: date | None = None,
        source_types: list[str] | None = None,
        search_type: str = "ann",
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
    ) -> tuple[list[EnrichedChunkResult], int, str]:
        """Execute enriched chunk search.

        Returns ``(results, total_searched, embedding_model)``.

        ``search_type`` selects the retrieval strategy (PLAN-0063 W5-3):

        * ``"ann"`` (default): vector ANN over HNSW indexes — needs exactly
          one of ``query_text`` / ``query_embedding``. Backwards-compatible
          path; the wave is a strict superset.
        * ``"lexical"``: Postgres FTS via tsv_english + tsv_simple GREATEST.
          Needs ``query_text``. Used by the eval harness and the boost-sweep
          mode for diagnostic purposes.
        * ``"hybrid"``: runs both legs in parallel and fuses with RRF (L9
          adaptive boost when the query has rare tokens). Needs
          ``query_text``; ``query_embedding`` is optional but recommended
          (skips the embed round-trip).

        Embedding model is reported as ``"hybrid+lexical"`` /
        ``"lexical-only"`` for the non-ANN paths so the response header is
        truthful — the lexical leg never runs an embedder.
        """
        if search_type == "ann":
            return await self._execute_ann(
                query_text=query_text,
                query_embedding=query_embedding,
                granularity=granularity,
                top_k=top_k,
                min_score=min_score,
                include_entities=include_entities,
                date_from=date_from,
                date_to=date_to,
                source_types=source_types,
                entity_ids=entity_ids,
                entity_types=entity_types,
            )
        if search_type == "lexical":
            return await self._execute_lexical(
                query_text=query_text or "",
                top_k=top_k,
                min_score=min_score,
                include_entities=include_entities,
                date_from=date_from,
                date_to=date_to,
                source_types=source_types,
                entity_ids=entity_ids,
                entity_types=entity_types,
            )
        if search_type == "hybrid":
            return await self._execute_hybrid(
                query_text=query_text or "",
                query_embedding=query_embedding,
                granularity=granularity,
                top_k=top_k,
                min_score=min_score,
                include_entities=include_entities,
                date_from=date_from,
                date_to=date_to,
                source_types=source_types,
                entity_ids=entity_ids,
                entity_types=entity_types,
            )
        raise ValueError(f"unknown search_type: {search_type!r}")

    # ── Strategy implementations ─────────────────────────────────────────────

    async def _execute_ann(
        self,
        *,
        query_text: str | None,
        query_embedding: list[float] | None,
        granularity: str,
        top_k: int,
        min_score: float,
        include_entities: bool,
        date_from: date | None,
        date_to: date | None,
        source_types: list[str] | None,
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
    ) -> tuple[list[EnrichedChunkResult], int, str]:
        """Vector ANN path — original B-3 behaviour."""
        vec, embedding_model = await self._resolve_embedding(query_text, query_embedding)

        raw_results, total_searched = await self._ann.ann_search(
            embedding=vec,
            granularity=granularity,
            top_k=top_k,
            min_score=min_score,
            date_from=date_from,
            date_to=date_to,
            source_types=source_types or [],
            entity_ids=entity_ids,
            entity_types=entity_types,
        )

        if not raw_results:
            return [], total_searched, embedding_model

        results = await self._enrich_raw_results(raw_results, include_entities=include_entities)
        return results, total_searched, embedding_model

    async def _execute_lexical(
        self,
        *,
        query_text: str,
        top_k: int,
        min_score: float,
        include_entities: bool,
        date_from: date | None,
        date_to: date | None,
        source_types: list[str] | None,
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
    ) -> tuple[list[EnrichedChunkResult], int, str]:
        """Postgres FTS path — used by the eval harness and lexical-only debug.

        Calls into ``ChunkANNRepository.lexical_search`` (W5-2). The
        BP-180 CAST guards live inside the repo — nothing to do here.
        """
        raw_rows, total = await self._ann.lexical_search(
            query_text=query_text,
            mode="both",
            top_k=top_k,
            min_score=min_score,
            date_from=date_from,
            date_to=date_to,
            source_types=source_types or None,
            entity_ids=entity_ids,
            entity_types=entity_types,
        )
        if not raw_rows:
            return [], total, "lexical-only"

        # The lexical_search rows come back without ``granularity`` set
        # (chunk-only in W5); inject it so _enrich_raw_results doesn't KeyError.
        for r in raw_rows:
            r.setdefault("granularity", "chunk")

        results = await self._enrich_raw_results(raw_rows, include_entities=include_entities)
        return results, total, "lexical-only"

    async def _execute_hybrid(
        self,
        *,
        query_text: str,
        query_embedding: list[float] | None,
        granularity: str,
        top_k: int,
        min_score: float,
        include_entities: bool,
        date_from: date | None,
        date_to: date | None,
        source_types: list[str] | None,
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
    ) -> tuple[list[EnrichedChunkResult], int, str]:
        """Hybrid ANN + lexical path with RRF + adaptive boost (L9)."""
        # Short-query fallback: 1-2 token FTS queries are too noisy.
        if len(query_text.split()) < _HYBRID_MIN_TOKENS:
            _log.info(  # type: ignore[no-any-return]
                "hybrid_short_query_fallback_to_ann",
                token_count=len(query_text.split()),
            )
            return await self._execute_ann(
                query_text=query_text,
                query_embedding=query_embedding,
                granularity=granularity,
                top_k=top_k,
                min_score=min_score,
                include_entities=include_entities,
                date_from=date_from,
                date_to=date_to,
                source_types=source_types,
                entity_ids=entity_ids,
                entity_types=entity_types,
            )

        # BP-NEW-ASYNCSESSION (this commit): the two legs are run SEQUENTIALLY,
        # not concurrently, because both ultimately use the same AsyncSession
        # held by ``self._repo``. SQLAlchemy AsyncSession is documented as
        # NOT safe for concurrent use from multiple coroutines (each connection
        # `_connection_for_bind` operation must complete before the next is
        # started). Running them under ``asyncio.gather`` raised
        # ``IllegalStateChangeError`` ("Method 'close()' can't be called here;
        # method '_connection_for_bind()' is already in progress") on every
        # request. Fix is sequential: ANN first (typically ~80-150ms), lex
        # second (~50ms). Total latency ~max+min instead of max — acceptable
        # tradeoff for correctness. A future wave that injects a session
        # factory (one session per leg) can restore true parallelism.
        (ann_results, ann_total, ann_model) = await self._execute_ann(
            query_text=query_text,
            query_embedding=query_embedding,
            granularity=granularity,
            top_k=top_k,
            min_score=min_score,
            include_entities=include_entities,
            date_from=date_from,
            date_to=date_to,
            source_types=source_types,
            entity_ids=entity_ids,
            entity_types=entity_types,
        )
        (lex_results, lex_total, _lex_model) = await self._execute_lexical(
            query_text=query_text,
            top_k=top_k,
            min_score=min_score,
            include_entities=include_entities,
            date_from=date_from,
            date_to=date_to,
            source_types=source_types,
            entity_ids=entity_ids,
            entity_types=entity_types,
        )

        # Adaptive boost: when the query has identifier-style rare tokens,
        # weight the lexical ranking up. The boost is tunable (L9).
        analysis = _analyze_rare_tokens(query_text)
        lex_weight = self._lexical_boost if analysis.has_rare_token else 1.0
        weights = (1.0, lex_weight)

        fused = reciprocal_rank_fuse(
            [ann_results, lex_results],
            k=_RRF_K,
            key=lambda r: r.chunk_id,
            weights=weights,
        )

        # Truncate to top_k and drop the score (callers re-rank downstream).
        # `total_searched` reports the union — this is approximate but
        # matches what the response field is intended to convey.
        results = [item for item, _score in fused[:top_k]]
        union_total = ann_total + lex_total
        return results, union_total, "hybrid+lexical:" + ann_model

    # ── Result assembly (shared by all paths) ────────────────────────────────

    async def _enrich_raw_results(
        self,
        raw_results: list[dict[str, Any]],
        *,
        include_entities: bool,
    ) -> list[EnrichedChunkResult]:
        """Hydrate raw repo rows with metadata, entities and chunk text.

        Factored out of ``_execute_ann`` so the lexical and hybrid paths
        share the same enrichment logic and produce identical
        EnrichedChunkResult shapes — that's what makes RRF dedup safe.
        """
        # ── Citation metadata ────────────────────────────────────────────────
        doc_ids = list({r["doc_id"] for r in raw_results})
        meta_map = await self._meta.batch_get(doc_ids)

        # ── Entity annotations ───────────────────────────────────────────────
        entity_map: dict[str, list[ChunkEntityAnnotation]] = {}
        if include_entities:
            chunk_ids = [r["chunk_id"] for r in raw_results]
            raw_mentions = await self._ann.fetch_entity_mentions(chunk_ids, _ENTITY_MIN_CONFIDENCE)

            entity_ids = list({m["resolved_entity_id"] for m in raw_mentions if m.get("resolved_entity_id")})
            canon_map = await self._canon.batch_get(entity_ids) if entity_ids else {}

            for m in raw_mentions:
                eid = m.get("resolved_entity_id")
                if not eid:
                    continue
                canon = canon_map.get(eid)
                if not canon:
                    continue
                cid_str = str(m["chunk_id"])
                entity_map.setdefault(cid_str, []).append(
                    ChunkEntityAnnotation(
                        entity_id=eid,
                        canonical_name=str(canon["canonical_name"]),
                        entity_type=str(canon["entity_type"]),
                        confidence=float(m["resolution_confidence"]),
                    )
                )

        # ── Chunk text fetch from MinIO (with Valkey cache) ──────────────────
        text_map = await self._fetch_chunk_texts(raw_results)

        # ── Assemble results ─────────────────────────────────────────────────
        results: list[EnrichedChunkResult] = []
        for r in raw_results:
            doc_meta = meta_map.get(r["doc_id"])
            src = (
                SourceMetadata(
                    title=doc_meta.title,
                    url=doc_meta.url,
                    published_at=doc_meta.published_at,
                    source_name=doc_meta.source_name,
                    source_type=doc_meta.source_type,
                )
                if doc_meta
                else SourceMetadata()
            )
            text = text_map.get(r["chunk_id"]) or r.get("text") or ""
            results.append(
                EnrichedChunkResult(
                    chunk_id=r["chunk_id"],
                    doc_id=r["doc_id"],
                    section_id=r.get("section_id"),
                    granularity=r.get("granularity", "chunk"),
                    text=text,
                    score=float(r["score"]),
                    source_metadata=src,
                    entities=entity_map.get(str(r["chunk_id"]), []),
                    section_type=r.get("section_type"),
                    heading_path=r.get("heading_path"),
                )
            )
        return results

    async def _fetch_chunk_texts(self, raw_results: list[dict[str, Any]]) -> dict[UUID, str]:
        """Fetch chunk text for results that have a ``chunk_text_key``.

        Checks Valkey cache first; falls back to ``_chunk_text_store.get_batch()``.
        Section results (no ``chunk_text_key``) are silently skipped.

        Returns a mapping of chunk_id → text for successfully fetched chunks.
        """
        if self._chunk_text_store is None:
            return {}

        key_map: dict[UUID, str] = {}
        for r in raw_results:
            text_key = r.get("chunk_text_key")
            if text_key and r.get("granularity") == "chunk":
                key_map[r["chunk_id"]] = text_key

        if not key_map:
            return {}

        text_map: dict[UUID, str] = {}
        uncached: dict[UUID, str] = {}

        for chunk_id, obj_key in key_map.items():
            cache_key = _chunk_text_cache_key(chunk_id)
            if self._valkey is not None:
                try:
                    cached = await self._valkey.get(cache_key)
                    if cached:
                        text_map[chunk_id] = cached.decode() if isinstance(cached, bytes) else str(cached)
                        continue
                except Exception:
                    _log.warning("chunk_text_cache_read_failed", chunk_id=str(chunk_id), exc_info=True)  # type: ignore[no-any-return]
            uncached[chunk_id] = obj_key

        if uncached:
            try:
                fetched = await self._chunk_text_store.get_batch(uncached)
                text_map.update(fetched)

                if self._valkey is not None:
                    for chunk_id, text in fetched.items():
                        try:
                            await self._valkey.set(
                                _chunk_text_cache_key(chunk_id),
                                text,
                                ex=_EMBED_CACHE_TTL,
                            )
                        except Exception:
                            _log.warning("chunk_text_cache_write_failed", chunk_id=str(chunk_id), exc_info=True)  # type: ignore[no-any-return]
            except Exception:
                _log.warning("chunk_text_fetch_batch_failed", exc_info=True)  # type: ignore[no-any-return]

        return text_map

    async def _resolve_embedding(
        self,
        query_text: str | None,
        query_embedding: list[float] | None,
    ) -> tuple[list[float], str]:
        """Return (embedding_vector, model_name).

        If *query_embedding* is provided, skip embedding step (cache not written).
        If *query_text* is provided, check Valkey cache first, then call
        EmbeddingClient.
        """
        model_name = "nomic-embed-text"

        if query_embedding is not None:
            return query_embedding, model_name

        assert query_text is not None, "exactly one of query_text/query_embedding must be set"

        cache_key = _embed_cache_key(query_text)
        if self._valkey is not None:
            try:
                import json

                cached = await self._valkey.get(cache_key)
                if cached:
                    return json.loads(cached), model_name
            except Exception:
                _log.warning("chunk_search_embed_cache_read_failed", key=cache_key, exc_info=True)  # type: ignore[no-any-return]

        if self._emb is None:
            raise RuntimeError("EmbeddingClient is required when query_text is provided without query_embedding")

        vec: list[float] = await self._emb.embed(query_text)  # type: ignore[attr-defined, assignment, arg-type]

        if self._valkey is not None:
            try:
                import json

                await self._valkey.set(cache_key, json.dumps(vec), ex=_EMBED_CACHE_TTL)
            except Exception:
                _log.warning("chunk_search_embed_cache_write_failed", key=cache_key, exc_info=True)  # type: ignore[no-any-return]

        return vec, model_name
