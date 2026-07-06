"""Unit tests for BaseKafkaConsumer transient-error resilience (BP-700).

Guards the platform against the "silent consumer death" failure mode: a
transient broker blip (connection setup timeout) combined with a concurrent DB
dead-letter ``TimeoutError`` previously escaped the consume loop, ended
``run()`` while the container process stayed alive on an HTTP server, and left a
zombie Docker never restarted.

The fix (in the SHARED ``libs/messaging`` base consumer) is exercised here:

* A transient broker error triggers a bounded-backoff RECONNECT and resumes —
  it does NOT permanently stop.
* The liveness heartbeat (``seconds_since_progress`` / the
  ``kafka_consumer_last_progress_timestamp`` gauge) updates on a successful poll
  cycle and goes stale when the loop is dead.
* A downstream dead-letter / store_failure DB write failure does NOT terminate
  the consume loop.
* When reconnect attempts are exhausted (a truly unrecoverable broker), the
  process force-exits non-zero so the orchestrator restarts the container.

The Kafka client + probe are mocked; no real broker is touched.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from messaging.kafka.consumer.base import (
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.errors import FatalError

pytestmark = pytest.mark.unit


class _NoopUoW(UnitOfWorkProtocol):
    async def __aenter__(self) -> _NoopUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _ResilienceConsumer(BaseKafkaConsumer[str]):
    """Concrete consumer whose failure-persistence can be scripted to raise."""

    def __init__(self, config: ConsumerConfig) -> None:
        super().__init__(config)
        # When set, store_failure + _dead_letter_impl raise this — models the
        # incident's concurrent asyncpg ``TimeoutError`` while dead-lettering.
        self.persist_error: BaseException | None = None
        self.store_failure_calls = 0
        self.dead_letter_calls = 0

    async def process_message(self, key: str | None, value: dict[str, Any], headers: dict[str, str]) -> None:
        pass

    async def is_duplicate(self, event_id: str) -> bool:
        return False

    async def mark_processed(self, event_id: str) -> None:
        pass

    async def store_failure(self, failure: FailureInfo[str]) -> str:
        self.store_failure_calls += 1
        if self.persist_error is not None:
            raise self.persist_error
        return failure.event_id

    async def update_failure(self, failure: FailureInfo[str]) -> None:
        pass

    async def _dead_letter_impl(self, failure: FailureInfo[str]) -> None:
        self.dead_letter_calls += 1
        if self.persist_error is not None:
            raise self.persist_error

    async def get_pending_retries(self) -> list[FailureInfo[str]]:
        return []

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoopUoW()

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        return json.loads(raw)

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", "unknown"))

    async def process_message_from_failure(self, failure: FailureInfo[str]) -> None:
        pass


def _build() -> _ResilienceConsumer:
    c = _ResilienceConsumer(ConsumerConfig(message_processing_timeout_s=0, group_id="resilience-grp"))
    # Tiny backoff so reconnect tests complete in milliseconds.
    c._config.initial_backoff_seconds = 0.001
    c._config.max_backoff_seconds = 0.01
    return c


def _msg(topic: str = "t", partition: int = 0, offset: int = 0) -> MagicMock:
    m = MagicMock()
    m.topic.return_value = topic
    m.partition.return_value = partition
    m.offset.return_value = offset
    m.value.return_value = b'{"event_id": "e1"}'
    m.key.return_value = None
    m.headers.return_value = []
    return m


# ── Transient-error classification ────────────────────────────────────────────


class TestTransientClassification:
    def test_timeout_error_is_transient(self) -> None:
        assert BaseKafkaConsumer._is_transient_broker_error(TimeoutError("setup timed out")) is True

    def test_connection_error_is_transient(self) -> None:
        assert BaseKafkaConsumer._is_transient_broker_error(ConnectionResetError()) is True

    def test_kafka_exception_name_is_transient(self) -> None:
        # We classify by class NAME so we need not import confluent_kafka here.
        class KafkaException(Exception):  # noqa: N818 — mirrors confluent_kafka's real class name
            pass

        assert BaseKafkaConsumer._is_transient_broker_error(KafkaException("blip")) is True

    def test_value_error_is_not_transient(self) -> None:
        # An application bug must NOT be masked as a broker blip.
        assert BaseKafkaConsumer._is_transient_broker_error(ValueError("bad data")) is False


# ── Liveness heartbeat ────────────────────────────────────────────────────────


class TestLivenessHeartbeat:
    def test_no_progress_before_first_tick(self) -> None:
        c = _build()
        assert c.seconds_since_progress() is None

    def test_record_progress_resets_staleness(self) -> None:
        c = _build()
        c._record_progress()
        since = c.seconds_since_progress()
        assert since is not None
        assert since < 1.0

    def test_staleness_grows_when_loop_dead(self) -> None:
        c = _build()
        c._record_progress()
        # Simulate a dead loop: rewind the last-progress timestamp far into the
        # past (what would happen if the poll loop stopped ticking).
        c._last_progress_ts -= 600.0
        since = c.seconds_since_progress()
        assert since is not None
        assert since >= 600.0


# ── Reconnect-with-backoff (does NOT permanently stop) ────────────────────────


class TestReconnectWithBackoff:
    async def test_transient_poll_error_reconnects_and_resumes(self) -> None:
        """A transient poll error rebuilds the consumer and keeps consuming.

        The loop must NOT exit: after the blip the consumer reconnects and a
        subsequent good poll cycle ticks the heartbeat.
        """
        c = _build()
        good = MagicMock()
        # poll: raise transient once, then return None forever (idle but alive).
        good.poll.side_effect = [TimeoutError("connection setup timed out"), *([None] * 1000)]

        init_calls = {"n": 0}

        def fake_init() -> None:
            init_calls["n"] += 1
            c._consumer = good

        async def _idle_forever() -> None:
            # Stand-in for the retry / probe background loops: sleep until the
            # surrounding test cancels the task, so they never interfere.
            await asyncio.sleep(100)

        with (
            patch.object(c, "_init_kafka", side_effect=fake_init),
            patch.object(c, "_shutdown_kafka"),
            patch.object(c, "_retry_loop", _idle_forever),
            patch.object(c, "_connectivity_probe_loop", _idle_forever),
        ):
            run_task = asyncio.create_task(c.run())
            # Give the loop time to: init → hit transient → reconnect → tick.
            await asyncio.sleep(0.1)
            c._stop_event.set()
            await asyncio.wait_for(run_task, timeout=2.0)

        # Reconnect rebuilt the consumer at least once beyond the initial init.
        assert init_calls["n"] >= 2, "expected a reconnect rebuild after the transient poll error"
        # The loop kept running and heartbeated after recovery.
        assert c.seconds_since_progress() is not None

    async def test_reconnect_exhaustion_force_exits(self) -> None:
        """A permanently-down broker force-exits (os._exit) — never a zombie.

        Escalation now goes through ``_force_process_exit`` (os._exit) instead
        of ``sys.exit``: a bare SystemExit raised in this Task-driven coroutine
        was captured/swallowed as the Task result, leaving the very zombie this
        path exists to prevent.
        """
        c = _build()
        c._reconnect_max_attempts = 2  # exhaust fast
        # Patch the escalation hook to raise SystemExit so the loop unwinds in
        # the test (real code calls os._exit, which we must not do under pytest).
        with patch.object(type(c), "_force_process_exit", side_effect=SystemExit) as exit_mock:
            # Drive attempts past the ceiling.
            for _ in range(3):
                try:
                    await c._reconnect_with_backoff()
                except SystemExit:
                    break
                # Make the rebuild a no-op so we only test the attempt ceiling.
                c._consumer = MagicMock()
        assert exit_mock.called, "exhausted reconnect must force-exit for a fresh container"
        assert exit_mock.call_args.args == (2,)

    async def test_reconnect_backoff_interrupted_by_stop(self) -> None:
        """A stop signal during the reconnect backoff ends cleanly (no rebuild)."""
        c = _build()
        c._config.initial_backoff_seconds = 5.0  # long enough to interrupt
        c._config.max_backoff_seconds = 5.0
        c._stop_event.set()  # stop already requested
        with patch.object(c, "_init_kafka") as init_mock:
            result = await c._reconnect_with_backoff()
        assert result is False
        init_mock.assert_not_called()


# ── DB dead-letter decoupling ─────────────────────────────────────────────────


class TestDeadLetterDecoupling:
    async def test_store_failure_db_error_does_not_escape(self) -> None:
        """A retryable failure whose store_failure raises (DB timeout) is swallowed."""
        c = _build()
        c.persist_error = TimeoutError("asyncpg connection timeout")
        from messaging.kafka.consumer.errors import RetryableError

        # Must NOT raise — historically commit-as-handled OFF path.
        settled = await c._handle_failure(_msg(), RetryableError("transient"))
        assert settled is True
        assert c.store_failure_calls == 1

    async def test_dead_letter_db_error_does_not_escape(self) -> None:
        """A fatal failure whose dead-letter DB write raises is swallowed."""
        c = _build()
        c.persist_error = TimeoutError("asyncpg connection timeout while dead-lettering")
        settled = await c._handle_failure(_msg(), FatalError("fatal"))
        assert settled is True
        assert c.dead_letter_calls == 1

    async def test_dead_letter_cap_runtime_error_still_propagates(self) -> None:
        """The poison-storm cap RuntimeError is an intentional crash — must propagate."""
        c = _build()
        c._config.dead_letter_cap = 0  # next dead-letter trips the cap
        # No persist_error: the cap check itself raises RuntimeError before the
        # DB write, and that intentional crash must NOT be swallowed.
        with pytest.raises(RuntimeError, match="Dead-letter cap"):
            await c._handle_failure(_msg(), FatalError("fatal"))
