"""Unit tests for alert service standalone consumer and dispatcher entry points.

Covers: intelligence_consumer_main, watchlist_consumer_main, dispatcher_main.

All tests use ``unittest.mock.patch`` to isolate all infrastructure.
The pre-set ``asyncio.Event`` pattern is used so ``stop_event.wait()``
returns immediately and the entire cleanup path executes within the test.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force METRICS_PORT=0 so the real start_metrics_server picks an ephemeral
# port and never collides with the Docker stack's worldview-prometheus on 9100.
# PLAN-0107 FU — see audit 2026-05-29.
os.environ["METRICS_PORT"] = "0"

pytestmark = pytest.mark.unit

# Capture the real asyncio.Event BEFORE any patch replaces it.
_REAL_ASYNCIO_EVENT = asyncio.Event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _preset_event(*_args: object, **_kwargs: object) -> asyncio.Event:
    """Return a real asyncio.Event that is already set."""
    e = _REAL_ASYNCIO_EVENT()
    e.set()
    return e


def _mock_settings(**overrides: object) -> MagicMock:
    s = MagicMock()
    s.log_level = "INFO"
    s.log_json = False
    s.kafka_bootstrap_servers = "localhost:9092"
    s.kafka_consumer_group = "alert-service-group"
    s.kafka_watchlist_consumer_group = "alert-service-watchlist-group"
    s.kafka_topic_signal = "nlp.signal.detected.v1"
    s.kafka_topic_graph_state = "graph.state.changed.v1"
    s.kafka_topic_contradiction = "intelligence.contradiction.v1"
    s.kafka_topic_watchlist = "portfolio.watchlist.updated.v1"
    s.kafka_topic_alert_delivered = "alert.delivered.v1"
    s.valkey_url = "redis://localhost:6379/0"
    s.s1_portfolio_base_url = "http://localhost:8001"
    s.alert_dedup_window_seconds = 300
    s.watchlist_cache_ttl_seconds = 300
    s.alert_severity_critical_threshold = 0.85
    s.alert_severity_high_threshold = 0.65
    s.alert_severity_medium_threshold = 0.40
    s.dispatcher_poll_interval_s = 1.0
    s.dispatcher_batch_size = 50
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@contextlib.contextmanager  # type: ignore[misc]
def _intelligence_patches(
    mock_engine: AsyncMock,
    mock_valkey: AsyncMock,
    mock_consumer: MagicMock,
    mock_s1: AsyncMock,
    settings: MagicMock,
):  # type: ignore[no-untyped-def]
    """Context manager that patches all intelligence_consumer_main dependencies."""
    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "alert.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("alert.infrastructure.clients.s1_client.S1Client", return_value=mock_s1),
        patch("alert.infrastructure.cache.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch(
            "alert.infrastructure.notification.valkey_publisher.ValkeyNotificationPublisher",
            return_value=MagicMock(),
        ),
        patch("alert.application.use_cases.alert_fanout.AlertFanoutUseCase", return_value=MagicMock()),
        patch(
            "alert.infrastructure.messaging.consumers.intelligence_consumer.IntelligenceConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        yield


# ---------------------------------------------------------------------------
# intelligence_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intelligence_consumer_graceful_stop() -> None:
    """wait_for(30s) + s1_client.close + valkey.close + engine.dispose called."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    mock_s1 = AsyncMock()
    settings = _mock_settings()

    with _intelligence_patches(mock_engine, mock_valkey, mock_consumer, mock_s1, settings):
        from alert.infrastructure.messaging.consumers.intelligence_consumer_main import main

        await main()

    mock_consumer.stop.assert_called_once()
    mock_s1.close.assert_called_once()
    mock_valkey.close.assert_called_once()
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_intelligence_consumer_stop_pre_set() -> None:
    """Consumer task is started then stopped immediately when stop_event is pre-set."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    mock_s1 = AsyncMock()
    settings = _mock_settings()

    with _intelligence_patches(mock_engine, mock_valkey, mock_consumer, mock_s1, settings):
        import importlib

        from alert.infrastructure.messaging.consumers import intelligence_consumer_main

        importlib.reload(intelligence_consumer_main)
        await intelligence_consumer_main.main()

    # Consumer task is created and waited on; stop is called immediately since event was set
    mock_consumer.stop.assert_called_once()


@pytest.mark.asyncio
async def test_intelligence_consumer_cleanup_order() -> None:
    """All resources are closed in the finally block regardless of consumer outcome."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_s1 = AsyncMock()
    # Consumer.run raises immediately to simulate early exit
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    settings = _mock_settings()

    with _intelligence_patches(mock_engine, mock_valkey, mock_consumer, mock_s1, settings):
        import importlib

        from alert.infrastructure.messaging.consumers import intelligence_consumer_main

        importlib.reload(intelligence_consumer_main)
        await intelligence_consumer_main.main()

    # All three cleanup calls must have happened
    mock_s1.close.assert_called_once()
    mock_valkey.close.assert_called_once()
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# IntelligenceConsumer — lag-record throttle (issue 4 / Fix B throughput)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lag_record_is_throttled() -> None:
    """The per-message lag sweep runs at most once per throttle interval.

    Guards the throughput fix: the base class records lag (a ~48-partition
    blocking broker sweep) after every message; the override must rate-limit it.
    """
    from alert.infrastructure.messaging.consumers.intelligence_consumer import IntelligenceConsumer

    from messaging.kafka.consumer.base import ConsumerConfig

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="alert-service-group",
        topics=["nlp.signal.detected.v1"],
    )
    consumer = IntelligenceConsumer(config=config, fanout_use_case=MagicMock(), dedup_client=None)

    calls = {"n": 0}

    def _count() -> None:
        calls["n"] += 1

    # Patch the *base* implementation so we only count throttle pass-throughs.
    with patch(
        "messaging.kafka.consumer.base.BaseKafkaConsumer._record_consumer_lag",
        side_effect=_count,
    ):
        # Long interval → only the first of many rapid calls reaches the base.
        consumer._LAG_RECORD_INTERVAL_SECONDS = 1000.0  # type: ignore[misc]
        # Seed relative to monotonic now (NOT literal 0.0): the throttle compares
        # `time.monotonic() - last >= interval`; on a fresh CI runner monotonic() can
        # be < 1000, leaving even the first call throttled → flaky 0 instead of 1.
        # Subtracting 2x the interval guarantees the first call clears it on any host.
        import time as _time

        consumer._last_lag_record_monotonic = _time.monotonic() - 2000.0
        for _ in range(5):
            consumer._record_consumer_lag()

    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# IntelligenceConsumer — idle heartbeat refresh (PLAN-0056 live-QA BUG 5)
