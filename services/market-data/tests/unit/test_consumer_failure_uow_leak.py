"""Regression tests for F-004 — market-data ``idle in transaction`` leak.

Live QA found 15-23 ``market_data_db`` backends stuck ``idle in transaction``
for up to ~25 min, all after ``INSERT INTO failed_tasks (...)`` with
``wait_event=ClientRead``. Root cause: the consumers' failed-task error path
(``store_failure`` / ``_dead_letter_impl``) wrote the row through
``self._current_uow`` — the per-message UoW that the base
``_handle_message`` had ALREADY rolled back and closed before dispatching to
``_handle_failure``. ``PgFailedTaskRepository.create`` only ``execute``s the
INSERT (no commit), so the re-checked-out pooled connection was returned to the
pool still in an open transaction → ``idle in transaction`` forever, cascade-
amplified by the MinIO/market-data outage which kept the worker erroring.

Fix: every failure path opens its OWN fresh UoW via ``self._uow_factory()``
and ``commit()``s it (so the row is durable AND the connection is released),
mirroring the earlier ohlcv_consumer fix (BUG-2026-06-16). These tests assert
the fresh UoW is the one written to + committed, and the stale ``_current_uow``
is never touched, for every affected sibling consumer.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from market_data.infrastructure.messaging.consumers.fundamentals_consumer import (
    FundamentalsConsumer,
)
from market_data.infrastructure.messaging.consumers.insider_transactions_consumer import (
    InsiderTransactionsConsumer,
)
from market_data.infrastructure.messaging.consumers.intraday_resampling_consumer import (
    IntradayResamplingConsumer,
)
from market_data.infrastructure.messaging.consumers.prediction_market_consumer import (
    PredictionMarketConsumer,
)
from market_data.infrastructure.messaging.consumers.quotes_consumer import QuotesConsumer

from messaging.kafka.consumer.base import FailureInfo

pytestmark = pytest.mark.unit


def _make_failure(event_id: str = "evt-1", attempt: int = 1) -> FailureInfo[dict]:
    return FailureInfo(
        event_id=event_id,
        topic="market.dataset.fetched",
        partition=0,
        offset=5,
        attempt=attempt,
        last_error=ValueError("boom"),
    )


def _construct(consumer_cls: type) -> tuple[object, AsyncMock]:
    """Build *consumer_cls* with a single-instance fresh UoW factory.

    Returns ``(consumer, fresh_uow)``. ``fresh_uow`` is the mock the factory
    hands out; the consumer's ``_current_uow`` is set to a DIFFERENT stale mock
    so the test can assert the failure path never writes through it.
    """
    fresh_uow = AsyncMock()
    # Every affected consumer takes ``uow_factory`` as the first positional arg;
    # the ones that also take ``object_storage`` accept ``None`` happily here
    # since the failure paths never touch storage.
    try:
        consumer = consumer_cls(uow_factory=lambda: fresh_uow, object_storage=AsyncMock())
    except TypeError:
        # PredictionMarketConsumer has no object_storage parameter.
        consumer = consumer_cls(uow_factory=lambda: fresh_uow)
    consumer._current_uow = AsyncMock()  # the stale UoW that must NOT be used
    return consumer, fresh_uow


# (consumer_cls, expected store_failure task_type, expected dead-letter task_type)
_CASES = [
    (
        IntradayResamplingConsumer,
        "intraday_resampling_consumer",
        "intraday_resampling_consumer_dead",
    ),
    (QuotesConsumer, "quotes_consumer", "quotes_consumer_dead"),
    (
        InsiderTransactionsConsumer,
        "insider_transactions_consumer",
        "insider_transactions_consumer_dead",
    ),
    (
        PredictionMarketConsumer,
        "prediction_market_consumer",
        "prediction_market_consumer_dead",
    ),
    (FundamentalsConsumer, "fundamentals_consumer", "fundamentals_consumer_dead"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("consumer_cls", "task_type", "_dead"), _CASES)
async def test_store_failure_opens_fresh_committed_uow(consumer_cls: type, task_type: str, _dead: str) -> None:
    consumer, fresh_uow = _construct(consumer_cls)

    await consumer.store_failure(_make_failure())  # type: ignore[attr-defined]

    entered = fresh_uow.__aenter__.return_value
    # The row was written through the FRESH UoW...
    entered.failed_tasks.create.assert_awaited_once()
    assert entered.failed_tasks.create.await_args.kwargs["task_type"] == task_type
    # ...and committed (the durability + connection-release fix)...
    entered.commit.assert_awaited_once()
    # ...and the FRESH UoW context manager was exited (connection always closed).
    fresh_uow.__aexit__.assert_awaited_once()
    # ...and the stale per-message UoW was NEVER written to (the leak source).
    consumer._current_uow.failed_tasks.create.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.parametrize(("consumer_cls", "_store", "dead_type"), _CASES)
async def test_dead_letter_opens_fresh_committed_uow(consumer_cls: type, _store: str, dead_type: str) -> None:
    consumer, fresh_uow = _construct(consumer_cls)

    await consumer._dead_letter_impl(_make_failure(event_id="evt-poison", attempt=5))  # type: ignore[attr-defined]

    entered = fresh_uow.__aenter__.return_value
    entered.failed_tasks.create.assert_awaited_once()
    kwargs = entered.failed_tasks.create.await_args.kwargs
    assert kwargs["task_type"] == dead_type
    assert kwargs["max_attempts"] == 0
    entered.commit.assert_awaited_once()
    fresh_uow.__aexit__.assert_awaited_once()
    consumer._current_uow.failed_tasks.create.assert_not_called()  # type: ignore[attr-defined]
