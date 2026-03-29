"""Unit tests for quote query use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.query_quotes import GetQuotesBatchUseCase, GetQuoteUseCase
from market_data.domain.entities import Quote

pytestmark = pytest.mark.unit


def _make_quote(instrument_id: str = "instr-001") -> Quote:
    return Quote(
        instrument_id=instrument_id,
        bid=Decimal("100.00"),
        ask=Decimal("100.10"),
        last=Decimal("100.05"),
        volume=1_000,
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _make_uow(
    single_quote: Quote | None = None,
    batch_quotes: list[Quote] | None = None,
) -> MagicMock:
    uow = MagicMock()
    repo = MagicMock()
    repo.find_by_instrument = AsyncMock(return_value=single_quote)
    repo.find_by_instruments = AsyncMock(return_value=batch_quotes or [])
    uow.quotes_read = repo
    return uow


@pytest.mark.asyncio
async def test_get_quote_found() -> None:
    quote = _make_quote()
    uow = _make_uow(single_quote=quote)
    uc = GetQuoteUseCase(uow)
    result = await uc.execute("instr-001")
    assert result is quote
    uow.quotes_read.find_by_instrument.assert_awaited_once_with("instr-001")


@pytest.mark.asyncio
async def test_get_quote_not_found() -> None:
    uow = _make_uow(single_quote=None)
    uc = GetQuoteUseCase(uow)
    result = await uc.execute("missing")
    assert result is None


@pytest.mark.asyncio
async def test_get_quotes_batch() -> None:
    quotes = [_make_quote("instr-001"), _make_quote("instr-002")]
    uow = _make_uow(batch_quotes=quotes)
    uc = GetQuotesBatchUseCase(uow)
    result = await uc.execute(["instr-001", "instr-002"])
    assert len(result) == 2
    uow.quotes_read.find_by_instruments.assert_awaited_once_with(["instr-001", "instr-002"])


@pytest.mark.asyncio
async def test_get_quotes_batch_empty() -> None:
    uow = _make_uow(batch_quotes=[])
    uc = GetQuotesBatchUseCase(uow)
    result = await uc.execute([])
    assert result == []
