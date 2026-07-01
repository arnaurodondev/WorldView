"""ChunkANNRepository — HNSW vector search on chunk_embeddings / section_embeddings.

Executes ANN queries against nlp_db using pgvector cosine distance operator
``<=>`` on pre-built HNSW indexes (idx_chunk_emb_hnsw / idx_section_emb_hnsw).

Chunk results include ``chunk_text_key`` — a MinIO object key populated by
Block 7 during document processing.  The search use case uses this key to
fetch full chunk text from MinIO (via ``ChunkTextStorePort``).

Section results have no ``chunk_text_key`` (sections are not stored as objects);
their ``text`` field falls back to ``sections.title`` (heading_path) or ``""``.

PLAN-0078 Wave C: implements ``ChunkSearchPort`` ABC.  The new ``entity_ids``
and ``entity_types`` parameters filter via the GIN-indexed
``chunks.entity_mentions`` JSONB column using @> containment queries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from nlp_pipeline.application.ports.chunk_search import ChunkSearchPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ── Public-tenant sentinel (BUG-3 / feat/fix-s6-search-quality) ───────────────
# The article consumer stamps public (non-tenant) content with the nil-UUID
# ``PUBLIC_TENANT_ID`` sentinel — NOT SQL NULL — whenever tenant resolution
# fails (BP-575).  On the live corpus ~86% of ready chunk embeddings are on
# sentinel-tenant chunks, so a bare ``tenant_id IS NULL`` public predicate made
# the vast majority of public content invisible to ANN/lexical search (the
# ``news_query.py`` repo already handles this three-way; chunk_search did not).
# We mirror the R35 three-row-class semantics: legacy NULL rows, the sentinel
# public tenant, and (when authenticated) the caller's own tenant.
_PUBLIC_TENANT_SENTINEL = "00000000-0000-0000-0000-000000000000"


def _tenant_predicate(params: dict[str, Any], column: str, tenant_id: str | None) -> str:
    """Return a parameterised tenant-visibility predicate for *column*.

    Public rows are BOTH ``NULL`` and the ``PUBLIC_TENANT_ID`` sentinel (BP-575).
    When *tenant_id* is provided the caller's own rows are additionally visible.
    """
    legs = [f"{column} IS NULL", f"{column} = '{_PUBLIC_TENANT_SENTINEL}'::uuid"]
    if tenant_id is not None:
        params["tenant_id_str"] = tenant_id
        legs.append(f"{column} = CAST(:tenant_id_str AS UUID)")
    return "(" + " OR ".join(legs) + ")"


def _build_entity_mention_filter(
    params: dict[str, Any],
    entity_ids: list[UUID] | None,
    entity_types: list[str] | None,
) -> str:
    """Build a parameterized SQL fragment for filtering chunks.entity_mentions.

    PLAN-0078 §3 filter semantics:
      - OR within entity_ids: chunk must mention ANY of the listed entity IDs.
      - OR within entity_types: any mention must match ANY of the listed types.
      - AND across fields: when both entity_ids and entity_types are provided,
        the SAME mention element must satisfy both conditions.

    Uses an EXISTS subquery over ``jsonb_array_elements`` so the GIN index is
    consulted for the outer chunk scan, and the row-level predicate is pushed
    into the subquery.  This avoids f-string SQL injection by keeping all
    values in the parameterised ``params`` dict.

    The ``entity_id_strs`` and ``entity_type_strs`` lists are passed as TEXT[]
    CAST (BP-180) to avoid asyncpg AmbiguousParameterError.
    """
    if not entity_ids and not entity_types:
        raise ValueError("_build_entity_mention_filter requires at least one non-empty filter list")

    clauses: list[str] = []
    if entity_ids:
        params["entity_id_strs"] = [str(eid) for eid in entity_ids]
        clauses.append("em.value->>'entity_id' = ANY(CAST(:entity_id_strs AS TEXT[]))")
    if entity_types:
        params["entity_type_strs"] = entity_types
        clauses.append("em.value->>'entity_type' = ANY(CAST(:entity_type_strs AS TEXT[]))")

    predicate = " AND ".join(clauses)
    return f"EXISTS (" f"SELECT 1 FROM jsonb_array_elements(c.entity_mentions) AS em(value) " f"WHERE {predicate}" f")"


class ChunkANNRepository(ChunkSearchPort):
    """Run ANN searches and fetch entity mention annotations from nlp_db."""

    def __init__(self, session: AsyncSession, ef_search: int = 200) -> None:
        self._session = session
        # BUG-3: pgvector post-filters the HNSW candidate set, so the default
        # ef_search=40 starves any selective WHERE filter. Raise it per ANN query.
        self._ef_search = ef_search

    async def _apply_ef_search(self) -> None:
        """Raise ``hnsw.ef_search`` for the current transaction (BUG-3).

        ``set_config(name, value, is_local=true)`` scopes the GUC to the current
        transaction, so it auto-reverts on commit/rollback and never leaks onto
        the pooled connection.  The read session runs statements inside an
        implicit transaction (SQLAlchemy autobegin), so this applies to the ANN
        query that follows on the same connection.  No-op when ef_search <= 0.
        """
        if self._ef_search and self._ef_search > 0:
            await self._session.execute(
                text("SELECT set_config('hnsw.ef_search', :ef, true)"),
                {"ef": str(self._ef_search)},
            )

    async def ann_search(
        self,
        embedding: list[float],
        granularity: str = "chunk",  # "chunk" | "section" | "both"
        top_k: int = 20,
        min_score: float = 0.0,
        date_from: Any | None = None,
        date_to: Any | None = None,
        source_types: list[str] | None = None,
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Run HNSW ANN query; return (results, total_searched).

        *embedding* must be a float list of length 1024.
        *total_searched* is the approximate count of indexed embeddings queried.
        PLAN-0086 Wave C-1: when tenant_id is None only public chunks (IS NULL)
        are returned. When non-None, public + tenant-owned chunks are returned.
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
                entity_ids=entity_ids,
                entity_types=entity_types,
                tenant_id=tenant_id,
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
                tenant_id=tenant_id,
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
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
        tenant_id: str | None = None,
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

        # PLAN-0078 Wave C: entity filter via GIN-indexed JSONB @> containment.
        # Filter semantics: OR within field, AND across fields (§3).
        # Uses parameterized CAST to avoid asyncpg type-ambiguity (BP-180).
        if entity_ids or entity_types:
            where_clauses.append(_build_entity_mention_filter(params, entity_ids, entity_types))

        # PLAN-0086 Wave C-1 + BUG-3: tenant_id filter — CRITICAL security boundary.
        # Public rows = NULL tenant OR the PUBLIC_TENANT_ID sentinel (BP-575);
        # authenticated callers additionally see their own tenant. See
        # _tenant_predicate for the R35 three-row-class rationale.
        where_clauses.append(_tenant_predicate(params, "c.tenant_id", tenant_id))

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
                c.document_title,
                s.section_type,
                dsm.source_type,
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

        # BUG-3: widen the HNSW candidate pool BEFORE the ANN query so the
        # post-filter (source_type / tenant / entity / date) has rows to keep.
        await self._apply_ef_search()
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
                # PLAN-0086 Wave C-1: expose document_title for RAG citation assembly.
                "document_title": row.document_title,
                # BUG-3 secondary smell: the chunk path never selected source_type,
                # so every ANN chunk row reported source_type=null. Surface it now.
                "source_type": row.source_type,
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
        tenant_id: str | None = None,
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

        # HR-053 / CRIT-1 + BUG-3: tenant_id filter — CRITICAL security boundary.
        # Public rows = NULL tenant OR the PUBLIC_TENANT_ID sentinel (BP-575);
        # authenticated callers additionally see their own tenant.
        where_clauses.append(_tenant_predicate(params, "s.tenant_id", tenant_id))

        where_filter = ("AND " + " AND ".join(where_clauses)) if where_clauses else ""

        query = text(
            f"""
            SELECT
                se.section_id      AS chunk_id,
                s.doc_id,
                se.section_id,
                s.title            AS heading_path,
                s.section_type,
                dsm.title          AS document_title,
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

        # BUG-3: widen the HNSW candidate pool before the section ANN query.
        await self._apply_ef_search()
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
                "document_title": row.document_title,
            }
            for row in rows
        ]

        # Count query also scoped to the same tenant context so the total
        # does not leak the count of other tenants' private sections (MED-3).
        # BUG-3: mirror the sentinel-aware predicate used by the SELECT above.
        count_params: dict[str, Any] = {}
        count_pred = _tenant_predicate(count_params, "s.tenant_id", tenant_id)
        count_sql = text(
            "SELECT COUNT(*) FROM section_embeddings se "
            "JOIN sections s ON s.section_id = se.section_id "
            f"WHERE {count_pred}"
        ).bindparams(**count_params)
        count_result = await self._session.execute(count_sql)
        total = int(count_result.scalar_one())

        return section_results, total

    async def lexical_search(
        self,
        query_text: str,
        *,
        mode: str = "both",
        granularity: str = "chunk",
        top_k: int = 20,
        min_score: float = 0.0,
        date_from: Any | None = None,
        date_to: Any | None = None,
        source_types: list[str] | None = None,
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Run a Postgres full-text search over the chunks table (PLAN-0063 W5-2).

        Args:
            query_text: User-provided search string. Passed through
                ``websearch_to_tsquery`` so familiar operators (``"phrase"``,
                ``-exclude``, ``OR``) work natively.
            mode: ``"english"`` (stemmed), ``"simple"`` (no stemming, preserves
                identifier tokens like ``AAPL`` or ``PLAN-0063``), or
                ``"both"`` (default — server-side ``GREATEST`` of the two ranks).
            granularity: only ``"chunk"`` is supported in W5; section-level
                lexical retrieval is deferred to a future wave.
            top_k: Result row cap.
            min_score: Filter out rows whose ``ts_rank_cd`` is strictly less
                than this value.
            date_from / date_to: Optional published_at bounds (UTC).
            source_types: Optional whitelist of ``document_source_metadata``
                source types (e.g. ``["sec_filing", "eodhd_news"]``).

        Returns:
            ``(rows, total_searched)`` — ``rows`` is a list of result dicts
            with the same shape as the ANN path (chunk_id, doc_id, section_id,
            heading_path, granularity, text, score, section_type,
            chunk_text_key); ``total_searched`` is the number of chunks that
            matched the WHERE clause BEFORE the LIMIT — separate COUNT(*)
            query, mirroring ``_search_chunks``.

        BP-180 — every nullable parameter goes through ``CAST(:param AS TYPE)``
        in the SQL because asyncpg raises ``AmbiguousParameterError`` otherwise
        when a parameter only appears inside ``IS NULL``-style guards. The CAST
        gives the planner a concrete type to bind to. Do NOT simplify these
        guards back to ``:param IS NULL``.
        """
        if granularity != "chunk":
            raise ValueError(
                "lexical_search supports granularity='chunk' only in W5; section-level lexical is deferred"
            )
        if mode not in {"english", "simple", "both"}:
            raise ValueError(f"lexical_search mode must be one of english/simple/both; got {mode!r}")

        # Build the WHERE / score expression based on mode.
        if mode == "english":
            match_sql = "c.tsv_english @@ websearch_to_tsquery('english', :q)"
            score_sql = "ts_rank_cd(c.tsv_english, websearch_to_tsquery('english', :q))"
        elif mode == "simple":
            match_sql = "c.tsv_simple @@ websearch_to_tsquery('simple', :q)"
            score_sql = "ts_rank_cd(c.tsv_simple, websearch_to_tsquery('simple', :q))"
        else:  # both
            match_sql = (
                "(c.tsv_english @@ websearch_to_tsquery('english', :q) "
                "OR c.tsv_simple @@ websearch_to_tsquery('simple', :q))"
            )
            score_sql = (
                "GREATEST("
                "ts_rank_cd(c.tsv_english, websearch_to_tsquery('english', :q)), "
                "ts_rank_cd(c.tsv_simple, websearch_to_tsquery('simple', :q))"
                ")"
            )

        params: dict[str, Any] = {
            "q": query_text,
            "min_score": min_score,
            "top_k": top_k,
            "date_from": date_from,
            "date_to": date_to,
            "source_types": source_types if source_types else None,
        }

        # Common date / source-type filter clauses (BP-180 CAST guards).
        date_filter = (
            "(CAST(:date_from AS TIMESTAMPTZ) IS NULL OR dsm.published_at >= CAST(:date_from AS TIMESTAMPTZ)) "
            "AND (CAST(:date_to AS TIMESTAMPTZ) IS NULL OR dsm.published_at <= CAST(:date_to AS TIMESTAMPTZ))"
        )
        source_filter = (
            "(CAST(:source_types AS TEXT[]) IS NULL OR dsm.source_type = ANY(CAST(:source_types AS TEXT[])))"
        )

        # PLAN-0078 Wave C: optional entity filter via GIN-indexed JSONB column.
        entity_filter_sql = ""
        if entity_ids or entity_types:
            entity_filter_sql = "AND " + _build_entity_mention_filter(params, entity_ids, entity_types)

        # PLAN-0086 Wave C-1 + BUG-3: tenant_id filter — CRITICAL security boundary.
        # Public rows = NULL tenant OR the PUBLIC_TENANT_ID sentinel (BP-575);
        # authenticated callers additionally see their own tenant. Without the
        # sentinel leg the lexical path (like the ANN path) hid ~86% of public
        # chunks — the same defect that made source_types=['sec_edgar'] return 0.
        tenant_filter_sql = "AND " + _tenant_predicate(params, "c.tenant_id", tenant_id)

        # Use a CTE so we can reuse the result set for COUNT and SELECT without
        # re-running the (relatively cheap, but not free) GIN match twice
        # against arbitrarily large filter sets.
        sql = f"""
            WITH matched AS (
                SELECT
                    c.chunk_id,
                    c.doc_id,
                    c.section_id,
                    c.heading_path,
                    c.chunk_text_key,
                    c.chunk_text,
                    c.document_title,
                    s.section_type,
                    {score_sql} AS score
                FROM chunks c
                JOIN sections s ON s.section_id = c.section_id
                LEFT JOIN document_source_metadata dsm ON dsm.doc_id = c.doc_id
                WHERE {match_sql}
                  AND {date_filter}
                  AND {source_filter}
                  {entity_filter_sql}
                  {tenant_filter_sql}
            )
            SELECT chunk_id, doc_id, section_id, heading_path, chunk_text_key,
                   chunk_text, document_title, section_type, score
            FROM matched
            WHERE score >= :min_score
            ORDER BY score DESC
            LIMIT :top_k
            """

        # Use the second-arg dict params form (instead of ``bindparams(**params)``)
        # because ``bindparams`` requires every key to appear in the SQL, and
        # the COUNT-only query below intentionally does not reference ``top_k``.
        # Both ``execute(text, params)`` and ``execute(text(...).bindparams(...))``
        # are public APIs; the dict form is the one with permissive key handling.
        result = await self._session.execute(text(sql), params)
        rows = result.all()

        chunk_results: list[dict[str, Any]] = [
            {
                "chunk_id": row.chunk_id,
                "doc_id": row.doc_id,
                "section_id": row.section_id,
                "granularity": "chunk",
                # ``text`` carries the actual chunk body (BP-NEW-CHUNK-TEXT) so
                # downstream snippet rendering does not require a MinIO fetch.
                # Falls back to heading_path when chunk_text is NULL (legacy
                # rows ingested before migration 0017).
                "text": row.chunk_text or row.heading_path or "",
                "score": float(row.score),
                "section_type": row.section_type,
                "heading_path": row.heading_path,
                "chunk_text_key": row.chunk_text_key,
                "chunk_text": row.chunk_text,
                # PLAN-0086 Wave C-1: expose document_title for RAG citations.
                "document_title": row.document_title,
            }
            for row in rows
        ]

        # total_searched = number of matched rows BEFORE LIMIT (post-filter).
        # We re-run the matched CTE through COUNT — slightly redundant but
        # mirrors the existing _search_chunks behaviour and avoids materialising
        # an OVER() window over the full result set.
        count_sql = f"""
            SELECT COUNT(*)
            FROM chunks c
            JOIN sections s ON s.section_id = c.section_id
            LEFT JOIN document_source_metadata dsm ON dsm.doc_id = c.doc_id
            WHERE {match_sql}
              AND {date_filter}
              AND {source_filter}
              {entity_filter_sql}
              {tenant_filter_sql}
              AND {score_sql} >= :min_score
            """
        count_result = await self._session.execute(text(count_sql), params)
        total = int(count_result.scalar_one())

        return chunk_results, total

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
