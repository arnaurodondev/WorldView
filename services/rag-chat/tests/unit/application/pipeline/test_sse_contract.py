"""Unit tests for the Phase-1 SSE contract standardization + human tool labels.

Covers:
  Part A — deterministic input-aware tool->label map + the `verifying` status.
  Part B — the versioned, single-source-of-truth SSE event contract.

These pin the wire contract the frontend (apps/worldview-web/features/chat)
consumes. They are deliberately strict about (a) additive-only evolution and
(b) the protocol version being surfaced on done + metadata.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from rag_chat.application.pipeline.sse_emitter import SSEEmitter
from rag_chat.application.pipeline.sse_events import (
    PROTOCOL_VERSION_KEY,
    SSE_PROTOCOL_VERSION,
    SSEEventType,
    SSEStatusStep,
)

pytestmark = pytest.mark.unit


# ── Part A: input-aware human tool labels ──────────────────────────────────────


class TestHumanToolLabels:
    def test_news_label_weaves_in_ticker_display_name(self) -> None:
        """get_entity_news(ticker=NVDA) -> 'Searching news for NVIDIA' (mapped name)."""
        emitter = SSEEmitter()
        event = emitter.emit_tool_call("get_entity_news", {"ticker": "NVDA"})
        data = json.loads(event["data"])
        assert data["label"] == "Searching news for NVIDIA"

    def test_kg_relations_tool_maps_to_knowledge_graph_label(self) -> None:
        """Path/relation tools map to a 'knowledge graph' phrasing."""
        emitter = SSEEmitter()
        # No subject -> static base label.
        base = json.loads(emitter.emit_tool_call("get_relations", {})["data"])
        assert "knowledge graph" in base["label"].lower()
        # With subject -> templated, still mentions the KG.
        subj = json.loads(emitter.emit_tool_call("get_relations", {"entity_name": "OpenAI"})["data"])
        assert subj["label"] == "Querying the knowledge graph for OpenAI"

    def test_risk_metrics_label(self) -> None:
        emitter = SSEEmitter()
        data = json.loads(emitter.emit_tool_call("get_risk_metrics", {})["data"])
        assert data["label"] == "Computing risk metrics..."

    def test_unknown_ticker_falls_back_to_raw_symbol(self) -> None:
        """A symbol not in the display-name map is used verbatim (never wrong)."""
        emitter = SSEEmitter()
        data = json.loads(emitter.emit_tool_call("get_price_history", {"ticker": "ZZZZ"})["data"])
        assert data["label"] == "Fetching price history for ZZZZ"

    def test_list_subject_is_joined(self) -> None:
        """compare_entities with a ticker list joins the mapped names."""
        emitter = SSEEmitter()
        data = json.loads(emitter.emit_tool_call("compare_entities", {"ticker": ["NVDA", "AMD"]})["data"])
        assert data["label"] == "Comparing NVIDIA, AMD"

    def test_no_subject_uses_static_base_label(self) -> None:
        emitter = SSEEmitter()
        data = json.loads(emitter.emit_tool_call("get_entity_news", {})["data"])
        assert data["label"] == "Searching news..."

    def test_query_text_is_not_used_as_subject(self) -> None:
        """Free-text 'query'/'text' must NEVER become the label subject (PII / noise)."""
        emitter = SSEEmitter()
        data = json.loads(emitter.emit_tool_call("search_documents", {"query": "secret stuff"})["data"])
        # No recognised subject key -> static base label, query text not leaked.
        assert data["label"] == "Searching documents..."

    def test_tool_result_carries_label_when_provided(self) -> None:
        """emit_tool_result(label=...) surfaces the same human line for the timeline."""
        emitter = SSEEmitter()
        label = emitter.human_tool_label("get_entity_news", {"ticker": "NVDA"})
        event = emitter.emit_tool_result("get_entity_news", status="ok", item_count=12, label=label)
        data = json.loads(event["data"])
        assert data["label"] == "Searching news for NVIDIA"
        assert data["item_count"] == 12

    def test_tool_result_omits_label_when_not_provided(self) -> None:
        """Legacy callers (no label) keep the byte-identical 4-key payload."""
        emitter = SSEEmitter()
        data = json.loads(emitter.emit_tool_result("get_price_history", status="ok", item_count=3)["data"])
        assert "label" not in data

    def test_human_tool_label_is_public_and_deterministic(self) -> None:
        """The public accessor returns the SAME label as emit_tool_call (one source)."""
        emitter = SSEEmitter()
        direct = emitter.human_tool_label("get_entity_news", {"ticker": "NVDA"})
        via_event = json.loads(emitter.emit_tool_call("get_entity_news", {"ticker": "NVDA"})["data"])["label"]
        assert direct == via_event == "Searching news for NVIDIA"


# ── Part A: verifying status ────────────────────────────────────────────────────


class TestVerifyingStatus:
    def test_verifying_status_event(self) -> None:
        emitter = SSEEmitter()
        event = emitter.emit_status(SSEStatusStep.VERIFYING.value)
        assert event["event"] == "status"
        data = json.loads(event["data"])
        assert data == {"step": "verifying"}


# ── Part B: versioned contract ──────────────────────────────────────────────────


class TestVersionedContract:
    def test_done_surfaces_protocol_version(self) -> None:
        emitter = SSEEmitter()
        data = json.loads(emitter.emit_done()["data"])
        assert data[PROTOCOL_VERSION_KEY] == SSE_PROTOCOL_VERSION
        assert data["type"] == "done"

    def test_metadata_surfaces_protocol_version(self) -> None:
        emitter = SSEEmitter()
        data = json.loads(emitter.emit_metadata(uuid4(), uuid4(), "FACTUAL_LOOKUP", "deepinfra", 100)["data"])
        assert data[PROTOCOL_VERSION_KEY] == SSE_PROTOCOL_VERSION

    def test_protocol_version_is_at_least_two(self) -> None:
        """Phase-1 introduced version 2 (labels + verifying + surfaced version)."""
        assert SSE_PROTOCOL_VERSION >= 2

    def test_event_type_values_are_stable_wire_strings(self) -> None:
        """The enum VALUES are the wire contract — renaming any breaks the FE.

        This guard freezes the existing string values so a refactor that renames
        an enum member without preserving its value is caught here.
        """
        expected = {
            "STATUS": "status",
            "THINKING": "thinking",
            "AGENT_ITERATION": "agent_iteration",
            "TOOL_CALL": "tool_call",
            "TOOL_RESULT": "tool_result",
            "TOKEN": "token",
            "FINAL_ANSWER": "final_answer",
            "CITATIONS": "citations",
            "SUGGESTIONS": "suggestions",
            "CONTRADICTIONS": "contradictions",
            "PENDING_ACTION": "pending_action",
            "ACTION_EXECUTED": "action_executed",
            "ACTION_REJECTED": "action_rejected",
            "METADATA": "metadata",
            "ERROR": "error",
            "DONE": "done",
        }
        actual = {m.name: m.value for m in SSEEventType}
        # Every expected pair must survive verbatim (additive-only: new members
        # may exist beyond this set, but none of these may change).
        for name, value in expected.items():
            assert actual.get(name) == value

    def test_emitters_use_enum_values(self) -> None:
        """Emitter ``event`` fields match the canonical enum values."""
        emitter = SSEEmitter()
        assert emitter.emit_token("x")["event"] == SSEEventType.TOKEN.value
        assert emitter.emit_status("loading_context")["event"] == SSEEventType.STATUS.value
        assert emitter.emit_tool_call("get_entity_news", {})["event"] == SSEEventType.TOOL_CALL.value
        assert emitter.emit_tool_result("get_entity_news", status="ok")["event"] == SSEEventType.TOOL_RESULT.value
