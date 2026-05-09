"""AsyncpgDocumentSearchRepository — full-text document search via tsv_english GIN.

Implements DocumentSearchRepositoryPort using SQLAlchemy AsyncSession with
raw SQL via ``session.execute(text(...))``. All queries target nlp_db only;
no cross-DB joins (R9). Entity names are fetched separately by the use case
via S7 HTTP; document titles are fetched via S5 HTTP (AD-W6-3).

SQL design (PLAN-0064 §3 AD-W6-2 + AD-W6-3):
  - ``websearch_to_tsquery`` for user-facing queries (supports quoted phrases,
    OR, and ``-`` operators; no injection vector since asyncpg parameterises
    the query value).
  - ``ts_rank_cd`` for per-chunk ranking; ``DISTINCT ON (doc_id)`` picks the
    best chunk per document (AD-W6-3: per-chunk-max, not BM25).
  - Recency x source-type blended final_score decays with a 90-day half-life
    (exp(-days/90)). SEC filings get a 1.5x boost vs plain news.
  - BP-180: all nullable params use ``CAST(:param AS type) IS NULL OR ...``
    to avoid asyncpg AmbiguousParameterError.
  - Sentinel bytes: ``chr(2)`` / ``chr(3)`` used as ts_headline StartSel/StopSel
    so the use case can strip them into plain text + char offsets (AD-W6-3
    snippet contract). These bytes never appear in UTF-8 prose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from nlp_pipeline.api.schemas import (
    SearchDocumentResult,
    SearchDocumentsFacet,
    SearchDocumentsRequest,
)
from nlp_pipeline.application.ports.document_search import DocumentSearchRepositoryPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ── Sentinel bytes for ts_headline (AD-W6-3 snippet contract) ────────────────
# These are control characters that cannot appear in UTF-8 text corpora.
# They are stripped by _strip_markers() in the use case layer.
_START_SEL = chr(2)  # \x02 — marks start of a matched fragment
_STOP_SEL = chr(3)  # \x03 — marks end of a matched fragment

# ts_headline options string: max 1 fragment, ~30-word window, sentinel markers.
# ShortWord=3 prevents single stop-words from becoming isolated highlights.
_TS_HEADLINE_OPTS = (
    f"MaxFragments=1, MaxWords=40, MinWords=15, ShortWord=3, " f"StartSel={_START_SEL}, StopSel={_STOP_SEL}"
)

# ── Main search CTE (search + count share the same WITH clauses) ─────────────
#
# Structure:
#   ranked_chunks      — FTS rank + ts_headline snippet per chunk row
#   top_chunk_per_doc  — DISTINCT ON (doc_id) picks best-ranked chunk
#   filtered           — applies entity / source_type / date filters
#
# BP-180: nullable params (:entity_ids, :source_type, :date_from, :date_to) all
# use CAST(...) IS NULL to short-circuit when the caller passes None.
# The asyncpg driver infers the param type from the CAST expression, avoiding
# the AmbiguousParameterError raised when a bare $N placeholder is NULL.

_SEARCH_CTE = """\
WITH ranked_chunks AS (
    SELECT
        c.doc_id,
        ts_rank_cd(c.tsv_english, websearch_to_tsquery('english', :q)) AS rank,
        ts_headline(
            'english',
            c.chunk_text,
            websearch_to_tsquery('english', :q),
            :ts_headline_opts
        ) AS snippet_marked
    FROM chunks c
    WHERE c.tsv_english @@ websearch_to_tsquery('english', :q)
),
top_chunk_per_doc AS (
    SELECT DISTINCT ON (rc.doc_id)
        rc.doc_id, rc.rank, rc.snippet_marked
    FROM ranked_chunks rc
    ORDER BY rc.doc_id, rc.rank DESC
),
filtered AS (
    SELECT t.doc_id, t.rank, t.snippet_marked
    FROM top_chunk_per_doc t
    LEFT JOIN document_source_metadata dsm ON dsm.doc_id = t.doc_id
    WHERE
        -- BP-180: CAST(NULL AS uuid[]) IS NULL short-circuits the subquery when
        -- no entity filter is requested; avoids asyncpg type-ambiguity.
        (
            CAST(:entity_ids AS uuid[]) IS NULL
            OR t.doc_id IN (
                SELECT DISTINCT em.doc_id
                FROM entity_mentions em
                WHERE em.resolved_entity_id = ANY(CAST(:entity_ids AS uuid[]))
            )
        )
        AND (
            CAST(:source_types AS text[]) IS NULL
            OR dsm.source_type = ANY(CAST(:source_types AS text[]))
        )
        AND (
            CAST(:date_from AS timestamptz) IS NULL
            OR dsm.published_at >= CAST(:date_from AS timestamptz)
        )
        AND (
            CAST(:date_to AS timestamptz) IS NULL
            OR dsm.published_at <= CAST(:date_to AS timestamptz)
        )
)"""

# ── SELECT leg: apply recency x source-type blend, paginate ─────────────────
# Blended final_score = rank x source_weight x recency_decay.
# source_weight: sec_edgar=1.5, news=1.0 (higher for structured filings).
# recency_decay: exp(-days_since_published/90) — 90-day half-life.
_SEARCH_SELECT = """\
SELECT
    f.doc_id,
    f.rank,
    f.snippet_marked,
    dsm.source_type AS source_type,
    (
        f.rank
        * CASE dsm.source_type
            WHEN 'sec_edgar' THEN 1.5
            WHEN 'news'      THEN 1.0
            ELSE                  1.0
          END
        * exp(
            - (extract(epoch from (now() - dsm.published_at)) / 86400.0) / 90.0
          )
    ) AS final_score
