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
# code. Source of truth: scripts/seed_demo_data.py:_FINNHUB_SOURCES.
DEMO_ENTITIES: list[tuple[str, str, str]] = [
    # (entity_id, canonical_name, ticker_for_log)
    ("11111111-0001-7000-8000-000000000001", "Apple Inc.", "AAPL"),
    ("11111111-0002-7000-8000-000000000001", "Microsoft Corporation", "MSFT"),
    ("11111111-0003-7000-8000-000000000001", "NVIDIA Corporation", "NVDA"),
    ("11111111-0004-7000-8000-000000000001", "Amazon.com Inc", "AMZN"),
    ("11111111-0005-7000-8000-000000000001", "Tesla Inc", "TSLA"),
    ("11111111-0006-7000-8000-000000000001", "Alphabet Inc Class A", "GOOGL"),
    ("11111111-0007-7000-8000-000000000001", "Meta Platforms Inc.", "META"),
    ("11111111-0008-7000-8000-000000000001", "JPMorgan Chase & Co", "JPM"),
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
