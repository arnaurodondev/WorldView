"""Polymarket Gamma ``/events`` adapter package (PLAN-0056 Wave B1)."""

from content_ingestion.infrastructure.adapters.polymarket_gamma_events.adapter import PolymarketEventsAdapter
from content_ingestion.infrastructure.adapters.polymarket_gamma_events.client import (
    GammaEventsPage,
    PolymarketEventsClient,
)

__all__ = ["GammaEventsPage", "PolymarketEventsAdapter", "PolymarketEventsClient"]
