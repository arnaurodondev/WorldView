"""Dedup hash repository — Stage A/B hash existence checks and insertions.

Uses ``INSERT ... ON CONFLICT DO NOTHING`` for idempotent inserts (BP-040).
Duplicate hash inserts (e.g. Kafka consumer re-delivery) are silently ignored
rather than raising ``UniqueViolationError``.

Also contains ``DuplicateClusterRepository`` for Stage C (MinHash near-dup
pair writes) and ``MinHashCorpusRepository`` for fetching recent signatures to
compare against.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select, text, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert

import common.ids  # type: ignore[import-untyped]
from content_store.application.ports.repositories import DedupHashRepositoryPort
from content_store.application.use_cases.get_cluster_articles import ClusterArticleDTO
from content_store.infrastructure.db.models import (
    DedupHashModel,
    DocumentModel,
    DuplicateClusterModel,
    MinHashSignatureModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class DedupHashRepository(DedupHashRepositoryPort):
    """PostgreSQL dedup hash repository for Stage A and Stage B lookups."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_exists(self, hash_type: str, hash_value: str, tenant_id: UUID | None = None) -> UUID | None:
        """Check if a hash exists for the given scope. Returns the associated doc_id or None.

        ``tenant_id=None`` looks up in the global (public news) hash space.
        Pass a tenant UUID to scope the lookup to that tenant's private content.
        SQLAlchemy ``== None`` compiles to ``IS NULL``, which is correct here.
        """
        result = await self._session.execute(
            select(DedupHashModel.doc_id).where(
                DedupHashModel.hash_type == hash_type,
                DedupHashModel.hash_value == hash_value,
                DedupHashModel.tenant_id == tenant_id,  # IS NULL or = <uuid>
            )
        )
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    async def insert(self, doc_id: UUID, hash_type: str, hash_value: str, tenant_id: UUID | None = None) -> None:
        """Insert a dedup hash record (raw_sha256 or normalized_sha256).

        ``tenant_id=None`` inserts into the global (public) hash space.
        Uses ``ON CONFLICT DO NOTHING`` on the relevant partial index so
        duplicate inserts (e.g. Kafka re-delivery) are silently ignored
        instead of raising ``UniqueViolationError`` (BP-040).

        Note: partial-index ON CONFLICT uses index name (index_where),
        not a named constraint.
        """
        # Choose the correct partial index target based on tenant scope.
        # PostgreSQL requires the ON CONFLICT target to match the partial index predicate.
        if tenant_id is None:
            stmt = (
                pg_insert(DedupHashModel)
                .values(
                    hash_id=common.ids.new_uuid7(),
                    doc_id=doc_id,
                    hash_type=hash_type,
                    hash_value=hash_value,
                    tenant_id=None,
                )
                .on_conflict_do_nothing(
                    index_elements=["hash_type", "hash_value"],
                    index_where=DedupHashModel.tenant_id.is_(None),
                )
            )
        else:
            stmt = (
                pg_insert(DedupHashModel)
                .values(
                    hash_id=common.ids.new_uuid7(),
                    doc_id=doc_id,
                    hash_type=hash_type,
                    hash_value=hash_value,
                    tenant_id=tenant_id,
                )
                .on_conflict_do_nothing(
                    index_elements=["tenant_id", "hash_type", "hash_value"],
                    index_where=DedupHashModel.tenant_id.isnot(None),
                )
            )
        await self._session.execute(stmt)

    async def insert_pair(
        self,
        doc_id: UUID,
        raw_hash: str,
        normalized_hash: str,
        tenant_id: UUID | None = None,
    ) -> None:
        """Insert both Stage A (raw) and Stage B (normalized) hashes in one call.

        Each insert is individually idempotent via ``ON CONFLICT DO NOTHING``.
        ``tenant_id`` is forwarded to both inserts so both hashes land in the
        correct scope (global or tenant-private).
        """
        await self.insert(doc_id, "raw_sha256", raw_hash, tenant_id=tenant_id)
        await self.insert(doc_id, "normalized_sha256", normalized_hash, tenant_id=tenant_id)