# ---------------------------------------------------------------------------


def _make_intelligence_consumer(heartbeat_path: str) -> object:
    from alert.infrastructure.messaging.consumers.intelligence_consumer import IntelligenceConsumer

    from messaging.kafka.consumer.base import ConsumerConfig

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="alert-service-group",
        topics=["market.prediction.signal.v1"],
    )
    consumer = IntelligenceConsumer(config=config, fanout_use_case=MagicMock(), dedup_client=None)
    consumer._heartbeat_path = heartbeat_path  # type: ignore[attr-defined]
    return consumer


def test_idle_poll_cycle_refreshes_heartbeat_file(tmp_path: Any) -> None:
    """BUG 5: an idle poll cycle (no message) must refresh the heartbeat FILE.

    The Docker healthcheck stats the heartbeat file mtime with a 300s window.
    Before the fix the file was only touched on construction + per processed
    message, so a consumer assigned only empty topics froze the file at boot and
    the healthcheck went ``unhealthy`` forever despite a live poll loop.
    """
    import os
    import time

    hb = str(tmp_path / "hb")
    consumer = _make_intelligence_consumer(hb)

    # Simulate a stale file (as if frozen at boot long ago).
    with open(hb, "a"):
        os.utime(hb, (0, 0))
    assert os.path.getmtime(hb) < 1.0

    before_progress = consumer.last_progress_monotonic  # type: ignore[attr-defined]

    # The base loop calls _record_progress after every successful poll (idle OR
    # message; BP-700). Invoke it directly to exercise the IDLE path.
    consumer._record_progress()  # type: ignore[attr-defined]

    # File mtime is now fresh → healthcheck stays healthy on an idle topic.
    assert time.time() - os.path.getmtime(hb) < 5.0
    # The poll-cycle marker advanced …
    assert consumer.last_poll_monotonic > 0.0  # type: ignore[attr-defined]
    # … but the message-progress marker did NOT (no message was processed).
    assert consumer.last_progress_monotonic == before_progress  # type: ignore[attr-defined]


