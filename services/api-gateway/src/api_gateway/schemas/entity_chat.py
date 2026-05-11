"""S9 public schemas for the Entity-Context Chat endpoint (PLAN-0074 Wave G).

EntityContextChatRequest mirrors S8's request body schema so S9 can validate
the entity_id and question fields before proxying.  The validator on question
is intentionally lighter here — S8 applies the full bleach HTML-strip + Pydantic
validation, so S9 only needs to check the basics to return early 422s.

WHY separate validation layer at S9:
  - entity_id must be a valid UUID — catches typos before a round-trip to S8.
  - question must be non-empty — avoids a network hop for obviously bad input.
  - S8's full bleach.clean() + length cap still applies as the second line of
    defence.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntityContextChatRequest(BaseModel):
    """Request body for POST /v1/chat/entity-context (S9 proxy → S8).

    Mirrors S8's rag_chat.api.schemas.EntityContextChatRequest.
    WHY not import from S8: S9 must never import from backend packages (R14).
    """

    model_config = ConfigDict(extra="allow")

    entity_id: UUID
    # min_length=1 catches the empty-string case; S8 also validates max=2000.
    question: str = Field(..., min_length=1, max_length=2000)
    # Maps to thread_id in S8's ChatRequest (alias kept to match S8's schema).
    conversation_id: UUID | None = None
    include_graph_context: bool = True

    @field_validator("question", mode="before")
    @classmethod
    def _question_not_empty(cls, v: object) -> str:
        """Reject empty or whitespace-only questions before proxying to S8.

        WHY here and not only in S8: an empty question would reach S8 and
        be rejected with a 422 after a network round-trip.  Catching it at
        S9 saves the hop and gives a cleaner error response to the frontend.
        """
        stripped = str(v).strip()
        if not stripped:
            raise ValueError("question cannot be empty")
        return stripped
