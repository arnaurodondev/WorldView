"""Domain value objects for the nightly intelligence-rollup sync.

These are pure value objects (no infrastructure dependencies) describing the
minimal parsed responses from the 4 upstream intelligence services.  They live
in the domain layer (R25) so both the application-layer ports / use case and the
infrastructure-layer HTTP clients can reference them without crossing layer
boundaries.

PLAN-0089 Wave L-5b — moved here from ``infrastructure/clients`` to satisfy the
application→infrastructure layer-isolation rule (R25 / LAYER-APP-ISOLATION).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class S6NewsRollup:
    """Parsed response from S6 ``GET /internal/v1/instruments/{id}/news-rollup-7d``."""

    news_count_7d: int
    llm_relevance_7d_max: float | None
    display_relevance_7d_weighted: float | None


@dataclass(frozen=True, slots=True)
class S7IntelligenceRollup:
    """Parsed response from S7 ``GET /internal/v1/instruments/{id}/intelligence-rollup-7d``."""

    recent_contradiction_count: int


@dataclass(frozen=True, slots=True)
class S10AlertFlag:
    """Parsed response from S10 ``GET /internal/v1/instruments/{id}/active-alert-flag``."""

    has_active_alert: bool


@dataclass(frozen=True, slots=True)
class S8BriefFlag:
    """Parsed response from S8 ``GET /internal/v1/instruments/{id}/ai-brief-flag``."""

    has_ai_brief: bool
