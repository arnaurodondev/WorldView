"""SSE event emitter - converts pipeline events into SSE data frames (T-F-3-02).

Uses sse-starlette conventions: each emit method returns a dict with
"event" and "data" keys, suitable for direct use with EventSourceResponse.

PLAN-0067 W11-3: added emit_thinking, updated emit_tool_call (label field,
new input_summary param), updated emit_tool_result (item_count param).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from rag_chat.domain.entities.conversation import Citation, ContradictionRef

# ── Tool label map ─────────────────────────────────────────────────────────────
# Maps tool names (from capability_manifest.yaml) to human-readable UI labels.
# WHY here: the SSEEmitter is the only layer that emits tool_call events, so
# co-locating the label map avoids a separate lookup on every call site.
_TOOL_LABELS: dict[str, str] = {
    "search_documents": "Searching documents...",
    "get_entity_graph": "Building entity map...",
    "traverse_graph": "Traversing knowledge graph...",
    "search_entity_relations": "Mapping relationships...",
    "search_claims": "Checking analyst claims...",
    "search_events": "Looking up corporate events...",
    "get_contradictions": "Detecting contradictions...",
    "get_portfolio_context": "Loading portfolio context...",
    "get_price_history": "Fetching price history...",
    "get_fundamentals_history": "Fetching fundamentals...",
    "get_entity_narrative": "Loading narrative...",
    "get_entity_paths": "Tracing entity paths...",
    "get_entity_health": "Computing health score...",
    "get_entity_intelligence": "Loading intelligence bundle...",
    # PLAN-0081 Wave A: catalog tools
    "get_morning_brief": "Loading morning brief...",
    "compare_entities": "Comparing entities...",
    "screen_universe": "Screening universe...",
    "get_market_movers": "Fetching market movers...",
    "get_economic_calendar": "Loading economic calendar...",
    "get_earnings_calendar": "Loading earnings calendar...",
    # PLAN-0082 Wave A: action tools
    "get_alerts": "Loading your alerts...",
    # PLAN-0082 Wave B: write action tools
    "create_alert": "Creating alert...",
}


class SSEEmitter:
    """Convert RAG pipeline events into SSE wire format dictionaries."""

    def emit_status(self, step: str) -> dict[str, str]:
        """Emit a pipeline step progress event."""
        return {"event": "status", "data": json.dumps({"step": step})}

    def emit_token(self, text: str) -> dict[str, str]:
        """Emit a single LLM token chunk."""
        return {"event": "token", "data": json.dumps({"text": text})}

    def emit_final_answer(self, text: str) -> dict[str, str]:
        """Emit the post-validation final answer in a single event.

        PLAN-0093 E-5 T-E-5-03: ``execute_sync`` uses this to avoid
        concatenating intermediate-draft token events together with the
        post-validation rewrite (F-CHAT-002 response duplication).
        Streaming clients can ignore this event — they already saw the
        token-by-token stream.
        """
        return {"event": "final_answer", "data": json.dumps({"text": text})}

    def emit_citations(self, citations: list[Citation]) -> dict[str, str]:
        """Emit the citations block after LLM generation completes."""
        return {
            "event": "citations",
            "data": json.dumps(
                [
                    {
                        "ref": c.ref,
                        "item_type": c.item_type,
                        "id": str(c.id),
                        "title": c.title,
                        "url": c.url,
                        "source_name": c.source_name,
                        "published_at": c.published_at.isoformat() if c.published_at else None,
                        "entity_name": c.entity_name,
                        "confidence": c.confidence,
                    }
                    for c in citations
                ]
            ),
        }

    def emit_contradictions(self, contradictions: list[ContradictionRef]) -> dict[str, str]:
        """Emit contradiction references detected during retrieval."""
        return {
            "event": "contradictions",
            "data": json.dumps(
                [
                    {
                        "claim_type": c.claim_type,
                        "strength": c.strength,
                        "sides": list(c.sides),
                    }
                    for c in contradictions
                ]
            ),
        }

    def emit_metadata(
        self,
        thread_id: UUID,
        message_id: UUID,
        intent: str,
        provider: str,
        latency_ms: int,
    ) -> dict[str, str]:
        """Emit final response metadata (thread/message IDs, latency, provider)."""
        return {
            "event": "metadata",
            "data": json.dumps(
                {
                    "thread_id": str(thread_id),
                    "message_id": str(message_id),
                    "intent": intent,
                    "provider": provider,
                    "latency_ms": latency_ms,
                }
            ),
        }

    def emit_error(self, code: str, message: str) -> dict[str, str]:
        """Emit an error event (pipeline failure, rate limit, etc.)."""
        return {"event": "error", "data": json.dumps({"code": code, "message": message})}

    def emit_done(self) -> dict[str, str]:
        """Emit the terminal SSE event signalling the stream is complete.

        WHY NEEDED: Without a ``done`` event the frontend EventSource listener has no
        reliable signal to close the connection — it relies on the server closing the
        HTTP stream, which some proxies buffer.  An explicit ``event: done`` lets the
        frontend close the EventSource immediately and mark the response as finished.
        """
        return {"event": "done", "data": json.dumps({"type": "done"})}

    def emit_thinking(self, stage: str = "tool_classification") -> dict[str, str]:
        """Emitted immediately when the first-turn LLM call starts (PLAN-0067 §0 I-1).

        WHY: non-streaming first turn adds ~600ms latency vs classical path. This event
        shows the user activity before the first token arrives — the frontend can show
        a pulsing "Thinking..." indicator immediately instead of a blank stream.

        Args:
            stage: identifies which sub-step the service is in. Defaults to
                   "tool_classification" (the only stage in the W11-3 path).
                   Future waves may add "entity_resolution", "reranking", etc.
        """
        return {"event": "thinking", "data": json.dumps({"stage": stage})}

    def emit_tool_call(
        self,
        tool_name: str,
        input_summary: dict,  # type: ignore[type-arg]
        status: str = "running",
        is_fallback: bool = False,
        fallback_of: str | None = None,
    ) -> dict[str, str]:
        """Emit a tool_call event before execution starts (PLAN-0066 Wave H T-W10-H-04).

        Updated in PLAN-0067 W11-3: added ``label`` field (user-friendly string) and
        renamed ``tool_input`` → ``input_summary`` (safe subset, no PII).

        FIX-LIVE-E (2026-05-24): added ``is_fallback``/``fallback_of`` so the
        orchestrator can flag automatic alt-tool retries after a primary tool
        returns empty.  The frontend can render a subtler "(retrying with X)"
        affordance instead of a fresh spinner.

        WHY BEFORE EXECUTE: the frontend can immediately show a spinner
        "Fetching AAPL price history..." without waiting for the S3 round-trip.
        The ``status: "running"`` field lets the UI differentiate from the result.

        WHY label: raw tool names ("get_price_history") are not user-friendly. The
        label ("Fetching price history...") is displayed in the chat UI while the
        tool executes.

        Args:
            tool_name:     Internal tool name (from capability_manifest.yaml).
            input_summary: Safe subset of the tool input, no PII. Displayed in UI.
            status:        Current tool status. Defaults to "running".
            is_fallback:   True when this is an automatic alt-tool retry after a
                           primary tool returned empty (FIX-LIVE-E).
            fallback_of:   Name of the originally-failed tool when is_fallback=True;
                           ignored otherwise.
        """
        label = _TOOL_LABELS.get(tool_name, f"{tool_name}...")
        payload: dict[str, Any] = {
            "type": "tool_call",
            "tool": tool_name,
            "label": label,
            "input": input_summary,
            "status": status,
        }
        if is_fallback:
            payload["is_fallback"] = True
            if fallback_of:
                payload["fallback_of"] = fallback_of
        return {
            "event": "tool_call",
            "data": json.dumps(payload),
        }

    def emit_pending_action(
        self,
        proposal_id: str,
        tool_name: str,
        description: str,
        params: dict,  # type: ignore[type-arg]
    ) -> dict[str, str]:
        """Emit a pending_action event when a write-action tool requires user confirmation.

        WHY a separate SSE event type (not tool_call): tool_call/tool_result are
        informational spinners — they fire for read tools and resolve automatically.
        ``pending_action`` is a blocking event: the frontend must show a modal and
        wait for explicit user confirmation before the action executes.

        The ``proposal_id`` is a server-generated UUID the frontend sends back via
        POST /v1/chat/proposals/{id}/confirm to execute the action.

        Args:
            proposal_id:  UUID string for the pending proposal (client sends back on confirm).
            tool_name:    Internal tool name (e.g. "create_alert").
            description:  Human-readable description of the pending action shown in modal.
            params:       Safe display parameters shown in the confirmation modal.
        """
        return {
            "event": "pending_action",
            "data": json.dumps(
                {
                    "type": "pending_action",
                    "proposal_id": proposal_id,
                    "tool": tool_name,
                    "description": description,
                    "params": params,
                }
            ),
        }

    def emit_action_executed(
        self,
        proposal_id: str,
        tool_name: str,
        result: dict,  # type: ignore[type-arg]
    ) -> dict[str, str]:
        """Emit an action_executed event after the user confirms and the action completes.

        WHY ALWAYS EMITTED on confirm: the frontend proposal modal opened by
        ``pending_action`` must always receive a close signal.  Emitting on
        success ensures the UI never hangs in a loading state.

        Args:
            proposal_id:  UUID string matching the prior pending_action proposal_id.
            tool_name:    Internal tool name matching the prior pending_action.
            result:       Action result summary (e.g. {"alert_id": "...", "condition": "..."}).
        """
        return {
            "event": "action_executed",
            "data": json.dumps(
                {
                    "type": "action_executed",
                    "proposal_id": proposal_id,
                    "tool": tool_name,
                    "result": result,
                }
            ),
        }

    def emit_action_rejected(
        self,
        proposal_id: str,
        tool_name: str,
        reason: str = "user_cancelled",
    ) -> dict[str, str]:
        """Emit an action_rejected event when the user dismisses the confirmation modal.

        WHY ALWAYS EMITTED on dismiss: mirrors emit_action_executed so the frontend
        always has a matching close signal regardless of whether the user confirmed
        or cancelled.

        Args:
            proposal_id:  UUID string matching the prior pending_action proposal_id.
            tool_name:    Internal tool name matching the prior pending_action.
            reason:       Rejection reason token. Default "user_cancelled".
        """
        return {
            "event": "action_rejected",
            "data": json.dumps(
                {
                    "type": "action_rejected",
                    "proposal_id": proposal_id,
                    "tool": tool_name,
                    "reason": reason,
                }
            ),
        }

    def emit_tool_result(
        self,
        tool_name: str,
        status: str,  # "ok" | "error" | "empty"
        item_count: int = 0,
    ) -> dict[str, str]:
        """Emit a tool_result event after execution completes (PLAN-0066 Wave H T-W10-H-04).

        Updated in PLAN-0067 W11-3: changed ``success: bool`` → ``status: str`` to
        support a third "empty" state (tool executed but returned no items), and added
        ``item_count`` so the frontend can show "Found 5 results" inline.

        WHY ALWAYS EMITTED: the frontend spinner opened by ``tool_call`` must always
        have a corresponding close signal. Emitting on both success and failure
        ensures the UI never hangs in a loading state.

        Args:
            tool_name:  Internal tool name matching the prior emit_tool_call.
            status:     "ok" | "error" | "empty". "empty" = tool ran but returned 0 items.
            item_count: Number of items returned by the tool (0 on error/empty).
        """
        return {
            "event": "tool_result",
            "data": json.dumps(
                {
                    "type": "tool_result",
                    "tool": tool_name,
                    "status": status,
                    "item_count": item_count,
                }
            ),
        }