# ── Stage C: duplicate cluster persistence ────────────────────────────────────


class DuplicateClusterRepository:
    """Repository for writing near-duplicate pairs discovered by MinHash Stage C.

    Uses ``ON CONFLICT DO NOTHING`` on the (primary_doc_id, duplicate_doc_id)
    unique constraint so Kafka consumer re-delivery is fully idempotent.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_pair(self, primary_doc_id: UUID, duplicate_doc_id: UUID, similarity: float) -> None:
        """Insert a near-duplicate pair into ``duplicate_clusters``.

        ``primary_doc_id`` is always the *lexicographically smaller* UUID so
        the pair is stored canonically regardless of which doc was processed
        first.  This prevents (A, B) and (B, A) from appearing as separate rows.

        On conflict the existing row is kept — the similarity score of the first
        detection is authoritative.
        """
        # Canonical ordering: smaller UUID is primary to prevent mirror pairs.
        if str(primary_doc_id) > str(duplicate_doc_id):
            primary_doc_id, duplicate_doc_id = duplicate_doc_id, primary_doc_id

        stmt = (
            pg_insert(DuplicateClusterModel)
            .values(
                cluster_id=common.ids.new_uuid7(),
                primary_doc_id=primary_doc_id,
                duplicate_doc_id=duplicate_doc_id,
                similarity=similarity,
                # Provide an explicit UTC timestamp so the server_default
                # (func.now()) is NOT used — avoids DB clock drift on replays.
                detected_at=datetime.now(tz=UTC),
            )
            # WHY index_elements (not constraint=): Using the column list is
            # more robust than a named constraint because it resolves the
            # conflict target by the unique index, not by constraint name.
            # The named-constraint approach broke in dev volumes where migration
            # 0002 auto-named the constraint differently (BP-442).
            .on_conflict_do_nothing(
                index_elements=["primary_doc_id", "duplicate_doc_id"],
            )
        )
        await self._session.execute(stmt)

    async def get_cluster_article_dtos(self, cluster_id: UUID) -> list[ClusterArticleDTO]:
        """Return all articles in a near-duplicate cluster.

        Collects every distinct doc_id that appears in ``duplicate_clusters``
        as either primary_doc_id or duplicate_doc_id for the given cluster_id,
        then joins with ``documents`` to fetch article metadata.

        WHY UNION (not just primary/duplicate split): a cluster_id is a row PK,
        so there is exactly one row per cluster_id — primary_doc_id and
        duplicate_doc_id are the two participants.  We union them to get both
        doc_ids, then join documents to enrich.

        WHY count via subquery: cluster_size is the total number of rows in
        duplicate_clusters with this cluster_id.  Since cluster_id is a PK,
        there is always exactly 1 row (2 articles).  We count participants
        (primary + duplicate) to compute cluster_size = 2.  This is consistent
        with the batch-cluster-sizes endpoint which counts appearances.

        Args:
            cluster_id: UUID of the duplicate cluster.

        Returns:
            List of ClusterArticleDTO (empty if cluster_id not found).
        """
        # Step 1: find the cluster row to get both doc_ids.
        cluster_result = await self._session.execute(
            select(DuplicateClusterModel.primary_doc_id, DuplicateClusterModel.duplicate_doc_id).where(
                DuplicateClusterModel.cluster_id == cluster_id
            )
        )
        row = cluster_result.one_or_none()
        if row is None:
            # Cluster does not exist — return empty list (not an error).
            return []

        primary_doc_id: UUID = row.primary_doc_id
        duplicate_doc_id: UUID = row.duplicate_doc_id
        doc_ids = [primary_doc_id, duplicate_doc_id]

        # Step 2: count total appearances across all clusters for each doc_id
        # to compute cluster_size consistently with the batch-cluster-sizes endpoint.
        # WHY union_all: counts primary + duplicate appearances per doc_id.
        combined = union_all(
            select(
                DuplicateClusterModel.primary_doc_id.label("doc_id"),
            ).where(DuplicateClusterModel.primary_doc_id.in_(doc_ids)),
            select(
                DuplicateClusterModel.duplicate_doc_id.label("doc_id"),
            ).where(DuplicateClusterModel.duplicate_doc_id.in_(doc_ids)),
        ).subquery()
        count_result = await self._session.execute(
            select(combined.c.doc_id, func.count().label("cnt")).group_by(combined.c.doc_id)
        )
        # cluster_size = appearances + 1 (include the document itself)
        size_map: dict[UUID, int] = {row.doc_id: row.cnt + 1 for row in count_result}

        # Step 3: fetch document metadata for both doc_ids.
        doc_result = await self._session.execute(
            select(
                DocumentModel.doc_id,
                DocumentModel.title,
                DocumentModel.source_url,
                DocumentModel.published_at,
                DocumentModel.source_type,
            ).where(DocumentModel.doc_id.in_(doc_ids))
        )
        dtos = [
            ClusterArticleDTO(
                id=r.doc_id,
                title=r.title,
                url=r.source_url,
                published_at=r.published_at,
                # WHY None: documents table has no source_name column — same as
                # DocumentMetadataDTO.source_name in the batch-documents endpoint.
                source_name=None,
                cluster_id=cluster_id,
                cluster_size=size_map.get(r.doc_id, 2),
            )
            for r in doc_result
        ]
        return dtos

    async def get_cluster_sizes(self, doc_ids: list[UUID]) -> dict[UUID, int]:
        """Return the near-duplicate cluster size for each requested doc_id.

        For each doc_id, counts how many rows in ``duplicate_clusters`` reference
        it as either primary_doc_id OR duplicate_doc_id.  A size of 1 means the
        document has no detected duplicates (it is alone in its cluster).

        Used by the gateway enrichment path to add ``cluster_size`` to ranked
        article responses without adding a cross-service JOIN at S6.

        Args:
            doc_ids: List of document UUIDs to look up.  Empty list returns {}.

        Returns:
            Dict mapping doc_id → cluster size (minimum 1).  doc_ids that have
            no rows in duplicate_clusters map to 1 (the document itself).
        """
        if not doc_ids:
            return {}

        # Count all rows where the doc appears as either side of the pair,
        # then add 1 (the document itself is always counted in the cluster).
        # union_all merges the primary and duplicate sides.
        #
        # WHY .subquery() + GROUP BY (not bare union_all execute): executing a
        # bare CompoundSelect with labeled UUID columns causes SQLAlchemy to
        # emit ``min(doc_id)`` when wrapping the union for result-row dedup,
        # but Postgres has no ``min(uuid)`` aggregate → 500. Wrapping the
        # union_all in an explicit subquery and aggregating with ``func.count()``
        # in the outer SELECT avoids the implicit ``min(uuid)`` wrap and lets
        # the database do the counting (also faster — no python-side Counter).
        combined = union_all(
            select(
                DuplicateClusterModel.primary_doc_id.label("doc_id"),
            ).where(DuplicateClusterModel.primary_doc_id.in_(doc_ids)),
            select(
                DuplicateClusterModel.duplicate_doc_id.label("doc_id"),
            ).where(DuplicateClusterModel.duplicate_doc_id.in_(doc_ids)),
        ).subquery()
        result = await self._session.execute(
            select(combined.c.doc_id, func.count().label("cnt")).group_by(combined.c.doc_id)
        )
        counts: dict[UUID, int] = {row.doc_id: row.cnt for row in result}
        # cluster_size = number of *other* docs detected as near-duplicates + 1 (self)
        return {doc_id: counts.get(doc_id, 0) + 1 for doc_id in doc_ids}

    async def get_cluster_ids(self, doc_ids: list[UUID]) -> dict[UUID, UUID]:
        """Return one cluster_id per doc_id for docs that are in a cluster.

        Docs that have no near-duplicate rows are absent from the result dict.

        WHY a separate method (not inline in get_cluster_sizes): the cluster_id
        lookup is only needed by the gateway enrichment path to populate the
        ``cluster_id`` field in ranked article responses — keeping it separate
        avoids adding a second subquery to the hot-path batch-cluster-sizes call.

        WHY "one cluster_id per doc_id": a document could appear in multiple
        cluster rows (e.g. near-duplicate of both doc A and doc B).  We pick
        the cluster_id where the doc appears as primary (lexicographically
        smaller UUID) first, falling back to the first duplicate-side row.
        The frontend uses cluster_id only to fetch the sibling list, which is
        fetched by cluster_id — any valid cluster_id for the doc is sufficient.

        Args:
            doc_ids: List of document UUIDs to look up.

        Returns:
            Mapping of doc_id → cluster_id for docs in at least one cluster.
        """
        if not doc_ids:
            return {}

        # Union primary and duplicate sides — select (doc_id, cluster_id) pairs.
        # WHY DISTINCT ON: PostgreSQL picks one cluster_id per doc_id (first row
        # in the union wins, which is the primary-side row if it exists).
        combined = union_all(
            select(
                DuplicateClusterModel.primary_doc_id.label("doc_id"),
                DuplicateClusterModel.cluster_id,
            ).where(DuplicateClusterModel.primary_doc_id.in_(doc_ids)),
            select(
                DuplicateClusterModel.duplicate_doc_id.label("doc_id"),
                DuplicateClusterModel.cluster_id,
            ).where(DuplicateClusterModel.duplicate_doc_id.in_(doc_ids)),
        ).subquery()

        # Group by doc_id, take any cluster_id (min for determinism).
        # WHY cast to text before min(): PostgreSQL has no built-in min() aggregate
        # for the UUID type — applying func.min() directly raises ProgrammingError:
        # "function min(uuid) does not exist". Casting to text makes the comparison
        # lexicographic (same ordering as UUID string form) which is deterministic
        # within a result set. The outer cast back to UUID restores the return type.
        result = await self._session.execute(
            select(
                combined.c.doc_id,
                func.min(combined.c.cluster_id.cast(text("text"))).cast(text("uuid")).label("cluster_id"),
            ).group_by(combined.c.doc_id)
        )
        return {row.doc_id: row.cluster_id for row in result}


# ── Corpus reader for MinHash near-dup candidate lookup ───────────────────────


class MinHashCorpusRepository:
    """Read recent MinHash signatures for pairwise Jaccard similarity checks.

    Fetches ``limit`` most-recently-created signatures (excluding the one
    belonging to ``exclude_doc_id``) so the Stage C consumer can compare the
    new document against the recent corpus without loading the entire table.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_recent_signatures(
        self,
        exclude_doc_id: UUID,
        within_days: int = 14,
        limit: int = 500,
    ) -> list[tuple[UUID, list[int]]]:
        """Return ``(doc_id, signature)`` pairs from the last *within_days* days.

        Uses the ``idx_minhash_sig_created`` index (created_at DESC) for fast
        time-window scans.  ``limit`` caps total rows to keep per-message
        latency predictable even as the corpus grows.

        Args:
            exclude_doc_id: The doc_id of the incoming article — excluded from
                results so we never compare a document against itself.
            within_days: How many calendar days back to scan.  Default 14 gives
                a 2-week recency window for news near-dup detection.
            limit: Max rows to return.  500 rows x 128 ints ~= 250 KB per message.
        """
        result = await self._session.execute(
            select(MinHashSignatureModel.doc_id, MinHashSignatureModel.signature)
            .where(
                MinHashSignatureModel.doc_id != exclude_doc_id,
                # Use a raw interval expression so PostgreSQL can use the index.
                MinHashSignatureModel.created_at >= text(f"NOW() - INTERVAL '{within_days} days'"),
            )
            .order_by(MinHashSignatureModel.created_at.desc())
            .limit(limit)
        )
        return [(row.doc_id, row.signature) for row in result]
