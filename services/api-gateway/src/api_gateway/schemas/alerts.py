"""Alert response schemas.

WHY: These Pydantic models mirror the TypeScript interfaces in
apps/worldview-web/types/api.ts (Alert).
GET /v1/alerts/pending proxies S10 and returns an AlertsResponse shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AlertResponse(BaseModel):
    """A single alert from S10.

    Mirrors the Alert TypeScript interface in types/api.ts.
    WHY title is optional: PLAN-0049 added the title column; alerts created
    before the migration may have NULL title. The frontend falls back to
    signal_label → humanised alert_type.
    WHY alert_id (not id): S10's AlertResponse uses alert_id as the PK field
    name to match the domain entity naming convention.
    """

    model_config = ConfigDict(extra="allow")

    alert_id: str
    title: str | None = None
    severity: str | None = None
    entity_id: str | None = None
    created_at: str | None = None
    acknowledged: bool = False
