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
    alert: httpx.AsyncClient


async def _checked_get(
    client: httpx.AsyncClient,
    service_name: str,
    path: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """GET with error translation."""
    resp = await client.get(path, **kwargs)
    if resp.status_code >= 400:
        # F-005: truncate error detail to avoid leaking internal service details to frontend
        raise DownstreamError(service_name, resp.status_code, resp.text[:200])
    return cast("dict[str, Any]", resp.json())


async def _checked_post(
    client: httpx.AsyncClient,
    service_name: str,
    path: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """POST with error translation."""
    resp = await client.post(path, **kwargs)
    if resp.status_code >= 400:
        # F-005: truncate error detail to avoid leaking internal service details to frontend
        raise DownstreamError(service_name, resp.status_code, resp.text[:200])
    return cast("dict[str, Any]", resp.json())


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
            clients.content_store,
            "content-store",
            "/v1/articles",
            params={"symbol": company_id, "limit": 10},
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


# ── Composed endpoints (PRD-0028 Wave S9-3) ────────────────────────────────


# F-015: GICS official sector order (not alphabetical) — matches S&P GICS 2.0 hierarchy
GICS_SECTORS = [
    "Energy",
    "Materials",
    "Industrials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Health Care",
    "Financials",
    "Information Technology",
    "Communication Services",
    "Utilities",
    "Real Estate",
]


async def _screener_for_sector(
    client: httpx.AsyncClient,
    sector: str,
) -> dict[str, Any]:
    """Screen instruments for a single GICS sector sorted by daily_return.

    Returns the raw S3 response or an error dict on failure.
    """
    import json as _json

    body = _json.dumps(
        {
            "filters": [{"metric": "daily_return", "min_value": -100, "max_value": 100, "sector": sector}],
            "sort_by": "daily_return",
            "sort_order": "desc",
            "limit": 20,
        }
    )
    resp = await client.post(
        "/api/v1/fundamentals/screen",
        content=body.encode(),
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code >= 400:
        return {"error": True, "sector": sector}
    # F-006: catch malformed JSON from downstream (e.g., HTML error page from reverse proxy)
    try:
        return cast("dict[str, Any]", resp.json())
    except Exception:
        return {"error": True, "sector": sector}


async def get_market_heatmap(clients: ServiceClients) -> dict[str, Any]:
    """Compute sector heatmap from S3 screener data.

    Makes 11 parallel S3 screener calls (one per GICS sector), computes average
    daily_return per sector. Uses asyncio.gather with return_exceptions=True
    so partial failures don't crash the whole heatmap (BP-114).
    """
    import asyncio

    calls = [_screener_for_sector(clients.market_data, sector) for sector in GICS_SECTORS]
    results = await asyncio.gather(*calls, return_exceptions=True)

    sectors = []
    # F-012: strict=True ensures len(results) == len(GICS_SECTORS) — catches gather bugs
    for sector_name, result in zip(GICS_SECTORS, results, strict=True):
        if isinstance(result, BaseException) or (isinstance(result, dict) and result.get("error")):
            sectors.append({"name": sector_name, "change_pct": None, "instrument_count": 0})
            continue
        instruments = result.get("results", [])
        daily_returns = [
            inst["metrics"]["daily_return"]
            for inst in instruments
            if inst.get("metrics", {}).get("daily_return") is not None
        ]
        avg_change = sum(daily_returns) / len(daily_returns) if daily_returns else None
        sectors.append(
            {
                "name": sector_name,
                "change_pct": round(avg_change, 4) if avg_change is not None else None,
                "instrument_count": len(instruments),
            }
        )

    return {"sectors": sectors}


async def get_top_movers(
    clients: ServiceClients,
    mover_type: str = "gainers",
    limit: int = 10,
) -> dict[str, Any]:
    """Get top gainers or losers from the screener.

    Composes a single S3 screener call with sort_by=daily_return and the appropriate
    sort order (desc for gainers, asc for losers).
    """
    import json as _json

    sort_order = "desc" if mover_type == "gainers" else "asc"
    body = _json.dumps(
        {
            "filters": [{"metric": "daily_return", "min_value": -100, "max_value": 100}],
            "sort_by": "daily_return",
            "sort_order": sort_order,
            "limit": limit,
        }
    )
    resp = await clients.market_data.post(
        "/api/v1/fundamentals/screen",
        content=body.encode(),
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code >= 400:
        raise DownstreamError("market-data", resp.status_code, resp.text)
    return cast("dict[str, Any]", resp.json())
