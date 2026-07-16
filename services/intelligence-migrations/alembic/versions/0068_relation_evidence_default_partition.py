"""Add a DEFAULT catch-all partition to relation_evidence — evidence-promoter unblock.

Revision ID: 0068
Revises: 0067
Create Date: 2026-07-16

WHY THIS MIGRATION EXISTS (prod data-quality review 2026-07-15, item: evidence
promoter drain ~0.2%):
  ``relation_evidence`` is RANGE-partitioned by ``evidence_date`` with monthly
  partitions created in migration 0001 — but ONLY for calendar years 2024, 2025
  and 2026 (``relation_evidence_2024_01`` … ``relation_evidence_2026_12``). Any
  row whose ``evidence_date`` falls OUTSIDE that window has no partition to land
  in, so the INSERT raises:

      asyncpg.exceptions.CheckViolationError: no partition of relation
      "relation_evidence" found for row
      DETAIL: Partition key of the failing row contains (evidence_date) = (2018-07-31 ...)

  Worker 13B (``RelationEvidencePromoterWorker``) promotes a batch of up to 200
  raw rows inside a SINGLE transaction ordered FIFO by ``extracted_at``. SEC-EDGAR
  filings carry historical filing dates (observed span 2018-03-31 … 2026-07-31),
  so as soon as the batch reaches one pre-2024 row the whole transaction rolls
  back and the run crashes (``relation_evidence_promoter_error`` /
  ``kg_worker_crashed``). Because the poison rows sit at the FRONT of the FIFO
  queue, EVERY subsequent run hits the same rows and rolls back — the promoter is
  permanently wedged. Live prod at review time: 48 promoted vs 4785 non-provisional
  rows that have a matching relation and pass the E-3 confidence gate (4748/4785
  have extraction_confidence >= 0.70). The quality gate is NOT the bottleneck; the
  missing partition is.

WHAT THIS MIGRATION ADDS:
  A single DEFAULT partition ``relation_evidence_default``. In a RANGE-partitioned
  table the DEFAULT partition receives any row whose key matches no other
  partition's bounds. This makes the INSERT total (no key value is ever
  unroutable), so the promoter can drain the historical SEC-filing backlog and can
  never again crash a whole batch on an out-of-window date. It also closes the
  looming FUTURE gap: the highest monthly partition ends at 2027-01-01, so from
  2027-01 onward new evidence would have crashed the promoter the same way — the
  DEFAULT partition covers that too.

WHY THIS IS REGRESSION-SAFE (R11 forward-compat):
  A DEFAULT partition only ever claims rows that NO existing monthly partition
  wants; routing of every in-window (2024-2026) date is completely unchanged. It
  adds no columns, no constraints, and no default values to existing rows.

  OPERATIONAL CAVEAT — the DEFAULT-partition attach trap (READ THIS):
  Postgres refuses to CREATE/ATTACH a new range partition whenever the DEFAULT
  partition already holds a row that would belong in the new range (it raises
  "updated partition constraint for default partition ... would be violated by
  some row" and rolls the statement back). This platform DOES create monthly
  partitions at RUNTIME, not only in migrations: knowledge-graph Workers 13G/13H
  (``infrastructure/workers/partitions.py``, MonthlyPartitionWorker /
  YearlyPartitionWorker) run at startup and on a schedule and issue
  ``CREATE TABLE ... PARTITION OF relation_evidence FOR VALUES FROM ... TO ...``
  for the current + next 2 months. So the trap is a live code path, not a purely
  hypothetical one.

  Why it does not fire in practice today: MonthlyPartitionWorker only creates
  partitions FORWARD (current month + 2) and prunes anything older than 24 months,
  while the rows that actually land in DEFAULT are historical SEC-EDGAR filing
  dates (observed 2018-2023, all in the PAST). The worker never attempts to create
  a 2018-2023 partition, so those DEFAULT rows can never collide with a create.
  Forward months are always created ~2 months ahead of any row arriving, so their
  partitions exist before a row could fall into DEFAULT for that month.

  Two residual risks a future maintainer must keep in mind:
    1. Latent wedge: if a row with a FUTURE evidence_date ever lands in DEFAULT
       before its monthly partition is created (worker downtime spanning a month
       boundary, or genuinely future-dated evidence), MonthlyPartitionWorker.run()
       will fail to create that month's partition and — because it creates 3 months
       + prunes in ONE transaction — roll back the whole cycle every run, silently
       wedging partition maintenance (the same poison-batch shape as the original
       promoter bug). Mitigation if this ever occurs: move the conflicting rows out
       of DEFAULT into a standalone table first, then let the worker create the
       partition (or make the worker create each partition in its own transaction
       and treat the default-conflict as non-fatal).
    2. Retention leak: ``_prune_old_monthly_partitions`` only drops
       ``relation_evidence_YYYY_MM`` partitions; it never touches DEFAULT, so the
       out-of-window historical rows now retained in DEFAULT are exempt from the
       24-month retention policy and accumulate indefinitely (currently ~374 rows —
       negligible, but unbounded in principle).
  Any future backfill of dedicated monthly partitions for a range that DEFAULT
  already holds MUST move the matching rows out of DEFAULT first (authored as its
  own migration).

IDEMPOTENT:
  ``CREATE TABLE IF NOT EXISTS ... PARTITION OF ... DEFAULT`` is safe to re-apply.

OWNERSHIP (R24):
  This DDL is authored exclusively here, in intelligence-migrations. S6/S7 keep
  ALEMBIC_ENABLED=false.

DOWNGRADE:
  Detaches and drops the DEFAULT partition. The DETACH runs first so any
  out-of-window rows the partition holds are preserved in a standalone table the
  operator can inspect/re-home rather than being silently dropped.
"""

from __future__ import annotations

from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade: attach a DEFAULT catch-all partition
# ---------------------------------------------------------------------------

_CREATE_DEFAULT_PARTITION = """
CREATE TABLE IF NOT EXISTS relation_evidence_default
    PARTITION OF relation_evidence DEFAULT
"""


def upgrade() -> None:
    op.execute(_CREATE_DEFAULT_PARTITION)


# ---------------------------------------------------------------------------
# Downgrade: detach (preserve rows) then drop the standalone table
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # DETACH keeps the out-of-window rows in a standalone table rather than
    # destroying them; the operator can inspect relation_evidence_default before
    # dropping. If the table is genuinely empty this is a no-op detach + drop.
    op.execute("ALTER TABLE relation_evidence DETACH PARTITION relation_evidence_default")
    op.execute("DROP TABLE IF EXISTS relation_evidence_default")
