"""Dashboard bundle response schema (F-2).

WHY a SECOND dashboard composite endpoint distinct from /v1/dashboard/snapshot:
  - /v1/dashboard/snapshot (PLAN-0070 C-2) was a "prefetcher" — its keys do
    not match the actual per-widget cache keys the dashboard widgets use, so
    each widget still fires its own initial fetch. That keeps the dashboard
    wave-serialized on cold start.
  - /v1/dashboard/bundle (F-2) is shape-aligned with the per-widget query
    keys so the page can hydrate them via queryClient.setQueryData and ELIMINATE
    the per-widget initial fetches entirely.

Each leg is independently nullable — failed legs degrade to None and the page
still renders. extra="allow" lets upstream services add fields without
needing schema updates here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class DashboardBundleResponse(BaseModel):
    """Dashboard page bundle — collapses N initial queries into 1 round-trip.

    F-2: single composite endpoint the dashboard page calls once at the top
    level. The page hydrates per-widget TanStack query caches from the legs
    so child widgets render without firing their own initial fetches.

    Fields (all nullable — failed legs degrade to None):
      brief             : AI-generated morning briefing (S8 rag-chat)
      portfolios        : list of user portfolios (S1 portfolio)
      top_gainers       : top universe-wide gainers (S3 market-data period-movers)
      top_losers        : top universe-wide losers (S3 market-data period-movers)
      sector_heatmap    : GICS sector heatmap (S3 market-data, 11-sector fan-out)
      recent_alerts     : latest 10 pending alerts (S10 alert)
      workspace         : reserved for future workspace state (always None today —
                          no workspace state endpoint exists upstream yet).
    """

    model_config = ConfigDict(extra="allow")

    brief: dict[str, Any] | None = None
    portfolios: dict[str, Any] | None = None
    top_gainers: dict[str, Any] | None = None
    top_losers: dict[str, Any] | None = None
    sector_heatmap: dict[str, Any] | None = None
    recent_alerts: dict[str, Any] | None = None
    workspace: dict[str, Any] | None = None
