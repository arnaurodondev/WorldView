"""Tests for storage.interface (ObjectStorage ABC)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from storage.interface import ObjectStorage


class ConcreteStorage(ObjectStorage):
    """Minimal concrete implementation for testing the ABC's helper methods."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], bytes] = {}

    async def put_bytes(
        self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self._data[(bucket, key)] = data

    async def get_bytes(self, bucket: str, key: str) -> bytes:
        return self._data[(bucket, key)]

    async def delete(self, bucket: str, key: str) -> None:
        self._data.pop((bucket, key), None)

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        return [k for (b, k) in self._data if b == bucket and k.startswith(prefix)]

    async def exists(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self._data

    async def delete_prefix(self, bucket: str, prefix: str) -> int:
        keys = [k for (b, k) in list(self._data) if b == bucket and k.startswith(prefix)]
        for k in keys:
            del self._data[(bucket, k)]
        return len(keys)


class TestObjectStorageABC:
    def test_cannot_instantiate_abstract_class(self) -> None:
        with pytest.raises(TypeError):
            ObjectStorage()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        store = ConcreteStorage()
        assert store is not None


class TestPutGetBytes:
    @pytest.mark.asyncio
    async def test_put_and_get_bytes(self) -> None:
        store = ConcreteStorage()
        await store.put_bytes("bucket", "key/v1.bin", b"hello")
        result = await store.get_bytes("bucket", "key/v1.bin")
        assert result == b"hello"

    @pytest.mark.asyncio
    async def test_put_overwrites_existing(self) -> None:
        store = ConcreteStorage()
        await store.put_bytes("b", "k", b"first")
        await store.put_bytes("b", "k", b"second")
        assert await store.get_bytes("b", "k") == b"second"


class TestPutGetJson:
    @pytest.mark.asyncio
    async def test_put_json_stores_serialised_bytes(self) -> None:
        store = ConcreteStorage()
        await store.put_json("b", "k", {"a": 1, "b": [2, 3]})
        raw = store._data[("b", "k")]
        assert json.loads(raw) == {"a": 1, "b": [2, 3]}

    @pytest.mark.asyncio
    async def test_get_json_deserialises(self) -> None:
        store = ConcreteStorage()
        await store.put_json("b", "k", {"x": "hello"})
        result = await store.get_json("b", "k")
        assert result == {"x": "hello"}

    @pytest.mark.asyncio
    async def test_put_json_uses_application_json_content_type(self) -> None:
        store = ConcreteStorage()
        put_mock = AsyncMock()
        store.put_bytes = put_mock  # type: ignore[method-assign]
        await store.put_json("b", "k", {"a": 1})
        put_mock.assert_awaited_once()
        # content_type is passed as keyword arg
        assert put_mock.call_args.kwargs.get("content_type") == "application/json"

    @pytest.mark.asyncio
    async def test_get_json_raises_on_invalid_json(self) -> None:
        store = ConcreteStorage()
        store._data[("b", "k")] = b"not-json"
        with pytest.raises(json.JSONDecodeError):
            await store.get_json("b", "k")


class TestExists:
    @pytest.mark.asyncio
    async def test_exists_true_after_put(self) -> None:
        store = ConcreteStorage()
        await store.put_bytes("b", "k", b"data")
        assert await store.exists("b", "k") is True

    @pytest.mark.asyncio
    async def test_exists_false_when_absent(self) -> None:
        store = ConcreteStorage()
        assert await store.exists("b", "absent") is False


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_key(self) -> None:
        store = ConcreteStorage()
        await store.put_bytes("b", "k", b"data")
        await store.delete("b", "k")
        assert await store.exists("b", "k") is False

    @pytest.mark.asyncio
    async def test_delete_prefix_removes_matching_keys(self) -> None:
        store = ConcreteStorage()
        await store.put_bytes("b", "svc/dom/r/art/v1.parquet", b"a")
        await store.put_bytes("b", "svc/dom/r/art/v2.parquet", b"b")
        await store.put_bytes("b", "other/key/v1.json", b"c")
        count = await store.delete_prefix("b", "svc/")
        assert count == 2
        assert await store.exists("b", "other/key/v1.json") is True

    @pytest.mark.asyncio
    async def test_delete_prefix_returns_zero_when_no_match(self) -> None:
        store = ConcreteStorage()
        count = await store.delete_prefix("b", "nonexistent/")
        assert count == 0


class TestListKeys:
    @pytest.mark.asyncio
    async def test_list_keys_empty(self) -> None:
        store = ConcreteStorage()
        assert await store.list_keys("b") == []

    @pytest.mark.asyncio
    async def test_list_keys_with_prefix(self) -> None:
        store = ConcreteStorage()
        await store.put_bytes("b", "svc/dom/k1/v1.bin", b"a")
        await store.put_bytes("b", "svc/dom/k2/v1.bin", b"b")
        await store.put_bytes("b", "other/k3/v1.bin", b"c")
        keys = await store.list_keys("b", "svc/")
        assert set(keys) == {"svc/dom/k1/v1.bin", "svc/dom/k2/v1.bin"}
