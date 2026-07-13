"""Standalone entry-point for the S3 PredictionMoveDetector worker.

PLAN-0056 Wave D1. Runs :class:`PredictionMoveDetector` on a fixed cadence
(``MARKET_DATA_PREDICTION_MOVE_DETECTOR_INTERVAL_SECONDS``, default 900 s) until
SIGTERM/SIGINT. Intended to run as its own container/process (R22).

Usage (standalone)::

    python -m market_data.infrastructure.workers.prediction_move_detector_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys

from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from market_data.config import Settings
    from market_data.infrastructure.db.session import (
        build_read_engine,
        build_session_factory,
        build_write_engine,
    )
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
    from market_data.infrastructure.workers.prediction_move_detector import (
        PredictionMoveDetector,
    )

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("market_data.prediction_move_detector_main")  # type: ignore[no-any-return]
    log.info("prediction_move_detector_starting", service=settings.service_name)

    # BP-704 parity with the consumers: expose /metrics + /healthz on 9100.
    metrics_handle = start_metrics_server(
        service_name="market-data-prediction-move-detector",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    write_engine = build_write_engine(settings)
    read_engine = build_read_engine(settings)
    write_factory = build_session_factory(write_engine)
    read_factory = build_session_factory(read_engine)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        # Read/write splitting: scans hit ``read_factory`` (replica, R27), the
        # outbox emit hits ``write_factory`` (primary, R8).
        return SqlAlchemyUnitOfWork(write_factory, read_factory)

    detector = PredictionMoveDetector(uow_factory=uow_factory, settings=settings, logger=log)
    interval_seconds = float(settings.prediction_move_detector_interval_seconds)

    log_runtime_banner(
        "market-data-prediction-move-detector",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "interval_seconds": interval_seconds,
            "delta_threshold": settings.prediction_move_delta_threshold,
            "min_liquidity_usd": settings.prediction_move_min_liquidity_usd,
            "min_volume_usd": settings.prediction_move_min_volume_usd,
        },
    )

    try:
        while not stop_event.is_set():
            try:
                await detector.run_cycle()
            except Exception as exc:
                # A cycle failure must never kill the loop — log and retry on the
                # next tick (the detector is best-effort signalling, not a
                # transactional consumer).
                log.error("prediction_move_detector_cycle_error", error=str(exc))

            # Interruptible sleep: wake immediately on shutdown.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
    except Exception as exc:
        log.error("prediction_move_detector_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await write_engine.dispose()
        if read_engine is not write_engine:
            await read_engine.dispose()
        log.info("prediction_move_detector_stopped")
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
