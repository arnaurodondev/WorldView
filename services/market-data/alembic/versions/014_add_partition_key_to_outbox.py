"""Add ``partition_key`` to ``outbox_events`` (PLAN-0057-followup Wave B).

PLAN-0057-followup Wave B / F-DATA-06 — Outbox Kafka partition key.

WHY THIS MIGRATION:
  The outbox dispatcher (``libs/messaging`` ``BaseOutboxDispatcher``) was
  previously calling ``producer.produce(topic=..., value=...)`` with no
  ``key=``. That left Kafka free to use sticky/round-robin partitioning,
  which BREAKS per-entity ordering for events that share an aggregate id
  (e.g., all ``market.instrument.created`` events for the same
  ``instrument_id`` must arrive in causal order at downstream consumers
  like S7 knowledge-graph).

  Wave B added ``OutboxRecordProtocol.partition_key: str | None`` and made
  the dispatcher pass ``key=partition_key.encode("utf-8")`` to Kafka.
  Each producing service now needs a column to persist the chosen key per
  outbox row.

FORWARD-COMPATIBILITY (R5 / R11):
  - ``partition_key`` is added as nullable TEXT with NO server_default.
  - NULL is the legacy semantic (round-robin partitioning) — events that
    pre-date this migration will continue to dispatch successfully.
  - Producers opt in by passing ``partition_key=`` to ``OutboxEventRepository.create``;
    code paths that don't care about ordering can continue to omit it.

  R11: adding a nullable column with no default is a forward-compatible
  schema change.

IDEMPOTENT:
  ``ADD COLUMN IF NOT EXISTS`` keeps re-runs safe across local dev DBs
  that may be at different states. The downgrade uses ``DROP COLUMN IF
  EXISTS`` so partial application is safe to roll back.

REFERENCE:
  ``docs/audits/2026-05-01-investigation-plan-0057-open-items.md`` §2.2
"""

from __future__ import annotations

from alembic import op

# Revision identifiers — chains after migration 013 to keep linear ordering.
revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WHY raw SQL (vs op.add_column): IF NOT EXISTS makes the migration safely
    # idempotent across local dev DBs that may be at different states. NULL
    # default (no server_default) is intentional — see module docstring.
    op.execute(
        """
        ALTER TABLE outbox_events
        ADD COLUMN IF NOT EXISTS partition_key TEXT
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE outbox_events
        DROP COLUMN IF EXISTS partition_key
        """
    )
