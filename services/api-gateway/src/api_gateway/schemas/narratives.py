"""S9 public schemas for Entity Narratives endpoints (PLAN-0074 Wave G).

NarrativeListResponse wraps paginated NarrativeVersionPublic entries.
NarrativeTriggerResponse mirrors S7's 202 trigger acknowledgement.

WHY separate file: narratives are a distinct sub-resource of entity
intelligence; keeping them separate makes the schema registry easier
to navigate and mirrors S7's module boundary.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api_gateway.schemas.intelligence import NarrativeVersionPublic  # noqa: TCH001


class NarrativeListResponse(BaseModel):
    """Paginated response for GET /v1/entities/{id}/narratives."""

    model_config = ConfigDict(extra="allow")

    entity_id: str
    versions: list[NarrativeVersionPublic]
    # next_cursor is None when there are no further pages.
    next_cursor: str | None = None


class NarrativeTriggerResponse(BaseModel):
    """202 acknowledgement for POST /v1/entities/{id}/narratives/generate."""

    model_config = ConfigDict(extra="allow")

    message: str
    entity_id: str
