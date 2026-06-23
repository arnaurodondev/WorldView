"""Bulk re-drive for the STALE outbox/DLQ backlogs (2026-06-22 dead-letter audit).

Scope (this script ONLY — do not confuse with scripts/ops/reprocess_nlp_dlq.py)
-------------------------------------------------------------------------------
This tool re-drives the two backlogs identified in
``docs/audits/2026-06-22-dead-letter-backlog-rootcause.md``:

  (a) ``nlp_db.outbox_events`` rows stuck in ``status='failed'`` (the 815-row
      06-18 incident). These were stranded by BUG-3 (mark_failed → 'failed' but
      claim_batch only selected 'pending'). The CODE fix makes the retry loop
      reachable for NEW failures; this script resets the ALREADY-stranded rows
      back to ``pending`` so the now-healthy dispatcher re-claims and delivers
      them. (``--target nlp-failed``)

  (b) ``content_ingestion_db.dead_letter_queue`` rows (the 606 raw articles
      ``content.article.raw.v1`` and/or the 1,653 Polymarket
      ``market.prediction.v1`` snapshots). These are re-enqueued by inserting a
      fresh ``pending`` outbox row from the preserved ``payload_json`` — mirroring
      the supported ``RetryDLQEntryUseCase.requeue`` — then marking the DLQ row
      resolved. (``--target ci-dlq``)

DISTINCT from ``reprocess_nlp_dlq.py`` which recovers the LIVE nlp
``dead_letter_queue`` ``message_processing_timeout`` rows (the
``content.article.stored.v1`` provisional_entity_queue path, owned by another
agent). That backlog is NOT touched here.

Safety / idempotency
---------------------
- ``--dry-run`` is the DEFAULT. Without ``--apply`` the script only SELECTs and
  prints what WOULD be re-driven (counts + a sample). No writes.
- nlp re-drive: resetting ``failed → pending`` is safe to repeat — the nlp outbox
  ``add()`` uses deterministic event_ids + ``ON CONFLICT DO NOTHING`` and the
  downstream nlp consumers are idempotent, so a re-delivered event is deduped.
  We reset ``retry_count=0`` and ``failed_at=NULL`` so the row gets a clean run.
- ci re-drive: each requeued row gets a FRESH outbox ``id`` (new uuid) and the
  source DLQ row is marked ``resolved`` in the SAME transaction, so a re-run
  cannot double-enqueue the same DLQ row (already-resolved rows are excluded by
  the ``resolved_at IS NULL`` filter). content-store dedup drops duplicates on
  content hash, so even a manual double-run is harmless.
- All writes happen in batches (``--limit``) so the contended Postgres is not
  hammered. Run repeatedly until the printed remaining count reaches 0.

Usage
-----
    # Plan only (DEFAULT) — counts + sample, NO writes:
    python scripts/ops/redrive_outbox_backlog.py --target nlp-failed --dry-run
    python scripts/ops/redrive_outbox_backlog.py --target ci-dlq --topic content.article.raw.v1 --dry-run

    # Re-drive 200 nlp failed outbox rows (oldest first):
    python scripts/ops/redrive_outbox_backlog.py --target nlp-failed --apply --limit 200

    # Re-enqueue 200 raw-article DLQ rows:
    python scripts/ops/redrive_outbox_backlog.py --target ci-dlq \
        --topic content.article.raw.v1 --apply --limit 200

The OLTP/OLAP split (2026-06-22) puts content_ingestion_db on the OLTP box and
nlp_db on the OLAP box. Pass --host/--port for the box that owns the target DB.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from uuid import uuid4

import asyncpg

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("redrive_outbox_backlog")


async def _connect(host: str, port: int, db: str, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(host=host, port=port, user=user, password=password, database=db)


# ── (a) nlp_db.outbox_events  failed → pending ──────────────────────────────


async def _redrive_nlp_failed(conn: asyncpg.Connection, *, limit: int, apply: bool) -> None:
    """Reset stranded nlp outbox ``failed`` rows back to ``pending``."""
    rows = await conn.fetch(
        """
        SELECT topic,
               count(*) AS total,
               count(*) FILTER (WHERE octet_length(payload_avro) > 0) AS recoverable
        FROM outbox_events
        WHERE status = 'failed'
        GROUP BY topic
        ORDER BY total DESC
        """,
    )
    total = sum(int(r["total"]) for r in rows)
    log.info("=" * 64)
    log.info("NLP OUTBOX failed->pending re-drive (%s)", "APPLY" if apply else "DRY-RUN")
    log.info("=" * 64)
    log.info("stranded 'failed' outbox rows: %d total", total)
    for r in rows:
        log.info("  topic=%-32s total=%-5d recoverable(payload>0)=%d", r["topic"], r["total"], r["recoverable"])

    if total == 0:
        log.info("nothing to re-drive.")
        return

    if not apply:
        log.info("DRY-RUN: would reset up to %d rows (oldest-first) to status='pending'", min(limit, total))
        log.info("re-run with --apply --limit N to perform the reset")
        return

    # Reset oldest-first, batched. retry_count=0 + failed_at=NULL gives the row a
    # clean run; only rows with intact payload (octet_length>0) are recoverable.
    await conn.execute(
        """
        WITH batch AS (
            SELECT event_id FROM outbox_events
            WHERE status = 'failed' AND octet_length(payload_avro) > 0
            ORDER BY created_at ASC
            LIMIT $1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE outbox_events o
        SET status = 'pending', retry_count = 0, failed_at = NULL
        FROM batch
        WHERE o.event_id = batch.event_id
        """,
        limit,
    )
    remaining = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE status = 'failed'")
    log.info("reset a batch of up to %d rows to 'pending'; remaining 'failed': %d", limit, int(remaining or 0))
    log.info("monitor: docker logs nlp-pipeline dispatcher — expect outbox_record_dispatched; repeat until 0")


# ── (b) content_ingestion_db.dead_letter_queue  → re-enqueue outbox ─────────


async def _redrive_ci_dlq(conn: asyncpg.Connection, *, topic: str, limit: int, apply: bool) -> None:
    """Re-enqueue content-ingestion DLQ rows by inserting fresh pending outbox rows."""
    counts = await conn.fetchrow(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE payload_json IS NOT NULL) AS replayable
        FROM dead_letter_queue
        WHERE topic = $1 AND resolved_at IS NULL
        """,
        topic,
    )
    total = int(counts["total"] or 0)
    replayable = int(counts["replayable"] or 0)
    log.info("=" * 64)
    log.info("CONTENT-INGESTION DLQ re-enqueue (%s) topic=%s", "APPLY" if apply else "DRY-RUN", topic)
    log.info("=" * 64)
    log.info("open DLQ rows: %d total, %d replayable (payload_json present)", total, replayable)

    sample = await conn.fetch(
        """
        SELECT dlq_id, original_event_id, error_detail
        FROM dead_letter_queue
        WHERE topic = $1 AND resolved_at IS NULL AND payload_json IS NOT NULL
        ORDER BY created_at ASC
        LIMIT 5
        """,
        topic,
    )
    for s in sample:
        log.info("  sample dlq_id=%s orig=%s error=%s", s["dlq_id"], s["original_event_id"], s["error_detail"])

    if replayable == 0:
        log.info("nothing replayable to re-drive.")
        return

    if not apply:
        log.info("DRY-RUN: would re-enqueue up to %d rows and mark them resolved", min(limit, replayable))
        log.info("re-run with --apply --limit N to perform the re-enqueue")
        return

    # Re-enqueue + resolve in ONE transaction so a row is never double-enqueued.
    # The DLQ row preserves payload_json (the canonical event body) + topic, so we
    # reconstruct a pending outbox row from those. aggregate_id/event_type columns
    # are NOT NULL, so derive them from the payload with safe fallbacks.
    async with conn.transaction():
        targets = await conn.fetch(
            """
            SELECT dlq_id, original_event_id, topic, payload_json
            FROM dead_letter_queue
            WHERE topic = $1 AND resolved_at IS NULL AND payload_json IS NOT NULL
            ORDER BY created_at ASC
            LIMIT $2
            FOR UPDATE SKIP LOCKED
            """,
            topic,
            limit,
        )
        for t in targets:
            raw = t["payload_json"]
            payload = json.loads(raw) if isinstance(raw, str) else raw
            aggregate_id = None
            event_type = topic.rsplit(".v", 1)[0]  # e.g. content.article.raw
            if isinstance(payload, dict):
                aggregate_id = payload.get("doc_id") or payload.get("market_id") or payload.get("aggregate_id")
                event_type = payload.get("event_type", event_type)
            await conn.execute(
                """
                INSERT INTO outbox_events
                  (id, aggregate_type, aggregate_id, event_type, topic, payload, status)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, 'pending')
                """,
                uuid4(),
                "redrive",
                aggregate_id or str(uuid4()),
                event_type,
                topic,
                json.dumps(payload),
            )
        dlq_ids = [t["dlq_id"] for t in targets]
        await conn.execute(
            """
            UPDATE dead_letter_queue
            SET resolved_at = now(),
                resolution_note = 'redrive_outbox_backlog: re-enqueued from payload_json (2026-06-22 backlog)'
            WHERE dlq_id = ANY($1)
            """,
            dlq_ids,
        )

    remaining = await conn.fetchval(
        "SELECT count(*) FROM dead_letter_queue WHERE topic = $1 AND resolved_at IS NULL",
        topic,
    )
    log.info("re-enqueued %d rows; remaining open DLQ for topic: %d", len(targets), int(remaining or 0))
    log.info("monitor: docker logs content-ingestion dispatcher — expect outbox_record_published; repeat until 0")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        required=True,
        choices=["nlp-failed", "ci-dlq"],
        help="nlp-failed = reset nlp outbox failed->pending; ci-dlq = re-enqueue content-ingestion DLQ rows.",
    )
    parser.add_argument(
        "--topic",
        default="content.article.raw.v1",
        help="ci-dlq only: which DLQ topic to re-drive (e.g. content.article.raw.v1, market.prediction.v1).",
    )
    parser.add_argument("--limit", type=int, default=200, help="Max rows to re-drive this batch (default 200).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only — NO writes (DEFAULT).")
    mode.add_argument("--apply", action="store_true", help="Actually perform the re-drive.")
    parser.add_argument("--host", default="localhost", help="Postgres host for the target DB.")
    parser.add_argument("--port", type=int, default=5432, help="Postgres port for the target DB.")
    parser.add_argument("--user", default="postgres", help="Postgres user.")
    parser.add_argument("--password", default="postgres", help="Postgres password (local-dev default).")
    args = parser.parse_args()

    apply = bool(args.apply)  # default (neither flag, or --dry-run) → plan only

    if args.target == "nlp-failed":
        conn = await _connect(args.host, args.port, "nlp_db", args.user, args.password)
        try:
            await _redrive_nlp_failed(conn, limit=args.limit, apply=apply)
        finally:
            await conn.close()
    else:  # ci-dlq
        conn = await _connect(args.host, args.port, "content_ingestion_db", args.user, args.password)
        try:
            await _redrive_ci_dlq(conn, topic=args.topic, limit=args.limit, apply=apply)
        finally:
            await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
