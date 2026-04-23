"""ChunkANNRepository — HNSW vector search on chunk_embeddings / section_embeddings.

Executes ANN queries against nlp_db using pgvector cosine distance operator
``<=>`` on pre-built HNSW indexes (idx_chunk_emb_hnsw / idx_section_emb_hnsw).

Chunk results include ``chunk_text_key`` — a MinIO object key populated by
Block 7 during document processing.  The search use case uses this key to
fetch full chunk text from MinIO (via ``ChunkTextStorePort``).

Section results have no ``chunk_text_key`` (sections are not stored as objects);
their ``text`` field falls back to ``sections.title`` (heading_path) or ``""``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ChunkANNRepository:
    """Run ANN searches and fetch entity mention annotations from nlp_db."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ann_search(
        self,
        embedding: list[float],
        granularity: str = "chunk",  # "chunk" | "section" | "both"
        top_k: int = 20,
        min_score: float = 0.0,
        date_from: Any | None = None,
        date_to: Any | None = None,
        source_types: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Run HNSW ANN query; return (results, total_searched).

        *embedding* must be a float list of length 1024.
        *total_searched* is the approximate count of indexed embeddings queried.
        """
        results: list[dict[str, Any]] = []
        total_searched = 0

        if granularity in ("chunk", "both"):
            chunk_rows, chunk_total = await self._search_chunks(
                embedding=embedding,
                top_k=top_k,
                min_score=min_score,
                date_from=date_from,
                date_to=date_to,
                source_types=source_types or [],
            )
            results.extend(chunk_rows)
            total_searched += chunk_total

        if granularity in ("section", "both"):
            section_rows, section_total = await self._search_sections(
                embedding=embedding,
                top_k=top_k,
                min_score=min_score,
                date_from=date_from,
                date_to=date_to,
                source_types=source_types or [],
            )
            results.extend(section_rows)
            total_searched += section_total

        # For "both": sort combined results by score descending, keep top_k
        if granularity == "both" and results:
            results.sort(key=lambda r: r["score"], reverse=True)
            results = results[:top_k]

        return results, total_searched

    async def _search_chunks(
        self,
        embedding: list[float],
        top_k: int,
        min_score: float,
        date_from: Any | None,
        date_to: Any | None,
        source_types: list[str],
    ) -> tuple[list[dict[str, Any]], int]:
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"

        # Build WHERE clauses for optional filters
        where_clauses = ["ce.embedding_status = 'ready'"]
        params: dict[str, Any] = {"vec": vec_str, "top_k": top_k, "min_score": min_score}

        if date_from is not None:
            where_clauses.append("dsm.published_at >= :date_from")
            params["date_from"] = date_from
        if date_to is not None:
            where_clauses.append("dsm.published_at <= :date_to")
            params["date_to"] = date_to
        if source_types:
            where_clauses.append("dsm.source_type = ANY(:source_types)")
            params["source_types"] = source_types

        where_sql = " AND ".join(where_clauses)

        meta_join = "LEFT JOIN document_source_metadata dsm ON dsm.doc_id = c.doc_id"

        query = text(
            f"""
            SELECT
                c.chunk_id,
                c.doc_id,
                c.section_id,
                c.heading_path,
                c.chunk_text_key,
                s.section_type,
                1 - (ce.embedding <=> cast(:vec AS vector)) AS score
            FROM chunk_embeddings ce
            JOIN chunks c ON c.chunk_id = ce.chunk_id
            JOIN sections s ON s.section_id = c.section_id
            {meta_join}
            WHERE {where_sql}
              AND 1 - (ce.embedding <=> cast(:vec AS vector)) >= :min_score
            ORDER BY ce.embedding <=> cast(:vec AS vector)
            LIMIT :top_k
            """,
        ).bindparams(**params)

        result = await self._session.execute(query)
        rows = result.all()

        chunk_results = [
            {
                "chunk_id": row.chunk_id,
                "doc_id": row.doc_id,
                "section_id": row.section_id,
                "granularity": "chunk",
                "text": row.heading_path or "",
                "score": float(row.score),
                "section_type": row.section_type,
                "heading_path": row.heading_path,
                "chunk_text_key": row.chunk_text_key,
            }
            for row in rows
        ]

        # Approximate total: count of ready chunk embeddings (cheap index scan)
        count_result = await self._session.execute(
            text("SELECT COUNT(*) FROM chunk_embeddings WHERE embedding_status = 'ready'"),
        )
        total = int(count_result.scalar_one())

        return chunk_results, total

    async def _search_sections(
        self,
        embedding: list[float],
        top_k: int,
        min_score: float,
        date_from: Any | None,
        date_to: Any | None,
        source_types: list[str],
    ) -> tuple[list[dict[str, Any]], int]:
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"

        where_clauses: list[str] = []
        params: dict[str, Any] = {"vec": vec_str, "top_k": top_k, "min_score": min_score}

        if date_from is not None:
            where_clauses.append("dsm.published_at >= :date_from")
            params["date_from"] = date_from
        if date_to is not None:
            where_clauses.append("dsm.published_at <= :date_to")
            params["date_to"] = date_to
        if source_types:
            where_clauses.append("dsm.source_type = ANY(:source_types)")
            params["source_types"] = source_types

        where_filter = ("AND " + " AND ".join(where_clauses)) if where_clauses else ""

        query = text(
            f"""
            SELECT
                se.section_id      AS chunk_id,
                s.doc_id,
                se.section_id,
                s.title            AS heading_path,
                s.section_type,
                1 - (se.embedding <=> cast(:vec AS vector)) AS score
            FROM section_embeddings se
            JOIN sections s ON s.section_id = se.section_id
            LEFT JOIN document_source_metadata dsm ON dsm.doc_id = s.doc_id
            WHERE 1 - (se.embedding <=> cast(:vec AS vector)) >= :min_score
              {where_filter}
            ORDER BY se.embedding <=> cast(:vec AS vector)
            LIMIT :top_k
            """,
        ).bindparams(**params)

        result = await self._session.execute(query)
        rows = result.all()

        section_results = [
            {
                "chunk_id": row.chunk_id,
                "doc_id": row.doc_id,
                "section_id": row.section_id,
                "granularity": "section",
                "text": row.heading_path or "",
                "score": float(row.score),
                "section_type": row.section_type,
                "heading_path": row.heading_path,
            }
            for row in rows
        ]

        count_result = await self._session.execute(
            text("SELECT COUNT(*) FROM section_embeddings"),
        )
        total = int(count_result.scalar_one())

        return section_results, total

    async def fetch_entity_mentions(
        self,
        chunk_ids: list[UUID],
        min_confidence: float = 0.45,
    ) -> list[dict[str, Any]]:
        """Fetch resolved entity mentions for the given chunk_ids.

        Returns rows with: chunk_id, resolved_entity_id, resolution_confidence.
        Only mentions with ``resolved_entity_id IS NOT NULL`` and
        ``resolution_confidence >= min_confidence`` are returned.
        """
        if not chunk_ids:
            return []

        result = await self._session.execute(
            text(
                """
                SELECT
                    cem.chunk_id,
                    em.resolved_entity_id,
                    em.resolution_confidence
                FROM chunk_entity_mentions cem
                JOIN entity_mentions em ON em.mention_id = cem.mention_id
                WHERE cem.chunk_id = ANY(:chunk_ids)
                  AND em.resolved_entity_id IS NOT NULL
                  AND em.resolution_confidence >= :min_conf
                """,
            ).bindparams(
                chunk_ids=[str(cid) for cid in chunk_ids],
                min_conf=min_confidence,
            ),
        )
        rows = result.all()
        return [
            {
                "chunk_id": row.chunk_id,
                "resolved_entity_id": row.resolved_entity_id,
                "resolution_confidence": float(row.resolution_confidence),
            }
            for row in rows
        ]
