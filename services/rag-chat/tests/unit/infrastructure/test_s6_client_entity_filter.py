"""Unit tests for S6Client entity filter forwarding (PLAN-0078 Wave D).

Verifies that entity_ids and entity_types in ChunkSearchRequest are forwarded
to the S6 POST /api/v1/search/chunks payload, and that the empty-list guard
(BP-183) still works correctly when entity filters are present.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from rag_chat.application.ports.upstream_clients import ChunkSearchRequest
from rag_chat.infrastructure.clients.s6_client import S6Client

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_CHUNK_SEARCH_EMPTY_RESPONSE = {"results": []}


def _make_client(handler: Any) -> S6Client:
    transport = httpx.MockTransport(handler)
    client = S6Client.__new__(S6Client)
    client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
    client._internal_jwt = None
    return client


class TestS6ClientEntityFilter:
    async def test_entity_ids_forwarded_to_payload(self) -> None:
        """entity_ids list is serialised as string UUIDs in the POST body."""
        captured: list[dict] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(json.loads(req.content))
            return httpx.Response(200, json=_CHUNK_SEARCH_EMPTY_RESPONSE)

        eid = uuid.uuid4()
        client = _make_client(handler)
        req = ChunkSearchRequest(query_text="Apple earnings", entity_ids=[eid])

        await client.search_chunks(req)

        assert captured, "No request was captured"
        body = captured[0]
        assert "entity_ids" in body
        assert body["entity_ids"] == [str(eid)]

    async def test_entity_types_forwarded_to_payload(self) -> None:
        """entity_types list is forwarded verbatim in the POST body."""
        captured: list[dict] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(json.loads(req.content))
            return httpx.Response(200, json=_CHUNK_SEARCH_EMPTY_RESPONSE)

        client = _make_client(handler)
        req = ChunkSearchRequest(query_text="Apple earnings", entity_types=["organization"])

        await client.search_chunks(req)

        body = captured[0]
        assert "entity_types" in body
        assert body["entity_types"] == ["organization"]

    async def test_none_entity_ids_not_included_in_payload(self) -> None:
        """When entity_ids is None the key must be absent from the payload."""
        captured: list[dict] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(json.loads(req.content))
            return httpx.Response(200, json=_CHUNK_SEARCH_EMPTY_RESPONSE)

        client = _make_client(handler)
        req = ChunkSearchRequest(query_text="Apple earnings", entity_ids=None, entity_types=None)

        await client.search_chunks(req)

        body = captured[0]
        assert "entity_ids" not in body
        assert "entity_types" not in body

    async def test_empty_entity_ids_not_included_in_payload(self) -> None:
        """Empty list entity_ids is falsy → key must be absent (no 422 from S6)."""
        captured: list[dict] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(json.loads(req.content))
            return httpx.Response(200, json=_CHUNK_SEARCH_EMPTY_RESPONSE)

        client = _make_client(handler)
        req = ChunkSearchRequest(query_text="Apple earnings", entity_ids=[], entity_types=[])

        await client.search_chunks(req)

        body = captured[0]
        assert "entity_ids" not in body
        assert "entity_types" not in body

    async def test_multiple_entity_ids_all_stringified(self) -> None:
        """Multiple UUIDs are each converted to string in the payload."""
        captured: list[dict] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(json.loads(req.content))
            return httpx.Response(200, json=_CHUNK_SEARCH_EMPTY_RESPONSE)

        eids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        client = _make_client(handler)
        req = ChunkSearchRequest(query_text="market news", entity_ids=eids)

        await client.search_chunks(req)

        body = captured[0]
        assert body["entity_ids"] == [str(e) for e in eids]
