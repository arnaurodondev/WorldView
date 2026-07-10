"""Polymarket CLOB ``/prices-history`` adapter package (PLAN-0056 Wave B1)."""

from content_ingestion.infrastructure.adapters.polymarket_clob.adapter import PolymarketClobHistoryAdapter
from content_ingestion.infrastructure.adapters.polymarket_clob.client import PolymarketClobHistoryClient

__all__ = ["PolymarketClobHistoryAdapter", "PolymarketClobHistoryClient"]
