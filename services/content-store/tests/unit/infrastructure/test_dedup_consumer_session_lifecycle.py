"""Regression tests for StoredArticleDedupConsumer session lifecycle (BP-443).

These tests guard against the MissingGreenlet regression where SQLAlchemy's
asyncpg pool reset fired an await_only() call from a non-greenlet context,
producing:

    RuntimeError: greenlet_spawn has not been called; can't call
    await_only() here. Was IO attempted in an unexpected place?

The fix: _SessionUnitOfWork.__aexit__ now explicitly calls
``await session.close()`` before delegating to the session context-manager,
ensuring the connection is returned to the pool cleanly (no pending async
reset on check-in).

Tests here verify:
1. __aexit__ calls session.close() exactly once (happy path).
2. __aexit__ calls session.close() exactly once on exception path
   (rollback was called by the UoW before __aexit__).
3. session.close() raising does NOT propagate to the caller — it is swallowed
   so the pool teardown error never crashes the consumer loop.
4. session reference is cleared (set to None) after __aexit__ returns so any
   accidental post-exit access raises AttributeError, not a pool error.
5. Full _handle_message → success path: close() is called, session not reused.
6. Full _handle_message → failure path: rollback() then close() both called.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer import (
    StoredArticleDedupConsumer,
    _SessionUnitOfWork,
)

pytestmark = pytest.mark.unit


# ── _SessionUnitOfWork unit tests ─────────────────────────────────────────────


class TestSessionUoWLifecycle:
    """BP-443 guard: _SessionUnitOfWork must close the session in __aexit__."""

    async def test_close_called_on_happy_path(self) -> None:
        """session.close() must be awaited once when __aexit__ is called normally."""
        mock_session = AsyncMock()

        @asynccontextmanager  # type: ignore[arg-type]
        async def _factory():
            yield mock_session

        session_factory = MagicMock(side_effect=_factory)
        uow = _SessionUnitOfWork(session_factory)

        async with uow:
            pass  # no exception — happy path

        # BP-443: explicit close() must have been called
        mock_session.close.assert_awaited_once()

    async def test_close_called_on_exception_path(self) -> None:
        """session.close() must be awaited even when __aexit__ receives an exception."""
        mock_session = AsyncMock()

        @asynccontextmanager  # type: ignore[arg-type]
        async def _factory():
            yield mock_session

        session_factory = MagicMock(side_effect=_factory)
        uow = _SessionUnitOfWork(session_factory)

        # Simulate rollback having already been called by the consumer loop,
        # then __aexit__ is invoked with the exception context.
        with pytest.raises(RuntimeError, match="simulated processing error"):
            async with uow:
                await uow.rollback()
                raise RuntimeError("simulated processing error")

        mock_session.rollback.assert_awaited_once()
        # close() must still be called after rollback, regardless of the error
        mock_session.close.assert_awaited_once()

    async def test_close_error_does_not_propagate(self) -> None:
        """If session.close() raises, __aexit__ must NOT propagate it.

        Pool teardown errors must never surface to the consumer message loop.
        """
        from sqlalchemy.exc import MissingGreenlet

        mock_session = AsyncMock()
        mock_session.close.side_effect = MissingGreenlet(
            "greenlet_spawn has not been called; can't call await_only() here."
        )

        @asynccontextmanager  # type: ignore[arg-type]
        async def _factory():
            yield mock_session

        session_factory = MagicMock(side_effect=_factory)
        uow = _SessionUnitOfWork(session_factory)

        # Must not raise even if close() triggers a MissingGreenlet
        async with uow:
            pass  # happy path inside — close() raises on exit

        mock_session.close.assert_awaited_once()

    async def test_session_cleared_after_aexit(self) -> None:
        """session attribute must be None after __aexit__ to prevent post-exit access."""
        mock_session = AsyncMock()

        @asynccontextmanager  # type: ignore[arg-type]
        async def _factory():
            yield mock_session

        session_factory = MagicMock(side_effect=_factory)
        uow = _SessionUnitOfWork(session_factory)

        async with uow:
            assert uow.session is mock_session  # available inside

        # After __aexit__ the reference must be cleared
        assert uow.session is None, (
            "session reference not cleared after __aexit__ — any accidental "
            "post-exit usage would trigger pool errors rather than a clean AttributeError"
        )

    async def test_close_then_session_cm_aexit_order(self) -> None:
        """close() must be called BEFORE _session_cm.__aexit__ is invoked."""
        call_order: list[str] = []
        mock_session = AsyncMock()
        mock_session.close.side_effect = lambda: call_order.append("close")

        # Build a manual context manager that records when __aexit__ fires
        class _RecordingCM:
            async def __aenter__(self) -> AsyncMock:
                return mock_session

            async def __aexit__(self, *args: object) -> None:
                call_order.append("cm_aexit")

        session_factory = MagicMock(return_value=_RecordingCM())
        uow = _SessionUnitOfWork(session_factory)

        async with uow:
            pass

        assert "close" in call_order
        assert "cm_aexit" in call_order
        assert call_order.index("close") < call_order.index(
            "cm_aexit"
        ), f"close() must fire before _session_cm.__aexit__; actual order: {call_order}"


# ── Consumer integration: _handle_message session lifecycle ───────────────────


def _make_dedup_consumer() -> tuple[StoredArticleDedupConsumer, list[AsyncMock]]:
    """Build a StoredArticleDedupConsumer with a tracking session factory.

    Returns ``(consumer, sessions_list)`` where ``sessions_list`` is populated
    with each AsyncMock session that was yielded by the factory.
    """
    sessions: list[AsyncMock] = []

    def _make_session_cm() -> object:
        s = AsyncMock()
        sessions.append(s)

        @asynccontextmanager  # type: ignore[arg-type]
        async def _cm():
            yield s

        return _cm()

    session_factory = MagicMock(side_effect=_make_session_cm)
    consumer = StoredArticleDedupConsumer(
        bootstrap_servers="localhost:9092",
        group_id="content-store-dedup-consumer",
        session_factory=session_factory,  # type: ignore[arg-type]
    )
    return consumer, sessions


def _make_stored_event(event_id: str = "evt-001", doc_id: str = "019e0000-0000-7000-0000-000000000001") -> MagicMock:
    """Build a minimal mock Kafka message for content.article.stored.v1."""
    msg = MagicMock()
    msg.topic.return_value = "content.article.stored.v1"
    msg.value.return_value = json.dumps(
        {
            "event_id": event_id,
            "doc_id": doc_id,
            "dedup_result": "unique",
        }
    ).encode()
    msg.key.return_value = None
    msg.headers.return_value = []
    return msg


class TestDedupConsumerSessionLifecycle:
    """BP-443 regression: full _handle_message must call session.close()."""

    @patch("content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer.ProcessedEventsRepository")
    @patch("content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer.MinHashRepository")
    async def test_session_closed_after_successful_message(
        self,
        mock_minhash_repo_cls: MagicMock,
        mock_pe_repo_cls: MagicMock,
    ) -> None:
        """After successful processing, the UoW session must be closed (BP-443).

        When the session is NOT explicitly closed before returning it to the
        pool, the pool tries to issue a ROLLBACK on check-in via await_only()
        outside a greenlet — this is the MissingGreenlet bug.
        """
        # ProcessedEventsRepository: not a duplicate
        mock_pe_repo = AsyncMock()
        mock_pe_repo.is_duplicate.return_value = False
        mock_pe_repo.mark_processed.return_value = None
        mock_pe_repo_cls.return_value = mock_pe_repo

        # MinHashRepository: no signature found → consumer returns early (no DB writes)
        mock_minhash_repo = AsyncMock()
        mock_minhash_repo.get_signature_by_doc_id.return_value = None
        mock_minhash_repo_cls.return_value = mock_minhash_repo

        consumer, sessions = _make_dedup_consumer()
        await consumer._handle_message(_make_stored_event())

        # At least one session must have been created (the UoW session)
        assert len(sessions) >= 1, "No sessions were created"

        # Find the UoW session — it is the one that had commit() called on it
        uow_sessions = [s for s in sessions if s.commit.await_count > 0]
        assert len(uow_sessions) == 1, f"Expected exactly 1 UoW session, got: {len(uow_sessions)}"

        uow_session = uow_sessions[0]
        # BP-443: close() must have been awaited
        uow_session.close.assert_awaited_once()

    @patch("content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer.ProcessedEventsRepository")
    @patch("content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer.MinHashRepository")
    async def test_session_closed_after_processing_error(
        self,
        mock_minhash_repo_cls: MagicMock,
        mock_pe_repo_cls: MagicMock,
    ) -> None:
        """After a processing error, rollback + close must both be called (BP-443)."""
        mock_pe_repo = AsyncMock()
        mock_pe_repo.is_duplicate.return_value = False
        mock_pe_repo_cls.return_value = mock_pe_repo

        # Simulate a DB error during MinHash fetch
        mock_minhash_repo = AsyncMock()
        mock_minhash_repo.get_signature_by_doc_id.side_effect = RuntimeError("DB connection lost")
        mock_minhash_repo_cls.return_value = mock_minhash_repo

        consumer, sessions = _make_dedup_consumer()

        with pytest.raises(RuntimeError):
            await consumer._handle_message(_make_stored_event())

        # The UoW session is the one that was NOT used for the is_duplicate check
        # (is_duplicate opens its own session since _current_uow is None at check time)
        # We expect at least 1 session overall; find the one that had rollback called.
        assert len(sessions) >= 1

        # At least one session must have had rollback called (the UoW session)
        rollback_sessions = [s for s in sessions if s.rollback.await_count > 0]
        assert len(rollback_sessions) >= 1, "rollback() was not called on any session after error"

        for s in rollback_sessions:
            # BP-443: close() must also have been called after rollback
            s.close.assert_awaited_once()
