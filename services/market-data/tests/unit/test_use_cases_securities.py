"""Unit tests for security query use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.query_securities import GetSecurityUseCase, ListSecuritiesUseCase
from market_data.domain.entities import Security

pytestmark = pytest.mark.unit


def _make_security(figi: str = "BBG000B9XRY4", isin: str = "US0378331005") -> Security:
    return Security(
        id="sec-001",
        figi=figi,
        isin=isin,
        name="Apple Inc.",
        sector="Technology",
        industry="Consumer Electronics",
        country="US",
        currency="USD",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _make_uow(figi_result: Security | None = None, isin_result: Security | None = None) -> MagicMock:
    uow = MagicMock()
    repo = MagicMock()
    repo.find_by_figi = AsyncMock(return_value=figi_result)
    repo.find_by_isin = AsyncMock(return_value=isin_result)
    repo.list = AsyncMock(return_value=([], 0))
    uow.securities_read = repo
    return uow


@pytest.mark.asyncio
async def test_get_security_by_figi() -> None:
    security = _make_security()
    uow = _make_uow(figi_result=security)
    uc = GetSecurityUseCase(uow)
    result = await uc.execute("BBG000B9XRY4")
    assert result is security
    uow.securities_read.find_by_figi.assert_awaited_once_with("BBG000B9XRY4")


@pytest.mark.asyncio
async def test_get_security_isin_format_checked_first() -> None:
    """12-char ISIN (2-letter prefix + 10 digits) is tried via find_by_isin directly."""
    security = _make_security()
    uow = _make_uow(isin_result=security)
    uc = GetSecurityUseCase(uow)
    result = await uc.execute("US0378331005")
    assert result is security
    uow.securities_read.find_by_isin.assert_awaited_once_with("US0378331005")
    uow.securities_read.find_by_figi.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_security_figi_fallback_to_isin() -> None:
    """Non-ISIN format: try FIGI first, then ISIN if FIGI misses."""
    security = _make_security()
    uow = _make_uow(figi_result=None, isin_result=security)
    uc = GetSecurityUseCase(uow)
    result = await uc.execute("SOMEID")
    assert result is security
    uow.securities_read.find_by_figi.assert_awaited_once_with("SOMEID")
    uow.securities_read.find_by_isin.assert_awaited_once_with("SOMEID")


@pytest.mark.asyncio
async def test_get_security_not_found() -> None:
    uow = _make_uow()
    uc = GetSecurityUseCase(uow)
    result = await uc.execute("UNKNOWN")
    assert result is None


@pytest.mark.asyncio
async def test_list_securities_by_figi() -> None:
    security = _make_security()
    uow = _make_uow(figi_result=security)
    uc = ListSecuritiesUseCase(uow)
    items, total = await uc.execute(figi="BBG000B9XRY4")
    assert total == 1
    assert items[0] is security
    uow.securities_read.find_by_figi.assert_awaited_once_with("BBG000B9XRY4")


@pytest.mark.asyncio
async def test_list_securities_by_figi_not_found() -> None:
    uow = _make_uow(figi_result=None)
    uc = ListSecuritiesUseCase(uow)
    items, total = await uc.execute(figi="NOTEXIST")
    assert total == 0
    assert items == []


@pytest.mark.asyncio
async def test_list_securities_by_isin() -> None:
    security = _make_security()
    uow = _make_uow(isin_result=security)
    uc = ListSecuritiesUseCase(uow)
    items, total = await uc.execute(isin="US0378331005")
    assert total == 1
    assert items[0] is security


@pytest.mark.asyncio
async def test_list_securities_no_filter_calls_list() -> None:
    uow = _make_uow()
    uow.securities_read.list = AsyncMock(return_value=([_make_security()], 1))
    uc = ListSecuritiesUseCase(uow)
    items, total = await uc.execute(limit=50, offset=0)
    assert total == 1
    uow.securities_read.list.assert_awaited_once_with(limit=50, offset=0)
