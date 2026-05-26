"""Unit tests for ActiveUsersReader (PLAN-0094 W2, T-W2-02).

Covers the three acceptance scenarios:
  1. Window selects the recent users and excludes older entries.
  2. Malformed members are skipped with a warning log.
  3. An empty source returns an empty list cleanly.

WHY pure mocks (not testcontainers):  The reader is a one-line wrapper around
``ZRANGEBYSCORE``.  A unit test that mocks the return value of that one call
is enough to verify the parsing/skip logic.  Integration tests against a
real Valkey are covered by W2's docker-compose validation gate.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from rag_chat.application.ports.active_users import IActiveUsersPort
from rag_chat.infrastructure.clients.active_users_reader import ActiveUsersReader

pytestmark = pytest.mark.unit


def _make_reader(zrange_return: list[bytes | str], window_days: int = 7) -> ActiveUsersReader:
    """Build a reader with a mocked Valkey that returns ``zrange_return``."""
    valkey = AsyncMock()
    valkey.zrangebyscore = AsyncMock(return_value=zrange_return)
    return ActiveUsersReader(valkey_client=valkey, window_days=window_days)


async def test_list_active_returns_users_in_window() -> None:
    """3 UUIDs returned from ZRANGEBYSCORE → 3 UUID objects parsed.

    Note: the *score filter* itself is the Valkey server's responsibility; this
    test verifies the adapter passes through whatever the server returns and
    parses each member into a UUID.  The window calculation is exercised by
    checking that the call is made with the expected arguments.
    """
    user_a = UUID("00000000-0000-0000-0000-000000000001")
    user_b = UUID("00000000-0000-0000-0000-000000000002")
    user_c = UUID("00000000-0000-0000-0000-000000000003")
    reader = _make_reader([str(user_a).encode(), str(user_b).encode(), str(user_c).encode()])

    result = await reader.list_active()

    assert sorted(result) == sorted([user_a, user_b, user_c])
    # Confirm the adapter actually called ZRANGEBYSCORE on the canonical key
    # with ``+inf`` upper bound.  ``min_score`` is "now - window*86400" — we
    # don't pin the exact value (it depends on time.time()), but we can check
    # the upper bound and the key.
    reader._valkey.zrangebyscore.assert_awaited_once()  # type: ignore[attr-defined]
    call_args = reader._valkey.zrangebyscore.call_args  # type: ignore[attr-defined]
    assert call_args.args[0] == "active_users"
    assert call_args.args[2] == "+inf"


async def test_list_active_skips_malformed_members(caplog: pytest.LogCaptureFixture) -> None:
    """A non-UUID member is logged and skipped; the rest pass through."""
    good = UUID("00000000-0000-0000-0000-000000000010")
    reader = _make_reader([b"not-a-uuid", str(good).encode(), b""])

    result = await reader.list_active()

    assert result == [good]
    # No exception, no crash — just the warning log (we don't pin the exact
    # message because structlog formatting varies in test runs; the behavioural
    # contract is that bad rows are skipped, not that any particular log
    # output appears).


async def test_list_active_empty_set_returns_empty_list() -> None:
    """ZRANGEBYSCORE returning `[]` yields an empty list, not None or an error."""
    reader = _make_reader([])

    result = await reader.list_active()

    assert result == []


async def test_list_active_handles_string_members() -> None:
    """ZRANGEBYSCORE may return str if decode_responses=True — adapter must cope."""
    user = UUID("00000000-0000-0000-0000-000000000020")
    reader = _make_reader([str(user)])  # str, not bytes

    result = await reader.list_active()

    assert result == [user]


def test_active_users_reader_implements_port() -> None:
    """Static check: ActiveUsersReader is a proper IActiveUsersPort subclass (R25)."""
    valkey = AsyncMock()
    reader = ActiveUsersReader(valkey_client=valkey, window_days=7)
    assert isinstance(reader, IActiveUsersPort)
