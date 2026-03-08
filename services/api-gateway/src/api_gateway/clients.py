"""Typed HTTP clients for downstream services.

The gateway never calls services by raw URL — it uses these client classes
which provide typed method signatures and handle errors consistently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx


class DownstreamError(Exception):
    """Raised when a downstream service returns an error."""

    def __init__(self, service: str, status: int, detail: str) -> None:
        self.service = service
        self.status = status
        self.detail = detail
        super().__init__(f"{service} returned {status}: {detail}")


@dataclass(frozen=True)
class ServiceClients:
    """Container for all downstream service HTTP clients."""

    portfolio: httpx.AsyncClient
    market_data: httpx.AsyncClient
    market_ingestion: httpx.AsyncClient
    content_ingestion: httpx.AsyncClient
    content_store: httpx.AsyncClient
    nlp_pipeline: httpx.AsyncClient
    knowledge_graph: httpx.AsyncClient
    rag_chat: httpx.AsyncClient


async def _checked_get(
    client: httpx.AsyncClient,
    service_name: str,
    path: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """GET with error translation."""
    resp = await client.get(path, **kwargs)
    if resp.status_code >= 400:
        raise DownstreamError(service_name, resp.status_code, resp.text)
    return cast(dict[str, Any], resp.json())


async def _checked_post(
    client: httpx.AsyncClient,
    service_name: str,
    path: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """POST with error translation."""
    resp = await client.post(path, **kwargs)
    if resp.status_code >= 400:
        raise DownstreamError(service_name, resp.status_code, resp.text)
    return cast(dict[str, Any], resp.json())


# ── Typed wrappers ────────────────────────────────────────────────


async def get_company_overview(
    clients: ServiceClients,
    company_id: str,
) -> dict[str, Any]:
    """Compose company overview from Market Data + Content Store."""
    import asyncio

    fundamentals, ohlcv, news = await asyncio.gather(
        _checked_get(clients.market_data, "market-data", f"/v1/instruments/{company_id}/fundamentals"),
        _checked_get(clients.market_data, "market-data", f"/v1/instruments/{company_id}/ohlcv", params={"limit": 90}),
        _checked_get(
            clients.content_store, "content-store", "/v1/articles", params={"symbol": company_id, "limit": 10}
        ),
    )
    return {
        "company_id": company_id,
        "fundamentals": fundamentals,
        "ohlcv": ohlcv,
        "latest_news": news,
    }


async def get_relevant_news(
    clients: ServiceClients,
    limit: int = 20,
) -> dict[str, Any]:
    """Get most relevant news articles."""
    return await _checked_get(
        clients.content_store,
        "content-store",
        "/v1/articles/relevant",
        params={"limit": limit},
    )


async def get_map_layers(
    clients: ServiceClients,
) -> dict[str, Any]:
    """Get map overlay layers (placeholder: returns available layer types)."""
    return {
        "layers": [
            {"id": "news", "label": "News Events", "enabled": True},
            {"id": "signals", "label": "NLP Signals", "enabled": False},
            {"id": "sentiment", "label": "Sentiment Heatmap", "enabled": False},
        ],
    }
