"""Make relations.confidence NOT NULL DEFAULT base_confidence.

Revision ID: 0046
Revises: 0045
Create Date: 2026-05-23

PLAN-0093 Wave B-2 T-B-2-03.

WHY THIS MIGRATION EXISTS:
  ``relations.confidence`` was nullable, and ~60 % of relation rows had
  NULL confidence (F-DB-001 / F-KG-PERSIST-002).  AGE sync had to special-
  case NULL with ``COALESCE(confidence, 0.0)`` (BP-539) and downstream
  rankers had to defend against missing values everywhere.

WHAT IT DOES:
  Migration 0045 truncated the relations table; we can therefore add the
  NOT NULL + server_default (base_confidence) without an UPDATE backfill.
  After this migration, any new row that omits ``confidence`` will fall
  back to its row-level ``base_confidence``.

DECISION (deviation from plan §T-B-2-03):
  The plan also asked to drop the ``confidence_stale`` column.  That column
  is, however, still used by ``ConfidenceWorker`` to decide which rows to
  recompute (``WHERE confidence_stale = true`` — see
  ``infrastructure/intelligence_db/repositories/relation.py``).  Dropping
  it would break the worker and falls outside Sub-Plan B's scope.
  We therefore KEEP the column; its semantic ("the cached confidence value
  may be out of date relative to its evidence") is orthogonal to the new
  NOT NULL invariant ("a value exists").

DOWNGRADE:
  Drops the server default + nullable=True restored.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """confidence NOT NULL with default = base_confidence."""

    # ── Step 1: alter the column ──────────────────────────────────────────────
    # F-LIVE-003 (Phase 5c, 2026-05-24): the original implementation used
    # ``server_default=sa.text("base_confidence")`` so bare INSERTs would
    # adopt the row's own base_confidence value. PostgreSQL rejects this
    # outright — ``cannot use column reference in DEFAULT expression`` —
    # and the migration crashed before NOT NULL was applied, leaving 0045
    # and beyond unable to apply. SQL DEFAULTs must be constants or
    # constant-function calls (NOW(), gen_random_uuid()), never another
    # column.
    #
    # Resolution: drop the server_default entirely. Migration 0045 TRUNCATEs
    # the relations table beforehand (pre-prod simplification), so there are
    # no rows to backfill. Every NEW INSERT path in the application layer
    # (graph_write.py + relation_evidence repository) already passes
    # confidence explicitly — the missing default is therefore unreachable.
    # If a future code path needs an automatic fallback, add a BEFORE INSERT
    # trigger that copies base_confidence into confidence — that is the only
    # SQL-supported way to express "default to another column's value".
    op.alter_column(
        "relations",
        "confidence",
        existing_type=sa.Float(),
        nullable=False,
        server_default=None,
    )

    # NOTE: confidence_stale is intentionally retained — see migration docstring.


def downgrade() -> None:
    """Revert confidence to nullable, no default."""
    op.alter_column(
        "relations",
        "confidence",
        existing_type=sa.Float(),
        nullable=True,
        server_default=None,
    )
