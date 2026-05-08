"""Pydantic request/response schemas for the RAG-Chat API (T-D-4-02, T-F-4-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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

__all__ = ["BriefBullet", "BriefCitation", "BriefSection"]


def _normalize_legacy_citation_keys(section: dict[str, Any]) -> dict[str, Any]:
    """Rewrite legacy ``source_id`` citation keys to canonical ``document_id``.

    WHY this helper exists (QA-PLAN-0083 F-001 / Data Platform): when the
    response model is rehydrated from a Valkey cache blob via
    ``model_validate_json``, sections come through as plain dicts and the
    ``BriefCitation.from_dict`` legacy-alias handling is bypassed (we never
    invoke ``from_dict`` on the cache-read path). If a cached blob still
    contains ``source_id`` keys (theoretically possible during a long
    rolling deploy from pre-PLAN-0062-W4 code), they would leak through to
    the wire response. This walker converts ``source_id → document_id`` on
    every citation so the API response contract is uniform regardless of
    cache vintage.

    Behaviour: if BOTH ``document_id`` and ``source_id`` are present, the
    canonical ``document_id`` wins (matching ``BriefCitation.from_dict``);
    the legacy key is dropped from the output dict.
    """
    bullets = section.get("bullets")
    if not isinstance(bullets, list):
        return section
    for bullet in bullets:
        if not isinstance(bullet, dict):
            continue
        cits = bullet.get("citations")
        if not isinstance(cits, list):
            continue
        for cit in cits:
            if not isinstance(cit, dict):
                continue
            if "source_id" in cit:
                # Canonical key wins if both are present; otherwise promote.
                if "document_id" not in cit:
                    cit["document_id"] = cit["source_id"]
                del cit["source_id"]
    return section


def _coerce_sections_to_dicts(value: Any) -> list[dict[str, Any]]:
    """Normalise ``sections`` input to ``list[dict]`` for JSON serialisation.

    WHY this helper: callers historically construct ``BriefingResponse(sections=[BriefSection(...)])``
    passing dataclass instances. After PLAN-0083, the response model stores
    ``list[dict]`` so JSON round-trip via ``model_dump_json`` / ``model_validate_json``
    keeps working. This validator accepts EITHER dataclass instances or plain
    dicts (cache reads come back as dicts after JSON parse) and emits dicts.

    Legacy alias normalisation: dict-shaped entries pass through
    ``_normalize_legacy_citation_keys`` so any cached blob that still carries
    ``source_id`` (pre-PLAN-0062-W4 vintage) is rewritten to ``document_id``
    before reaching the wire (QA-PLAN-0083 F-001 / Data Platform).
    """
    if value is None:
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, BriefSection):
            # WHY to_dict: domain dataclass → JSON-serialisable dict per
            # PLAN-0083 §3 Pattern 1 (preferred over arbitrary_types_allowed).
            out.append(item.to_dict())
        elif isinstance(item, dict):
            # Already a dict (e.g. legacy parser output, cache read) — normalise
            # citation keys before passing through.
            out.append(_normalize_legacy_citation_keys(item))
        else:
            raise TypeError(f"sections entries must be BriefSection or dict, got {type(item).__name__}")
    return out


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

    # WHY mode="before": runs prior to Pydantic's own list validation so we can
    # accept dataclass instances passed in from the use case layer.
    @field_validator("sections", mode="before")
    @classmethod
    def _validate_sections(cls, v: Any) -> list[dict[str, Any]]:
        return _coerce_sections_to_dicts(v)


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

    # PLAN-0066 Wave F: expose the DB id of the persisted brief so the frontend
    # can use it in feedback and alert-prefill POST requests. Optional because
    # cached responses generated before the archive write-path was wired (Wave A)
    # won't have this field. The frontend guards on ``brief_id is not None`` before
    # rendering feedback widgets.
    id: str | None = None
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
    # WHY list[dict[str, Any]]: see BriefingResponse.sections comment above.
    sections: list[dict[str, Any]] = Field(default_factory=list)
    # WHY default=1.0: safe fallback; no amber warning badge shown when all
    # cached briefs lack this field after the first deploy.
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # WHY max_length=1000: mirrors BriefingResponse.lead — 1-3 sentences fit
    # comfortably within 1000 chars even on dense financial-domain prose.
    lead: str | None = Field(default=None, max_length=1000)

    @field_validator("sections", mode="before")
    @classmethod
    def _validate_sections(cls, v: Any) -> list[dict[str, Any]]:
        return _coerce_sections_to_dicts(v)
