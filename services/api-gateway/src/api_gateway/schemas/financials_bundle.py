"""Financials tab bundle response schema (PLAN-0099 follow-up E).

WHY this exists:
  The Financials tab on /instruments/[id] previously fired ~8 unique HTTP
  round-trips on cold-start (fundamentals, snapshot, income statement,
  earnings history, technicals, share statistics, splits/dividends,
  fundamentals timeseries, beat-miss-history). Each is gated by S9 auth +
  internal-JWT issuance, so the page was wave-serialized by the slowest leg.

  This bundle collapses the fan-out into ONE round-trip. S9 fires the legs
  in parallel via ``asyncio.gather(return_exceptions=True)`` and returns a
  composite dict. The frontend then hydrates each per-widget TanStack
  query cache via ``queryClient.setQueryData(...)`` so the existing child
  components hit warm cache.

Mirrors the F-2 dashboard bundle pattern at
``services/api-gateway/src/api_gateway/schemas/dashboard_bundle.py``.

Each leg is independently nullable — failed legs degrade to ``None`` and
the page still renders. ``extra="allow"`` lets upstream add fields without
forcing schema updates here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class FinancialsBundleResponse(BaseModel):
    """Financials tab bundle — collapses 8 RTTs into 1.

    Fields (all nullable — failed legs degrade to None):
      fundamentals             : raw S3 fundamentals (records[] envelope)
      fundamentals_snapshot    : pre-computed derived metrics flat object
      income_statement         : annual income-statement records (section envelope)
      earnings_history         : annual EPS actuals (section envelope; powers
                                 EarningsBarChart + BeatMissHistoryPanel via
                                 shared TanStack key)
      share_statistics         : ownership / shares-outstanding (section envelope)
      splits_dividends         : split + dividend history (section envelope)
      beat_miss_history        : alias of earnings_history for keyed-cache
                                 hydration; kept distinct in schema so the
                                 frontend can hydrate the sidebar key without
                                 a re-derive step.
      fundamentals_timeseries  : reserved for future inclusion (always None
                                 today — the panel has a metric/period
                                 selector so server-side prefetch needs a
                                 selected metric+period the bundle endpoint
                                 cannot know up front).
    """

    model_config = ConfigDict(extra="allow")

    fundamentals: dict[str, Any] | None = None
    fundamentals_snapshot: dict[str, Any] | None = None
    income_statement: dict[str, Any] | None = None
    earnings_history: dict[str, Any] | None = None
    share_statistics: dict[str, Any] | None = None
    splits_dividends: dict[str, Any] | None = None
    beat_miss_history: dict[str, Any] | None = None
    fundamentals_timeseries: dict[str, Any] | None = None
