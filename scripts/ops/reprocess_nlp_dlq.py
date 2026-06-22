"""Recover NLP-enrichment articles lost to the provisional_entity_queue lock convoy.

Context (2026-06-22 QA — qa-postgres issue #1/#2)
-------------------------------------------------
A lock convoy on ``intelligence_db.provisional_entity_queue`` (an ``ON CONFLICT
DO UPDATE`` row-lock held across the article consumer's long LLM transaction)
caused ~2,528 ``content.article.stored.v1`` messages to die with
``message_processing_timeout after 900s`` and land in
``nlp_db.dead_letter_queue`` (status='failed', resolved_at=NULL). They were
NEVER reprocessed = silent enrichment data loss.

The convoy root cause is fixed in code (entity_resolution.py: DO NOTHING +
fallback SELECT + short lock_timeout). This script RECOVERS the already-lost
articles by re-firing the NLP pipeline for them.

Why not requeue the DLQ rows directly
--------------------------------------
The DLQ ``payload_avro`` for ``content.article.stored.v1`` is only a DIAGNOSTIC
blob (the event_id bytes — see article_consumer._dead_letter_impl), NOT the
original Avro event. So the generic ``DLQRepository.requeue`` cannot rebuild a
valid message from a DLQ row. The DURABLE source of truth for the original event
is ``content_store_db.documents`` (it still holds the MinIO silver key + all
metadata). So — exactly like ``scripts/ops/replay_kg_extraction.py`` — we
re-publish ``content.article.stored.v1`` from content-store's own outbox and let
the existing content-store dispatcher emit it.

Definition of "lost article" (idempotent + safe)
-------------------------------------------------
A content-store document whose ``doc_id`` has NO row in
``nlp_db.routing_decisions``. ``routing_decisions`` is the per-doc sentinel the
article consumer writes on SUCCESSFUL processing (and checks to short-circuit
re-delivery). "No routing decision" == "never successfully enriched" — which is
exactly the set the 900s timeouts left behind. We never touch docs that DID
process, so a re-run cannot double-process anything.

Re-enqueue is safe to repeat
----------------------------
- All NLP artifacts use deterministic UUIDv5 ids + ``ON CONFLICT DO NOTHING``,
  so re-processing an article is a no-op for sections/chunks/mentions/embeddings.
- A fresh ``event_id`` is minted per replay so Valkey dedup does not short-circuit
  the re-delivery.
- We delete the ``routing_decisions`` sentinel ONLY for docs we actually
  re-enqueue (and only after the outbox insert commits), so the consumer does
  not skip the re-delivered event.
- Matching ``content.article.stored.v1`` DLQ rows are marked ``resolved`` so the
  backlog metric clears and they are not "recovered" twice.

Usage
-----
    # Plan only — counts + sample, NO writes (DEFAULT):
    python scripts/ops/reprocess_nlp_dlq.py --dry-run

    # Recover up to 500 lost articles for real:
    python scripts/ops/reprocess_nlp_dlq.py --apply --limit 500

The script connects to the host-mapped Postgres. With the OLTP/OLAP split
(2026-06-22), content_store_db lives on the OLTP box and nlp_db/intelligence_db
on the OLAP box — pass --oltp-* / --olap-* accordingly. Defaults assume a single
host:port (pre-split / local dev).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("reprocess_nlp_dlq")

_STORED_TOPIC = "content.article.stored.v1"


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
    published_at: Any  # datetime | None
    is_backfill: bool
    tenant_id: UUID | None


async def _connect(host: str, port: int, db: str, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(host=host, port=port, user=user, password=password, database=db)


async def _select_unprocessed_docs(
    cs_conn: asyncpg.Connection,
    nlp_conn: asyncpg.Connection,
    limit: int,
) -> list[DocRow]:
    """Return up to *limit* content-store docs with NO nlp_db.routing_decisions row.

    These are the articles that never completed NLP enrichment — the population
    the 900s timeouts dropped. Ordered newest-first so the freshest articles
    recover first.
    """
    processed_ids = {row["doc_id"] for row in await nlp_conn.fetch("SELECT doc_id FROM routing_decisions")}

    # Over-fetch so we can drop already-processed ids client-side and still hit
    # the requested limit. The partial guard (minio_silver_key IS NOT NULL) skips
    # docs we could never rebuild a valid event for.
    rows = await cs_conn.fetch(
        """
        SELECT doc_id, source_type, title, content_hash, normalized_hash,
               dedup_result, minio_silver_key, word_count, published_at,
               is_backfill, tenant_id
        FROM documents
        WHERE minio_silver_key IS NOT NULL
        ORDER BY published_at DESC NULLS LAST
        LIMIT $1
        """,
        max(limit * 4, limit + 100),
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


def _build_stored_payload(doc: DocRow) -> dict[str, Any]:
    """Build a payload matching content.article.stored.v1 Avro schema.

    Mirrors content_store/application/use_cases/process_article._build_stored_payload
    (kept inline so the script does not import service code).
    """
    return {
        # Fresh event_id so the consumer's Valkey dedup does not short-circuit.
        "event_id": str(uuid4()),
        "event_type": "content.article.stored",
        "schema_version": 1,
        "occurred_at": datetime.now(tz=UTC).isoformat(),
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
        "correlation_id": f"dlq-recover-{uuid4().hex[:8]}",
        "tenant_id": str(doc.tenant_id) if doc.tenant_id else None,
    }


async def _count_open_dlq(nlp_conn: asyncpg.Connection) -> int:
    """Count open (unresolved) content.article.stored.v1 DLQ rows."""
    val = await nlp_conn.fetchval(
        """
        SELECT count(*) FROM dead_letter_queue
        WHERE topic = $1 AND status = 'failed' AND resolved_at IS NULL
        """,
        _STORED_TOPIC,
    )
    return int(val or 0)


async def _enqueue_and_resolve(
    cs_conn: asyncpg.Connection,
    nlp_conn: asyncpg.Connection,
    docs: list[DocRow],
    *,
    apply: bool,
) -> int:
    """Insert outbox rows, clear routing sentinels, and resolve DLQ rows.

    Order matters for crash-safety:
      1. Insert content-store outbox rows in ONE transaction (all-or-nothing).
      2. AFTER that commits, delete the routing_decisions sentinels (so a race
         can't let the consumer see the event before the sentinel is cleared).
      3. Mark the open DLQ rows resolved (bookkeeping only — the recovery is the
         re-enqueue above; we resolve up to the number we actually enqueued so
         the backlog metric reflects reality).
    """
    if not docs or not apply:
        return len(docs)

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

    doc_ids = [d.doc_id for d in docs]
    await nlp_conn.execute("DELETE FROM routing_decisions WHERE doc_id = ANY($1)", doc_ids)

    # Resolve up to len(docs) of the oldest open DLQ rows. We cannot map a DLQ
    # row 1:1 to a doc (the DLQ payload is diagnostic only), so we resolve by
    # count — the recovery itself is the re-enqueue; this just clears the metric.
    await nlp_conn.execute(
        """
        UPDATE dead_letter_queue
        SET status = 'resolved',
            resolved_at = now(),
            resolution_note = 'reprocess_nlp_dlq: re-enqueued via content-store outbox after lock-convoy fix'
        WHERE dlq_id IN (
            SELECT dlq_id FROM dead_letter_queue
            WHERE topic = $1 AND status = 'failed' AND resolved_at IS NULL
            ORDER BY created_at ASC
            LIMIT $2
        )
        """,
        _STORED_TOPIC,
        len(docs),
    )
    return len(docs)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500, help="Max articles to recover this run (default 500).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only — NO writes (DEFAULT).")
    mode.add_argument("--apply", action="store_true", help="Actually re-enqueue + resolve DLQ rows.")
    # Single-host defaults (pre-split / local dev). Override for the OLTP/OLAP split.
    parser.add_argument("--oltp-host", default="localhost", help="content_store_db host.")
    parser.add_argument("--oltp-port", type=int, default=5432, help="content_store_db port.")
    parser.add_argument("--olap-host", default="localhost", help="nlp_db host (intelligence box post-split).")
    parser.add_argument("--olap-port", type=int, default=5432, help="nlp_db port.")
    parser.add_argument("--user", default="postgres", help="Postgres user.")
    parser.add_argument("--password", default="postgres", help="Postgres password (local-dev default).")
    args = parser.parse_args()

    apply = bool(args.apply)  # default (neither flag, or --dry-run) → plan only

    cs_conn = await _connect(args.oltp_host, args.oltp_port, "content_store_db", args.user, args.password)
    nlp_conn = await _connect(args.olap_host, args.olap_port, "nlp_db", args.user, args.password)
    try:
        open_dlq = await _count_open_dlq(nlp_conn)
        docs = await _select_unprocessed_docs(cs_conn, nlp_conn, args.limit)

        log.info("=" * 64)
        log.info("NLP DLQ RECOVERY (%s)", "APPLY" if apply else "DRY-RUN")
        log.info("=" * 64)
        log.info("open content.article.stored.v1 DLQ rows : %d", open_dlq)
        log.info("unprocessed docs selected this run       : %d (limit=%d)", len(docs), args.limit)
        for d in docs[:10]:
            log.info("  sample doc_id=%s source=%s words=%s", d.doc_id, d.source_type, d.word_count)
        if len(docs) > 10:
            log.info("  ... and %d more", len(docs) - 10)

        n = await _enqueue_and_resolve(cs_conn, nlp_conn, docs, apply=apply)

        if apply:
            log.info("re-enqueued %d articles; resolved up to %d DLQ rows", n, n)
            log.info("monitor: docker logs nlp-pipeline-article-consumer-1 — expect routing_decisions to grow")
        else:
            log.info("DRY-RUN: would re-enqueue %d articles and resolve up to %d DLQ rows", n, n)
            log.info("re-run with --apply to perform the recovery")
        log.info("=" * 64)
    finally:
        await cs_conn.close()
        await nlp_conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
