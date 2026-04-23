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

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.protocols import EmbeddingClient  # type: ignore[import-not-found]

    from nlp_pipeline.application.ports.repositories import (
        ChunkTextStorePort,
        DocumentSourceMetadataRepository,
    )
    from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import CanonicalEntityRepository
    from nlp_pipeline.infrastructure.nlp_db.repositories.chunk_search import ChunkANNRepository

_log = get_logger(__name__)  # type: ignore[no-any-return]

_EMBED_CACHE_TTL = 3600  # 1 hour
_ENTITY_MIN_CONFIDENCE = 0.45

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
        chunk_ann_repo: ChunkANNRepository,
        source_metadata_repo: DocumentSourceMetadataRepository,
        canonical_entity_repo: CanonicalEntityRepository,
        valkey: Any | None = None,  # redis.asyncio.Redis
        embedding_client: EmbeddingClient | None = None,
        chunk_text_store: ChunkTextStorePort | None = None,
    ) -> None:
        self._ann = chunk_ann_repo
        self._meta = source_metadata_repo
        self._canon = canonical_entity_repo
        self._valkey = valkey
        self._emb = embedding_client
        self._chunk_text_store = chunk_text_store

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
    ) -> tuple[list[EnrichedChunkResult], int, str]:
        """Execute enriched chunk search.

        Returns ``(results, total_searched, embedding_model)``.

        Exactly one of *query_text* or *query_embedding* must be provided.
        """
        vec, embedding_model = await self._resolve_embedding(query_text, query_embedding)

        raw_results, total_searched = await self._ann.ann_search(
            embedding=vec,
            granularity=granularity,
            top_k=top_k,
            min_score=min_score,
            date_from=date_from,
            date_to=date_to,
            source_types=source_types or [],
        )

        if not raw_results:
            return [], total_searched, embedding_model

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
            # text_map wins; fall back to heading_path (sections) or ""
            text = text_map.get(r["chunk_id"]) or r.get("text") or ""
            results.append(
                EnrichedChunkResult(
                    chunk_id=r["chunk_id"],
                    doc_id=r["doc_id"],
                    section_id=r.get("section_id"),
                    granularity=r["granularity"],
                    text=text,
                    score=float(r["score"]),
                    source_metadata=src,
                    entities=entity_map.get(str(r["chunk_id"]), []),
                    section_type=r.get("section_type"),
                    heading_path=r.get("heading_path"),
                )
            )

        return results, total_searched, embedding_model

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
