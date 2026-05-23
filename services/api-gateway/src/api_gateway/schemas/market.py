"""Market data response schemas (PLAN-0091 Wave A-2)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class YieldPoint(BaseModel):
    """One maturity on the yield curve."""

    model_config = ConfigDict(extra="allow")

    maturity: str  # "2Y" | "5Y" | "10Y" | "30Y"
    yield_pct: float | None = None  # annual yield in percent
    source: str | None = None  # "macro_indicator" | "etf_proxy" | None


class YieldCurveResponse(BaseModel):
    """Response for GET /v1/market/yield-curve (PLAN-0091 T-A-2-04)."""

    model_config = ConfigDict(extra="allow")

    points: list[YieldPoint] = []
    spread_2s10s: float | None = None  # 10Y - 2Y in basis points
    spread_2s10s_inverted: bool | None = None  # True when spread < 0
    source: str | None = None  # "macro_indicator" | "etf_proxy" | "unavailable"
