"""Feedback subsystem repository ports (PLAN-0052 Wave D / T-D-4-03).

These are abstract interfaces. Concrete SQLAlchemy implementations live
in ``portfolio.infrastructure.db.repositories.feedback_*``; in-memory
fakes live in ``tests/unit/fakes.py``.

Why dataclass DTOs (not domain entities): the feedback subsystem is
flat data that is born at the API edge, sanitised, and persisted —
there is no rich domain behaviour, so we skip the domain-entity layer
and pass dataclasses directly. This is the same pattern used by
``OutboxRecord`` and ``IdempotencyRecord`` in
``application/ports/repositories.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from builtins import list as _list
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

# ── DTOs ─────────────────────────────────────────────────────────────────────


@dataclass
class FeedbackSubmissionRecord:
    """In-memory representation of one ``feedback_submissions`` row."""

    id: UUID
    tenant_id: UUID
    user_id: UUID | None
    email: str | None
    kind: str
    severity: str | None
    description: str
    console_logs: Any | None
    screenshot_url: str | None
    page_url: str | None
    user_agent: str | None
    status: str
    tags: list[str]
    assigned_to: UUID | None
    created_at: datetime
    updated_at: datetime
    # REQ-002d: caller-supplied Idempotency-Key (UUID). NULL when the header
    # is absent. Unique per (tenant_id, idempotency_key) when set.
    idempotency_key: UUID | None = None


@dataclass
class NPSScoreRecord:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    score: int
    comment: str | None
    surface: str | None
    created_at: datetime


@dataclass
class FeatureRequestRecord:
    id: UUID
    tenant_id: UUID
    created_by_user_id: UUID | None
    title: str
    description: str
    status: str
    category: str | None
    vote_count: int
    is_public: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class FeatureVoteRecord:
    feature_request_id: UUID
    user_id: UUID
    tenant_id: UUID
    created_at: datetime


@dataclass
class MicroSurveyRecord:
    id: UUID
    tenant_id: UUID
    user_id: UUID | None
    survey_key: str
    response: str
    comment: str | None
    created_at: datetime


@dataclass
class BetaEnrollmentRecord:
    tenant_id: UUID
    user_id: UUID
    enrolled: bool
    programs: list[str] = field(default_factory=list)
    enrolled_at: datetime | None = None
    updated_at: datetime | None = None


# ── Ports ────────────────────────────────────────────────────────────────────


class FeedbackSubmissionRepo(ABC):
    @abstractmethod
    async def add(self, record: FeedbackSubmissionRecord) -> None: ...

    @abstractmethod
    async def get(self, submission_id: UUID, tenant_id: UUID) -> FeedbackSubmissionRecord | None: ...

    @abstractmethod
    async def list(
        self,
        tenant_id: UUID,
        *,
        user_id: UUID | None = None,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[FeedbackSubmissionRecord], int]: ...

    @abstractmethod
    async def update(
        self,
        submission_id: UUID,
        tenant_id: UUID,
        *,
        status: str | None = None,
        tags: _list[str] | None = None,
        assigned_to: UUID | None = None,
    ) -> FeedbackSubmissionRecord | None: ...

    @abstractmethod
    async def delete(self, submission_id: UUID, tenant_id: UUID) -> bool: ...

    @abstractmethod
    async def find_by_idempotency_key(
        self,
        tenant_id: UUID,
        idempotency_key: UUID,
    ) -> FeedbackSubmissionRecord | None:
        """Return the submission created earlier with this idempotency key.

        REQ-002d. Tenant-scoped — anonymous submissions live under the
        platform-support tenant so they have a tenant_id too.
        """
        ...


class NPSScoreRepo(ABC):
    @abstractmethod
    async def add(self, record: NPSScoreRecord) -> None:
        """Persist an NPS score.

        Rate limiting (one per user per 30 days) is enforced primarily in
        ``SubmitNPSScoreUseCase`` via :meth:`find_recent_by_user`. The
        repository ALSO maps any ``IntegrityError`` to ``NPSRateLimitError``
        as belt-and-suspenders against a tiny SELECT-then-INSERT race window.
        """
        ...

    @abstractmethod
    async def find_recent_by_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        since: datetime,
    ) -> NPSScoreRecord | None:
        """Return the most recent NPS row for (tenant, user) since ``since``.

        Used by ``SubmitNPSScoreUseCase`` to enforce the 30-day rate limit
        in the application layer (the original DB-level partial-unique
        index used a non-IMMUTABLE ``now()`` predicate that Postgres rejects).
        """
        ...

    @abstractmethod
    async def aggregate(
        self,
        tenant_id: UUID,
        *,
        days: int = 30,
    ) -> tuple[int, int, int]:
        """Return (promoter_count, passive_count, detractor_count) for the last N days."""
        ...


class FeatureRequestRepo(ABC):
    @abstractmethod
    async def add(self, record: FeatureRequestRecord) -> None: ...

    @abstractmethod
    async def get(self, feature_request_id: UUID, tenant_id: UUID) -> FeatureRequestRecord | None: ...

    @abstractmethod
    async def list(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        category: str | None = None,
        is_public: bool | None = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[FeatureRequestRecord], int]: ...

    @abstractmethod
    async def update(
        self,
        feature_request_id: UUID,
        tenant_id: UUID,
        *,
        status: str | None = None,
        category: str | None = None,
        is_public: bool | None = None,
    ) -> FeatureRequestRecord | None: ...

    @abstractmethod
    async def refresh_vote_count(self, feature_request_id: UUID) -> int:
        """Recompute ``vote_count`` from ``feature_votes`` and persist it."""
        ...


class FeatureVoteRepo(ABC):
    @abstractmethod
    async def upsert(self, record: FeatureVoteRecord) -> bool:
        """Insert a vote; return True if new, False if it already existed."""
        ...

    @abstractmethod
    async def has_voted(self, feature_request_id: UUID, user_id: UUID, tenant_id: UUID) -> bool:
        """True if (feature, user, tenant) has a vote row.

        WHY tenant_id is required: feature_votes carries tenant_id and votes
        are tenant-scoped; omitting the predicate could let a user belonging
        to two tenants probe whether they voted on a feature in the *other*
        tenant by enumerating feature ids (F-Q1-09).
        """
        ...


class MicroSurveyRepo(ABC):
    @abstractmethod
    async def add(self, record: MicroSurveyRecord) -> None: ...


class BetaEnrollmentRepo(ABC):
    @abstractmethod
    async def get(self, tenant_id: UUID, user_id: UUID) -> BetaEnrollmentRecord | None: ...

    @abstractmethod
    async def upsert(self, record: BetaEnrollmentRecord) -> BetaEnrollmentRecord: ...
