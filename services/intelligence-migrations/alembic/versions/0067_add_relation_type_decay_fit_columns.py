"""Add per-type decay-fit columns to relation_type_registry — PLAN-0123 Wave 1 (PRD-0120).

Revision ID: 0067
Revises: 0066
Create Date: 2026-07-14

Changes (PLAN-0123 Wave 1, task T-A-1-01 / PRD-0120 FR-1):
  relation_type_registry:
    - ADD COLUMN decay_alpha       FLOAT        NULL
    - ADD COLUMN half_life_days    FLOAT        NULL
    - ADD COLUMN alpha_fit_n       INTEGER      NULL
    - ADD COLUMN alpha_fit_method  TEXT         NULL
    - ADD COLUMN alpha_fit_at      TIMESTAMPTZ  NULL

WHY:
  Today every relation type's decay rate (`decay_alpha`) is looked up from the
  6-row `decay_class_config` table via the type's `decay_class` FK — a coarse
  class-level value shared by every type in that class. PRD-0120 fits a
  per-type `decay_alpha` empirically (offline, censored-survival estimation)
  for `TEMPORAL_CLAIM` types, using the class value as an empirical-Bayes prior
  for cold-start/sparse types. This migration adds the storage for that
  per-type override; it does NOT change any lookup behavior by itself — see
  the companion `relation_type_registry.py` repository change (Wave 1,
  task T-A-1-02) that reads `COALESCE(decay_alpha, <class value>)`.

  `half_life_days`, `alpha_fit_n`, `alpha_fit_method`, `alpha_fit_at` are
  provenance columns (readability + auditability of a fitted value) — never
  read by the confidence engine, only by the fitter and observability tooling.

FORWARD-COMPATIBILITY (R11):
  All 5 columns are nullable with NO default. Existing 20+ seed rows get all-
  NULL values after this migration, which is behaviorally identical to today
  (the registry-first/class-fallback lookup falls back to the class value
  whenever `decay_alpha IS NULL`). No backfill required, no row invalidated.

DOWNGRADE:
  Drops all 5 columns. Safe at any time — a NULL-only column set carries no
  data that a downgrade could destroy unless a fit has already been written
  back (Wave 3); dropping the columns simply reverts every type to the
  class-fallback alpha it would have used pre-PRD-0120.

IDEMPOTENT:
  ADD COLUMN IF NOT EXISTS / DROP COLUMN IF EXISTS is safe to re-apply after a
  partially-failed run.

OWNERSHIP (R24):
  This DDL is authored exclusively here, in intelligence-migrations. S7
  (knowledge-graph) keeps ALEMBIC_ENABLED=false and only reads/writes these
  columns through the application code added in Waves 1-3.
"""

from __future__ import annotations

from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade: add the 5 nullable per-type decay-fit columns
# ---------------------------------------------------------------------------

_ADD_DECAY_FIT_COLUMNS = """
ALTER TABLE relation_type_registry
    ADD COLUMN IF NOT EXISTS decay_alpha FLOAT NULL,
    ADD COLUMN IF NOT EXISTS half_life_days FLOAT NULL,
    ADD COLUMN IF NOT EXISTS alpha_fit_n INTEGER NULL,
    ADD COLUMN IF NOT EXISTS alpha_fit_method TEXT NULL,
    ADD COLUMN IF NOT EXISTS alpha_fit_at TIMESTAMPTZ NULL
"""

# ---------------------------------------------------------------------------
# Downgrade: drop the 5 columns
# ---------------------------------------------------------------------------

_DROP_DECAY_FIT_COLUMNS = """
ALTER TABLE relation_type_registry
    DROP COLUMN IF EXISTS alpha_fit_at,
    DROP COLUMN IF EXISTS alpha_fit_method,
    DROP COLUMN IF EXISTS alpha_fit_n,
    DROP COLUMN IF EXISTS half_life_days,
    DROP COLUMN IF EXISTS decay_alpha
"""


def upgrade() -> None:
    op.execute(_ADD_DECAY_FIT_COLUMNS)


def downgrade() -> None:
    op.execute(_DROP_DECAY_FIT_COLUMNS)
