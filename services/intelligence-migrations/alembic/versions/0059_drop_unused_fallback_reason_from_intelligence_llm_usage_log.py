"""Drop the unused ``fallback_reason`` from intelligence_db.llm_usage_log (fixes 0058).

Revision ID: 0059
Revises: 0058
Create Date: 2026-06-16

WHY THIS MIGRATION EXISTS (corrective forward-fix for 0058, Task #36):
  Revision 0058 added ``fallback_reason`` to intelligence_db.llm_usage_log on the
  rationale that the knowledge-graph service owns an ``llm_usage_log`` there and the
  audit column should be "consistent across both usage-log tables." In practice the
  extraction 429-fallback feature writes ONLY nlp_db.llm_usage_log (nlp-pipeline
  migration 0022 + the DeepSeekExtractionAdapter audit path). NO active code writes
  ``fallback_reason`` to the intelligence_db table — the knowledge-graph usage-log
  writer was not changed by Task #36 — so the 0058 column is dead schema on the
  shared intelligence_db.

  We do NOT rewrite history (0058 is already applied in environments). Instead this
  forward migration drops the unused column. If a KG-side extraction path later
  adopts the fallback adapter, re-add the column in a new revision at that point.

ADDITIVE-SAFE / FORWARD-COMPATIBLE (Hard Rule 11): drops a NULLABLE column that no
  code reads or writes. Existing rows are unaffected (the column held only NULLs).
  Idempotent: guarded so re-running on an environment that never had 0058's column
  (or already dropped it) is a no-op rather than an error.
"""

from __future__ import annotations

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF EXISTS so the drop is idempotent across environments (e.g. one that
    # applied 0058 then this, vs a fresh DB that never materialised the column).
    op.execute('ALTER TABLE llm_usage_log DROP COLUMN IF EXISTS fallback_reason')


def downgrade() -> None:
    # Restore 0058's column (nullable) so downgrading this revision returns the
    # schema to the post-0058 state.
    op.execute('ALTER TABLE llm_usage_log ADD COLUMN IF NOT EXISTS fallback_reason TEXT')
