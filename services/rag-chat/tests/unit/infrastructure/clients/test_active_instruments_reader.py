"""Unit tests for ActiveInstrumentsReader (AI-brief-flag fix, 2026-06-19).

Covers the active-window cutoff computation, byte/str normalisation, and
error-degradation, mirroring the ActiveUsersReader test surface.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from rag_chat.infrastructure.clients.active_instruments_reader import (
    ACTIVE_INSTRUMENTS_KEY,
    ActiveInstrumentsReader,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_queries_correct_key_and_window() -> None:
    """ZRANGEBYSCORE is called on the right key with a min-score = now - window."""
    valkey = MagicMock()
    valkey.zrangebyscore = AsyncMock(return_value=["e1", "e2"])

    reader = ActiveInstrumentsReader(valkey_client=valkey, window_days=7)
    result = await reader.list_active()

    assert result == ["e1", "e2"]
    valkey.zrangebyscore.assert_awaited_once()
    args = valkey.zrangebyscore.await_args.args
    assert args[0] == ACTIVE_INSTRUMENTS_KEY
    # min_score should be ~ now - 7*86400 (allow a few seconds of clock drift).
    expected_min = int(time.time()) - 7 * 86400
    assert abs(args[1] - expected_min) <= 5
    assert args[2] == "+inf"


@pytest.mark.asyncio
async def test_normalises_bytes_members() -> None:
    """Members returned as bytes are decoded to str."""
    valkey = MagicMock()
    valkey.zrangebyscore = AsyncMock(return_value=[b"e1", "e2"])

    reader = ActiveInstrumentsReader(valkey_client=valkey, window_days=1)
    assert await reader.list_active() == ["e1", "e2"]


@pytest.mark.asyncio
async def test_empty_set_returns_empty_list() -> None:
    valkey = MagicMock()
    valkey.zrangebyscore = AsyncMock(return_value=[])
    reader = ActiveInstrumentsReader(valkey_client=valkey, window_days=7)
    assert await reader.list_active() == []


@pytest.mark.asyncio
async def test_valkey_error_degrades_to_empty() -> None:
    """A Valkey error degrades to [] (the pass does no work rather than crashing)."""
    valkey = MagicMock()
    valkey.zrangebyscore = AsyncMock(side_effect=RuntimeError("valkey down"))
    reader = ActiveInstrumentsReader(valkey_client=valkey, window_days=7)
    assert await reader.list_active() == []
