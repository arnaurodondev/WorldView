"""ORM model registry for rag-chat service (T-D-2-01)."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all rag-chat ORM models."""


from rag_chat.infrastructure.db.models.message import MessageModel  # noqa: E402
from rag_chat.infrastructure.db.models.thread import ThreadModel  # noqa: E402
from rag_chat.infrastructure.db.models.user_brief import BriefFeedbackModel, UserBriefModel  # noqa: E402

__all__ = [
    "Base",
    "BriefFeedbackModel",
    "MessageModel",
    "ThreadModel",
    "UserBriefModel",
]