FROM filtered f
LEFT JOIN document_source_metadata dsm ON dsm.doc_id = f.doc_id
ORDER BY final_score DESC NULLS LAST
LIMIT :limit OFFSET :offset"""

# ── COUNT leg: same CTEs, no LIMIT/OFFSET ────────────────────────────────────
_COUNT_SELECT = "SELECT count(*) FROM filtered"

# ── Facets query ──────────────────────────────────────────────────────────────
# Returns top-25 entity mentions by distinct doc_id count.
# resolved_entity_id IS NOT NULL is enforced by the WHERE clause (not a filter —
# confirmed by the fact that the column is nullable in entity_mentions).
_FACETS_SQL = """\
SELECT
    em.resolved_entity_id,
    em.mention_class AS entity_type,
    COUNT(DISTINCT em.doc_id) AS cnt
FROM entity_mentions em
WHERE em.doc_id = ANY(CAST(:doc_ids AS uuid[]))
  AND em.resolved_entity_id IS NOT NULL
GROUP BY em.resolved_entity_id, em.mention_class
ORDER BY cnt DESC
LIMIT 25"""


class AsyncpgDocumentSearchRepository(DocumentSearchRepositoryPort):
    """Full-text document search backed by PostgreSQL + tsv_english GIN index.

    Uses SQLAlchemy AsyncSession with raw SQL text() queries.  The session is
    injected by the dependency injection layer in ``api/dependencies.py``
    (Wave 3 wires this).

    All asyncpg nullable-param edge cases (BP-180) are handled via
    ``CAST(:param AS type) IS NULL`` short-circuit guards in the SQL.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(self, request: SearchDocumentsRequest) -> tuple[list[SearchDocumentResult], int]:
        """Execute FTS query using tsv_english GIN index.

        Returns (results_with_raw_snippets, total_count).

        Snippets contain raw sentinel bytes (\\x02/\\x03); the use case layer
        strips them into plain text + offset pairs (AD-W6-3).
        """
        params = _build_search_params(request)

        # ── Total count (same CTE, no LIMIT) ─────────────────────────────────
        count_sql = _SEARCH_CTE + "\n" + _COUNT_SELECT
        count_result = await self._session.execute(text(count_sql).bindparams(**params))
        total: int = int(count_result.scalar_one())

        if total == 0:
            return [], 0

        # ── Ranked results ────────────────────────────────────────────────────
        offset = (request.page - 1) * request.page_size
        paged_params = {
            **params,
            "limit": request.page_size,
            "offset": offset,
        }
        search_sql = _SEARCH_CTE + "\n" + _SEARCH_SELECT
        result = await self._session.execute(text(search_sql).bindparams(**paged_params))
        rows = result.all()

        results: list[SearchDocumentResult] = []
        for row in rows:
            # source_type from document_source_metadata; fall back to "unknown"
            # when the metadata row has not yet been populated (best-effort).
            source_type: str = row.source_type or "unknown"

            results.append(
                SearchDocumentResult(
                    doc_id=row.doc_id,
                    title=None,  # filled in by use case via S5 batch call
                    source_type=source_type,
                    source_url=None,  # filled in by use case via S5 batch call
                    published_at=None,  # filled in by use case via S5 batch call
                    snippet=row.snippet_marked,  # still has sentinel bytes
                    match_offsets=[],  # filled in by use case after stripping
                    score=float(row.final_score) if row.final_score is not None else 0.0,
                    entity_hits=[],  # filled in by use case from entity_ids filter
                )
            )

        return results, total

    async def facets(self, request: SearchDocumentsRequest, hit_doc_ids: list[UUID]) -> list[SearchDocumentsFacet]:
        """Return top-25 entity facets for the given hit doc_ids.

        ``name`` is left as an empty string — the use case fills it in via
        the S7 batch HTTP call.  This keeps the repo free of HTTP dependencies.
        """
        if not hit_doc_ids:
            return []

        result = await self._session.execute(
            text(_FACETS_SQL).bindparams(
                # BP-180: pass as list of strings; CAST(:doc_ids AS uuid[])
                # tells asyncpg the expected type, preventing AmbiguousParameterError.
                doc_ids=[str(d) for d in hit_doc_ids],
            )
        )
        rows = result.all()

        return [
            SearchDocumentsFacet(
                entity_id=row.resolved_entity_id,
                name="",  # filled in by use case via S7 batch
                entity_type=row.entity_type or "unknown",
                count=int(row.cnt),
            )
            for row in rows
        ]


