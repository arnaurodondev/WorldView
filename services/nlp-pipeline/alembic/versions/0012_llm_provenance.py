"""LLM provenance — append-only document_source_llm_scores + AIW provenance columns.

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-30

PLAN-0055 Sub-Plan C-1.

Why: ``ArticleRelevanceScoringWorker`` and ``PriceImpactLabellingWorker`` currently
overwrite values in ``document_source_metadata`` and ``article_impact_windows`` on
every run. Re-scoring with a new model (or fixing a prompt) silently destroys the
prior model's output — there's no way to audit *which* model produced a score, or
roll back a bad rollout without re-fetching every article.

This migration introduces:

  1. ``document_source_llm_scores`` — append-only, one row per
     ``(doc_id, score_type, model_id, prompt_version)``. The latest row wins;
     historical rows are kept for audit + replay.

  2. Provenance columns (``model_id``, ``prompt_version``, ``input_hash``) on
     ``article_impact_windows`` so the same audit trail extends to price-impact
     scores. The existing UNIQUE INDEX on ``(article_id, entity_id, window_type)``
     is dropped and replaced by a UNIQUE CONSTRAINT that includes the model and
     prompt — letting two different models score the same window.

Forward-compatibility (BP-126):
  - All new columns are nullable on the existing AIW table → no server_default
    needed and existing rows survive the migration.
  - The new ``document_source_llm_scores`` table is brand-new; legacy readers
    are unaffected until Wave C-3 wires the materialized view.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

# revision identifiers
revision: str = "0012"
down_revision: str = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. document_source_llm_scores ─────────────────────────────────────────
    # Append-only ledger. Worker INSERTs ON CONFLICT DO NOTHING so duplicate
    # scoring of the same (doc, type, model, prompt) is a no-op without raising.
    op.create_table(
        "document_source_llm_scores",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("doc_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("score_type", sa.String(32), nullable=False),
        sa.Column("score_value", sa.Numeric(6, 4), nullable=True),
        sa.Column("score_label", sa.String(32), nullable=True),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "doc_id",
            "score_type",
            "model_id",
            "prompt_version",
            name="uq_dsls_dedup",
        ),
        sa.CheckConstraint(
            "score_type IN ('relevance', 'sentiment', 'impact_label')",
            name="ck_dsls_score_type",
        ),
    )
    op.create_index("ix_dsls_doc", "document_source_llm_scores", ["doc_id"])
    # Composite index for the materialized view's DISTINCT ON (doc_id, score_type)
    # ORDER BY generated_at DESC scan — picks "latest score per doc per type" in O(log n).
    op.create_index(
        "ix_dsls_doc_score_latest",
        "document_source_llm_scores",
        ["doc_id", "score_type", sa.text("generated_at DESC")],
    )

    # ── 2. article_impact_windows: provenance columns ────────────────────────
    op.add_column("article_impact_windows", sa.Column("model_id", sa.String(128), nullable=True))
    op.add_column("article_impact_windows", sa.Column("prompt_version", sa.String(32), nullable=True))
    op.add_column("article_impact_windows", sa.Column("input_hash", sa.String(64), nullable=True))

    # ── 3. article_impact_windows: swap UNIQUE INDEX for UNIQUE CONSTRAINT ───
    # Migration 0009 created a UNIQUE INDEX (not constraint) named
    # idx_article_impact_windows_unique. drop_constraint() would fail; must use
    # drop_index() — see plan §1 codebase verification table.
    op.drop_index("idx_article_impact_windows_unique", table_name="article_impact_windows")
    op.create_unique_constraint(
        "uq_article_impact_windows_dedup",
        "article_impact_windows",
        ["article_id", "entity_id", "window_type", "model_id", "prompt_version"],
    )


def downgrade() -> None:
    # Restore the original UNIQUE INDEX on (article_id, entity_id, window_type).
    op.drop_constraint("uq_article_impact_windows_dedup", "article_impact_windows", type_="unique")
    op.create_index(
        "idx_article_impact_windows_unique",
        "article_impact_windows",
        ["article_id", "entity_id", "window_type"],
        unique=True,
    )
    op.drop_column("article_impact_windows", "input_hash")
    op.drop_column("article_impact_windows", "prompt_version")
    op.drop_column("article_impact_windows", "model_id")

    op.drop_index("ix_dsls_doc_score_latest", table_name="document_source_llm_scores")
    op.drop_index("ix_dsls_doc", table_name="document_source_llm_scores")
    op.drop_table("document_source_llm_scores")
