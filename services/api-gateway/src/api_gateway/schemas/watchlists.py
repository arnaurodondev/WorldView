"""Watchlist response schemas.

WHY: These Pydantic models mirror the TypeScript interfaces in
apps/worldview-web/types/api.ts (Watchlist, WatchlistMember).
GET /v1/watchlists proxies S1 and returns a list of Watchlist objects.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WatchlistResponse(BaseModel):
    """A single watchlist.

    Mirrors the Watchlist TypeScript interface in types/api.ts.
    WHY members is list[dict]: WatchlistMember detail varies (entity_id,
    instrument_id, ticker, name, added_at, resolution) but the shape is
    not worth a separate schema at this tier — kept flexible so S1 can
    evolve the member payload without requiring a schema change here.
    """

    model_config = ConfigDict(extra="allow")

    watchlist_id: str
    name: str
    members: list[dict] = []  # member detail varies; keep flexible
