"""Screener response schemas.

WHY: These Pydantic models mirror the TypeScript ScreenerResponse/ScreenerResult
interfaces in apps/worldview-web/types/api.ts and the S3 ScreenResponse shape in
services/market-data/src/market_data/api/schemas/fundamental_metrics.py.

S3 ScreenInstrumentResponse has:
    instrument_id, ticker, name, exchange, sector, metrics (dict[str, float|None])

S3 ScreenResponse has:
    results: list[ScreenInstrumentResponse], count: int, total: int

WHY metrics is dict (not typed object): S3 stores metrics dynamically based on
available fundamentals data — the keys are metric names (e.g. "pe_ratio",
"market_cap") and the values are nullable floats. Typing as dict matches S3's
schema and remains forward-compatible with new metrics added without a gateway
schema change.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ScreenerResultItem(BaseModel):
    """One instrument row in a screener result.

    Mirrors S3 ScreenInstrumentResponse and the TypeScript ScreenerResult interface.
    WHY extra=allow: S3 may add new top-level fields (e.g. entity_id) without
    requiring a gateway schema bump.
    """

    model_config = ConfigDict(extra="allow")

    instrument_id: str
    ticker: str | None = None
    name: str | None = None
    exchange: str | None = None
    sector: str | None = None
    # WHY dict (not ScreenerMetrics sub-object): S3 returns metrics as a flat
    # dict keyed on metric name. The TypeScript side reads individual keys from
    # ScreenerResult (market_cap, pe_ratio, daily_return, etc.) — those are
    # surfaced to the frontend via the screener result's top-level fields or
    # the metrics dict. Using extra="allow" means any future metric key on the
    # metrics dict passes through without a schema change.
    metrics: dict[str, float | None] | None = None


class NLScreenerRequest(BaseModel):
    """Request body for POST /v1/screener/nl-translate (PLAN-0091 Wave E-1)."""

    model_config = ConfigDict(extra="allow")

    query: str  # natural-language screening query, e.g. "profitable tech stocks under $50"


class NLScreenerResponse(BaseModel):
    """Structured screener filter object parsed from the LLM response."""

    model_config = ConfigDict(extra="allow")

    filters: dict[str, object] = {}  # field → value/range; keys validated against /screen/fields
    natural_language_query: str = ""  # echo of the original query


class ScreenerResponse(BaseModel):
    """Response from POST /v1/fundamentals/screen.

    Mirrors the TypeScript ScreenerResponse interface and S3 ScreenResponse.

    WHY both count + total: S3 returns both `count` (rows in this page) and
    `total` (total rows matching filters). The frontend uses `total` for
    pagination. `count` is forwarded via extra="allow".

    WHY offset default 0 / limit default 50: S9 injects these when the frontend
    omits them so paginators can render correctly even for partial responses.
    """

    model_config = ConfigDict(extra="allow")

    results: list[ScreenerResultItem] = []
    total: int = 0
    # WHY offset/limit optional: S3 ScreenResponse does not include these fields
    # (it only has count+total). They are included here as defaults so the
    # OpenAPI schema advertises them (the frontend reads them) but validation
    # won't fail if S3 omits them.
    offset: int = 0
    limit: int = 50
