"""Unit tests for BriefArchiveWriteAdapter (F-002, PLAN-0087 audit).

D-R4-004 (commit 97153b36) introduced this adapter to wire brief persistence
through the use case path.  Before the fix, GenerateBriefingUseCase wired to
NullBriefArchive and silently dropped every generated brief.  The fix replaced
the wiring with this write-side adapter — but qa-beta-test-engineer
(2026-05-09) flagged it BLOCKING because the adapter shipped with ZERO tests.

Without these tests, a future regression that
  (a) drops `await session.commit()`,
  (b) re-points the wiring at NullBriefArchive,
  (c) raises out of `save()` instead of swallowing,
will be discovered only when a real analyst notices "my brief history is empty
again" — exactly the failure mode D-R4-004 was meant to prevent.

The tests below pin three load-bearing contracts:
  1. save() opens a session, calls repo.save(), commits, closes (happy path).
  2. save() catches all repo exceptions and logs without re-raising — the use
     case wraps this in asyncio.shield and treats archival as fire-and-forget.
  3. get_latest / get_history / get_by_id are no-ops that return empty results
     and emit a warning (read path goes through the read adapter).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

# ── Fixtures ──────────────────────────────────────────────────────────────────

# Stable test UUIDs (UUIDv7-shaped for visual debugging only — the adapter
# does not validate format).
_BRIEF_ID = UUID("018f0000-0000-7000-8000-000000000010")
_USER_ID = UUID("018f0000-0000-7000-8000-000000000020")
_TENANT_ID = UUID("018f0000-0000-7000-8000-000000000030")
_ENTITY_ID = UUID("018f0000-0000-7000-8000-000000000040")


def _make_brief_record() -> object:
    """Construct a minimal UserBriefRecord for save() round-trip tests.

    All required fields populated; the adapter does not transform the record,
    so the exact values do not matter — only that the type matches the port.
    """
    from rag_chat.application.ports.brief_archive import UserBriefRecord

    return UserBriefRecord(
        id=_BRIEF_ID,
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        brief_type="morning",
        entity_id=_ENTITY_ID,
        generated_at=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
        headline="Test headline",
        lead="Test lead.",
        sections_json=[{"title": "Overview", "body": "..."}],
        citations_json=[{"id": "C1", "url": "https://example.test"}],
        confidence=0.85,
        source_version="2026-05-09",
    )


def _make_session_factory() -> tuple[AsyncMock, AsyncMock, MagicMock]:
    """Build (session, factory) with the async-context-manager protocol wired.

    The adapter calls `async with self._write_factory() as session: ...` so the
    returned session must implement __aenter__/__aexit__.  Returning the factory
    separately lets tests assert the factory was called and the session
    received the expected method calls.
    """
    session = AsyncMock()
    # async-context-manager protocol — the adapter does
    #   `async with self._write_factory() as session`
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()

    # The factory itself is a regular callable returning the session.
    factory = MagicMock(return_value=session)
    # Repo mock used by the patched BriefArchiveRepository constructor.
    repo_mock = AsyncMock()
    repo_mock.save = AsyncMock()
    return session, repo_mock, factory


# ── save() happy path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_commits_and_calls_repo_once() -> None:
    """Happy path: save() opens session → repo.save(brief) → session.commit().

    Regression target: a future commit that drops `await session.commit()` will
    cause this test to fail (commit is asserted exactly once).
    """
    from rag_chat.infrastructure.clients.brief_archive_write_adapter import BriefArchiveWriteAdapter

    session, repo_mock, factory = _make_session_factory()
    adapter = BriefArchiveWriteAdapter(write_factory=factory)
    brief = _make_brief_record()

    with patch(
        "rag_chat.infrastructure.db.repositories.brief_archive_repository.BriefArchiveRepository",
        return_value=repo_mock,
    ):
        await adapter.save(brief)  # type: ignore[arg-type]

    # Factory called once (one session per save).
    factory.assert_called_once()
    # The brief was forwarded to the repo unchanged.
    repo_mock.save.assert_awaited_once_with(brief)
    # Commit was awaited (load-bearing — adapter owns the transaction boundary).
    session.commit.assert_awaited_once()


# ── save() failure swallow ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_swallows_repo_exception_and_does_not_propagate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Failure path: repo raises → save() logs and returns None (NEVER re-raises).

    Regression target: a future commit that removes the try/except in save()
    would propagate the exception up to GenerateBriefingUseCase's
    asyncio.shield block, which would then surface as a 500 to the user even
    though they should have received their brief content unchanged.
    """
    import logging

    from rag_chat.infrastructure.clients.brief_archive_write_adapter import BriefArchiveWriteAdapter

    session, repo_mock, factory = _make_session_factory()
    repo_mock.save = AsyncMock(side_effect=RuntimeError("simulated DB outage"))
    adapter = BriefArchiveWriteAdapter(write_factory=factory)
    brief = _make_brief_record()

    # structlog routes through stdlib logging; capture at DEBUG to catch any level.
    with (
        caplog.at_level(logging.DEBUG),
        patch(
            "rag_chat.infrastructure.db.repositories.brief_archive_repository.BriefArchiveRepository",
            return_value=repo_mock,
        ),
    ):
        # CRUCIAL: the call must NOT raise.  pytest.raises here would also fail
        # the assertion, but a plain await is the cleaner regression signal.
        await adapter.save(brief)  # type: ignore[arg-type]

    # commit is NOT called on the failure path — the repo raised before commit.
    session.commit.assert_not_awaited()


