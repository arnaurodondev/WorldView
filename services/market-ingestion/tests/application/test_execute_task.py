"""Tests for ExecuteTaskUseCase (T-MI-12). ≥12 test functions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import (
    ProviderAuthError,
    ProviderDataError,
    ProviderRateLimited,
    ProviderUnavailable,
    StorageUnavailable,
    WatermarkViolation,
)
from market_ingestion.domain.value_objects import ObjectRef

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ohlcv_json() -> bytes:
    return json.dumps([{"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100}]).encode()


def _quotes_json() -> bytes:
    return json.dumps([{"bid": 1.0, "ask": 1.01, "mid": 1.005}]).encode()


def _fundamentals_json() -> bytes:
    return json.dumps({"revenue": 1_000_000, "net_income": 100_000}).encode()


def _fetch_result(raw_data: bytes = b"", content_type: str = "application/json") -> MagicMock:
    fr = MagicMock()
    fr.raw_data = raw_data or _ohlcv_json()
    fr.content_type = content_type
    fr.fetched_at = datetime.now(UTC)
    fr.duration_ms = 50
    return fr


def _object_ref(sha256: str = "deadbeef" * 8, bucket: str = "b", key: str = "k") -> ObjectRef:
    return ObjectRef(bucket=bucket, key=key, sha256=sha256, byte_length=128, mime_type="application/octet-stream")


def _make_task(
    dataset_type: DatasetType = DatasetType.OHLCV,
    provider: Provider = Provider.EODHD,
    symbol: str = "AAPL",
    exchange: str | None = "US",
    timeframe: str | None = "1d",
    variant: str | None = None,
    range_end: datetime | None = None,
) -> MagicMock:
    task = MagicMock()
    task.id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    task.provider = provider
    task.dataset_type = dataset_type
    task.symbol = symbol
    task.exchange = exchange
    task.timeframe = timeframe
    task.variant = variant
    task.range_start = None
    task.range_end = range_end or datetime.now(UTC)
    task.succeed = MagicMock()
    task.retry = MagicMock()
    task.fail = MagicMock()
    return task


def _make_watermark(changed: bool = True) -> MagicMock:
    wm = MagicMock()
    wm.current_bar_ts = None
    wm.content_hash = None
    wm.advance_bar_ts = MagicMock()  # sync; raises WatermarkViolation when patched
    wm.has_changed = MagicMock(return_value=changed)
    return wm


def _make_uow(watermark: MagicMock | None = None) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()

    wm = watermark or _make_watermark()
    uow.watermarks = MagicMock()
    uow.watermarks.get_or_create = AsyncMock(return_value=wm)
    uow.watermarks.save = AsyncMock()

    uow.outbox = MagicMock()
    uow.outbox.add = AsyncMock()

    uow.tasks = MagicMock()
    uow.tasks.save = AsyncMock()

    return uow


def _make_store(sha256: str = "deadbeef" * 8, *, bronze_side_effect=None, canonical_side_effect=None) -> MagicMock:
    store = MagicMock()
    bronze_ref = _object_ref(sha256=sha256, bucket="market-bronze", key="bronze/key")
    canonical_ref = _object_ref(sha256=sha256, bucket="market-canonical", key="canonical/key")

    if bronze_side_effect:
        store.put = AsyncMock(side_effect=[bronze_side_effect])
    elif canonical_side_effect:
        store.put = AsyncMock(side_effect=[bronze_ref, canonical_side_effect])
    else:
        store.put = AsyncMock(side_effect=[bronze_ref, canonical_ref])

    store.get = AsyncMock(return_value=b"data")
    store.exists = AsyncMock(return_value=False)
    return store


def _make_serializer() -> MagicMock:
    s = MagicMock()
    s.serialize_ohlcv = MagicMock(return_value=b'{"bar": 1}\n')
    s.serialize_quotes = MagicMock(return_value=b'{"bid": 1.0}\n')
    s.serialize_fundamentals = MagicMock(return_value=b'{"revenue": 1000}\n')
    return s


def _make_registry(*, raw_data: bytes | None = None, fetch_side_effect=None) -> MagicMock:
    adapter = MagicMock()
    fr = _fetch_result(raw_data=raw_data or _ohlcv_json())
    if fetch_side_effect:
        adapter.fetch_ohlcv = AsyncMock(side_effect=fetch_side_effect)
        adapter.fetch_quotes = AsyncMock(side_effect=fetch_side_effect)
        adapter.fetch_fundamentals = AsyncMock(side_effect=fetch_side_effect)
    else:
        adapter.fetch_ohlcv = AsyncMock(return_value=fr)
        adapter.fetch_quotes = AsyncMock(return_value=fr)
        adapter.fetch_fundamentals = AsyncMock(return_value=fr)
    registry = MagicMock()
    registry.get = MagicMock(return_value=adapter)
    return registry


def _make_use_case(
    uow=None,
    registry=None,
    store=None,
    serializer=None,
) -> tuple[ExecuteTaskUseCase, MagicMock, MagicMock, MagicMock, MagicMock]:
    uow = uow or _make_uow()
    registry = registry or _make_registry()
    store = store or _make_store()
    serializer = serializer or _make_serializer()
    uc = ExecuteTaskUseCase(
        uow=uow,
        provider_registry=registry,
        object_store=store,
        serializer=serializer,
        bronze_bucket="market-bronze",
        canonical_bucket="market-canonical",
    )
    return uc, uow, registry, store, serializer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_happy_path_ohlcv_end_to_end() -> None:
    """Full 5-step pipeline: fetch → bronze → canonical → watermark → outbox → succeed."""
    task = _make_task(dataset_type=DatasetType.OHLCV)
    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    uc, uow, registry, store, serializer = _make_use_case(uow=uow)

    await uc.execute(task)

    # Step 1: fetched via correct method
    registry.get(task.provider).fetch_ohlcv.assert_awaited_once()

    # Step 2 & 4: put called twice (bronze + canonical)
    assert store.put.await_count == 2

    # Step 3: serializer called
    serializer.serialize_ohlcv.assert_called_once()

    # Step 5: watermark advanced, outbox added, task succeeded
    wm.advance_bar_ts.assert_called_once()
    uow.outbox.add.assert_awaited_once()
    task.succeed.assert_called_once()
    uow.commit.assert_awaited()


@pytest.mark.unit
async def test_provider_rate_limited_retries_task() -> None:
    """ProviderRateLimited → task.retry() called, exception propagates."""
    task = _make_task()
    exc = ProviderRateLimited("rate limit hit")
    uc, uow, _, _, _ = _make_use_case(registry=_make_registry(fetch_side_effect=exc))

    with pytest.raises(ProviderRateLimited):
        await uc.execute(task)

    task.retry.assert_called_once_with(exc)
    uow.tasks.save.assert_awaited()
    uow.commit.assert_awaited()


@pytest.mark.unit
async def test_provider_unavailable_retries_task() -> None:
    """ProviderUnavailable → task.retry() called, exception propagates."""
    task = _make_task()
    exc = ProviderUnavailable("service unavailable")
    uc, uow, _, _, _ = _make_use_case(registry=_make_registry(fetch_side_effect=exc))

    with pytest.raises(ProviderUnavailable):
        await uc.execute(task)

    task.retry.assert_called_once_with(exc)


@pytest.mark.unit
async def test_provider_auth_error_fails_task() -> None:
    """ProviderAuthError → task.fail() called (fatal), exception propagates."""
    task = _make_task()
    exc = ProviderAuthError("bad credentials")
    uc, uow, _, _, _ = _make_use_case(registry=_make_registry(fetch_side_effect=exc))

    with pytest.raises(ProviderAuthError):
        await uc.execute(task)

    task.fail.assert_called_once_with(exc)
    task.retry.assert_not_called()


@pytest.mark.unit
async def test_provider_data_error_fails_task() -> None:
    """ProviderDataError → task.fail() called (fatal), exception propagates."""
    task = _make_task()
    exc = ProviderDataError("malformed response")
    uc, uow, _, _, _ = _make_use_case(registry=_make_registry(fetch_side_effect=exc))

    with pytest.raises(ProviderDataError):
        await uc.execute(task)

    task.fail.assert_called_once_with(exc)
    task.retry.assert_not_called()


@pytest.mark.unit
async def test_storage_unavailable_on_bronze_retries_task() -> None:
    """StorageUnavailable on bronze store → task.retry(), exception propagates."""
    task = _make_task()
    exc = StorageUnavailable("s3 down")
    store = _make_store(bronze_side_effect=exc)
    uc, uow, _, _, _ = _make_use_case(store=store)

    with pytest.raises(StorageUnavailable):
        await uc.execute(task)

    task.retry.assert_called_once_with(exc)
    task.fail.assert_not_called()


@pytest.mark.unit
async def test_storage_unavailable_on_canonical_retries_task() -> None:
    """StorageUnavailable on canonical store → task.retry(), exception propagates."""
    task = _make_task()
    exc = StorageUnavailable("s3 canonical shard down")
    store = _make_store(canonical_side_effect=exc)
    uc, uow, _, _, _ = _make_use_case(store=store)

    with pytest.raises(StorageUnavailable):
        await uc.execute(task)

    task.retry.assert_called_once_with(exc)
    task.fail.assert_not_called()


@pytest.mark.unit
async def test_unchanged_sha256_skips_outbox() -> None:
    """If watermark.has_changed() returns False, outbox.add() is NOT called."""
    task = _make_task()
    wm = _make_watermark(changed=False)
    uow = _make_uow(watermark=wm)
    uc, uow, _, _, _ = _make_use_case(uow=uow)

    await uc.execute(task)

    uow.outbox.add.assert_not_awaited()
    task.succeed.assert_called_once()  # pipeline still completes


@pytest.mark.unit
async def test_changed_sha256_adds_outbox_event() -> None:
    """If watermark.has_changed() returns True, outbox.add() IS called."""
    task = _make_task()
    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    uc, uow, _, _, _ = _make_use_case(uow=uow)

    await uc.execute(task)

    uow.outbox.add.assert_awaited_once()


@pytest.mark.unit
async def test_watermark_advanced_with_range_end() -> None:
    """Watermark.advance_bar_ts() is called with task.range_end when set."""
    range_end = datetime(2024, 6, 30, tzinfo=UTC)
    task = _make_task(range_end=range_end)
    wm = _make_watermark()
    uow = _make_uow(watermark=wm)
    uc, _, _, _, _ = _make_use_case(uow=uow)

    await uc.execute(task)

    wm.advance_bar_ts.assert_called_once_with(range_end)


@pytest.mark.unit
async def test_watermark_violation_fails_task_and_propagates() -> None:
    """WatermarkViolation from advance_bar_ts propagates without persisting fail/retry state."""
    task = _make_task()
    wm = _make_watermark()
    wm.advance_bar_ts.side_effect = WatermarkViolation("non-monotonic advance")
    uow = _make_uow(watermark=wm)
    uc, _, _, _, _ = _make_use_case(uow=uow)

    with pytest.raises(WatermarkViolation):
        await uc.execute(task)

    task.fail.assert_not_called()
    task.retry.assert_not_called()


@pytest.mark.unit
async def test_ohlcv_uses_fetch_ohlcv_and_serialize_ohlcv() -> None:
    """DatasetType.OHLCV routes to fetch_ohlcv() and serialize_ohlcv()."""
    task = _make_task(dataset_type=DatasetType.OHLCV)
    registry = _make_registry(raw_data=_ohlcv_json())
    serializer = _make_serializer()
    uc, _, registry, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    registry.get(task.provider).fetch_ohlcv.assert_awaited_once()
    registry.get(task.provider).fetch_quotes.assert_not_awaited()
    registry.get(task.provider).fetch_fundamentals.assert_not_awaited()
    serializer.serialize_ohlcv.assert_called_once()
    serializer.serialize_quotes.assert_not_called()
    serializer.serialize_fundamentals.assert_not_called()


@pytest.mark.unit
async def test_quotes_uses_fetch_quotes_and_serialize_quotes() -> None:
    """DatasetType.QUOTES routes to fetch_quotes() and serialize_quotes()."""
    task = _make_task(dataset_type=DatasetType.QUOTES)
    registry = _make_registry(raw_data=_quotes_json())
    serializer = _make_serializer()
    uc, _, registry, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    registry.get(task.provider).fetch_quotes.assert_awaited_once()
    registry.get(task.provider).fetch_ohlcv.assert_not_awaited()
    serializer.serialize_quotes.assert_called_once()
    serializer.serialize_ohlcv.assert_not_called()
    serializer.serialize_fundamentals.assert_not_called()


@pytest.mark.unit
async def test_fundamentals_uses_fetch_fundamentals_and_serialize_fundamentals() -> None:
    """DatasetType.FUNDAMENTALS routes to fetch_fundamentals() and serialize_fundamentals()."""
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS, variant="annual")
    registry = _make_registry(raw_data=_fundamentals_json())
    serializer = _make_serializer()
    uc, _, registry, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    registry.get(task.provider).fetch_fundamentals.assert_awaited_once()
    registry.get(task.provider).fetch_ohlcv.assert_not_awaited()
    registry.get(task.provider).fetch_quotes.assert_not_awaited()
    serializer.serialize_fundamentals.assert_called_once()
    serializer.serialize_ohlcv.assert_not_called()
    serializer.serialize_quotes.assert_not_called()


@pytest.mark.unit
async def test_fundamentals_enriches_with_required_fields() -> None:
    """Verify enriched dict has symbol, exchange, period, report_date."""
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS, variant="annual", exchange="US", symbol="AAPL")
    registry = _make_registry(raw_data=_fundamentals_json())
    serializer = _make_serializer()
    uc, _, _, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    # Verify serialize_fundamentals was called with enriched data
    call_args = serializer.serialize_fundamentals.call_args
    enriched_data = call_args[0][0]

    assert enriched_data["symbol"] == "AAPL"
    assert enriched_data["exchange"] == "US"
    assert enriched_data["period"] == "annual"
    assert "report_date" in enriched_data


@pytest.mark.unit
async def test_fundamentals_variant_none_defaults_to_annual() -> None:
    """When variant is None, period should be 'annual'."""
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS, variant=None)
    registry = _make_registry(raw_data=_fundamentals_json())
    serializer = _make_serializer()
    uc, _, _, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    call_args = serializer.serialize_fundamentals.call_args
    enriched_data = call_args[0][0]
    assert enriched_data["period"] == "annual"


@pytest.mark.unit
async def test_fundamentals_exchange_none_becomes_empty_string() -> None:
    """When exchange is None, it should be empty string."""
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS, exchange=None)
    registry = _make_registry(raw_data=_fundamentals_json())
    serializer = _make_serializer()
    uc, _, _, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    call_args = serializer.serialize_fundamentals.call_args
    enriched_data = call_args[0][0]
    assert enriched_data["exchange"] == ""


@pytest.mark.unit
async def test_fundamentals_report_date_generated_when_missing() -> None:
    """When report_date missing from raw data, should be auto-generated."""
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS)
    registry = _make_registry(raw_data=_fundamentals_json())  # no report_date
    serializer = _make_serializer()
    uc, _, _, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    call_args = serializer.serialize_fundamentals.call_args
    enriched_data = call_args[0][0]

    assert "report_date" in enriched_data
    # Verify it's a valid ISO format datetime string
    from datetime import datetime

    datetime.fromisoformat(enriched_data["report_date"])


@pytest.mark.unit
async def test_fundamentals_report_date_preserved_when_present() -> None:
    """When report_date already in raw data, should be preserved."""
    raw_date = "2023-12-31T00:00:00"
    raw_data = json.dumps({"revenue": 1_000_000, "report_date": raw_date}).encode()
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS)
    registry = _make_registry(raw_data=raw_data)
    serializer = _make_serializer()
    uc, _, _, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    call_args = serializer.serialize_fundamentals.call_args
    enriched_data = call_args[0][0]
    assert enriched_data["report_date"] == raw_date
