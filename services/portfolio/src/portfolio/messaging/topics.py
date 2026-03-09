"""Kafka topic constants and routing for the Portfolio service."""

from __future__ import annotations

PORTFOLIO_EVENTS_V1 = "portfolio.events.v1"

EVENT_TOPIC_MAP: dict[str, str] = {
    "tenant.created": PORTFOLIO_EVENTS_V1,
    "tenant.status_changed": PORTFOLIO_EVENTS_V1,
    "user.created": PORTFOLIO_EVENTS_V1,
    "user.status_changed": PORTFOLIO_EVENTS_V1,
    "portfolio.created": PORTFOLIO_EVENTS_V1,
    "portfolio.renamed": PORTFOLIO_EVENTS_V1,
    "portfolio.archived": PORTFOLIO_EVENTS_V1,
    "transaction.recorded": PORTFOLIO_EVENTS_V1,
    "holding.changed": PORTFOLIO_EVENTS_V1,
    "instrument_ref.created": PORTFOLIO_EVENTS_V1,
}
