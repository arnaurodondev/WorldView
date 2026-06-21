"""Add ``promoted_at`` promotion marker to relation_evidence_raw (promoter hot-path).

Revision ID: 0061
Revises: 0060
Create Date: 2026-06-21

WHY THIS MIGRATION EXISTS:
  Worker 13B (``RelationEvidencePromoterWorker``) runs every 5 minutes and
  promotes eligible ``relation_evidence_raw`` rows into the immutable
  ``relation_evidence`` table.  Until now the worker had NO durable marker for
  "this raw row has already been promoted".  It re-detected promotion state on
  every run with a correlated ``NOT EXISTS`` anti-join against
  ``relation_evidence`` keyed on (relation_id, doc_id, evidence_date).

  Because that anti-join is evaluated for EVERY non-provisional raw row on
  EVERY run, the worker re-scanned the *entire already-promoted backlog* — on
  the live dev instance that was 81,769 rows already present in
  ``relation_evidence`` — only to promote 0 new rows.  A live capture showed a
  single 5-minute run staying alive 7.5-12+ minutes and ultimately dying with
  ``ConnectionDoesNotExistError`` (connection closed mid-operation), pinning the
  shared Postgres instance and starving the UI-facing OLTP databases
  (the "UI-timeout incident").

  NOTE: the ``processed`` boolean already on this table is NOT a promotion
  marker.  It is owned by Worker 13A (``ConfidenceWorker``), which sets it after
  recomputing a triple's confidence score.  On live data ALL 82,380
  non-provisional rows are ``processed = true`` yet only ~81,769 are actually
  promoted — so ``processed`` cannot be reused to gate promotion without
  breaking the confidence worker.  Hence a dedicated marker.

WHAT THIS MIGRATION ADDS:
  1. ``promoted_at TIMESTAMPTZ NULL`` column.  NULL = not yet promoted; a
     timestamp = the row was promoted into ``relation_evidence`` at that time.
     The promoter now sets this in the same transaction as the INSERT and
     filters ``promoted_at IS NULL`` in ``_FETCH_SQL`` so each run scans only
     UNpromoted rows.
  2. ``idx_raw_evidence_unpromoted`` — partial btree on (extracted_at) WHERE
     ``promoted_at IS NULL AND entity_provisional = false``.  Mirrors the
     existing ``idx_raw_evidence_unprocessed`` (which keys off ``processed``)
     but for the promotion dimension, so the FIFO ``ORDER BY extracted_at``
     scan touches only the small unpromoted frontier.

BACKFILL (the critical part):
  Every existing raw row that is ALREADY in ``relation_evidence`` is stamped
  ``promoted_at = now()`` so the worker does not re-promote / re-scan it on its
  first post-deploy run.  "Already promoted" is determined with EXACTLY the
  same key the promoter's anti-join used:
    (relation matched on triple) AND
    EXISTS row in relation_evidence on (relation_id, doc_id, evidence_date).
  Rows that are gated by the E-3 quality gate, orphaned (no matching relation),
  or provisional are correctly left with ``promoted_at = NULL`` so they remain
  eligible for future promotion once corroborating evidence accumulates.

WHY plain SQL (no CONCURRENTLY):
  ``relation_evidence_raw`` is an ordinary (non-partitioned) heap.  worldview's
  intelligence-migrations are applied serially by a one-shot init container at
  deploy time (BP-393 / 0029 / 0033 / 0049), where plain
  ``ADD COLUMN IF NOT EXISTS`` + ``CREATE INDEX IF NOT EXISTS`` is the
  established convention: transactional, idempotent on re-run, and avoids the
  ``autocommit_block()`` ceremony CONCURRENTLY requires.

IDEMPOTENCY:
  ``ADD COLUMN IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS`` and a backfill
  UPDATE that only touches rows still ``promoted_at IS NULL`` — safe to re-run
  against a DB that already has the column/index/backfill (e.g. a stale volume).

DOWNGRADE:
  Drops the index and the column.  The promoter reverts to the anti-join-only
  behaviour (slow, but correct).
"""

from __future__ import annotations

from alembic import op

revision: str = "0061"
down_revision: str = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Promotion marker column.  NULL = not yet promoted.
    op.execute(
        """
        ALTER TABLE relation_evidence_raw
            ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ
        """
    )

    # 2. Partial index serving the promoter's FIFO unpromoted scan
    #    (ORDER BY extracted_at, filtered to the unpromoted frontier).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_evidence_unpromoted
            ON relation_evidence_raw (extracted_at)
            WHERE promoted_at IS NULL AND entity_provisional = false
        """
    )

    # 3. Backfill: stamp every raw row that is ALREADY in relation_evidence so
    #    the worker does not re-scan the already-promoted backlog on first run.
    #    The EXISTS key (relation_id via triple JOIN, doc_id, evidence_date) is
    #    identical to the promoter's original NOT EXISTS anti-join, so this
    #    marks exactly the set the worker used to (re-)detect as "promoted".
    #
    #    Only rows still NULL are touched, keeping the migration idempotent on
    #    re-run.  Provisional / orphan / quality-gated rows stay NULL and remain
    #    eligible for future promotion.
    op.execute(
        """
        UPDATE relation_evidence_raw rer
        SET promoted_at = now()
        FROM relations r
        WHERE rer.promoted_at IS NULL
          AND rer.entity_provisional = false
          AND r.subject_entity_id = rer.subject_entity_id
          AND r.object_entity_id  = rer.object_entity_id
          AND r.canonical_type    = rer.canonical_type
          AND EXISTS (
              SELECT 1 FROM relation_evidence re
              WHERE re.relation_id   = r.relation_id
                AND re.doc_id        = rer.source_document_id
                AND re.evidence_date = rer.evidence_date
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_raw_evidence_unpromoted")
    op.execute("ALTER TABLE relation_evidence_raw DROP COLUMN IF EXISTS promoted_at")