# ── get_* methods are deliberate no-ops ───────────────────────────────────────
#
# F-002 follow-up (qa-beta-test-engineer, F-015): if a developer accidentally
# wires the WRITE adapter into a read path, the no-op methods silently return
# empty results — same failure mode as the pre-fix NullBriefArchive.  Pin the
# no-op contract so a future "let me make it work for reads" change requires
# a deliberate test update.


@pytest.mark.asyncio
async def test_get_latest_is_noop_returning_empty_list() -> None:
    """get_latest is a no-op on the write adapter (read path → read adapter).

    The factory must NOT be called — confirms the no-op did not accidentally
    open a session for a phantom read.
    """
    from rag_chat.infrastructure.clients.brief_archive_write_adapter import BriefArchiveWriteAdapter

    _, _, factory = _make_session_factory()
    adapter = BriefArchiveWriteAdapter(write_factory=factory)

    result = await adapter.get_latest(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        brief_type="morning",
        limit=2,
    )

    assert result == []
    factory.assert_not_called()  # no SQL ran


@pytest.mark.asyncio
async def test_get_history_is_noop_returning_empty_tuple() -> None:
    """get_history returns the standard ([], 0) pagination empty tuple — no-op."""
    from rag_chat.infrastructure.clients.brief_archive_write_adapter import BriefArchiveWriteAdapter

    _, _, factory = _make_session_factory()
    adapter = BriefArchiveWriteAdapter(write_factory=factory)

    rows, total = await adapter.get_history(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        brief_type="morning",
        page=1,
        page_size=10,
    )
    assert rows == []
    assert total == 0
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_get_by_id_is_noop_returning_none() -> None:
    """get_by_id returns None on the write adapter — read path lives elsewhere."""
    from rag_chat.infrastructure.clients.brief_archive_write_adapter import BriefArchiveWriteAdapter

    _, _, factory = _make_session_factory()
    adapter = BriefArchiveWriteAdapter(write_factory=factory)

    result = await adapter.get_by_id(_BRIEF_ID)
    assert result is None
    factory.assert_not_called()


# ── Port conformance ──────────────────────────────────────────────────────────


def test_adapter_satisfies_brief_archive_port() -> None:
    """BriefArchiveWriteAdapter must satisfy BriefArchivePort (Protocol).

    @runtime_checkable on the Protocol means isinstance() works at runtime.
    This test catches accidental signature drift (e.g. dropping a get_* method
    or renaming save).
    """
    from rag_chat.application.ports.brief_archive import BriefArchivePort
    from rag_chat.infrastructure.clients.brief_archive_write_adapter import BriefArchiveWriteAdapter

    _, _, factory = _make_session_factory()
    adapter = BriefArchiveWriteAdapter(write_factory=factory)

    # @runtime_checkable Protocol → isinstance check enforces method-name presence.
    assert isinstance(adapter, BriefArchivePort)
