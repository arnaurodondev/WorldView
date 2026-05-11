"""Kafka topic constants and routing for the Portfolio service."""

from __future__ import annotations

PORTFOLIO_EVENTS_V1 = "portfolio.events.v1"
WATCHLIST_UPDATED_V1 = "portfolio.watchlist.updated.v1"

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
    "watchlist.created": PORTFOLIO_EVENTS_V1,
    "watchlist.deleted": PORTFOLIO_EVENTS_V1,
    "watchlist.renamed": WATCHLIST_UPDATED_V1,
    "watchlist.item_added": WATCHLIST_UPDATED_V1,
    "watchlist.item_deleted": WATCHLIST_UPDATED_V1,
}
