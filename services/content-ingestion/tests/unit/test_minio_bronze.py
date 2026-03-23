"""Unit tests for MinioBronzeAdapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.exceptions import StorageError
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter

pytestmark = pytest.mark.unit

_KEY = "content-ingestion/eodhd/abc123/raw/v1.json"
_DATA = b'{"url": "https://example.com/news"}'


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.MINIO_BUCKET = "worldview-bronze"
    return settings


class TestMinioBronzeAdapter:
    async def test_put_object_calls_client(self) -> None:
        """put_object wraps sync client.put_object via asyncio.to_thread."""
        client = MagicMock()
        adapter = MinioBronzeAdapter(client=client, settings=_make_settings())

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = None
            await adapter.put_object(key=_KEY, data=_DATA)

        mock_to_thread.assert_awaited_once()
        call_args = mock_to_thread.await_args
        assert call_args.args[0] == client.put_object
        assert call_args.args[1] == "worldview-bronze"
        assert call_args.args[2] == _KEY

    async def test_put_object_raises_storage_error_on_failure(self) -> None:
        """StorageError wraps client exceptions."""
        client = MagicMock()
        adapter = MinioBronzeAdapter(client=client, settings=_make_settings())

        with (
            patch("asyncio.to_thread", new_callable=AsyncMock, side_effect=RuntimeError("conn refused")),
            pytest.raises(StorageError, match="conn refused"),
        ):
            await adapter.put_object(key=_KEY, data=_DATA)

    async def test_object_exists_returns_true_when_found(self) -> None:
        """object_exists returns True if stat_object succeeds."""
        client = MagicMock()
        adapter = MinioBronzeAdapter(client=client, settings=_make_settings())

        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=MagicMock()):
            result = await adapter.object_exists(_KEY)

        assert result is True

    async def test_object_exists_returns_false_when_not_found(self) -> None:
        """object_exists returns False if stat_object raises (key absent)."""
        client = MagicMock()
        adapter = MinioBronzeAdapter(client=client, settings=_make_settings())

        with patch("asyncio.to_thread", new_callable=AsyncMock, side_effect=Exception("NoSuchKey")):
            result = await adapter.object_exists(_KEY)

        assert result is False
