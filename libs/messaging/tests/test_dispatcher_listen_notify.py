"""Tests for LIB-003 / TASK-W4-01 — LISTEN/NOTIFY wake-up in the outbox dispatcher.

These tests exercise the back-compat-safe optimisation that lets the
dispatcher wake on a Postgres ``NOTIFY outbox_events_new`` event
instead of polling every 5s. The Postgres driver is mocked — the
contract under test is:

* The dispatcher calls :meth:`BaseOutboxDispatcher.register_notify_listener`
  on start-up.
* When the registered callback fires, the dispatcher wakes within a
  few milliseconds and re-runs its dispatch loop.
* If registration raises, the dispatcher falls back to short-interval
  polling (no exception escapes).
* The ``idle_poll_interval_seconds`` acts as a safety-net timeout
  when no NOTIFY arrives.
* On stop/cancel, the cleanup callable returned by the subclass is
  invoked exactly once.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from typing import TYPE_CHECKING, Any

import pytest

from messaging.kafka.dispatcher import OUTBOX_NOTIFY_CHANNEL
from messaging.kafka.dispatcher.base import (
    BaseOutboxDispatcher,
    DispatcherConfig,
    OutboxRecordProtocol,
    UnitOfWorkWithOutboxProtocol,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime


# ── Test doubles (kept independent from test_dispatcher_integration.py) ──────
#
# We intentionally duplicate the minimal in-memory repo/uow/producer here
# instead of importing across test modules — keeping tests self-contained
# makes them easier to read in isolation.


@dataclasses.dataclass
class _OutboxRecord:
    id: int
    event_type: str
    topic: str
    payload: dict[str, Any]
    attempts: int = 0
    leased_until: datetime | None = None


class _InMemoryOutboxRepo:
    """Bounded in-memory repo. Pending list mutable from tests."""

    def __init__(self, records: list[_OutboxRecord] | None = None) -> None:
        self._records: dict[int, _OutboxRecord] = {r.id: r for r in (records or [])}
        self.published_ids: list[int] = []
        self.dead_letter_ids: list[int] = []
        self.fetch_calls: int = 0

    def add(self, record: _OutboxRecord) -> None:
        self._records[record.id] = record

    async def fetch_pending(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecordProtocol]:
        self.fetch_calls += 1
        pending = [
            r for r in self._records.values() if r.id not in self.published_ids and r.id not in self.dead_letter_ids
        ]
        return list(pending[:batch_size])  # type: ignore[return-value]

    async def mark_published(self, record_id: Any) -> None:
        self.published_ids.append(record_id)

    async def increment_attempts(self, record_id: Any) -> None:
        if record_id in self._records:
            self._records[record_id].attempts += 1

    async def move_to_dead_letter(self, record_id: Any) -> None:
        self.dead_letter_ids.append(record_id)


class _InMemoryUoW:
    def __init__(self, repo: _InMemoryOutboxRepo) -> None:
        self.outbox: _InMemoryOutboxRepo = repo  # type: ignore[assignment]

    async def __aenter__(self) -> _InMemoryUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _NoopProducer:
    """Producer stub that always succeeds — we only care about wake-up wiring."""

    def produce(
        self,
        topic: str,
        value: Any = None,
        key: Any = None,
        headers: Any = None,
        on_delivery: Any = None,
    ) -> None:
        if on_delivery is not None:
            on_delivery(None, None)

    def flush(self, timeout: float = -1.0) -> int:
        return 0


class _ListenDispatcher(BaseOutboxDispatcher):
    """Dispatcher that wires a fake LISTEN/NOTIFY implementation.

    The subclass captures the ``on_notify`` callback handed to it by
    :meth:`BaseOutboxDispatcher.register_notify_listener` so tests can
    fire NOTIFYs at will via :meth:`fire_notify`.
    """

    def __init__(
        self,
        repo: _InMemoryOutboxRepo,
        *,
        config: DispatcherConfig | None = None,
        registration_error: BaseException | None = None,
        registration_returns_none: bool = False,
    ) -> None:
        super().__init__(config)
        self._repo = repo
        self._producer = _NoopProducer()
        self._registration_error = registration_error
        self._registration_returns_none = registration_returns_none
        # Test observation hooks
        self.register_calls: int = 0
        self.unregister_calls: int = 0
        self._captured_callback: Callable[[], None] | None = None

    async def get_unit_of_work(self) -> UnitOfWorkWithOutboxProtocol:
        return _InMemoryUoW(self._repo)  # type: ignore[return-value]

    def get_serializer(self, event_type: str) -> Any:
        return lambda v, ctx: b"{}"

    def get_producer(self) -> Any:
        return self._producer

    async def register_notify_listener(
        self,
        on_notify: Callable[[], None],
    ) -> Callable[[], Awaitable[None]] | None:
        self.register_calls += 1
        if self._registration_error is not None:
            raise self._registration_error
        if self._registration_returns_none:
            return None
        self._captured_callback = on_notify

        async def _cleanup() -> None:
            self.unregister_calls += 1

        return _cleanup

    def fire_notify(self) -> None:
        """Simulate a Postgres NOTIFY arriving on the channel."""
        if self._captured_callback is None:
            raise RuntimeError("register_notify_listener was not called yet")
        self._captured_callback()


# ── Tests ────────────────────────────────────────────────────────────────────


class TestChannelConstant:
    def test_channel_name_is_outbox_events_new(self) -> None:
        # The channel name is part of the public contract because services
        # must use it inside their AFTER-INSERT trigger.
        assert OUTBOX_NOTIFY_CHANNEL == "outbox_events_new"


class TestDispatcherConfigDefaults:
    def test_idle_poll_interval_defaults_to_60_seconds(self) -> None:
        config = DispatcherConfig()
        assert config.idle_poll_interval_seconds == 60.0

    def test_poll_interval_still_defaults_to_5_seconds_for_back_compat(self) -> None:
        config = DispatcherConfig()
        assert config.poll_interval_seconds == 5.0


class TestRegistrationOnStartup:
    async def test_run_invokes_register_notify_listener(self) -> None:
        """The dispatcher MUST attempt to register a listener on startup."""
        repo = _InMemoryOutboxRepo()
        dispatcher = _ListenDispatcher(
            repo,
            config=DispatcherConfig(idle_poll_interval_seconds=10.0),
        )
        task = asyncio.create_task(dispatcher.run())
        # Give the run loop time to call register_notify_listener.
        await asyncio.sleep(0.05)
        dispatcher.stop()
        await task

        assert dispatcher.register_calls == 1


class TestNotifyWakesDispatcher:
    async def test_notify_triggers_immediate_re_poll(self) -> None:
        """A NOTIFY must wake the dispatcher within < 100ms.

        We set ``idle_poll_interval_seconds`` to a very large value so
        that the safety-net poll cannot mask the test — only a real
        NOTIFY wake-up can cause a second ``fetch_pending`` call.
        """
        repo = _InMemoryOutboxRepo()
        dispatcher = _ListenDispatcher(
            repo,
            config=DispatcherConfig(idle_poll_interval_seconds=300.0),
        )
        task = asyncio.create_task(dispatcher.run())
        # Wait for the first fetch_pending call (registration + initial poll).
        await asyncio.sleep(0.05)
        baseline_calls = repo.fetch_calls
        assert baseline_calls >= 1

        # Fire a NOTIFY — the dispatcher should wake and re-poll.
        dispatcher.fire_notify()
        await asyncio.sleep(0.05)

        try:
            assert repo.fetch_calls > baseline_calls
        finally:
            dispatcher.stop()
            await task


class TestGracefulFallback:
    async def test_registration_exception_does_not_kill_dispatcher(self) -> None:
        """If add_listener raises, dispatcher must fall back to polling.

        We use a very short ``poll_interval_seconds`` so the test
        proves the fall-back path actually polls.
        """
        repo = _InMemoryOutboxRepo()
        dispatcher = _ListenDispatcher(
            repo,
            registration_error=RuntimeError("DB does not support LISTEN"),
            config=DispatcherConfig(
                poll_interval_seconds=0.05,
                idle_poll_interval_seconds=300.0,  # would be 300s if LISTEN active
            ),
        )
        task = asyncio.create_task(dispatcher.run())
        # 200ms is enough for several short-interval polls.
        await asyncio.sleep(0.25)
        dispatcher.stop()
        await task

        # Should have polled multiple times even though registration failed.
        assert repo.fetch_calls >= 2

    async def test_registration_returning_none_falls_back_to_short_poll(self) -> None:
        """Subclasses opting out via ``return None`` keep legacy polling."""
        repo = _InMemoryOutboxRepo()
        dispatcher = _ListenDispatcher(
            repo,
            registration_returns_none=True,
            config=DispatcherConfig(
                poll_interval_seconds=0.05,
                idle_poll_interval_seconds=300.0,
            ),
        )
        task = asyncio.create_task(dispatcher.run())
        await asyncio.sleep(0.25)
        dispatcher.stop()
        await task

        assert repo.fetch_calls >= 2
        # Cleanup MUST NOT be called when registration returned None.
        assert dispatcher.unregister_calls == 0


class TestIdlePollSafetyNet:
    async def test_idle_timeout_still_polls_without_notify(self) -> None:
        """When LISTEN is active but no NOTIFY arrives, the safety-net
        timeout must still produce a poll."""
        repo = _InMemoryOutboxRepo()
        dispatcher = _ListenDispatcher(
            repo,
            config=DispatcherConfig(idle_poll_interval_seconds=0.05),
        )
        task = asyncio.create_task(dispatcher.run())
        await asyncio.sleep(0.20)
        dispatcher.stop()
        await task

        # With a 50ms idle timeout we expect several polls within 200ms.
        assert repo.fetch_calls >= 2


class TestCleanup:
    async def test_unregister_called_exactly_once_on_stop(self) -> None:
        repo = _InMemoryOutboxRepo()
        dispatcher = _ListenDispatcher(
            repo,
            config=DispatcherConfig(idle_poll_interval_seconds=10.0),
        )
        task = asyncio.create_task(dispatcher.run())
        await asyncio.sleep(0.05)
        dispatcher.stop()
        await task

        assert dispatcher.unregister_calls == 1

    async def test_unregister_called_on_cancellation(self) -> None:
        """Cancelling the run task must still release the LISTEN connection."""
        repo = _InMemoryOutboxRepo()
        dispatcher = _ListenDispatcher(
            repo,
            config=DispatcherConfig(idle_poll_interval_seconds=10.0),
        )
        task = asyncio.create_task(dispatcher.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert dispatcher.unregister_calls == 1


class TestDefaultRegistrationIsNoop:
    """The base class default MUST be a no-op so existing services keep
    using their current polling behaviour without code changes."""

    async def test_base_register_returns_none(self) -> None:
        class _NoOverrideDispatcher(BaseOutboxDispatcher):
            async def get_unit_of_work(self) -> UnitOfWorkWithOutboxProtocol:
                return _InMemoryUoW(_InMemoryOutboxRepo())  # type: ignore[return-value]

            def get_serializer(self, event_type: str) -> Any:
                return lambda v, ctx: b"{}"

            def get_producer(self) -> Any:
                return _NoopProducer()

        dispatcher = _NoOverrideDispatcher()
        # Calling the default implementation directly should yield None
        # so :meth:`run` keeps the legacy short-interval poll.
        result = await dispatcher.register_notify_listener(lambda: None)
        assert result is None


@pytest.mark.skip(
    reason=(
        "Integration test against a real Postgres requires asyncpg + a live DB. "
        "Mark with @pytest.mark.requires_postgres in an integration suite when wired."
    ),
)
async def test_notify_round_trip_against_postgres() -> None:
    """Placeholder for the real LISTEN/NOTIFY round-trip test.

    Run manually against ``intelligence-postgres`` to confirm:

        CREATE FUNCTION notify_outbox_events_new() ...
        INSERT INTO outbox_events (...);
        -> NOTIFY outbox_events_new
        -> add_listener callback fires within ~5ms
    """
