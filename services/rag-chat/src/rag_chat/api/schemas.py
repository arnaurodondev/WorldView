"""Pydantic request/response schemas for the RAG-Chat API (T-D-4-02, T-F-4-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Request schemas ───────────────────────────────────────────────────────────


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
    message_id: UUID
    role: str
    content: str
    intent: str | None
    citations: list[dict[str, Any]]
    created_at: datetime


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


class BriefCitation(BaseModel):
    """One source-document reference attached to a bullet (PLAN-0062-W4).

    WHY document_id (not source_id): the new bullet-level citation model uses
    'document_id' as the primary key to align with S6/S7 internal naming.
    The 'source_id' alias is kept for back-compat with legacy callers that
    still send the old field name (R11: never break wire format).

    WHY Literal source_type: strongly typed so the frontend can branch on
    source_type to decide which deep-link route to construct. Adding new
    source types requires a schema bump, which is correct behaviour.
    """

    document_id: str
    snippet: str = Field(..., max_length=400)
    url: str | None = Field(default=None)
    source_type: Literal["article", "event", "alert"] = "article"
    title: str | None = None
    # WHY populate_by_name=True: accepts both 'document_id' and the legacy
    # 'source_id' alias so older callers are not immediately broken.
    model_config = ConfigDict(populate_by_name=True)


class BriefBullet(BaseModel):
    """One bullet inside a section (PLAN-0062-W4).

    WHY citations min_length=1: this is the 100% citation gate. Every bullet
    that reaches the response MUST have at least one citation. Bullets without
    citations are filtered out by _backfill_uncited_bullets() before
    construction, so a BriefBullet with citations=[] should never be created.

    WHY text max_length=400: generous cap that covers the longest real brief
    bullets (140 chars target, 400 hard cap to tolerate LLM verbosity).
    """

    text: str = Field(..., min_length=1, max_length=400)
    citations: list[BriefCitation] = Field(..., min_length=1)


class BriefingRequest(BaseModel):
    """Request body for POST /internal/v1/briefings (called by S10 email scheduler)."""

    user_id: UUID
    tenant_id: UUID
    portfolio_context: dict[str, Any]
    market_snapshots: list[dict[str, Any]] = Field(..., min_length=1)
    active_signals: list[dict[str, Any]] = []
    lookback_days: int = Field(7, ge=1, le=30)


class BriefSection(BaseModel):
    """One section of a structured AI brief (PLAN-0049 T-A-1-04, F-D-001).

    Renders as a heading followed by a bullet list. The frontend
    ``<MorningBriefCard>`` and ``<InstrumentAISubheader>`` prefer this
    structured shape when ``sections`` is non-empty; otherwise both fall
    back to rendering ``narrative`` through ``<MarkdownContent>``.

    PLAN-0062-W4: bullets changed from list[str] to list[BriefBullet] so
    each bullet carries citations. min_length=0 enables the backfill pattern
    where sections with zero remaining bullets are dropped rather than crashing.
    """

    title: str = Field(..., max_length=120)
    # WHY min_length=0 (was 1): the backfill pass may remove all uncited bullets
    # from a section. We set min_length=0 here and drop empty sections in
    # _backfill_uncited_bullets() so the constraint is enforced at the list level
    # rather than at construction time (which would throw before we can filter).
    bullets: list[BriefBullet] = Field(..., min_length=0, max_length=8)


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
    - ``lead``: the lead sentence(s) from the ## LEAD block with [cN] markers
      resolved. None when the LLM didn't emit a lead or no valid citations.
    """

    narrative: str
    risk_summary: dict[str, Any]
    citations: list[dict[str, Any]] = []
    generated_at: str
    # WHY optional with None default: legacy briefings (pre-v2.2 prompt) had no
    # summary block. The frontend handles `summary == null` by falling back to
    # showing a clamp-3 of the narrative — safe degradation across rollouts.
    summary: str | None = None
    # PLAN-0049 additive fields. Leave blank for backwards compatibility.
    headline: str | None = Field(default=None, max_length=240)
    sections: list[BriefSection] = Field(default_factory=list)
    # PLAN-0062-W4 additive fields — default values ensure old callers are unaffected.
    # WHY ge=0 le=1: confidence is a probability — clamped to [0.0, 1.0] by the
    # formula. default=1.0 means "fully cited" which is the safe fallback for
    # callers that don't populate this field (no citation badge shown).
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # WHY lead optional: the v3.0 prompt emits a ## LEAD block; older prompts,
    # cached briefs, and instrument briefs (no ## LEAD) pass None here.
    lead: str | None = Field(default=None, max_length=600)


# ── Public briefing schemas (PLAN-0029 T-2-01) ───────────────────────────────


class PublicBriefingResponse(BaseModel):
    """Response for GET /api/v1/briefings/* (called via S9 proxy).

    Extends BriefingResponse with ``cached`` flag and optional ``entity_id``
    to indicate cache hits and instrument-specific briefings.

    PLAN-0048 Wave A added ``summary`` (1-2 sentence headline) — emitted by the
    v2.2 MORNING_BRIEFING prompt's ``## SUMMARY`` block and consumed by the
    frontend MorningBriefCard collapsed view. ``None`` on legacy/instrument
    briefs (forward-compatible).

    PLAN-0062-W4 added ``confidence`` and ``lead`` — same semantics as
    BriefingResponse. Both default to safe values for backward compatibility.
    """

    narrative: str
    risk_summary: dict[str, Any] = {}
    citations: list[dict[str, Any]] = []
    generated_at: str
    cached: bool = False
    entity_id: str | None = None
    # WHY default None: instrument briefs and any cached responses generated
    # before v2.2 will lack this field. The frontend treats None as "no two-tier
    # output available — render clamp-3 of narrative as before".
    summary: str | None = None
    # PLAN-0049 T-A-1-04 — structured render fields. Optional for forward
    # compat: when present, the frontend renders headline + sections; when
    # absent, it falls back to narrative through ``<MarkdownContent>``.
    headline: str | None = Field(default=None, max_length=240)
    sections: list[BriefSection] = Field(default_factory=list)
    # PLAN-0062-W4 additive fields — same as BriefingResponse.
    # WHY default=1.0: safe fallback; no amber warning badge shown when all
    # cached briefs lack this field after the first deploy.
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    lead: str | None = Field(default=None, max_length=600)
