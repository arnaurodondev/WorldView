"""Pydantic request/response schemas for the RAG-Chat API (T-D-4-02, T-F-4-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# F-ARCH-001 (QA-PLAN-0093 iter-9): PublicBriefingResponse moved to the
# application layer so the morning-brief pre-generation worker can import it
# without violating LAYER-APP-ISOLATION (R25). Re-exported here so all API
# routes, tests, and external callers continue to import it from this module.
from rag_chat.application.schemas import (
    PublicBriefingResponse,
    _coerce_sections_to_dicts,
)

# WHY import from domain: BriefCitation/BriefBullet/BriefSection are domain
# value objects used by the application-layer use case (generate_briefing.py).
# Defining them here would force the use case to import from api (LAYER-APP-
# ISOLATION violation). We re-export them so API routes that use them in
# BriefingResponse/PublicBriefingResponse continue to work unchanged.
#
# PLAN-0083 Wave A: BriefCitation/BriefBullet/BriefSection are now frozen
# dataclasses (not Pydantic models). Pydantic response models below declare
# ``sections`` as ``list[dict[str, Any]]`` and use a ``field_validator`` to
# coerce dataclass instances to dicts via ``to_dict()`` (Pattern 1 in
# PLAN-0083 §3 — preferred over arbitrary_types_allowed metaclass tricks).
# This keeps ``model_dump_json()`` / ``model_validate_json()`` working as
# JSON-only round-trips, which is the path used by the Valkey cache writer
# and reader in routes/public_briefings.py.
from rag_chat.domain.brief import BriefBullet, BriefCitation, BriefSection

__all__ = [
    "BriefBullet",
    "BriefCitation",
    "BriefSection",
    "PublicBriefingResponse",
]


# NOTE: ``_normalize_legacy_citation_keys`` and ``_coerce_sections_to_dicts``
# are imported above from ``rag_chat.application.schemas`` (F-ARCH-001 move).


# ── Request schemas ───────────────────────────────────────────────────────────


class EntityContextChatRequest(BaseModel):
    """Request body for POST /api/v1/chat/entity-context (PLAN-0074 Wave F).

    R14: This endpoint is proxied by S9 in Wave G — frontend never calls S8 directly.
    """

    entity_id: UUID
    question: str = Field(..., min_length=1, max_length=2000)
    conversation_id: UUID | None = None  # WHY alias: maps to thread_id in ChatRequest
    include_graph_context: bool = True

    @field_validator("question", mode="before")
    @classmethod
    def _strip_html_and_validate(cls, v: Any) -> str:
        """Strip all HTML tags, validate length, raise on empty.

        §12: HTML strip via bleach.clean() is applied here (API layer) so the
        use case always receives clean text. This mirrors the InputValidator
        behaviour for the standard /api/v1/chat endpoint (Wave E-1).
        bleach is already a declared dependency of this service (pyproject.toml).
        """
        import bleach  # type: ignore[import-untyped]

        stripped: str = str(bleach.clean(str(v), tags=[], strip=True)).strip()
        if not stripped:
            raise ValueError("question cannot be empty")
        if len(stripped) > 2000:
            raise ValueError("question exceeds 2000 characters")
        return stripped


class EntityContextChatResponse(BaseModel):
    """Synchronous response from POST /api/v1/chat/entity-context."""

    answer: str
    citations: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    thread_id: str | None = None
    message_id: str | None = None
    intent: str | None = None
    provider: str | None = None
    latency_ms: int | None = None


class CreateThreadRequest(BaseModel):
    title: str | None = Field(None, max_length=200)
    entity_ids: list[UUID] = Field(default=[], max_length=5)


class UpdateThreadRequest(BaseModel):
    """Patch a thread's mutable fields (PLAN-0051 T-E-5-06).

    Only ``title`` is currently patchable.  Field is optional so callers
    can submit an empty PATCH (no-op) without triggering 422.  Length is
    capped at 200 to match ``CreateThreadRequest`` for symmetry.
    """

    title: str | None = Field(default=None, max_length=200)


class ChatRequestSchema(BaseModel):
    """Request body for POST /api/v1/chat and POST /api/v1/chat/stream."""

    message: str = Field(..., min_length=1, max_length=2000)
    thread_id: UUID | None = None
    entity_ids: list[UUID] = Field(default=[], max_length=5)


class ChatResponse(BaseModel):
    """Synchronous chat response."""

    answer: str
    citations: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    thread_id: str | None = None
    message_id: str | None = None
    intent: str | None = None
    provider: str | None = None
    latency_ms: int | None = None


# ── Response schemas ──────────────────────────────────────────────────────────


class CreateThreadResponse(BaseModel):
    thread_id: UUID
    title: str | None
    created_at: datetime


class MessageResponse(BaseModel):
    """Serialised message returned in thread history responses.

    Q-9: Extended with optional debug/observability fields that are already
    persisted in the ``messages`` table.  All new fields default to ``None``
    so responses for legacy rows (NULL columns) remain valid (R11: forward-
    compatible schema changes).
    """

    message_id: UUID
    role: str
    content: str
    intent: str | None
    citations: list[dict[str, Any]]
    created_at: datetime
    # Q-9: fields persisted in the DB but previously omitted from the history
    # API.  All nullable — legacy rows (pre-Q-9) have NULL in these columns.
    # WHY None default (not empty list): returning None vs [] distinguishes
    # "never populated" from "populated with zero items"; clients can guard on
    # ``is not None`` if they want to render debug panels.
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    resolved_entities: list[dict[str, Any]] | None = None
    retrieval_plan: dict[str, Any] | None = None
    # WHY "contradictions" (not "contradiction_refs"): the DB column is
    # ``contradiction_refs`` but the API surface uses the friendlier name
    # ``contradictions``, matching EntityContextChatResponse and ChatResponse.
    contradictions: list[dict[str, Any]] | None = None


class ThreadSummaryResponse(BaseModel):
    thread_id: UUID
    title: str | None
    last_msg_at: datetime | None
    message_count: int
    entity_ids: list[UUID]
    created_at: datetime


class ThreadDetailResponse(BaseModel):
    thread_id: UUID
    title: str | None
    created_at: datetime
    messages: list[MessageResponse]


class PaginatedThreadsResponse(BaseModel):
    threads: list[ThreadSummaryResponse]
    total: int


class DeleteThreadResponse(BaseModel):
    thread_id: UUID
    archived_at: datetime


# ── Briefing schemas (T-B-2-03, PRD-0016 §6.2) ───────────────────────────────
# BriefCitation, BriefBullet, BriefSection live in rag_chat.domain.brief and are
# re-exported at the top of this file. BriefingRequest and BriefingResponse are
# API-layer schemas (they reference the domain types as nested fields).


class BriefingRequest(BaseModel):
    """Request body for POST /internal/v1/briefings (called by S10 email scheduler)."""

    user_id: UUID
    tenant_id: UUID
    portfolio_context: dict[str, Any]
    market_snapshots: list[dict[str, Any]] = Field(..., min_length=1)
    active_signals: list[dict[str, Any]] = []
    lookback_days: int = Field(7, ge=1, le=30)


class BriefingResponse(BaseModel):
    """Response from POST /internal/v1/briefings.

    PLAN-0048 Wave A added the optional ``summary`` field — a 1-2 sentence
    headline produced by the v2.2 prompt's ``## SUMMARY`` block. Older
    callers that don't populate it default to ``None`` for forward
    compatibility (R11: never break wire format).

    PLAN-0049 T-A-1-04 added optional ``headline`` and ``sections``: when
    populated, the frontend renders structured cards instead of bare
    markdown. ``narrative`` is kept as the always-present fallback so older
    clients keep working unchanged (graceful degradation, BP-019).

    PLAN-0062-W4 added ``confidence`` and ``lead``:
    - ``confidence``: composite citation quality score in [0.0, 1.0].
      1.0 = all bullets have citations; lower values indicate partial coverage.
    - ``lead``: 1-3 sentence executive summary from the ## LEAD block with
      inline [cN] markers. None when the LLM didn't emit a lead or no valid
      citations exist.
    """

    narrative: str
    risk_summary: dict[str, Any]
    citations: list[dict[str, Any]] = []
    generated_at: str
    # WHY optional with None default: legacy briefings (pre-v2.2 prompt) had no
    # summary block. The frontend handles `summary == null` by falling back to
    # showing a clamp-3 of the narrative — safe degradation across rollouts.
    summary: str | None = None
    # WHY list[dict[str, Any]] (not list[BriefSection]): BriefSection is now a
    # frozen dataclass (PLAN-0083). The field_validator below converts dataclass
    # instances to dicts on construction so JSON round-trip stays clean.
    sections: list[dict[str, Any]] = Field(default_factory=list)
    # WHY ge=0 le=1: confidence is a probability — clamped to [0.0, 1.0] by the
    # formula. default=1.0 means "fully cited" which is the safe fallback for
    # callers that don't populate this field (no citation badge shown).
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # WHY max_length=1000: v3.0 prompt allows 1-3 sentences; on high-activity
    # days or large portfolios three dense sentences can approach 600 chars.
    lead: str | None = Field(default=None, max_length=1000)
    # PLAN-0103 W3 (BP-624): collapsed-view summary paragraph (1-3 sentences,
    # ≤300 chars target / 600 max). See PublicBriefingResponse for full
    # rationale. Optional + default None preserves wire compatibility (R11).
    summary_paragraph: str | None = Field(default=None, max_length=600)

    # WHY mode="before": runs prior to Pydantic's own list validation so we can
    # accept dataclass instances passed in from the use case layer.
    @field_validator("sections", mode="before")
    @classmethod
    def _validate_sections(cls, v: Any) -> list[dict[str, Any]]:
        return _coerce_sections_to_dicts(v)


# ── Public briefing schemas (PLAN-0029 T-2-01) ───────────────────────────────
# PublicBriefingResponse moved to ``rag_chat.application.schemas`` (F-ARCH-001
# / LAYER-APP-ISOLATION). Re-exported at the top of this module so all imports
# from ``rag_chat.api.schemas`` continue to work unchanged.
