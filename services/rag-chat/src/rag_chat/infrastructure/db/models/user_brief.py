"""SQLAlchemy ORM models for user_briefs and brief_feedback tables (PLAN-0066 Wave A T-W10-A-02).

WHY two models in one file: user_briefs and brief_feedback are tightly coupled
(FK relationship, always imported together) so colocating them avoids circular
import gymnastics between two separate model files.

WHY JSONB: sections_json and citations_json store serialised list[BriefSection]
and list[BriefCitation] respectively. Using JSONB (not TEXT) lets Postgres index,
query, and validate JSON structure if needed. The application layer owns
deserialisation via BriefSection.from_dict / BriefCitation.from_dict.

WHY default=new_uuid7 on id columns: all IDs are generated app-side (Hard Rule
R10). The migration sets NO server_default on these columns, so Postgres will
reject inserts that omit the id rather than silently generating a random UUID4.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from common.ids import new_uuid7  # type: ignore[import-untyped]
from rag_chat.infrastructure.db.models import Base


class UserBriefModel(Base):
    """Persistent record of a generated AI brief (PLAN-0066 Wave A).

    One row per brief generation event. Rows are immutable after creation —
    the brief itself never changes, only associated feedback rows are added.

    Column notes:
      brief_type    — discriminator: 'morning' | 'entity' (extensible, no enum)
      entity_id     — NULL for morning briefs; set for entity-scoped briefs
      sections_json — list[dict] serialised from list[BriefSection]
      citations_json — list[dict] serialised from list[BriefCitation]
      source_version — tracks which prompt/pipeline version produced this brief
    """

    __tablename__ = "user_briefs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=new_uuid7,  # WHY: R10 — app-side UUIDv7, no DB default
    )
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # WHY String(20) not Enum: keeps the migration forward-compatible when new
    # brief_type values are added (just a new string constant, no ALTER TYPE).
    brief_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        # WHY no server_default: caller must supply a UTC-aware datetime via
        # common.time.utc_now() (R11). DB default would silently mask missing values.
    )
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    lead: Mapped[str | None] = mapped_column(Text, nullable=True)
    # WHY JSONB + default=list: Postgres JSONB enables GIN indexing and jsonb_path
    # operators if future queries need to reach inside the JSON structure.
    # Python-side default=list ensures the ORM never inserts NULL.
    sections_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    citations_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    source_version: Mapped[str] = mapped_column(String(10), nullable=False, default="v2", server_default="v2")


class BriefFeedbackModel(Base):
    """User reaction attached to a generated brief (PLAN-0066 Wave A).

    Granularity is controlled by the (scope, section_idx, bullet_idx) triple:
      scope='brief'   → section_idx=None, bullet_idx=None  (whole-brief reaction)
      scope='section' → section_idx=N,    bullet_idx=None  (one section)
      scope='bullet'  → section_idx=N,    bullet_idx=M     (one bullet)

    WHY ON DELETE CASCADE on brief_id: when a brief is deleted (unlikely in
    practice, but possible for privacy compliance / data retention policies),
    all associated feedback rows are removed atomically by Postgres.
    """

    __tablename__ = "brief_feedback"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=new_uuid7,  # WHY: R10 — app-side UUIDv7, no DB default
    )
    brief_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("user_briefs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # WHY String(10) not Enum: same forward-compat reasoning as brief_type above.
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    section_idx: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    bullet_idx: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    reaction: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        # WHY no Python-side default: created_at is always written explicitly by
        # the repository adapter (using common.time.utc_now()) so there is no
        # risk of an omitted value. server_default="now()" is the safety net for
        # any direct SQL inserts (e.g. migrations, admin scripts).
        server_default="now()",
    )
