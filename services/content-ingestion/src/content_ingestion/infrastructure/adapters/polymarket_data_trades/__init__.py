"""Polymarket Data-API ``/trades`` adapter package (PLAN-0056 Wave B1)."""

from content_ingestion.infrastructure.adapters.polymarket_data_trades.adapter import PolymarketTradesAdapter
from content_ingestion.infrastructure.adapters.polymarket_data_trades.client import (
    PolymarketTradesClient,
    TradesPage,
)

__all__ = ["PolymarketTradesAdapter", "PolymarketTradesClient", "TradesPage"]