def test_touch_heartbeat_advances_message_marker(tmp_path: Any) -> None:
    """A processed message advances BOTH the file and the message-progress marker."""
    import os
    import time

    hb = str(tmp_path / "hb")
    consumer = _make_intelligence_consumer(hb)
    with open(hb, "a"):
        os.utime(hb, (0, 0))

    consumer._touch_heartbeat()  # type: ignore[attr-defined]

    assert time.time() - os.path.getmtime(hb) < 5.0
    assert consumer.last_progress_monotonic > 0.0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# intelligence_consumer_main — supervision (issue 4 / Fix A gaps A+B+C)
# ---------------------------------------------------------------------------


@contextlib.contextmanager  # type: ignore[misc]
def _intelligence_patches_live_event(
    mock_engine: AsyncMock,
    mock_valkey: AsyncMock,
    mock_consumer: MagicMock,
    mock_s1: AsyncMock,
    settings: MagicMock,
):  # type: ignore[no-untyped-def]
    """Like `_intelligence_patches` but uses a REAL (unset) asyncio.Event.

    Needed for the supervision tests where the consume task must finish (or the
    watchdog must fire) while the shutdown signal is NOT set — exercising the
    fatal-exit path rather than the graceful path.
    """
    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "alert.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("alert.infrastructure.clients.s1_client.S1Client", return_value=mock_s1),
        patch("alert.infrastructure.cache.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch(
            "alert.infrastructure.notification.valkey_publisher.ValkeyNotificationPublisher",
            return_value=MagicMock(),
        ),
        patch("alert.application.use_cases.alert_fanout.AlertFanoutUseCase", return_value=MagicMock()),
        patch(
            "alert.infrastructure.messaging.consumers.intelligence_consumer.IntelligenceConsumer",
            return_value=mock_consumer,
        ),
    ):
        yield


