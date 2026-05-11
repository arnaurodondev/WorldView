"""Polymarket Gamma API adapter package."""

from content_ingestion.infrastructure.adapters.polymarket.adapter import PolymarketAdapter
from content_ingestion.infrastructure.adapters.polymarket.client import GammaMarketsPage, PolymarketClient

__all__ = ["GammaMarketsPage", "PolymarketAdapter", "PolymarketClient"]
