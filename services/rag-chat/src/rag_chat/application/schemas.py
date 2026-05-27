"""Application-layer DTOs shared between use cases / workers and the API layer.

WHY this module exists (LAYER-APP-ISOLATION, R25): the application layer must
not depend on ``rag_chat.api`` — that would invert the dependency direction
(api → application, not the other way). The morning-brief pre-generation
worker (``application/workers/morning_brief_pregeneration_worker.py``) needs
to serialise its output into the same shape the public API returns
(``PublicBriefingResponse``), so the canonical Pydantic model lives here
and is re-exported from ``rag_chat.api.schemas`` for backward compatibility.

What's here:
* ``PublicBriefingResponse`` — the wire shape for GET /api/v1/briefings/*.
* Two small private helpers (``_coerce_sections_to_dicts`` and
  ``_normalize_legacy_citation_keys``) used by the model's field_validator
  and re-imported by ``BriefingResponse`` in the API layer (the API model
  isn't moved here because it is used only by API routes).

Move history: F-ARCH-001 (QA-PLAN-0093 iter-9). Originally lived in
``rag_chat/api/schemas.py``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

# Domain dataclasses used by the response model. ``BriefSection`` is the only
# one referenced directly in this file (for the coercion helper).
from rag_chat.domain.brief import BriefSection


def _normalize_legacy_citation_keys(section: dict[str, Any]) -> dict[str, Any]:
    """Rewrite legacy ``source_id`` citation keys to canonical ``document_id``.

    Behaviour: if BOTH ``document_id`` and ``source_id`` are present, the
    canonical ``document_id`` wins (matching ``BriefCitation.from_dict``);
    the legacy key is dropped from the output dict. See the original docstring
    in the previous api/schemas.py location for the full QA-PLAN-0083 F-001
    rationale.
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
                if "document_id" not in cit:
                    cit["document_id"] = cit["source_id"]
                del cit["source_id"]
    return section


def _coerce_sections_to_dicts(value: Any) -> list[dict[str, Any]]:
    """Normalise ``sections`` input to ``list[dict]`` for JSON serialisation.

    Accepts dataclass instances or plain dicts (cache reads come back as
    dicts after JSON parse) and emits dicts. Legacy ``source_id`` keys are
    rewritten to ``document_id`` so cached blobs from before PLAN-0062-W4
    still serialise correctly (QA-PLAN-0083 F-001).
    """
    if value is None:
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, BriefSection):
            out.append(item.to_dict())
        elif isinstance(item, dict):
            out.append(_normalize_legacy_citation_keys(item))
        else:
            raise TypeError(f"sections entries must be BriefSection or dict, got {type(item).__name__}")
    return out


class PublicBriefingResponse(BaseModel):
    """Response for GET /api/v1/briefings/* (called via S9 proxy).

    Mirrors the canonical shape served by the API layer and also written into
    Valkey by the pre-generation worker.

    See the historical docstring in ``rag_chat/api/schemas.py`` for the full
    field-evolution history (PLAN-0029, PLAN-0048, PLAN-0062-W4, PLAN-0066,
    PLAN-0094). All changes here MUST remain forward-compatible (R11) — add
    fields with safe defaults, never remove or rename.
    """

    id: str | None = None
    narrative: str
    risk_summary: dict[str, Any] = {}
    citations: list[dict[str, Any]] = []
    generated_at: str
    cached: bool = False
    entity_id: str | None = None
    summary: str | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    lead: str | None = Field(default=None, max_length=1000)
    # PLAN-0094 W2: signals the frontend the brief came from the last-known-good
    # cache because regeneration failed. Default False so legacy callers don't break.
    is_stale: bool = False

    @field_validator("sections", mode="before")
    @classmethod
    def _validate_sections(cls, v: Any) -> list[dict[str, Any]]:
        return _coerce_sections_to_dicts(v)


__all__ = [
    "PublicBriefingResponse",
    "_coerce_sections_to_dicts",
    "_normalize_legacy_citation_keys",
]
