"""ArticleProcessingConsumer — Valkey-backed persistent-retry attempt counter.

Transient-failure resilience (2026-06-14): with ``enable_persistent_retry=True``
the base ON retry path needs a DURABLE attempt count keyed by
(group_id, event_id), otherwise the count resets to 0 on every redelivery and a
transiently-failing doc loops until the dead_letter_cap crashes the consumer
instead of dead-lettering at max_retries.  These tests exercise the consumer's
``_get_attempt_count`` / ``_record_attempt`` overrides against a fake Valkey
client, including the fail-closed behaviour when Valkey is unavailable.

The consumer is built via ``object.__new__`` so we only wire the few attributes
the counter path touches (``_dedup_client`` + ``_config``).
"""

from __future__ import annotations

from typing import Any

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)

pytestmark = pytest.mark.asyncio


class _FakeConfig:
    group_id = "nlp-test-group"
    max_retries = 5


class _FakeValkey:
    """In-memory stand-in for ValkeyClient (get/incr/expire only)."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.expires: dict[str, int] = {}
        self.fail = False

    async def get(self, key: str) -> str | None:
        if self.fail:
            raise RuntimeError("valkey down")
        v = self.store.get(key)
        return str(v) if v is not None else None

    async def incr(self, key: str, amount: int = 1) -> int:
        if self.fail:
            raise RuntimeError("valkey down")
        self.store[key] = self.store.get(key, 0) + amount
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> bool:
        if self.fail:
            raise RuntimeError("valkey down")
        self.expires[key] = seconds
        return True


def _make_consumer(valkey: Any) -> ArticleProcessingConsumer:
    c = object.__new__(ArticleProcessingConsumer)
    c._config = _FakeConfig()  # type: ignore[attr-defined]
    c._dedup_client = valkey  # type: ignore[attr-defined]
    return c


async def test_attempt_count_starts_at_zero() -> None:
    c = _make_consumer(_FakeValkey())
    assert await c._get_attempt_count("evt-1") == 0


async def test_record_attempt_increments_and_persists() -> None:
    vk = _FakeValkey()
    c = _make_consumer(vk)

    await c._record_attempt("evt-2", 1, RuntimeError("boom"))
    assert await c._get_attempt_count("evt-2") == 1
    await c._record_attempt("evt-2", 2, RuntimeError("boom"))
    assert await c._get_attempt_count("evt-2") == 2

    # A TTL was applied so the counter self-expires after recovery/DLQ.
    key = c._retry_attempt_key("evt-2")
    assert vk.expires[key] == ArticleProcessingConsumer._RETRY_ATTEMPT_TTL_SECONDS


async def test_key_is_namespaced_by_group() -> None:
    c = _make_consumer(_FakeValkey())
    key = c._retry_attempt_key("evt-3")
    assert key == f"{ArticleProcessingConsumer._RETRY_ATTEMPT_PREFIX}:nlp-test-group:evt-3"


async def test_get_fails_closed_to_dlq_when_valkey_down() -> None:
    """A read failure returns max_retries so the doc dead-letters, not loops forever."""
    vk = _FakeValkey()
    vk.fail = True
    c = _make_consumer(vk)
    assert await c._get_attempt_count("evt-4") == _FakeConfig.max_retries


async def test_get_fails_closed_when_no_valkey_client() -> None:
    """No dedup client → cannot persist a count → fail closed toward DLQ."""
    c = _make_consumer(None)
    assert await c._get_attempt_count("evt-5") == _FakeConfig.max_retries


async def test_record_attempt_swallows_valkey_errors() -> None:
    """A write failure is best-effort and never raises (would crash the consumer)."""
    vk = _FakeValkey()
    vk.fail = True
    c = _make_consumer(vk)
    # Must not raise.
    await c._record_attempt("evt-6", 1, RuntimeError("boom"))


async def test_record_attempt_noop_without_client() -> None:
    c = _make_consumer(None)
    await c._record_attempt("evt-7", 1, RuntimeError("boom"))  # no-op, no raise
