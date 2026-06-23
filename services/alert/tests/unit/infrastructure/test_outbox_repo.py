"""Tests for alert OutboxRepository — BUG-3 failed-record retry reachability.

Root cause (docs/audits/2026-06-22-dead-letter-backlog-rootcause.md): the alert
outbox had the IDENTICAL bug as nlp-pipeline — ``mark_failed`` set
``status=FAILED`` while ``fetch_pending`` only selected ``PENDING``, so a record
that failed ONE delivery was permanently stranded (no retry, silent loss).

These tests prove (a) a failed-but-not-exhausted record is re-claimable (retry
REACHABLE) and (b) it flips to terminal ``FAILED`` only at MAX_DISPATCH_ATTEMPTS
(CAPPED). The repo uses a server-side CASE so the decision is race-free.

``OutboxStatus`` is a ``StrEnum`` with no SQLAlchemy literal-bind renderer, so we
inspect the compiled SQL structure plus the bound parameter values (rather than
``literal_binds=True``, which raises a CompileError for the enum).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from alert.infrastructure.db.repositories.outbox import (
    MAX_DISPATCH_ATTEMPTS,
    OutboxRepository,
)
from sqlalchemy.dialects import postgresql

pytestmark = pytest.mark.unit

_FIXED_ID = UUID("12345678-0000-0000-0000-000000000099")


def _make_session() -> tuple[MagicMock, list[Any]]:
    """Return (session mock, list of executed statements)."""
    executed: list[Any] = []

    async def _fake_execute(stmt: Any, *args: Any, **kwargs: Any) -> MagicMock:
        executed.append(stmt)
        return MagicMock()

    session = MagicMock()
    session.execute = _fake_execute
    return session, executed


def _compiled(stmt: Any) -> Any:
    """Compile to the postgres dialect (bind params preserved)."""
    return stmt.compile(dialect=postgresql.dialect())


@pytest.mark.asyncio
async def test_fetch_pending_includes_failed_pending_after_backoff() -> None:
    """fetch_pending must re-select failed-but-pending rows (retry REACHABLE).

    The claim WHERE clause must admit fresh (``failed_at IS NULL``) and
    backed-off rows so a record ``mark_failed`` kept ``pending`` is retried.
    """
    session, executed = _make_session()
    repo = OutboxRepository(session)

    await repo.fetch_pending(batch_size=10)

    sql = str(_compiled(executed[0]))
    assert "status =" in sql
    assert "failed_at IS NULL" in sql
    assert "failed_at <=" in sql
    assert " OR " in sql


@pytest.mark.asyncio
async def test_mark_failed_uses_case_to_stay_pending_below_cap() -> None:
    """mark_failed must keep the record 'pending' below the cap (no silent loss).

    The UPDATE must use a server-side CASE; its branch values are the
    ``OutboxStatus`` strings 'failed' (terminal, at the cap) and 'pending'
    (retry, below the cap). The cap (MAX_DISPATCH_ATTEMPTS) appears in the CASE
    predicate.
    """
    session, executed = _make_session()
    repo = OutboxRepository(session)

    await repo.mark_failed(_FIXED_ID)

    compiled = _compiled(executed[0])
    sql = str(compiled).upper()
    assert "CASE" in sql, "decision must be a server-side CASE (race-free)"
    assert "WHEN" in sql

    # The CASE branch values + the cap are carried as bound parameters.
    param_values = set(compiled.params.values())
    assert "failed" in param_values, "CASE must flip to terminal 'failed' at the cap"
    assert "pending" in param_values, "below-cap path must keep the record 'pending'"
    assert MAX_DISPATCH_ATTEMPTS in param_values, "cap must appear in the CASE predicate"


@pytest.mark.asyncio
async def test_mark_failed_increments_retry_count_and_stamps_failed_at() -> None:
    """mark_failed must increment retry_count and stamp failed_at (backoff anchor)."""
    session, executed = _make_session()
    repo = OutboxRepository(session)

    await repo.mark_failed(_FIXED_ID)

    sql = str(_compiled(executed[0])).lower()
    assert "retry_count" in sql
    assert "failed_at" in sql


def test_max_dispatch_attempts_value() -> None:
    """Alert cap must be 5 (BUG-3 parity with nlp-pipeline)."""
    assert MAX_DISPATCH_ATTEMPTS == 5
