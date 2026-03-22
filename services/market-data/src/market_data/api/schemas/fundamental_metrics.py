"""Pydantic schemas for fundamental_metrics API (timeseries + screening)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class MetricDataPointResponse(BaseModel):
    """A single timeseries data point."""

    as_of_date: date
    value_numeric: float | None = None
    value_text: str | None = None
    period_type: str | None = None


class TimeseriesResponse(BaseModel):
    """Timeseries data for a single instrument + metric."""

    instrument_id: str
    metric: str
    data: list[MetricDataPointResponse]


class ScreenFilterRequest(BaseModel):
    """A single metric filter for screening."""

    metric: str
    min_value: float | None = None
    max_value: float | None = None
    period_type: str | None = None
    sector: str | None = None


class ScreenRequest(BaseModel):
    """Screening request body."""

    filters: list[ScreenFilterRequest] = Field(..., min_length=1)
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class ScreenInstrumentResponse(BaseModel):
    """One instrument matching screen criteria."""

    instrument_id: str
    metrics: dict[str, float | None]


class ScreenResponse(BaseModel):
    """Screening results."""

    results: list[ScreenInstrumentResponse]
    count: int


class AvailableMetricsResponse(BaseModel):
    """List of metric names available for an instrument."""

    instrument_id: str
    metrics: list[str]
