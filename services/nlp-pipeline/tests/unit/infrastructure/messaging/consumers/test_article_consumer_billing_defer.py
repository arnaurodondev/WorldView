"""ArticleProcessingConsumer — spend-cap (HTTP 402) billing-defer settle policy.

402-replay hardening: a DeepInfra spend-cap / auth refusal surfaces as
``ml_clients.errors.ProviderBillingError`` (a ``RetryableError``). The settle loop must
NOT route it through the generic transient branch — that counts against ``max_retries``
and DEAD-LETTERS the article (the 2026-07-18 incident lost 693 articles this way).
Instead a billing refusal is DEFERRED without consuming the transient retry budget and
NEVER dead-lettered:

  * a short cap self-heals in place with zero operator action, and
  * a persistent refusal (revoked key) returns a commit BARRIER (offset uncommitted,
    NOT dead-lettered) after ``_BILLING_DEFER_MAX_IN_PLACE`` deferrals so the slot frees
    and the article is redelivered on the next restart/rebalance once the cap clears.

The consumer is built via ``object.__new__`` so we wire only the few attributes the
settle path touches — no ML/DB/Kafka/Valkey. The 5-minute billing backoff is patched to
zero so the test does not actually sleep.
"""

from __future__ import annotations

from typing import Any

import pytest
from ml_clients.errors import ProviderBillingError  # type: ignore[import-not-found]
from nlp_pipeline.infrastructure.messaging.consumers import article_consumer as ac
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)

pytestmark = pytest.mark.asyncio


class _FakeMsg:
    def __init__(self, topic: str = "content.article.stored.v1", partition: int = 0, offset: int = 7) -> None:
        self._topic = topic
        self._partition = partition
        self._offset = offset

    def topic(self) -> str:
        return self._topic

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset


class _FakeConfig:
    max_retries = 5


def _make_consumer() -> ArticleProcessingConsumer:
    """Build a consumer via ``object.__new__`` with only the settle-path deps stubbed."""
    c = object.__new__(ArticleProcessingConsumer)
    c._config = _FakeConfig()  # type: ignore[attr-defined]
    c._compute_backoff = lambda attempt: 0.0  # type: ignore[attr-defined,method-assign]

    # Deterministic event id (skip the real deserialize path).
    async def _safe_event_id(msg: Any) -> str:
        return f"evt-{msg.partition()}-{msg.offset()}"

    c._safe_event_id = _safe_event_id  # type: ignore[attr-defined,method-assign]

    # Durable transient-attempt counter — record calls so we can assert the billing
    # path NEVER consumes the transient budget.
    c.recorded_attempts = []  # type: ignore[attr-defined]

    async def _durable_attempt_count(event_id: str) -> int:
        return 0

    async def _record_attempt(event_id: str, attempt: int, exc: BaseException) -> None:
        c.recorded_attempts.append((event_id, attempt))  # type: ignore[attr-defined]

    c._durable_attempt_count = _durable_attempt_count  # type: ignore[attr-defined,method-assign]
    c._record_attempt = _record_attempt  # type: ignore[attr-defined,method-assign]

    # Dead-letter sink — a billing refusal must NEVER reach it.
    c.dead_lettered = []  # type: ignore[attr-defined]

    async def _dead_letter_poison(msg: Any, exc: BaseException, *, event_id: str, reason: str) -> bool:
        c.dead_lettered.append((event_id, reason))  # type: ignore[attr-defined]
        return True

    c._dead_letter_poison = _dead_letter_poison  # type: ignore[attr-defined,method-assign]

    # Count billing-deferral metric increments without touching the global registry.
    c.billing_metric_calls = 0  # type: ignore[attr-defined]

    def _safe_record_article_billing_deferred() -> None:
        c.billing_metric_calls += 1  # type: ignore[attr-defined]

    c._safe_record_article_billing_deferred = _safe_record_article_billing_deferred  # type: ignore[attr-defined,method-assign]
    return c


@pytest.fixture(autouse=True)
def _no_billing_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero the 5-minute billing backoff so tests do not actually sleep."""
    monkeypatch.setattr(ac, "_BILLING_RETRY_BACKOFF_SECONDS", 0.0)


async def test_transient_cap_self_heals_without_dead_letter() -> None:
    """A cap that clears mid-defer: two 402s then success → settled True, no DLQ, no budget spent."""
    c = _make_consumer()
    calls = {"n": 0}

    async def fake_handle(msg: Any) -> None:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ProviderBillingError("HTTP 402 Payment Required (spend cap)")
        # third attempt succeeds — the operator raised the cap.

    c._handle_message = fake_handle  # type: ignore[attr-defined,method-assign]

    settled = await c._settle_message(_FakeMsg())

    assert settled is True  # success → offset may advance
    assert c.dead_lettered == []  # NEVER dead-lettered on a billing refusal
    assert c.recorded_attempts == []  # transient budget untouched by billing deferrals
    assert c.billing_metric_calls == 2  # one per deferral


async def test_persistent_billing_returns_barrier_and_never_dead_letters() -> None:
    """A revoked key (permanent 402/403): barrier after the in-place cap, still no DLQ."""
    c = _make_consumer()

    async def always_402(msg: Any) -> None:
        raise ProviderBillingError("HTTP 402 Payment Required")

    c._handle_message = always_402  # type: ignore[attr-defined,method-assign]

    settled = await c._settle_message(_FakeMsg())

    assert settled is False  # commit barrier — offset held, redelivered on restart
    assert c.dead_lettered == []  # never dead-lettered (no data loss)
    assert c.recorded_attempts == []  # transient budget never consumed
    assert c.billing_metric_calls == ac._BILLING_DEFER_MAX_IN_PLACE


async def test_billing_defer_does_not_erode_transient_budget() -> None:
    """Billing deferrals before a genuine transient error leave the full transient budget.

    After several 402s the provider recovers but the pipeline hits a real 5xx-style
    error; that must still get the full ``max_retries`` budget (billing deferrals must
    not have pre-counted against it).
    """
    c = _make_consumer()
    seq = {"i": 0}

    async def handle(msg: Any) -> None:
        seq["i"] += 1
        if seq["i"] <= 2:
            raise ProviderBillingError("HTTP 402")
        raise RuntimeError("transient 5xx")  # never recovers → exhausts transient budget

    c._handle_message = handle  # type: ignore[attr-defined,method-assign]

    settled = await c._settle_message(_FakeMsg())

    assert settled is True  # dead-letter stub returns True (poison drained)
    assert c.dead_lettered == [("evt-0-7", "max_retries")]  # only after real transient exhaustion
    # Exactly max_retries transient attempts were recorded (billing deferrals excluded).
    assert len(c.recorded_attempts) == _FakeConfig.max_retries
    assert c.billing_metric_calls == 2
