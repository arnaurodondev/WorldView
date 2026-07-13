"""Polymarket Data-API open-interest adapter package (PLAN-0056 Wave B1)."""

from content_ingestion.infrastructure.adapters.polymarket_data_oi.adapter import PolymarketOIAdapter
from content_ingestion.infrastructure.adapters.polymarket_data_oi.client import PolymarketOIClient

__all__ = ["PolymarketOIAdapter", "PolymarketOIClient"]
