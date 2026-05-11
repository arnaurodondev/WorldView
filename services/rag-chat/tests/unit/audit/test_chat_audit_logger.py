"""Unit tests for ChatAuditLogger (E-12 per-turn audit log).

Tests verify:
- record_tool_call accumulates entries in _tool_entries
- increment_iteration increments _iteration_count
- finalize() calls session_factory and writes entries
- finalize() failure (DB error) does not propagate to caller
- SHA-256 hash is stored, not full answer text
"""

from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_FAKE_UUID_1 = UUID("00000000-0000-0000-0000-000000000001")
_FAKE_UUID_2 = UUID("00000000-0000-0000-0000-000000000002")
_FAKE_UUID_3 = UUID("00000000-0000-0000-0000-000000000003")


class TestChatAuditLoggerAccumulation:
    def test_record_tool_call_accumulates_entries(self) -> None:
        """record_tool_call() accumulates entries without any I/O."""
        from rag_chat.application.audit.chat_audit_logger import ChatAuditLogger

        logger = ChatAuditLogger(turn_id=_FAKE_UUID_1, thread_id=_FAKE_UUID_2, user_id=_FAKE_UUID_3)

        logger.record_tool_call("get_price_history", success=True, latency_ms=240)
        logger.record_tool_call(
            "search_documents", success=False, latency_ms=50, entity_name="Apple Inc", match_count=0
        )

        assert len(logger._tool_entries) == 2
        assert logger._tool_entries[0].tool_name == "get_price_history"
        assert logger._tool_entries[0].success is True
        assert logger._tool_entries[0].latency_ms == 240
        assert logger._tool_entries[1].entity_name == "Apple Inc"
        assert logger._tool_entries[1].match_count == 0

    def test_increment_iteration_increments_counter(self) -> None:
        """increment_iteration() correctly increments _iteration_count."""
        from rag_chat.application.audit.chat_audit_logger import ChatAuditLogger

        logger = ChatAuditLogger(turn_id=_FAKE_UUID_1, thread_id=_FAKE_UUID_2, user_id=_FAKE_UUID_3)

        assert logger._iteration_count == 0
        logger.increment_iteration()
        logger.increment_iteration()
        logger.increment_iteration()
        assert logger._iteration_count == 3

    def test_initial_state(self) -> None:
        """Fresh logger has empty entries and zero iteration count."""
        from rag_chat.application.audit.chat_audit_logger import ChatAuditLogger

        logger = ChatAuditLogger(turn_id=_FAKE_UUID_1, thread_id=_FAKE_UUID_2, user_id=_FAKE_UUID_3)

        assert logger._tool_entries == []
        assert logger._iteration_count == 0
        assert logger.turn_id == _FAKE_UUID_1
        assert logger.thread_id == _FAKE_UUID_2
        assert logger.user_id == _FAKE_UUID_3


class TestChatAuditLoggerFinalize:
    def test_finalize_calls_session_factory(self) -> None:
        """finalize() calls session_factory and executes SQL inserts."""
        from rag_chat.application.audit.chat_audit_logger import ChatAuditLogger

        logger = ChatAuditLogger(turn_id=_FAKE_UUID_1, thread_id=_FAKE_UUID_2, user_id=_FAKE_UUID_3)
        logger.record_tool_call("get_price_history", success=True, latency_ms=300)

        # Mock session_factory: returns async context manager → mock session
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        asyncio.run(logger.finalize(answer="The stock price is $150.", session_factory=mock_factory))

        # session_factory must have been called to create a session
        mock_factory.assert_called_once()
        # execute must have been called: one for the tool row + one for the summary row
        assert mock_session.execute.call_count == 2
        # commit must have been called
        mock_session.commit.assert_called_once()

    def test_finalize_stores_sha256_not_full_text(self) -> None:
        """finalize() stores SHA-256 hash of the answer, not the full answer text."""
        from rag_chat.application.audit.chat_audit_logger import ChatAuditLogger

        logger = ChatAuditLogger(turn_id=_FAKE_UUID_1, thread_id=_FAKE_UUID_2, user_id=_FAKE_UUID_3)

        answer = "The revenue for Apple Inc in Q4 2024 was $94.9 billion."
        expected_hash = hashlib.sha256(answer.encode()).hexdigest()

        # Capture the SQL parameters passed to session.execute
        captured_params: list = []

        async def _capture_execute(stmt, params=None):  # type: ignore[no-untyped-def]
            if params:
                captured_params.append(params)

        mock_session = AsyncMock()
        mock_session.execute = _capture_execute
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        asyncio.run(logger.finalize(answer=answer, session_factory=mock_factory))

        # The summary row params (last captured) should contain answer_hash
        assert len(captured_params) >= 1
        # Find the params dict that contains answer_hash (summary row)
        summary_params = next((p for p in captured_params if "answer_hash" in p), None)
        assert summary_params is not None, "No params with answer_hash found"
        assert summary_params["answer_hash"] == expected_hash
        # Full answer text must NOT be stored
        assert answer not in str(summary_params.values())

    def test_finalize_failure_does_not_propagate(self) -> None:
        """finalize() swallows DB errors — must never raise to the caller."""
        from rag_chat.application.audit.chat_audit_logger import ChatAuditLogger

        logger = ChatAuditLogger(turn_id=_FAKE_UUID_1, thread_id=_FAKE_UUID_2, user_id=_FAKE_UUID_3)

        # session_factory that raises on creation
        def _failing_factory():
            raise RuntimeError("DB connection failed")

        # Must NOT raise — just logs a warning
        asyncio.run(logger.finalize(answer="some answer", session_factory=_failing_factory))
        # If we reach here, the test passes (no exception propagated)

    def test_finalize_no_tool_entries_writes_summary_only(self) -> None:
        """When no tool calls were recorded, finalize() writes only the summary row."""
        from rag_chat.application.audit.chat_audit_logger import ChatAuditLogger

        logger = ChatAuditLogger(turn_id=_FAKE_UUID_1, thread_id=_FAKE_UUID_2, user_id=_FAKE_UUID_3)
        # No tool calls recorded

        execute_call_count = [0]

        async def _count_execute(stmt, params=None):  # type: ignore[no-untyped-def]
            execute_call_count[0] += 1

        mock_session = AsyncMock()
        mock_session.execute = _count_execute
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        asyncio.run(logger.finalize(answer="Direct answer.", session_factory=mock_factory))

        # Only 1 execute call (the summary row, no tool rows)
        assert execute_call_count[0] == 1

    def test_finalize_includes_iteration_count(self) -> None:
        """Summary row must include the current iteration_count."""
        from rag_chat.application.audit.chat_audit_logger import ChatAuditLogger

        logger = ChatAuditLogger(turn_id=_FAKE_UUID_1, thread_id=_FAKE_UUID_2, user_id=_FAKE_UUID_3)
        logger.increment_iteration()
        logger.increment_iteration()

        captured_summary: dict = {}

        async def _capture_execute(stmt, params=None):  # type: ignore[no-untyped-def]
            if params and "iteration_count" in params:
                captured_summary.update(params)

        mock_session = AsyncMock()
        mock_session.execute = _capture_execute
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        asyncio.run(logger.finalize(answer="Answer after 2 iterations.", session_factory=mock_factory))

        assert captured_summary.get("iteration_count") == 2
