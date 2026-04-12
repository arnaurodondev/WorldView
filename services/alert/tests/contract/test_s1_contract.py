"""Contract tests for S1 Portfolio internal endpoints.

Uses ``pytest-httpserver`` to stand up a local HTTP server that mimics
the S1 internal API.  Validates that ``S1Client`` correctly parses
responses and degrades gracefully on errors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from alert.config import Settings
from alert.infrastructure.clients.s1_client import S1Client
from werkzeug import Response

if TYPE_CHECKING:
    from pytest_httpserver import HTTPServer


def _make_client(httpserver: HTTPServer) -> S1Client:
    """Create an S1Client pointing at the test HTTP server."""
    from httpx import AsyncClient

    settings = Settings(
        s1_portfolio_base_url=httpserver.url_for(""),
        s8_internal_token="test-s8-token",
        s1_internal_token="test-s1-token",
    )
    return S1Client(settings, client=AsyncClient(timeout=5.0))


class TestS1Contract:
    @pytest.mark.contract
    async def test_get_watchers_by_entity_returns_user_ids(self, httpserver: HTTPServer) -> None:
        """GET /internal/v1/watchlists/by-entity/{entity_id} → list of watchers."""
        httpserver.expect_request(
            "/internal/v1/watchlists/by-entity/eid-1",
            method="GET",
        ).respond_with_json(
            {
                "entity_id": "eid-1",
                "watchers": [
                    {"user_id": "user-aaa", "watchlist_id": "wl-1", "alert_types": ["SIGNAL"]},
                    {"user_id": "user-bbb", "watchlist_id": "wl-2", "alert_types": []},
                ],
            },
        )

        client = _make_client(httpserver)
        watchers, ok = await client.get_watchers_by_entity("eid-1")

        assert ok is True
        assert len(watchers) == 2
        assert watchers[0].user_id == "user-aaa"
        assert watchers[0].watchlist_id == "wl-1"
        assert watchers[0].alert_types == ["SIGNAL"]
        assert watchers[1].user_id == "user-bbb"

    @pytest.mark.contract
    async def test_post_watchers_by_entities_returns_map(self, httpserver: HTTPServer) -> None:
        """POST /internal/v1/watchlists/by-entities → {entity_id: [watchers]}."""
        httpserver.expect_request(
            "/internal/v1/watchlists/by-entities",
            method="POST",
        ).respond_with_json(
            {
                "results": {
                    "e1": [{"user_id": "u1", "watchlist_id": "w1", "alert_types": []}],
                    "e2": [
                        {"user_id": "u2", "watchlist_id": "w2", "alert_types": ["GRAPH_CHANGE"]},
                        {"user_id": "u3", "watchlist_id": "w3", "alert_types": []},
                    ],
                },
            },
        )

        client = _make_client(httpserver)
        result = await client.get_watchers_by_entities(["e1", "e2"])

        assert len(result) == 2
        assert len(result["e1"]) == 1
        assert result["e1"][0].user_id == "u1"
        assert len(result["e2"]) == 2

    @pytest.mark.contract
    async def test_s1_503_returns_empty_list(self, httpserver: HTTPServer) -> None:
        """S1 returning 503 → S1Client returns empty list (graceful degradation)."""
        httpserver.expect_request(
            "/internal/v1/watchlists/by-entity/eid-1",
            method="GET",
        ).respond_with_response(Response(status=503))

        client = _make_client(httpserver)
        watchers, ok = await client.get_watchers_by_entity("eid-1")

        assert ok is False
        assert watchers == []