# ── Param builder ─────────────────────────────────────────────────────────────

# Maps API source_type values to the actual source_type strings stored in
# document_source_metadata.  The API exposes a coarser taxonomy than the DB
# (which records the exact ingestion adapter name).
_SOURCE_TYPE_MAP: dict[str, list[str]] = {
    "news": ["eodhd_news", "finnhub_news", "press_release"],
    "sec_edgar": ["sec_10k", "sec_8k", "sec_10q"],
}

# Maps date_preset values to a relative window in days before now.
# "since_last_visit" requires per-user state and is treated as no filter here.
_DATE_PRESET_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}


def _build_search_params(request: SearchDocumentsRequest) -> dict:
    """Build the parameter dict for the search + count SQL queries.

    BP-180: nullable params are passed as None and use CAST(...) IS NULL in
    the SQL to avoid asyncpg AmbiguousParameterError for NULL typed params.

    source_type filter: "all" means no filter → pass None (CAST(NULL AS text[]) IS NULL).
    source_types filter: list of DB values when source_type is not "all".
    entity_ids filter: empty list means no filter → pass None.
    date_preset: resolved to date_from when set; "since_last_visit" treated as no preset.
    """
    # Entity IDs: None when the list is empty (no filter).
    entity_ids_param = [str(eid) for eid in request.entity_ids] if request.entity_ids else None

    # source_types: None means no filter; mapped from API taxonomy to DB values.
    source_types_param: list[str] | None = None
    if request.source_type and request.source_type != "all":
        source_types_param = _SOURCE_TYPE_MAP.get(request.source_type)

    # date_preset: wins over date_from when both are supplied.
    date_from = request.date_from
    if request.date_preset and request.date_preset in _DATE_PRESET_DAYS:
        days = _DATE_PRESET_DAYS[request.date_preset]
        date_from = datetime.now(tz=UTC) - timedelta(days=days)

    return {
        "q": request.q,
        "ts_headline_opts": _TS_HEADLINE_OPTS,
        "entity_ids": entity_ids_param,
        "source_types": source_types_param,
        "date_from": date_from,
        "date_to": request.date_to,
    }
