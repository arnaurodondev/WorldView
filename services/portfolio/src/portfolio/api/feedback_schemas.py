"""Pydantic v2 schemas for the feedback subsystem (PLAN-0052 Wave D / T-D-4-02).

Kept in a separate module from the existing ``portfolio.api.schemas``
to avoid touching that file's imports during this wave. The feedback
router is the only consumer.

Field length bounds match the audit-spec exactly:
    description: 10-5000 chars
    NPS comment / micro-survey comment: ≤2000 chars
    feature title: 1-200 chars
    feature description: 1-5000 chars
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

# Literal types — single source of truth for enum-style validation.
FeedbackKind = Literal["bug", "feature_request", "ux", "design", "other"]
FeedbackSeverity = Literal["low", "medium", "high", "critical"]
FeedbackStatus = Literal["open", "triaged", "in_progress", "resolved", "closed", "duplicate"]
FeatureStatus = Literal["proposed", "planned", "in_progress", "shipped", "rejected"]
SurveyResponse = Literal["positive", "negative", "neutral"]


# ── Feedback submissions ─────────────────────────────────────────────────────


class FeedbackSubmissionCreate(BaseModel):
    """Request body for ``POST /v1/feedback/submissions``.

    Either ``user_id`` (derived from the JWT) or ``email`` must be set —
    enforced at the route level after JWT extraction. When the request
    arrives unauthenticated, the user must supply an email so we can
    follow up.
    """

    kind: FeedbackKind
    severity: FeedbackSeverity | None = None
    description: str = Field(min_length=10, max_length=5000)
    console_logs: Any | None = None
    screenshot_url: str | None = Field(default=None, max_length=2048)
    email: EmailStr | None = None
    page_url: str | None = Field(default=None, max_length=2048)
    user_agent: str | None = Field(default=None, max_length=512)

    @field_validator("screenshot_url")
    @classmethod
    def _validate_screenshot_url(cls, v: str | None) -> str | None:
        """F-Q1-08: reject ``javascript:`` / ``data:`` / non-https URLs.

        ``screenshot_url`` is rendered by the admin UI; without scheme
        validation a user could store ``javascript:alert(...)`` and trigger
        XSS on admin view. We require https-only as a v1 mitigation; a
        host-allow-list (must match ``settings.feedback_s3_bucket``) is a
        follow-up once the pre-signed PUT upload route exists.
        """
        if v is None:
            return None
        if len(v) > 2048:
            raise ValueError("screenshot_url too long")
        parsed = urlparse(v)
        if parsed.scheme != "https":
            raise ValueError("screenshot_url must use https")
        if not parsed.netloc:
            raise ValueError("screenshot_url must include a host")
        return v


class FeedbackSubmissionResponse(BaseModel):
    """Full response shape — all fields including admin-managed ones."""

    id: UUID
    tenant_id: UUID
    user_id: UUID | None
    email: str | None
    kind: FeedbackKind
    severity: FeedbackSeverity | None
    description: str  # already redacted before persist
    console_logs: Any | None
    screenshot_url: str | None
    page_url: str | None
    user_agent: str | None
    status: FeedbackStatus
    tags: list[str]
    assigned_to: UUID | None
    created_at: datetime
    updated_at: datetime


class FeedbackSubmissionUpdate(BaseModel):
    """Admin-only update payload (PATCH)."""

    status: FeedbackStatus | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    assigned_to: UUID | None = None


class FeedbackListResponse(BaseModel):
    items: list[FeedbackSubmissionResponse]
    total: int


# ── NPS ──────────────────────────────────────────────────────────────────────


class NPSSubmissionCreate(BaseModel):
    score: int = Field(ge=0, le=10)
    comment: str | None = Field(default=None, max_length=2000)
    surface: str | None = Field(default=None, max_length=50)


class NPSSubmissionResponse(BaseModel):
    id: UUID
    score: int
    created_at: datetime


class NPSAggregateResponse(BaseModel):
    promoter_count: int
    passive_count: int
    detractor_count: int
    nps_score: float
    sample_size: int
    period_days: int


# ── Micro-survey ─────────────────────────────────────────────────────────────


class MicroSurveyCreate(BaseModel):
    survey_key: str = Field(min_length=1, max_length=100)
    response: SurveyResponse
    comment: str | None = Field(default=None, max_length=2000)


class MicroSurveyResponseSchema(BaseModel):
    id: UUID
    survey_key: str
    response: SurveyResponse
    created_at: datetime


# ── Feature requests ─────────────────────────────────────────────────────────


class FeatureRequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    category: str | None = Field(default=None, max_length=50)


class FeatureRequestResponse(BaseModel):
    id: UUID
    title: str
    description: str
    status: FeatureStatus
    category: str | None
    vote_count: int
    is_public: bool
    created_at: datetime
    updated_at: datetime
    has_voted: bool  # computed at query time per viewer


class FeatureRequestListResponse(BaseModel):
    items: list[FeatureRequestResponse]
    total: int


class FeatureRequestUpdate(BaseModel):
    """Admin-only payload."""

    status: FeatureStatus | None = None
    category: str | None = Field(default=None, max_length=50)
    is_public: bool | None = None


class FeatureVoteResponse(BaseModel):
    feature_request_id: UUID
    vote_count: int
    has_voted: bool


# ── Beta enrollment ──────────────────────────────────────────────────────────


class BetaEnrollmentResponse(BaseModel):
    enrolled: bool
    programs: list[str]
    enrolled_at: datetime | None
    updated_at: datetime | None


class BetaEnrollmentUpdate(BaseModel):
    enrolled: bool
    programs: list[str] = Field(default_factory=list, max_length=20)
