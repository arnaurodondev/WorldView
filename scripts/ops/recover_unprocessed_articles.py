"""P0-③ (2026-06-18 deadletter investigation) — recover ALL unprocessed articles.

Goal
----
Recover the ~2,316 articles that were terminally dead-lettered by the
article-consumer watchdog timeout (see
``docs/audits/2026-06-18-article-consumer-timeout-deadletter-investigation.md``).
Those articles produced ZERO ``routing_decisions`` (the whole-article rollback
discarded all partial work) and therefore ZERO entities / relations in the KG.

Why this cannot be driven off the DLQ
--------------------------------------
``_dead_letter_impl`` historically wrote only ``{"event_id":...}`` into
``payload_avro`` (fixed forward by P0-①, but the 2,316 HISTORICAL rows are
already lost stubs).  ``dlq.original_event_id`` is the *article event_id*, which
matches ZERO rows in ``content_store_db.documents.doc_id`` and carries no
``minio_silver_key``.  So the DLQ rows are forensic markers only — they cannot
tell us which document each one was.

The real, durable signature of a lost article is therefore:

    a ``content_store_db.documents`` row (with a ``minio_silver_key``) that has
    NO corresponding ``nlp_db.routing_decisions`` row.

This is exactly what the existing ``replay_kg_extraction.py --source-mode``
selector checks — but that script is ticker/source scoped.  This script
generalises it to "EVERY unprocessed document, regardless of source".

Relationship to ``replay_kg_extraction.py``
--------------------------------------------
``replay_kg_extraction.py`` re-publishes ``content.article.stored.v1`` from
MinIO silver by doc_id (ticker- or source- scoped, demo-edge-density focused).
This script reuses the SAME mechanism (write outbox rows → content-store
dispatcher publishes; delete the routing_decision sentinel so the consumer does
not short-circuit) but its selector is "all docs lacking a routing_decision",
which is the recovery cohort for the timeout bleed.

Idempotency
-----------
- A re-published event gets a FRESH ``event_id`` (consumer dedup is keyed on
  event_id, so reusing one would be short-circuited).
- The routing_decision sentinel is deleted so the consumer reprocesses; every
  other artifact (entity_mentions, embeddings, chunks) writes with deterministic
  UUIDv5 + ``ON CONFLICT DO NOTHING`` so re-running is a no-op for them.
- Running the script twice is safe: once a doc has been reprocessed it gains a
  routing_decision row again and is therefore NO LONGER selected.  A doc that
  is still in-flight (no routing_decision yet) may be re-enqueued, but the
  consumer's event_id dedup + deterministic upserts absorb the duplicate.

Pacing / load-spiral safety
---------------------------
Re-firing thousands of articles at once is exactly the load spiral that CAUSED
the bleed.  This script is built to run in SMALL PACED BATCHES:

    # See the real lost count without writing anything:
    python scripts/ops/recover_unprocessed_articles.py --dry-run

    # Recover a tiny batch (validate end-to-end before scaling up):
    python scripts/ops/recover_unprocessed_articles.py --limit 2

    # The operator paces the rest in small waves, watching GLiNER/extraction load:
    python scripts/ops/recover_unprocessed_articles.py --limit 100

It deliberately has NO "recover everything" default — ``--limit`` is mandatory
in spirit (defaults to a conservative 50) and the operator raises it per wave.

The script connects to host postgres on the docker-mapped port (5432) and
writes outbox rows into ``content_store_db.outbox_events`` exactly like
``replay_kg_extraction.py`` — the same publish path that originally emitted the
events handles the recovery.
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

# WHY stdlib logging: this script lives outside the service tree, so it does not
# get the structlog factory wired by ``observability.configure_logging``.  Using
# stdlib keeps the ops surface zero-dependency.
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("recover_unprocessed_articles")


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
    published_at: Any  # datetime | None — only serialised to ISO string
    is_backfill: bool
    tenant_id: UUID | None


def select_unprocessed_doc_ids(all_doc_ids: set[UUID], processed_doc_ids: set[UUID]) -> set[UUID]:
    """Return doc_ids present in content_store but with NO routing_decision.

    Pure set difference, extracted so the recovery cohort logic can be unit
    tested without a live database.  This is the signature of an article that
    was dead-lettered before it produced any routing_decision (the whole-article
    rollback on the watchdog timeout).

    Args:
        all_doc_ids: every content_store doc_id that has a minio_silver_key.
        processed_doc_ids: every doc_id that already has a routing_decision row.

    Returns:
        The doc_ids that still need recovery.
    """
    return all_doc_ids - processed_doc_ids


async def _connect(host: str, port: int, db: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=host,
        port=port,
        user="postgres",
        password="postgres",  # noqa: S106 — local-dev docker-compose secret
        database=db,
    )


async def _count_unprocessed(cs_conn: asyncpg.Connection, nlp_conn: asyncpg.Connection) -> int:
    """Return the TOTAL number of unprocessed docs (the real lost count).

    Computed independently of ``--limit`` so a dry run reports the full recovery
    backlog even when the operator only intends to enqueue a small wave.  The
    two databases are distinct Postgres catalogs (no cross-db JOIN), so we diff
    the id sets in Python — mirroring ``replay_kg_extraction.py``.
    """
    all_ids = {
        row["doc_id"]
        for row in await cs_conn.fetch(
            "SELECT doc_id FROM documents WHERE minio_silver_key IS NOT NULL",
        )
    }
    processed_ids = {row["doc_id"] for row in await nlp_conn.fetch("SELECT doc_id FROM routing_decisions")}
    return len(select_unprocessed_doc_ids(all_ids, processed_ids))


async def _select_unprocessed_docs(
    cs_conn: asyncpg.Connection,
    nlp_conn: asyncpg.Connection,
    limit: int,
) -> list[DocRow]:
    """Return up to *limit* content_store docs that have NO routing_decision.

    Ordered most-recent-first so a paced run recovers the freshest (most
    useful) articles first.  We over-fetch from content_store then drop the
    already-processed ids in Python (the two databases cannot be JOINed).
    """
    processed_ids = {row["doc_id"] for row in await nlp_conn.fetch("SELECT doc_id FROM routing_decisions")}
    # Over-fetch so that, after dropping already-processed docs, we still have a
    # full batch.  A generous multiplier keeps the query cheap while tolerating a
    # high already-processed ratio.
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
        max(limit * 8, limit + 100),
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


def build_stored_payload(doc: DocRow) -> dict[str, Any]:
    """Build a payload matching the ``content.article.stored.v1`` Avro schema.

    Mirrors ``content_store/application/use_cases/process_article.py`` and
    ``replay_kg_extraction.py._build_stored_payload``.  A FRESH ``event_id`` is
    minted so consumer dedup does not short-circuit the recovery.
    """
    return {
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
        "correlation_id": f"recover-p0-{uuid4().hex[:8]}",
        "tenant_id": str(doc.tenant_id) if doc.tenant_id else None,
    }


async def _enqueue_recovery(
    cs_conn: asyncpg.Connection,
    nlp_conn: asyncpg.Connection,
    docs: list[DocRow],
    *,
    dry_run: bool,
) -> int:
    """Insert outbox rows + delete routing-decision sentinels (atomic per batch)."""
    if not docs:
        return 0
    if dry_run:
        return len(docs)

    # All-or-nothing per batch: a partial failure must not leave routing-decision
    # deletes without their outbox rows (which would strand docs as unprocessed).
    async with cs_conn.transaction():
        for doc in docs:
            payload = build_stored_payload(doc)
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

    # Delete the routing-decision sentinel AFTER the outbox insert commits so the
    # consumer does not short-circuit on the re-delivered event.  Idempotent: a
    # doc with no sentinel deletes zero rows.
    doc_ids = [d.doc_id for d in docs]
    await nlp_conn.execute("DELETE FROM routing_decisions WHERE doc_id = ANY($1)", doc_ids)
    return len(docs)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help=(
            "Max docs to recover in THIS run (default 50 — a conservative wave). "
            "The operator paces multiple small runs to avoid re-creating the "
            "load spiral that caused the bleed."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only — report the FULL lost count and the batch that WOULD be enqueued; write nothing.",
    )
    parser.add_argument("--postgres-host", type=str, default="localhost", help="Postgres host (default localhost).")
    parser.add_argument("--postgres-port", type=int, default=5432, help="Postgres port (default 5432).")
    args = parser.parse_args()

    cs_conn = await _connect(args.postgres_host, args.postgres_port, "content_store_db")
    nlp_conn = await _connect(args.postgres_host, args.postgres_port, "nlp_db")
    try:
        # Always report the FULL backlog so the operator knows how many waves
        # remain, independent of this run's --limit.
        total_lost = await _count_unprocessed(cs_conn, nlp_conn)
        log.info("unprocessed_total=%d (content_store docs with no routing_decision — the real lost count)", total_lost)

        docs = await _select_unprocessed_docs(cs_conn, nlp_conn, args.limit)
        log.info(
            "recovery_batch_selected docs=%d limit=%d (avg_words=%s)",
            len(docs),
            args.limit,
            sum(d.word_count or 0 for d in docs) // max(1, len(docs)),
        )
        for doc in docs[:5]:
            log.info(
                "  sample doc_id=%s source=%s words=%s title=%s",
                doc.doc_id,
                doc.source_type,
                doc.word_count,
                (doc.title or "")[:70],
            )

        n = await _enqueue_recovery(cs_conn, nlp_conn, docs, dry_run=args.dry_run)
        log.info(
            "recovery_enqueued docs=%d remaining=%d dry_run=%s%s",
            n,
            max(0, total_lost - (0 if args.dry_run else n)),
            args.dry_run,
            " (NOTHING WRITTEN — dry run)" if args.dry_run else "",
        )
        if not args.dry_run and n:
            log.info(
                "Next: watch docker logs of nlp-pipeline-article-consumer + knowledge-graph-enriched-consumer; "
                "let this wave drain (no DLQ growth) BEFORE running the next --limit batch.",
            )
    finally:
        await cs_conn.close()
        await nlp_conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