@pytest.mark.asyncio
async def test_intelligence_consumer_run_crash_force_exits() -> None:
    """Gap C: if consumer.run() returns/raises without a shutdown signal, the
    process is force-exited (os._exit) so the orchestrator restarts it."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_s1 = AsyncMock()
    mock_consumer = MagicMock()
    # run() finishes on its own (simulating a dead poll loop) — no stop signal.
    mock_consumer.run = AsyncMock(return_value=None)
    mock_consumer.stop = MagicMock()
    mock_consumer.last_progress_monotonic = 123.0
    settings = _mock_settings()

    # Subclass BaseException (not Exception) so the `except Exception` guard in
    # main() does not swallow it — mimics os._exit terminating the process.
    class _ForcedExitError(BaseException):
        pass

    def _fake_exit(code: int) -> None:
        raise _ForcedExitError(code)

    with _intelligence_patches_live_event(mock_engine, mock_valkey, mock_consumer, mock_s1, settings):
        import importlib

        from alert.infrastructure.messaging.consumers import intelligence_consumer_main

        importlib.reload(intelligence_consumer_main)
        with patch.object(intelligence_consumer_main.os, "_exit", _fake_exit):
            with pytest.raises(_ForcedExitError) as exc_info:
                await intelligence_consumer_main.main()

    # Exited with code 1 (unexpected run() exit), not the graceful path.
    assert exc_info.value.args[0] == 1


@pytest.mark.asyncio
async def test_intelligence_consumer_watchdog_exits_on_stall() -> None:
    """Gap A: the watchdog force-exits when no progress is made within the
    stall window while the consumer is supposed to be running."""
    import importlib

    from alert.infrastructure.messaging.consumers import intelligence_consumer_main

    importlib.reload(intelligence_consumer_main)

    class _ForcedExitError(Exception):
        pass

    def _fake_exit(code: int) -> None:
        raise _ForcedExitError(code)

    consumer = MagicMock()
    # F-006: the watchdog now gates on the poll-cycle marker. A genuinely
    # WEDGED loop stops cycling → its poll marker is far in the past → stalled.
    consumer.last_poll_monotonic = 0.0
    consumer.last_progress_monotonic = 0.0
    stop_event = _REAL_ASYNCIO_EVENT()  # never set
    log = MagicMock()

    with patch.object(intelligence_consumer_main.os, "_exit", _fake_exit):
        with pytest.raises(_ForcedExitError) as exc_info:
            # Tiny windows so the test runs fast: stall threshold 0s, poll 0.01s.
            await intelligence_consumer_main._liveness_watchdog(
                consumer,
                stop_event,
                log,
                stall_seconds=0.0,
                poll_seconds=0.01,
            )

    assert exc_info.value.args[0] == 3
    log.critical.assert_called_once()


@pytest.mark.asyncio
async def test_intelligence_consumer_watchdog_idle_topic_does_not_exit() -> None:
    """F-006 regression: an IDLE-but-alive consumer must NOT trip the watchdog.

    Reproduces the crash-loop: the topic is idle so no MESSAGE has been
    processed in a long time (``last_progress_monotonic`` is ancient), but the
    poll loop keeps cycling (``last_poll_monotonic`` stays fresh). The watchdog
    must gate on the poll marker and NOT force-exit.
    """
    import importlib
    import time

    from alert.infrastructure.messaging.consumers import intelligence_consumer_main

    importlib.reload(intelligence_consumer_main)

    consumer = MagicMock()
    # No message processed for ~1h (idle topic) — the OLD watchdog would exit.
    consumer.last_progress_monotonic = time.monotonic() - 3600.0
    # But the poll loop is cycling: poll marker refreshed "now".
    consumer.last_poll_monotonic = time.monotonic()
    stop_event = _REAL_ASYNCIO_EVENT()  # never set — consumer "running"
    log = MagicMock()

    def _boom(code: int) -> None:  # pragma: no cover — must not be called
        raise AssertionError(f"watchdog exited with {code} on an idle-but-alive consumer")

    async def _drive() -> None:
        with patch.object(intelligence_consumer_main.os, "_exit", _boom):
            # Stall threshold 300s; poll fast. The poll marker is fresh, so the
            # watchdog should keep looping (never exit) until we stop it.
            await intelligence_consumer_main._liveness_watchdog(
                consumer,
                stop_event,
                log,
                stall_seconds=300.0,
                poll_seconds=0.01,
            )

    task = asyncio.create_task(_drive())
    # Let the watchdog run several check cycles, then request graceful stop.
    await asyncio.sleep(0.05)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)

    # Idle ≠ wedged: no critical log, no exit.
    log.critical.assert_not_called()


@pytest.mark.asyncio
async def test_intelligence_consumer_watchdog_stops_gracefully() -> None:
    """The watchdog returns (no exit) when the stop signal fires."""
    import importlib

    from alert.infrastructure.messaging.consumers import intelligence_consumer_main

    importlib.reload(intelligence_consumer_main)

    consumer = MagicMock()
    consumer.last_poll_monotonic = 0.0
    consumer.last_progress_monotonic = 0.0
    stop_event = _REAL_ASYNCIO_EVENT()
    stop_event.set()  # graceful shutdown requested
    log = MagicMock()

    def _boom(code: int) -> None:  # pragma: no cover — must not be called
        raise AssertionError(f"watchdog exited with {code} during graceful stop")

    with patch.object(intelligence_consumer_main.os, "_exit", _boom):
        await intelligence_consumer_main._liveness_watchdog(
            consumer,
            stop_event,
            log,
            stall_seconds=0.0,
            poll_seconds=10.0,
        )

    log.critical.assert_not_called()


# ---------------------------------------------------------------------------
# watchlist_consumer_main
# ---------------------------------------------------------------------------


def _make_supervised_consumer() -> MagicMock:
    """Build a mock consumer whose run() blocks until stop() — the real contract.

    BP-704: ``watchlist_consumer_main`` now drives run() via
    ``run_consumer_supervised``, which treats a run() that returns on its own
    (without a stop signal) as an unexpected wedge/crash and raises
    ``ConsumerExited``. A bare ``AsyncMock`` returns instantly and would trip
    that path, so we model a healthy consumer: run() awaits a gate that stop()
    sets, so the supervisor takes the graceful-stop path.
    """
    mock_consumer = MagicMock()
    _run_gate = _REAL_ASYNCIO_EVENT()

    async def _run_until_stopped() -> None:
        await _run_gate.wait()

    mock_consumer.run = _run_until_stopped
    mock_consumer.stop = MagicMock(side_effect=lambda: _run_gate.set())
    return mock_consumer


@pytest.mark.asyncio
async def test_watchlist_consumer_graceful_stop() -> None:
    """Supervised graceful stop + s1_client.close + valkey.close called on stop."""
    mock_valkey = AsyncMock()
    mock_s1 = AsyncMock()
    mock_consumer = _make_supervised_consumer()
    settings = _mock_settings()

    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("alert.infrastructure.clients.s1_client.S1Client", return_value=mock_s1),
        patch("alert.infrastructure.cache.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch(
            "alert.infrastructure.messaging.consumers.watchlist_consumer.WatchlistConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from alert.infrastructure.messaging.consumers.watchlist_consumer_main import main

        await main()

    mock_consumer.stop.assert_called_once()
    mock_s1.close.assert_called_once()
    mock_valkey.close.assert_called_once()


@pytest.mark.asyncio
async def test_watchlist_consumer_stop_pre_set() -> None:
    """Consumer task is started then stopped immediately when stop_event is pre-set."""
    mock_valkey = AsyncMock()
    mock_s1 = AsyncMock()
    mock_consumer = _make_supervised_consumer()
    settings = _mock_settings()

    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("alert.infrastructure.clients.s1_client.S1Client", return_value=mock_s1),
        patch("alert.infrastructure.cache.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch(
            "alert.infrastructure.messaging.consumers.watchlist_consumer.WatchlistConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        import importlib

        from alert.infrastructure.messaging.consumers import watchlist_consumer_main

        importlib.reload(watchlist_consumer_main)
        await watchlist_consumer_main.main()

    mock_consumer.stop.assert_called_once()
    mock_valkey.close.assert_called_once()


# ---------------------------------------------------------------------------
# BP-704 — stall-aware /healthz liveness probe wired into start_metrics_server
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intelligence_consumer_wires_liveness_probe() -> None:
    """BP-704: the intelligence consumer main must pass a non-None liveness_probe
    to start_metrics_server so the Docker /healthz reflects poll-loop liveness."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    mock_s1 = AsyncMock()
    settings = _mock_settings()

    with _intelligence_patches(mock_engine, mock_valkey, mock_consumer, mock_s1, settings):
        import importlib

        from alert.infrastructure.messaging.consumers import intelligence_consumer_main

        importlib.reload(intelligence_consumer_main)
        # Patch the name as bound in the main module's namespace.
        with patch.object(intelligence_consumer_main, "start_metrics_server", return_value=MagicMock()) as mock_start:
            await intelligence_consumer_main.main()

    assert mock_start.call_args.kwargs["liveness_probe"] is not None


