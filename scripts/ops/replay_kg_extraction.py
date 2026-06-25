"""PLAN-0088 Wave I-2 — Replay KG relation extraction from silver storage.

Goal
----
Boost knowledge-graph edge density for AAPL (≥ 30 edges) and the eight demo
tickers (AAPL, MSFT, NVDA, AMZN, TSLA, GOOGL, META, JPM — each ≥ 20 edges)
by re-firing the NLP article pipeline on documents already cleaned and
stored in MinIO silver but never (or only weakly) processed end-to-end into
``relations``.

Why a script (not the existing ``POST /v1/signals/reprocess/{article_id}``)
--------------------------------------------------------------------------
The existing reprocess endpoint emits ``nlp.reprocess.v1`` events, which
*no consumer subscribes to* (verified 2026-05-09). This makes that endpoint
a dead-end. The pipeline's natural input is ``content.article.stored.v1``;
the only durable way to re-trigger NLP processing is to re-publish that
event with a fresh event_id.

Why deleting routing_decisions is required
------------------------------------------
``ArticleProcessingConsumer.process_message`` short-circuits via::

    if await check_routing_repo.get_by_doc(doc_id) is not None:
        return  # skip

so a re-published event is silently dropped on the consumer side unless we
clear the routing-decision sentinel first. We delete only the sentinel; all
other artifacts (entity_mentions, embeddings, chunks) write with
deterministic UUIDv5 + ``ON CONFLICT DO NOTHING`` so re-running is a no-op
for them. The new work happens inside Block 9 (deep extraction) — that is
where every fresh ``relation_evidence_raw`` row originates, and that is the
LLM spend the user authorised.

Idempotency / spend bound
-------------------------
- Per-ticker cap (default 100) keeps a worst-case bound on LLM cost.
- Cluster-wide cap (default 600 across all tickers).
- Each replay = at most one DEEP-tier extraction call (the primary cost) +
  embedding + relevance-scoring; bounded by routing-decision tier.
- ``relation_evidence_raw`` has NO unique constraint so duplicates from
  replays are possible, but the downstream aggregation worker dedupes into
  ``relations`` via deterministic relation_id, so edge counts cannot
  inflate.

Operations
----------
This script writes outbox rows directly into ``content_store_db.outbox_events``
and lets the existing ``content-store-dispatcher`` publish them to Kafka. We
do not create a side-channel producer — the same code path that originally
published the events handles the replay.

Usage
-----
    # Inside the venv (libs already on PYTHONPATH):
    python scripts/ops/replay_kg_extraction.py --dry-run
    python scripts/ops/replay_kg_extraction.py --per-ticker 100

    # Re-extract the EMPTY DEEP-tier cohort (deep-routed docs that produced no
    # narrative relation — mostly lost to the now-fixed DeepInfra 429 storm):
    python scripts/ops/replay_kg_extraction.py --empty-cohort --dry-run
    python scripts/ops/replay_kg_extraction.py --empty-cohort            # full run
    python scripts/ops/replay_kg_extraction.py --empty-cohort --limit 1000  # one wave

The script connects to host postgres on the docker-mapped port (5432).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC
from typing import Any
from uuid import UUID, uuid4

import asyncpg

# WHY structured logger via stdlib here: this script lives outside the
# service tree so it does not get the structlog factory wired by
# ``observability.configure_logging``. Using stdlib keeps the ops surface
# zero-dependency (no need to install libs/observability into the venv).
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("replay_kg_extraction")


# ── Demo entities (PRD-0087 demo-12, currently 8 seeded) ────────────────────
# WHY hardcoded: the seed file (scripts/seed_demo_data.py) declares the same
# set; duplicating here keeps the script runnable without importing service
# code. Source of truth: scripts/seed_demo_data.py.
# M-017 (2026-06-14): entity_id == the instrument id (01900000-…-00000000100X),
# kept in lockstep with the seed. The old placeholder "11111111-000X" ids
# existed nowhere in the KG and would no longer resolve.
DEMO_ENTITIES: list[tuple[str, str, str]] = [
    # (entity_id, canonical_name, ticker_for_log)
    ("01900000-0000-7000-8000-000000001001", "Apple Inc.", "AAPL"),
    ("01900000-0000-7000-8000-000000001002", "Microsoft Corporation", "MSFT"),
    ("01900000-0000-7000-8000-000000001006", "NVIDIA Corporation", "NVDA"),
    ("01900000-0000-7000-8000-000000001005", "Amazon.com Inc", "AMZN"),
    ("01900000-0000-7000-8000-000000001004", "Tesla Inc", "TSLA"),
    ("01900000-0000-7000-8000-000000001003", "Alphabet Inc Class A", "GOOGL"),
    ("01900000-0000-7000-8000-000000001007", "Meta Platforms Inc.", "META"),
    ("01900000-0000-7000-8000-000000001008", "JPMorgan Chase & Co", "JPM"),
]


@dataclass
class DocRow:
    """Subset of content_store_db.documents needed to rebuild the stored event."""

    doc_id: UUID
    source_type: str
    title: str | None
    content_hash: str
    normalized_hash: str
    dedup_result: str
    minio_silver_key: str
    word_count: int | None
    published_at: Any  # datetime | None — we only serialise to ISO string
    is_backfill: bool
    tenant_id: UUID | None


async def _connect(host: str, port: int, db: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=host,
        port=port,
        user="postgres",
        password="postgres",  # noqa: S106 — local-dev docker-compose secret
        database=db,
    )


async def _select_docs_by_source(
    cs_conn: asyncpg.Connection,
    nlp_conn: asyncpg.Connection,
    source_type: str,
    limit: int,
) -> list[DocRow]:
    """Return up to *limit* documents of *source_type* not yet processed.

    "Not yet processed" = no row in nlp_db.routing_decisions for this doc_id.
    This is the high-leverage path for EODHD/SEC long-form articles that
    were stored in MinIO silver but never reached the NLP pipeline.
    """
    # WHY this query path: 561 EODHD articles (avg 693 words) currently sit
    # unprocessed; replaying just these will yield far more relations per
    # LLM-spend dollar than re-running already-processed Finnhub headlines
    # (avg 47 words, ~1 unique relation per article).
    processed_ids = {row["doc_id"] for row in await nlp_conn.fetch("SELECT doc_id FROM routing_decisions")}
    rows = await cs_conn.fetch(
        """
        SELECT doc_id, source_type, title, content_hash, normalized_hash,
               dedup_result, minio_silver_key, word_count, published_at,
               is_backfill, tenant_id
        FROM documents
        WHERE source_type = $1
          AND minio_silver_key IS NOT NULL
        ORDER BY published_at DESC NULLS LAST
        LIMIT $2
        """,
        source_type,
        limit * 4,  # over-fetch so we can drop already-processed ones
    )
    out: list[DocRow] = []
    for row in rows:
        if row["doc_id"] in processed_ids:
            continue
        out.append(
            DocRow(
                doc_id=row["doc_id"],
                source_type=row["source_type"],
                title=row["title"],
                content_hash=row["content_hash"],
                normalized_hash=row["normalized_hash"],
                dedup_result=row["dedup_result"],
                minio_silver_key=row["minio_silver_key"],
                word_count=row["word_count"],
                published_at=row["published_at"],
                is_backfill=row["is_backfill"],
                tenant_id=row["tenant_id"],
            ),
        )
        if len(out) >= limit:
            break
    return out


async def _select_docs_for_entity(
    nlp_conn: asyncpg.Connection,
    cs_conn: asyncpg.Connection,
    entity_id: UUID,
    limit: int,
) -> list[DocRow]:
    """Return up to *limit* documents that mention *entity_id*.

    The join goes through nlp_db.entity_mentions (resolved_entity_id) →
    distinct doc_id → content_store_db.documents. We deliberately prefer
    documents that have NOT yet contributed to ``relation_evidence_raw`` so
    we don't waste LLM spend on already-extracted articles.
    """
    # Step 1: distinct doc_ids that mention this entity, ordered by recency
    # (entity_mentions.created_at) so we replay the freshest articles first.
    doc_ids: list[UUID] = [
        row["doc_id"]
        for row in await nlp_conn.fetch(
            """
            SELECT DISTINCT em.doc_id, MAX(em.created_at) AS most_recent
            FROM entity_mentions em
            WHERE em.resolved_entity_id = $1
            GROUP BY em.doc_id
            ORDER BY most_recent DESC
            LIMIT $2
            """,
            entity_id,
            limit * 2,  # Fetch extra so we can drop already-extracted ones.
        )
    ]
    if not doc_ids:
        return []

    # Step 2: filter out docs that already have relation_evidence_raw rows
    # for THIS entity. We don't want to waste a replay if the article already
    # contributed an edge.
    # Note: this check is per-entity not per-doc-overall — an article could
    # have produced relations for OTHER entities but still owe us one for this
    # ticker. We accept that and re-run.
    intel_conn = await _connect(_HOST, _PORT, "intelligence_db")
    try:
        already_extracted = {
            row["source_document_id"]
            for row in await intel_conn.fetch(
                """
                SELECT DISTINCT source_document_id
                FROM relation_evidence_raw
                WHERE source_document_id = ANY($1)
                  AND (subject_entity_id = $2 OR object_entity_id = $2)
                """,
                doc_ids,
                entity_id,
            )
        }
    finally:
        await intel_conn.close()

    # WHY include already-extracted as a fallback: when there are not enough
    # "fresh" docs, we want to re-attempt extraction on docs that produced
    # weak or zero relations the first time around. The relation_id
    # determinism guarantees this won't inflate edge counts artificially.
    fresh_ids = [d for d in doc_ids if d not in already_extracted]
    selected_ids = fresh_ids[:limit]
    if len(selected_ids) < limit:
        # Top up with already-extracted ones (they may produce additional
        # relations on a second pass with a current LLM).
        selected_ids.extend([d for d in doc_ids if d in already_extracted][: limit - len(selected_ids)])

    if not selected_ids:
        return []

    # Step 3: hydrate full document rows from content_store_db.documents.
    rows = await cs_conn.fetch(
        """
        SELECT doc_id, source_type, title, content_hash, normalized_hash,
               dedup_result, minio_silver_key, word_count, published_at,
               is_backfill, tenant_id
        FROM documents
        WHERE doc_id = ANY($1)
          AND minio_silver_key IS NOT NULL
        """,
        selected_ids,
    )
    return [
        DocRow(
            doc_id=row["doc_id"],
            source_type=row["source_type"],
            title=row["title"],
            content_hash=row["content_hash"],
            normalized_hash=row["normalized_hash"],
            dedup_result=row["dedup_result"],
            minio_silver_key=row["minio_silver_key"],
            word_count=row["word_count"],
            published_at=row["published_at"],
            is_backfill=row["is_backfill"],
            tenant_id=row["tenant_id"],
        )
        for row in rows
    ]


async def _select_empty_deep_cohort(
    cs_conn: asyncpg.Connection,
    nlp_conn: asyncpg.Connection,
    limit: int,
) -> list[DocRow]:
    """Return up to *limit* EMPTY DEEP-tier docs for re-extraction.

    Cohort definition (see docs/audits/2026-06-13-relation-extraction-quality-audit.md
    and docs/audits/2026-06-14-extraction-transient-failure-investigation.md):
    deep-routed news articles that produced NO narrative relation — most of
    them lost to the now-fixed DeepInfra 429 ``engine_overloaded`` storm (1,003
    of 1,013 failed docs never recovered). Re-firing them through the
    retry-enabled consumers should finally extract their relations.

    A doc qualifies when ALL of the following hold:

    1. ``nlp_db.routing_decisions.final_routing_tier = 'deep'`` — it was routed
       to the deep-extraction tier (the only tier that runs Block 9 LLM
       extraction at full strength).
    2. Its ``source_document_id`` has ZERO *narrative* rows in
       ``intelligence_db.relation_evidence_raw``. "Narrative" means
       ``canonical_type <> 'is_in_sector'``: the audit established that 62,718
       of 76,869 raw rows are STRUCTURED ``is_in_sector`` enrichment emitted by
       the fundamentals path (one financial_instrument -> sector per doc), NOT
       by the news LLM. We therefore EXCLUDE those rows when deciding whether a
       doc is "empty" — a doc whose ONLY evidence is ``is_in_sector`` still
       counts as empty-narrative and is eligible for replay.
    3. It still exists in ``content_store_db.documents`` WITH a
       ``minio_silver_key`` — so the ``content.article.stored.v1`` event can be
       rebuilt AND the consumer can re-read the cleaned silver text.

    Because these are three SEPARATE physical databases (nlp_db,
    intelligence_db, content_store_db on the same Postgres server but distinct
    catalogs), we cannot cross-database JOIN. We fetch the three doc-id sets
    independently and intersect them in Python, mirroring the set-difference
    approach already used by ``_select_docs_by_source`` (which diffs against the
    processed-id set).
    """
    # Set 1 — all deep-tier doc_ids (nlp_db).
    deep_ids: set[UUID] = {
        row["doc_id"]
        for row in await nlp_conn.fetch(
            "SELECT DISTINCT doc_id FROM routing_decisions WHERE final_routing_tier = 'deep'",
        )
    }
    log.info("empty_cohort_deep_docs=%d", len(deep_ids))

    # Set 2 — doc_ids that already have at least one NARRATIVE relation
    # (anything other than the structured ``is_in_sector`` enrichment). These
    # are NOT empty and must be excluded. ``IS DISTINCT FROM`` also keeps NULL
    # ``canonical_type`` rows in the narrative set (a proposed-but-unmapped
    # predicate still means the LLM produced *something*), so a doc with such a
    # row is correctly treated as non-empty.
    intel_conn = await _connect(_HOST, _PORT, "intelligence_db")
    try:
        narrative_ids: set[UUID] = {
            row["source_document_id"]
            for row in await intel_conn.fetch(
                """
                SELECT DISTINCT source_document_id
                FROM relation_evidence_raw
                WHERE canonical_type IS DISTINCT FROM 'is_in_sector'
                """,
            )
        }
    finally:
        await intel_conn.close()
    log.info("empty_cohort_narrative_docs=%d (excluded)", len(narrative_ids))

    # Candidate doc_ids = deep AND NOT narrative. These are the empty-deep docs;
    # we still need to confirm each is rebuildable from content_store.
    candidate_ids = deep_ids - narrative_ids
    log.info("empty_cohort_candidates=%d (deep minus narrative)", len(candidate_ids))
    if not candidate_ids:
        return []

    # Set 3 — hydrate ONLY the candidates that still exist in
    # content_store_db.documents and carry a silver key. We pass the candidate
    # id list as a bind parameter so Postgres filters server-side; the
    # ``minio_silver_key IS NOT NULL`` predicate enforces rebuildability. We
    # order by recency so a partial (--limit) run replays the freshest docs
    # first, matching the ordering convention of the other selectors.
    rows = await cs_conn.fetch(
        """
        SELECT doc_id, source_type, title, content_hash, normalized_hash,
               dedup_result, minio_silver_key, word_count, published_at,
               is_backfill, tenant_id
        FROM documents
        WHERE doc_id = ANY($1)
          AND minio_silver_key IS NOT NULL
        ORDER BY published_at DESC NULLS LAST
        LIMIT $2
        """,
        list(candidate_ids),
        limit,
    )
    return [
        DocRow(
            doc_id=row["doc_id"],
            source_type=row["source_type"],
            title=row["title"],
            content_hash=row["content_hash"],
            normalized_hash=row["normalized_hash"],
            dedup_result=row["dedup_result"],
            minio_silver_key=row["minio_silver_key"],
            word_count=row["word_count"],
            published_at=row["published_at"],
            is_backfill=row["is_backfill"],
            tenant_id=row["tenant_id"],
        )
        for row in rows
    ]


def _build_stored_payload(doc: DocRow) -> dict[str, Any]:
    """Build a payload matching content.article.stored.v1 Avro schema.

    Mirrors content_store/application/use_cases/process_article.py
    ``_build_stored_payload`` (lines 350-374). Kept inline so the script does
    not import service code (would force the full content-store dependency
    chain into the venv).
    """
    return {
        # WHY new event_id: dedup at the consumer is keyed on event_id; reusing
        # an old one would cause Valkey to short-circuit the replay.
        "event_id": str(uuid4()),
        "event_type": "content.article.stored",
        "schema_version": 1,
        "occurred_at": _utc_iso_now(),
        "doc_id": str(doc.doc_id),
        "content_hash": doc.content_hash,
        "normalized_hash": doc.normalized_hash,
        "dedup_result": doc.dedup_result,
        "minio_silver_key": doc.minio_silver_key,
        "source_type": doc.source_type,
        "title": doc.title,
        "word_count": doc.word_count,
        "published_at": doc.published_at.isoformat() if doc.published_at else None,
        "is_backfill": doc.is_backfill,
        "correlation_id": f"replay-i2-{uuid4().hex[:8]}",
        "tenant_id": str(doc.tenant_id) if doc.tenant_id else None,
    }


def _utc_iso_now() -> str:
    """Return current UTC time as ISO-8601 string with timezone."""
    # Local import to keep the top-level import surface tight.
    from datetime import datetime

    return datetime.now(tz=UTC).isoformat()


async def _enqueue_replay(
    cs_conn: asyncpg.Connection,
    nlp_conn: asyncpg.Connection,
    docs: list[DocRow],
    *,
    dry_run: bool,
) -> int:
    """Insert outbox rows + delete routing-decision sentinels (atomic)."""
    if not docs:
        return 0

    if dry_run:
        return len(docs)

    # WHY transactional batch: we want all-or-nothing semantics per ticker so
    # a partial failure mid-batch does not leave the routing_decision deletes
    # without their corresponding outbox rows (which would cause downstream
    # data drift on the next live ingest).
    async with cs_conn.transaction():
        for doc in docs:
            payload = _build_stored_payload(doc)
            await cs_conn.execute(
                """
                INSERT INTO outbox_events
                  (id, aggregate_type, aggregate_id, event_type, topic, payload, status)
                VALUES
                  ($1, 'document', $2, 'content.article.stored.v1',
                   'content.article.stored.v1', $3::jsonb, 'pending')
                """,
                uuid4(),
                doc.doc_id,
                json.dumps(payload),
            )

    # Delete routing-decision sentinels so the NLP article-consumer does not
    # short-circuit on the re-delivered event. This MUST happen AFTER the
    # outbox insert commits — otherwise a race could let the consumer see
    # the event before we clear the sentinel.
    doc_ids = [d.doc_id for d in docs]
    await nlp_conn.execute(
        """
        DELETE FROM routing_decisions
        WHERE doc_id = ANY($1)
        """,
        doc_ids,
    )

    return len(docs)


_HOST = "localhost"
_PORT = 5432


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--per-ticker",
        type=int,
        default=100,
        help="Max replays per demo ticker (default 100).",
    )
    parser.add_argument(
        "--cluster-cap",
        type=int,
        default=600,
        help="Hard cap on total replays across all tickers (default 600).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only — do not insert outbox rows or delete sentinels.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated tickers to restrict replay to (e.g. 'AAPL,MSFT').",
    )
    parser.add_argument(
        "--source-mode",
        type=str,
        default="",
        help=(
            "Replay all unprocessed docs of a given source_type "
            "(e.g. 'eodhd', 'sec_edgar'). When set, skips per-ticker selection "
            "and replays all matching docs that have NO routing_decisions row."
        ),
    )
    parser.add_argument(
        "--source-limit",
        type=int,
        default=200,
        help="Max docs to replay in --source-mode (default 200).",
    )
    parser.add_argument(
        "--empty-cohort",
        action="store_true",
        help=(
            "Replay the EMPTY DEEP-tier cohort: deep-routed docs "
            "(routing_decisions.final_routing_tier='deep') that produced ZERO "
            "narrative relation-evidence (canonical_type<>'is_in_sector') and "
            "still exist in content_store with a silver key. Bypasses per-ticker "
            "selection; intended for the post-429-fix re-extraction. "
            "Respects --limit and --cluster-cap (raise the cap for a full run)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help=(
            "Max docs to replay in --empty-cohort mode (default 10000 — large "
            "enough for the full ~6k cohort). Use a smaller value to run in "
            "safe waves (combine with the doc ordering: most-recent first)."
        ),
    )
    parser.add_argument(
        "--postgres-host",
        type=str,
        default="localhost",
        help="Postgres host (default localhost — host network).",
    )
    parser.add_argument(
        "--postgres-port",
        type=int,
        default=5432,
        help="Postgres port (default 5432).",
    )
    args = parser.parse_args()

    global _HOST, _PORT
    _HOST = args.postgres_host
    _PORT = args.postgres_port

    only_set: set[str] = set()
    if args.only:
        only_set = {t.strip().upper() for t in args.only.split(",") if t.strip()}

    cs_conn = await _connect(_HOST, _PORT, "content_store_db")
    nlp_conn = await _connect(_HOST, _PORT, "nlp_db")
    try:
        total_enqueued = 0
        per_ticker_results: dict[str, int] = {}

        # ── Empty-cohort shortcut ─────────────────────────────────────────────
        # Highest-leverage post-429-fix path: replay the deep-routed docs that
        # the rate-limit storm left with zero narrative relations. The bound is
        # --limit (default 10000, i.e. the whole ~6k cohort fits); the operator
        # can lower it to run in safe waves. --limit IS the explicit cap here,
        # so the demo per-ticker --cluster-cap (default 600) does NOT clamp it.
        if args.empty_cohort:
            log.info("empty_cohort_replay limit=%d dry_run=%s", args.limit, args.dry_run)
            docs = await _select_empty_deep_cohort(cs_conn, nlp_conn, args.limit)
            log.info(
                "empty_cohort_selected docs=%d (avg_words=%s)",
                len(docs),
                sum(d.word_count or 0 for d in docs) // max(1, len(docs)),
            )
            # Sample (first 5) so the operator can eyeball the selection in a
            # dry run before authorising the live LLM spend.
            for doc in docs[:5]:
                log.info(
                    "  sample doc_id=%s source=%s words=%s title=%s",
                    doc.doc_id,
                    doc.source_type,
                    doc.word_count,
                    (doc.title or "")[:70],
                )
            n = await _enqueue_replay(cs_conn, nlp_conn, docs, dry_run=args.dry_run)
            log.info(
                "empty_cohort_enqueued docs=%d dry_run=%s%s",
                n,
                args.dry_run,
                " (NOTHING WRITTEN — dry run)" if args.dry_run else "",
            )
            return 0

        # ── Source-mode shortcut ──────────────────────────────────────────────
        # When operator passes --source-mode eodhd we bypass the per-ticker
        # routing entirely and replay every unprocessed doc of that source.
        # This is the highest-leverage path for long-form articles (EODHD,
        # SEC) that never reached NLP — they will produce far more relations
        # per LLM call than the short Finnhub teasers we already processed.
        if args.source_mode:
            log.info(
                "source_mode_replay source=%s limit=%d",
                args.source_mode,
                args.source_limit,
            )
            docs = await _select_docs_by_source(
                cs_conn,
                nlp_conn,
                args.source_mode,
                args.source_limit,
            )
            log.info(
                "source_mode_selected source=%s docs=%d (avg_words=%s)",
                args.source_mode,
                len(docs),
                sum(d.word_count or 0 for d in docs) // max(1, len(docs)),
            )
            n = await _enqueue_replay(cs_conn, nlp_conn, docs, dry_run=args.dry_run)
            log.info(
                "source_mode_enqueued source=%s docs=%d dry_run=%s",
                args.source_mode,
                n,
                args.dry_run,
            )
            return 0

        for entity_id_str, name, ticker in DEMO_ENTITIES:
            if only_set and ticker not in only_set:
                continue
            if total_enqueued >= args.cluster_cap:
                log.warning("cluster_cap_reached cap=%d", args.cluster_cap)
                break

            entity_id = UUID(entity_id_str)
            remaining = args.cluster_cap - total_enqueued
            limit = min(args.per_ticker, remaining)

            log.info("selecting docs ticker=%s name=%s limit=%d", ticker, name, limit)
            docs = await _select_docs_for_entity(nlp_conn, cs_conn, entity_id, limit)

            if not docs:
                log.warning("no_docs_found ticker=%s entity_id=%s", ticker, entity_id)
                per_ticker_results[ticker] = 0
                continue

            n = await _enqueue_replay(cs_conn, nlp_conn, docs, dry_run=args.dry_run)
            per_ticker_results[ticker] = n
            total_enqueued += n
            log.info(
                "enqueued ticker=%s docs=%d total=%d dry_run=%s",
                ticker,
                n,
                total_enqueued,
                args.dry_run,
            )

        log.info("=" * 60)
        log.info("REPLAY SUMMARY (dry_run=%s)", args.dry_run)
        log.info("=" * 60)
        for ticker, n in per_ticker_results.items():
            log.info("  %-6s  %4d", ticker, n)
        log.info("  %-6s  %4d", "TOTAL", total_enqueued)
        log.info("=" * 60)
        log.info(
            "Next: monitor docker logs of nlp-pipeline-article-consumer-1 + "
            "knowledge-graph-enriched-consumer-1; expect ~1-3s/article extraction. "
            "Re-run the validation query (see Wave I-2 spec) in 5-10 min.",
        )
    finally:
        await cs_conn.close()
        await nlp_conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
