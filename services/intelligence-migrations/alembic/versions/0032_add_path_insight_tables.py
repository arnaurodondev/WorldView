"""Add ``path_insight_jobs`` and ``path_insights`` tables.

Revision ID: 0032
Revises: 0031
Create Date: 2026-05-08

WHY (T-A-02 — PRD-0074 §8.3, §8.4):
  The intelligence layer's PathInsightWorker (Wave E1) needs two tables:

  ``path_insight_jobs`` — a work queue for the worker.  One job is created per
  hub entity by the nightly PathInsightSeeder.  The partial UNIQUE index on
  ``(entity_id) WHERE status IN ('pending','running')`` prevents duplicate jobs
  from racing when the seeder and the worker overlap.

  ``path_insights`` — pre-computed multi-hop opportunity paths, each scored by
  harmonic mean of edge confidences (harmonic_score), entity-type diversity
  reward (diversity_score), path rarity (surprise_score), and an optional
  template-match bonus (0.1 if matched, else 0.0).  The composite_score is
  clamped to 1.0.

  Both tables carry a ``tenant_id UUID NULL`` overlay column.  NULL means
  "shared platform" (visible to all tenants).  Per-tenant enrichment overlay
  is a deferred item tracked in PLAN-0023.

FORWARD-COMPATIBILITY (R5):
  New tables — no existing rows affected.

DOWNGRADE:
  Drops both tables CASCADE.
"""

from __future__ import annotations

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. path_insight_jobs — work queue for PathInsightWorker
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE path_insight_jobs (
    job_id        UUID        NOT NULL DEFAULT new_uuid7(),
    entity_id     UUID        NOT NULL,
    tenant_id     UUID,
    status        TEXT        NOT NULL DEFAULT 'pending'
        CONSTRAINT chk_path_job_status
            CHECK (status IN ('pending', 'running', 'done', 'failed')),
    claimed_by    TEXT,
    claimed_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    paths_found   INT,
    error_text    TEXT,
    retry_count   INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (job_id),
    CONSTRAINT fk_path_insight_job_entity
        FOREIGN KEY (entity_id)
        REFERENCES canonical_entities (entity_id)
        ON DELETE CASCADE
)
""")

    # Claim index: used by workers polling for pending jobs.
    with op.get_context().autocommit_block():
        op.execute("""
CREATE INDEX CONCURRENTLY idx_path_insight_jobs_claim
    ON path_insight_jobs (status, retry_count)
    WHERE status = 'pending'
""")

    # Prevent two active jobs for the same entity at the same time.
    # A second INSERT with status='pending'|'running' for the same entity
    # raises IntegrityError — seeder uses ON CONFLICT to skip gracefully.
    with op.get_context().autocommit_block():
        op.execute("""
CREATE UNIQUE INDEX CONCURRENTLY uq_path_insight_jobs_active
    ON path_insight_jobs (entity_id)
    WHERE status IN ('pending', 'running')
""")

    # -------------------------------------------------------------------------
    # 2. path_insights — pre-computed scored multi-hop paths
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE path_insights (
    insight_id        UUID        NOT NULL DEFAULT new_uuid7(),
    anchor_entity_id  UUID        NOT NULL,
    tenant_id         UUID,
    path_nodes        JSONB       NOT NULL,
    path_edges        JSONB       NOT NULL,
    hop_count         INT         NOT NULL
        CONSTRAINT chk_path_insight_hop_count
            CHECK (hop_count BETWEEN 2 AND 5),
    harmonic_score    FLOAT       NOT NULL,
    diversity_score   FLOAT       NOT NULL,
    surprise_score    FLOAT       NOT NULL,
    template_match    TEXT,
    composite_score   FLOAT       NOT NULL
        CONSTRAINT chk_path_insight_composite_score
            CHECK (composite_score BETWEEN 0.0 AND 1.0),
    llm_explanation   TEXT,
    explanation_model TEXT,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    explanation_at    TIMESTAMPTZ,
    PRIMARY KEY (insight_id),
    CONSTRAINT fk_path_insight_anchor_entity
        FOREIGN KEY (anchor_entity_id)
        REFERENCES canonical_entities (entity_id)
        ON DELETE CASCADE
)
""")

    # Primary query index: GET /entities/{id}/paths ordered by composite_score.
    with op.get_context().autocommit_block():
        op.execute("""
CREATE INDEX CONCURRENTLY idx_path_insights_anchor_score
    ON path_insights (anchor_entity_id, composite_score DESC)
""")

    # Freshness check: used by the seeder to decide when to recompute.
    with op.get_context().autocommit_block():
        op.execute("""
CREATE INDEX CONCURRENTLY idx_path_insights_anchor_freshness
    ON path_insights (anchor_entity_id, computed_at DESC)
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS path_insights CASCADE")
    op.execute("DROP TABLE IF EXISTS path_insight_jobs CASCADE")
