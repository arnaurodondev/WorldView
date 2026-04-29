"""Create feedback subsystem tables (PLAN-0052 Wave D / T-D-4-01).

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-29

Adds 6 tables to portfolio_db that back the feedback subsystem
(in-app feedback modal, NPS, micro-surveys, public feature roadmap,
beta program enrolment). Decision D-3 from
``docs/audits/2026-04-28-qa-frontend-design-roadmap.md``: extend
portfolio_db rather than spinning up a new feedback service.

All tables are tenant-scoped — every row carries ``tenant_id`` and is
queried with a ``WHERE tenant_id = :tid`` predicate at the repository
layer.

Idempotency:
    The ``upgrade()`` function uses an inspector check so re-applying
    the migration on a dev DB that already created the tables is a
    no-op (matches BP-128 dev-rebuild contract).

NPS rate limit (F-Q1-01 fix):
    The original migration tried a partial unique index with
    ``WHERE created_at > now() - INTERVAL '30 days'`` but Postgres
    rejects ``now()`` in index predicates (must be IMMUTABLE). We now
    enforce the 30-day-per-(tenant,user) rate limit in the use case
    layer (SubmitNPSScoreUseCase) via a SELECT-then-INSERT, backed by
    a non-unique composite index for fast lookup. The repository keeps
    a try/except IntegrityError → NPSRateLimitError mapping in case
    a race slips through (belt-and-suspenders, harmless if redundant).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Composite index name for the NPS rate-limit lookup. The 30-day predicate
# is enforced in the use case layer, not the index (now() is not IMMUTABLE
# in Postgres → cannot live in an index predicate).
_NPS_RECENT_INDEX = "ix_nps_scores_user_recent"


def _table_exists(inspector: sa.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1. feedback_submissions ────────────────────────────────────────────────
    if not _table_exists(inspector, "feedback_submissions"):
        op.create_table(
            "feedback_submissions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            # user_id is nullable so anonymous feedback (with email) can land here.
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("email", sa.String(320), nullable=True),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("severity", sa.String(20), nullable=True),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("console_logs", postgresql.JSONB, nullable=True),
            sa.Column("screenshot_url", sa.Text, nullable=True),
            sa.Column("page_url", sa.Text, nullable=True),
            sa.Column("user_agent", sa.Text, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'open'")),
            sa.Column(
                "tags",
                postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "kind IN ('bug','feature_request','ux','design','other')",
                name="ck_feedback_submissions_kind",
            ),
            sa.CheckConstraint(
                "severity IS NULL OR severity IN ('low','medium','high','critical')",
                name="ck_feedback_submissions_severity",
            ),
            sa.CheckConstraint(
                "status IN ('open','triaged','in_progress','resolved','closed','duplicate')",
                name="ck_feedback_submissions_status",
            ),
        )
        op.create_index(
            "ix_feedback_submissions_tenant_created",
            "feedback_submissions",
            ["tenant_id", sa.text("created_at DESC")],
        )
        op.create_index(
            "ix_feedback_submissions_tenant_status",
            "feedback_submissions",
            ["tenant_id", "status"],
        )
        op.create_index(
            "ix_feedback_submissions_tenant_kind",
            "feedback_submissions",
            ["tenant_id", "kind"],
        )

    # ── 2. nps_scores ──────────────────────────────────────────────────────────
    if not _table_exists(inspector, "nps_scores"):
        op.create_table(
            "nps_scores",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("score", sa.SmallInteger, nullable=False),
            sa.Column("comment", sa.Text, nullable=True),
            sa.Column("surface", sa.String(50), nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint("score BETWEEN 0 AND 10", name="ck_nps_scores_range"),
        )
        op.create_index(
            "ix_nps_scores_tenant_created",
            "nps_scores",
            ["tenant_id", sa.text("created_at DESC")],
        )
        # Non-unique composite index for the use-case-layer rate-limit lookup
        # (SubmitNPSScoreUseCase queries
        # ``WHERE tenant_id=:tid AND user_id=:uid AND created_at > :cutoff``
        # and short-circuits with NPSRateLimitError if any row matches).
        # See module docstring for why we don't enforce this at the index level.
        op.create_index(
            _NPS_RECENT_INDEX,
            "nps_scores",
            ["tenant_id", "user_id", sa.text("created_at DESC")],
            unique=False,
        )

    # ── 3. feature_requests ────────────────────────────────────────────────────
    if not _table_exists(inspector, "feature_requests"):
        op.create_table(
            "feature_requests",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'proposed'"),
            ),
            sa.Column("category", sa.String(50), nullable=True),
            sa.Column("vote_count", sa.Integer, nullable=False, server_default=sa.text("0")),
            sa.Column("is_public", sa.Boolean, nullable=False, server_default=sa.text("true")),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "status IN ('proposed','planned','in_progress','shipped','rejected')",
                name="ck_feature_requests_status",
            ),
        )
        op.create_index(
            "ix_feature_requests_tenant_status",
            "feature_requests",
            ["tenant_id", "status"],
        )
        op.create_index(
            "ix_feature_requests_tenant_votes",
            "feature_requests",
            ["tenant_id", sa.text("vote_count DESC")],
        )

    # ── 4. feature_votes ───────────────────────────────────────────────────────
    if not _table_exists(inspector, "feature_votes"):
        op.create_table(
            "feature_votes",
            sa.Column(
                "feature_request_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("feature_requests.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("feature_request_id", "user_id", name="pk_feature_votes"),
        )
        op.create_index(
            "ix_feature_votes_tenant",
            "feature_votes",
            ["tenant_id"],
        )

    # ── 5. micro_survey_responses ──────────────────────────────────────────────
    if not _table_exists(inspector, "micro_survey_responses"):
        op.create_table(
            "micro_survey_responses",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("survey_key", sa.String(100), nullable=False),
            sa.Column("response", sa.String(20), nullable=False),
            sa.Column("comment", sa.Text, nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.CheckConstraint(
                "response IN ('positive','negative','neutral')",
                name="ck_micro_survey_responses_response",
            ),
        )
        op.create_index(
            "ix_micro_survey_responses_tenant_key_created",
            "micro_survey_responses",
            ["tenant_id", "survey_key", sa.text("created_at DESC")],
        )

    # ── 6. beta_enrollments ────────────────────────────────────────────────────
    if not _table_exists(inspector, "beta_enrollments"):
        op.create_table(
            "beta_enrollments",
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("enrolled", sa.Boolean, nullable=False, server_default=sa.text("true")),
            sa.Column(
                "programs",
                postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "enrolled_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("tenant_id", "user_id", name="pk_beta_enrollments"),
        )


def downgrade() -> None:
    # Drop in reverse-dependency order: feature_votes references feature_requests.
    op.execute("DROP TABLE IF EXISTS beta_enrollments")
    op.execute("DROP TABLE IF EXISTS micro_survey_responses")
    op.execute("DROP TABLE IF EXISTS feature_votes")
    op.execute("DROP TABLE IF EXISTS feature_requests")
    op.execute(f"DROP INDEX IF EXISTS {_NPS_RECENT_INDEX}")
    op.execute("DROP TABLE IF EXISTS nps_scores")
    op.execute("DROP TABLE IF EXISTS feedback_submissions")
