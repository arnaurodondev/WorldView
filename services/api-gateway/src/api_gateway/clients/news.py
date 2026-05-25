"""News and map-layer endpoints exposed to the frontend.

- ``get_relevant_news`` — proxies S6 nlp-pipeline ``/news/top`` and adds
  pagination envelope fields the frontend ``NewsResponse`` type expects.
- ``get_map_layers``    — placeholder layer registry for the geographic
  map overlay UI.

Split from the original 1424-line ``clients.py`` (TASK-W4-06 / REF-002).
Behavior preserved exactly.
"""

from __future__ import annotations

from typing import Any

from api_gateway.clients.base import ServiceClients, _checked_get


async def get_relevant_news(
    clients: ServiceClients,
    limit: int = 20,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Get most relevant news articles.

    Proxies to S6 nlp-pipeline GET /news/top which provides display_relevance_score
    ranked articles.  Adds ``offset`` and ``limit`` envelope fields for frontend
    NewsResponse compatibility (the frontend expects {articles, total, offset, limit}).

    NOTE: S5 content-store never implemented /v1/articles/relevant; S6 /news/top
    is the canonical ranked-news source (PRD-0026).
    """
    raw = await _checked_get(
        clients.nlp_pipeline,
        "nlp-pipeline",
        "/api/v1/news/top",
        headers=headers,
        params={"limit": limit},
    )
    # Ensure envelope fields expected by the frontend NewsResponse type
    raw.setdefault("offset", 0)
    raw.setdefault("limit", limit)
    return raw


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


__all__ = ["get_map_layers", "get_relevant_news"]
