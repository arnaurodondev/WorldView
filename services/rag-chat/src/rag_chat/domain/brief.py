"""Domain value objects for structured AI briefings (PLAN-0062-W4).

WHY IN DOMAIN: BriefCitation, BriefBullet, BriefSection are constructed and
manipulated by the application-layer use case (generate_briefing.py) and also
appear in API response schemas. Placing them in domain lets application code
import them without crossing the LAYER-APP-ISOLATION boundary (application must
not import from api).

The api/schemas.py re-exports these classes so existing API callers are unaffected.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
