"""tool_result SSE enrichment — duration_ms + result_preview + suggestions event.

Contract:
  - ``duration_ms`` is attached when supplied (server-measured; the frontend
    prefers it over client-side timing when present).
  - ``result_preview`` is a bounded list (≤3 entries of {id, title}); omitted
    when None or empty so legacy frames stay byte-identical.
  - ``build_result_preview`` caps item count and string lengths and never
    raises on unexpected shapes.
  - ``emit_suggestions`` serialises a plain JSON array of strings.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from rag_chat.application.pipeline.sse_emitter import SSEEmitter

pytestmark = pytest.mark.unit


def _item(item_id: str, title: str | None) -> Any:
    it = MagicMock()
    it.item_id = item_id
    it.citation_meta = MagicMock()
    it.citation_meta.title = title
    return it


class TestToolResultEnrichment:
    def test_duration_ms_attached_when_supplied(self) -> None:
        frame = SSEEmitter().emit_tool_result("get_price_history", status="ok", item_count=2, duration_ms=183)
        payload = json.loads(frame["data"])
        assert payload["duration_ms"] == 183

    def test_legacy_shape_preserved_without_optional_fields(self) -> None:
        """No duration/preview → byte-identical 4-key payload (frontend snapshot contract)."""
        frame = SSEEmitter().emit_tool_result("search_documents", status="empty", item_count=0)
        payload = json.loads(frame["data"])
        assert set(payload.keys()) == {"type", "tool", "status", "item_count"}

    def test_result_preview_attached_when_non_empty(self) -> None:
        preview = [{"id": "tool:graph:abc", "title": "Knowledge graph: Apple Inc."}]
        frame = SSEEmitter().emit_tool_result(
            "get_entity_graph", status="ok", item_count=1, duration_ms=42, result_preview=preview
        )
        payload = json.loads(frame["data"])
        assert payload["result_preview"] == preview

    def test_empty_preview_omitted(self) -> None:
        frame = SSEEmitter().emit_tool_result("get_entity_graph", status="empty", item_count=0, result_preview=[])
        payload = json.loads(frame["data"])
        assert "result_preview" not in payload

    def test_transport_error_fields_coexist_with_duration(self) -> None:
        frame = SSEEmitter().emit_tool_result(
            "search_claims",
            status="transport_error",
            item_count=0,
            reason="upstream_timeout",
            status_code=None,
            elapsed_ms=5000,
            duration_ms=5001,
        )
        payload = json.loads(frame["data"])
        assert payload["reason"] == "upstream_timeout"
        assert payload["elapsed_ms"] == 5000
        assert payload["duration_ms"] == 5001


class TestBuildResultPreview:
    def test_caps_at_three_items(self) -> None:
        items = [_item(f"tool:doc:{i}", f"Title {i}") for i in range(10)]
        preview = SSEEmitter.build_result_preview(items)
        assert len(preview) == 3
        assert preview[0] == {"id": "tool:doc:0", "title": "Title 0"}

    def test_truncates_long_titles_and_ids(self) -> None:
        items = [_item("x" * 500, "t" * 500)]
        preview = SSEEmitter.build_result_preview(items)
        assert preview[0]["id"] is not None and len(preview[0]["id"]) == 64
        assert preview[0]["title"] is not None and len(preview[0]["title"]) == 80

    def test_missing_title_degrades_to_none(self) -> None:
        it = MagicMock()
        it.item_id = "tool:claim:1"
        it.citation_meta = None
        preview = SSEEmitter.build_result_preview([it])
        assert preview == [{"id": "tool:claim:1", "title": None}]

    def test_unknown_shapes_never_raise(self) -> None:
        preview = SSEEmitter.build_result_preview([object(), 42, "str"])
        assert len(preview) == 3
        assert all(p["id"] is None for p in preview)

    def test_serialised_frame_stays_bounded(self) -> None:
        """A worst-case preview must keep the whole SSE frame small (<1KB)."""
        items = [_item("i" * 500, "t" * 500) for _ in range(50)]
        frame = SSEEmitter().emit_tool_result(
            "search_documents",
            status="ok",
            item_count=50,
            duration_ms=1,
            result_preview=SSEEmitter.build_result_preview(items),
        )
        assert len(frame["data"]) < 1024


class TestEmitSuggestions:
    def test_emits_json_array_of_strings(self) -> None:
        suggestions = ["What's the latest news on Apple Inc.?", "How has AAPL performed recently?", "Risks?"]
        frame = SSEEmitter().emit_suggestions(suggestions)
        assert frame["event"] == "suggestions"
        assert json.loads(frame["data"]) == suggestions
