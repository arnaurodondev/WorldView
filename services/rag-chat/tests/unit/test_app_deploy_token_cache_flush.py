"""Unit tests for the rag-chat deploy-version cache flush startup hook.

PLAN-0097 W4 T-W4-04. Covers ``_maybe_flush_completion_cache``:

  1. Disabled (empty token)              → no Valkey calls.
  2. Stored token equal                  → no flush.
  3. Stored token differs (or unset)     → delete_pattern called + token set.
  4. Valkey GET failure                  → no crash, no flush.
  5. Valkey delete_pattern failure       → no crash, no token persisted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from rag_chat.app import (
    _COMPLETION_CACHE_PATTERN,
    _DEPLOY_TOKEN_KEY,
    _maybe_flush_completion_cache,
)

pytestmark = pytest.mark.unit


def _make_valkey(
    get_return: str | None = None,
    *,
    raise_on_get: bool = False,
    raise_on_delete: bool = False,
    raise_on_set: bool = False,
) -> MagicMock:
    """Build an AsyncMock-shaped ValkeyClient matching the methods used."""
    valkey = MagicMock()
    if raise_on_get:
        valkey.get = AsyncMock(side_effect=RuntimeError("valkey down"))
    else:
        valkey.get = AsyncMock(return_value=get_return)
    if raise_on_delete:
        valkey.delete_pattern = AsyncMock(side_effect=RuntimeError("scan failed"))
    else:
        valkey.delete_pattern = AsyncMock(return_value=42)
    if raise_on_set:
        valkey.set = AsyncMock(side_effect=RuntimeError("set failed"))
    else:
        valkey.set = AsyncMock()
    return valkey


def _make_log() -> MagicMock:
    log = MagicMock()
    log.info = MagicMock()
    log.warning = MagicMock()
    log.debug = MagicMock()
    return log


class TestDeployTokenCacheFlush:
    @pytest.mark.asyncio
    async def test_empty_token_is_noop(self) -> None:
        """When the deploy token is empty, the helper must not touch Valkey at all."""
        valkey = _make_valkey()
        log = _make_log()

        await _maybe_flush_completion_cache(valkey, "", log)

        valkey.get.assert_not_called()
        valkey.delete_pattern.assert_not_called()
        valkey.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_stored_token_equal_skips_flush(self) -> None:
        """When the stored token matches the current deploy token, do not flush."""
        valkey = _make_valkey(get_return="deploy-123")
        log = _make_log()

        await _maybe_flush_completion_cache(valkey, "deploy-123", log)

        valkey.get.assert_awaited_once_with(_DEPLOY_TOKEN_KEY)
        valkey.delete_pattern.assert_not_called()
        valkey.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_changed_token_triggers_flush(self) -> None:
        """When the stored token differs, delete_pattern + set must be called."""
        valkey = _make_valkey(get_return="old-token")
        log = _make_log()

        await _maybe_flush_completion_cache(valkey, "new-token", log)

        valkey.get.assert_awaited_once_with(_DEPLOY_TOKEN_KEY)
        valkey.delete_pattern.assert_awaited_once_with(_COMPLETION_CACHE_PATTERN)
        valkey.set.assert_awaited_once_with(_DEPLOY_TOKEN_KEY, "new-token")
        # An INFO log line should record the flush; assert it was emitted.
        assert log.info.called

    @pytest.mark.asyncio
    async def test_unset_stored_token_triggers_flush(self) -> None:
        """First observation (Valkey GET → None) must trigger the flush path."""
        valkey = _make_valkey(get_return=None)
        log = _make_log()

        await _maybe_flush_completion_cache(valkey, "first-deploy", log)

        valkey.delete_pattern.assert_awaited_once_with(_COMPLETION_CACHE_PATTERN)
        valkey.set.assert_awaited_once_with(_DEPLOY_TOKEN_KEY, "first-deploy")

    @pytest.mark.asyncio
    async def test_valkey_get_failure_does_not_crash(self) -> None:
        """A Valkey GET error must be swallowed and skip the flush — never crash startup."""
        valkey = _make_valkey(raise_on_get=True)
        log = _make_log()

        # Must NOT raise.
        await _maybe_flush_completion_cache(valkey, "any-token", log)

        valkey.delete_pattern.assert_not_called()
        valkey.set.assert_not_called()
        log.warning.assert_called()

    @pytest.mark.asyncio
    async def test_delete_pattern_failure_does_not_persist_token(self) -> None:
        """If delete_pattern raises, we must NOT persist the new token (so next
        startup retries the flush). Startup must still proceed cleanly.
        """
        valkey = _make_valkey(get_return="old", raise_on_delete=True)
        log = _make_log()

        await _maybe_flush_completion_cache(valkey, "new", log)

        valkey.delete_pattern.assert_awaited_once()
        valkey.set.assert_not_called()
        log.warning.assert_called()