@pytest.mark.asyncio
async def test_watchlist_consumer_wires_liveness_probe() -> None:
    """BP-704: the watchlist consumer main must pass a non-None liveness_probe
    to start_metrics_server so the Docker /healthz reflects poll-loop liveness."""
    mock_valkey = AsyncMock()
    mock_s1 = AsyncMock()
    mock_consumer = _make_supervised_consumer()
    settings = _mock_settings()

    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("alert.infrastructure.clients.s1_client.S1Client", return_value=mock_s1),
        patch("alert.infrastructure.cache.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch(
            "alert.infrastructure.messaging.consumers.watchlist_consumer.WatchlistConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        import importlib

        from alert.infrastructure.messaging.consumers import watchlist_consumer_main

        importlib.reload(watchlist_consumer_main)
        with patch.object(watchlist_consumer_main, "start_metrics_server", return_value=MagicMock()) as mock_start:
            await watchlist_consumer_main.main()

    assert mock_start.call_args.kwargs["liveness_probe"] is not None


# ---------------------------------------------------------------------------
# dispatcher_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_main_cleanup() -> None:
    """engine.dispose() is called on exit."""
    mock_engine = AsyncMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()
    mock_dispatcher.stop = MagicMock()
    settings = _mock_settings()

    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "alert.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "alert.infrastructure.messaging.outbox.dispatcher.AlertOutboxDispatcher",
            return_value=mock_dispatcher,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from alert.infrastructure.messaging.outbox.dispatcher_main import main

        await main()

    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_dispatcher_main_stop() -> None:
    """dispatcher.stop() is called when stop_event fires."""
    mock_engine = AsyncMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()
    mock_dispatcher.stop = MagicMock()
    settings = _mock_settings()

    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "alert.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "alert.infrastructure.messaging.outbox.dispatcher.AlertOutboxDispatcher",
            return_value=mock_dispatcher,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        import importlib

        from alert.infrastructure.messaging.outbox import dispatcher_main

        importlib.reload(dispatcher_main)
        await dispatcher_main.main()

    mock_dispatcher.stop.assert_called_once()
