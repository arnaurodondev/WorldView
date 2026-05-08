"""SSE event emitter - converts pipeline events into SSE data frames (T-F-3-02).

Uses sse-starlette conventions: each emit method returns a dict with
"event" and "data" keys, suitable for direct use with EventSourceResponse.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from rag_chat.domain.entities.conversation import Citation, ContradictionRef


class SSEEmitter:
    """Convert RAG pipeline events into SSE wire format dictionaries."""

    def emit_status(self, step: str) -> dict[str, str]:
        """Emit a pipeline step progress event."""
        return {"event": "status", "data": json.dumps({"step": step})}

    def emit_token(self, text: str) -> dict[str, str]:
        """Emit a single LLM token chunk."""
        return {"event": "token", "data": json.dumps({"text": text})}

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

    def emit_tool_call(self, tool_name: str, tool_input: dict) -> dict[str, str]:
        """Emit a tool_call event before execution starts (PLAN-0066 Wave H T-W10-H-04).

        WHY BEFORE EXECUTE: the frontend can immediately show a spinner
        "Fetching AAPL price history..." without waiting for the S3 round-trip.
        The ``status: "running"`` field lets the UI differentiate from the result.
        """
        return {
            "event": "tool_call",
            "data": json.dumps({"type": "tool_call", "tool": tool_name, "input": tool_input, "status": "running"}),
        }

    def emit_tool_result(self, tool_name: str, success: bool) -> dict[str, str]:
        """Emit a tool_result event after execution completes (PLAN-0066 Wave H T-W10-H-04).

        WHY ALWAYS EMITTED: the frontend spinner opened by ``tool_call`` must always
        have a corresponding close signal. Emitting on both success and failure
        ensures the UI never hangs in a loading state.
        """
        status = "ok" if success else "error"
        return {
            "event": "tool_result",
            "data": json.dumps({"type": "tool_result", "tool": tool_name, "status": status}),
        }
