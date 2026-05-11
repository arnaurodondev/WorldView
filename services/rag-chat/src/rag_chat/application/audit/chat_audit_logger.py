"""Per-turn structured audit logger for the agent loop (E-12).

Records tool-call outcomes and final answer metadata to the chat_audit_log table.
One ChatAuditLogger instance is created per request (turn) and writes:
  - One row per tool call (tool_name, success, latency_ms, entity_name, match_count)
  - One summary row (answer_hash, total_latency_ms, iteration_count)

WHY write at finalize time (not inline): the tool loop yields SSE events and
must not pause for DB writes between iterations. We buffer entries in memory and
flush them all in finalize() which is called in a try/finally after the stream
ends. This keeps the hot path (tool execution + SSE streaming) free of DB I/O.

WHY SHA-256 of answer: full answer text is large and privacy-sensitive. The hash
lets us detect identical answers (e.g. the model giving the same canned response
for failed retrievals) without storing the full text in the audit table.

WHY try/except around finalize(): audit failures must NEVER propagate to the user.
The answer has already been streamed by the time finalize() is called; a DB error
here would cause the SSE stream to close with an error after the user already
received their response, which is deeply confusing.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


@dataclass
class ToolCallAuditEntry:
    """One tool invocation's audit data."""

    tool_name: str
    success: bool
    latency_ms: int
    entity_name: str | None = None
    match_count: int | None = None


class ChatAuditLogger:
    """Records per-turn structured audit data for agent loop observability (E-12).

    Usage::
        logger = ChatAuditLogger(turn_id=new_uuid7(), thread_id=..., user_id=...)
        # During tool loop:
        logger.record_tool_call("get_price_history", success=True, latency_ms=240)
        logger.increment_iteration()
        # After stream ends:
        await logger.finalize(answer="...", session_factory=app.state.write_factory)
    """

    def __init__(self, turn_id: UUID, thread_id: UUID, user_id: UUID) -> None:
        self.turn_id = turn_id
        self.thread_id = thread_id
        self.user_id = user_id
        self._tool_entries: list[ToolCallAuditEntry] = []
        self._start_time = time.monotonic()
        self._iteration_count: int = 0

    def record_tool_call(
        self,
        tool_name: str,
        success: bool,
        latency_ms: int,
        entity_name: str | None = None,
        match_count: int | None = None,
    ) -> None:
        """Accumulate one tool-call audit entry in memory.

        Called inline during the tool loop — no I/O, just a list append.
        The data is flushed to DB in finalize().
        """
        self._tool_entries.append(
            ToolCallAuditEntry(
                tool_name=tool_name,
                success=success,
                latency_ms=latency_ms,
                entity_name=entity_name,
                match_count=match_count,
            )
        )

    def increment_iteration(self) -> None:
        """Increment the loop iteration counter.

        Called at the end of each tool-use iteration in the agent loop.
        """
        self._iteration_count += 1

    async def finalize(self, answer: str, session_factory: Any) -> None:
        """Write all buffered audit entries plus a summary row to the DB.

        Called exactly once, in the try/finally at the end of execute_streaming.
        Wrapped in try/except so audit failures never propagate to the user.

        Args:
            answer: The full assistant answer text (hashed before storing).
            session_factory: Callable that returns an AsyncSession context manager.
                             Must be the WRITE session factory (R23).
        """
        from rag_chat.application.metrics.prometheus import rag_audit_entries_total

        try:
            await self._write_entries(answer, session_factory)
            # Count total entries written: one per tool call + one summary row.
            entries_written = len(self._tool_entries) + 1
            rag_audit_entries_total.inc(entries_written)
        except Exception as exc:
            # Audit failure must never propagate — the answer was already streamed.
            log.warning(  # type: ignore[no-any-return]
                "chat_audit_finalize_failed",
                error=str(exc),
                turn_id=str(self.turn_id),
            )

    async def _write_entries(self, answer: str, session_factory: Any) -> None:
        """Internal: write tool-call rows + summary row to chat_audit_log."""
        from sqlalchemy import text

        # SHA-256 of the full answer text — stored for dedup analysis without
        # the privacy and storage cost of the full answer string.
        answer_hash = hashlib.sha256(answer.encode()).hexdigest()
        total_latency_ms = int((time.monotonic() - self._start_time) * 1000)

        # Build parameter dicts for all inserts. We use raw SQL (sqlalchemy text)
        # rather than ORM models because chat_audit_log is a simple append-only table
        # with no relationships — raw SQL is simpler and avoids the need for a model.
        async with session_factory() as session:
            # One row per tool call
            for entry in self._tool_entries:
                await session.execute(
                    text("""
                        INSERT INTO chat_audit_log
                        (turn_id, thread_id, user_id, tool_name, tool_success,
                         tool_latency_ms, entity_name, match_count, created_at)
                        VALUES
                        (:turn_id, :thread_id, :user_id, :tool_name, :tool_success,
                         :tool_latency_ms, :entity_name, :match_count, NOW())
                    """),
                    {
                        "turn_id": str(self.turn_id),
                        "thread_id": str(self.thread_id),
                        "user_id": str(self.user_id),
                        "tool_name": entry.tool_name,
                        "tool_success": entry.success,
                        "tool_latency_ms": entry.latency_ms,
                        "entity_name": entry.entity_name,
                        "match_count": entry.match_count,
                    },
                )

            # Summary row with answer_hash + total_latency + iteration_count.
            # tool_name/tool_success/tool_latency_ms are NULL in the summary row.
            await session.execute(
                text("""
                    INSERT INTO chat_audit_log
                    (turn_id, thread_id, user_id, answer_hash, total_latency_ms,
                     iteration_count, created_at)
                    VALUES
                    (:turn_id, :thread_id, :user_id, :answer_hash, :total_latency_ms,
                     :iteration_count, NOW())
                """),
                {
                    "turn_id": str(self.turn_id),
                    "thread_id": str(self.thread_id),
                    "user_id": str(self.user_id),
                    "answer_hash": answer_hash,
                    "total_latency_ms": total_latency_ms,
                    "iteration_count": self._iteration_count,
                },
            )

            await session.commit()


__all__ = ["ChatAuditLogger", "ToolCallAuditEntry"]
