"""Dashboard snapshot response schema.

WHY: Adding response_model= to the /v1/dashboard/snapshot route generates
a typed OpenAPI component schema for the frontend type generator.

WHY extra="allow": the snapshot bundles pass-through JSON from 6 upstream
services. New fields added by any upstream don't need a schema update here;
they flow through automatically via extra="allow".

WHY all legs are `dict | None`: each leg is the raw JSON from the corresponding
downstream service. Using dict preserves all fields without mapping them to a
nested Pydantic model per service — the frontend types/api.ts DashboardSnapshotResponse
declares the per-leg shapes from the TypeScript side.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DashboardSnapshotResponse(BaseModel):
    """Dashboard snapshot — all initial page data in one response.

    PLAN-0070 C-2: collapses 6 dashboard page requests into one round-trip.
    Each leg is independently nullable — _meta.partial=True when any leg failed.

    Fields:
      news              : top 8 ranked articles (S6 nlp-pipeline)
      heatmap           : GICS sector heatmap (S3 market-data, 11-sector fan-out)
      prediction_markets: top 5 prediction markets (S3 market-data)
      earnings_calendar : upcoming 7-day company earnings (S7 knowledge-graph)
      alerts            : top 10 pending alerts (S10 alert)
      morning_brief     : AI-generated morning briefing (S8 rag-chat)
    """

    model_config = ConfigDict(extra="allow")

    news: dict | None = None
    heatmap: dict | None = None
    prediction_markets: dict | None = None
    earnings_calendar: dict | None = None
    alerts: dict | None = None
    morning_brief: dict | None = None
