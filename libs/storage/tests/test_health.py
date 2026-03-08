"""Tests for storage.health (check_storage_health)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from storage.exceptions import BucketNotFoundError, StorageUnavailableError
from storage.health import check_storage_health


class TestCheckStorageHealth:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        store = MagicMock()
        store.list_keys = AsyncMock(return_value=[])
        result = await check_storage_health(store, "worldview")
        assert result is True
        store.list_keys.assert_awaited_once_with("worldview", prefix="__health__")

    @pytest.mark.asyncio
    async def test_returns_false_on_storage_error(self) -> None:
        store = MagicMock()
        store.list_keys = AsyncMock(side_effect=StorageUnavailableError("down"))
        result = await check_storage_health(store, "worldview")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_bucket_not_found(self) -> None:
        store = MagicMock()
        store.list_keys = AsyncMock(side_effect=BucketNotFoundError("no bucket"))
        result = await check_storage_health(store, "worldview")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_unexpected_exception(self) -> None:
        store = MagicMock()
        store.list_keys = AsyncMock(side_effect=RuntimeError("unexpected"))
        result = await check_storage_health(store, "worldview")
        assert result is False

    @pytest.mark.asyncio
    async def test_never_raises(self) -> None:
        store = MagicMock()
        store.list_keys = AsyncMock(side_effect=Exception("anything"))
        # Must not propagate
        result = await check_storage_health(store, "test")
        assert result is False
