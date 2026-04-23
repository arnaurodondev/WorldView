"""Entry point for the PriceImpactLabellingWorker process (PRD-0020 §6.5, R22).

Run as a standalone process (never as a background task inside the API):

    python -m nlp_pipeline.workers.price_impact_labelling_worker

Responsibilities:
  - Configure logging
  - Load Settings from environment
  - Wire MarketDataClient (httpx.AsyncClient) + nlp_db session factory
  - Install SIGINT / SIGTERM handlers
  - Run PriceImpactLabellingWorker.run_forever() until stop event is set
  - Exit with code 0 on clean shutdown, code 1 on startup failure
"""

from __future__ import annotations

import asyncio
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    import httpx

    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.http.market_data_client import MarketDataClient
    from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories
    from nlp_pipeline.infrastructure.workers.price_impact_labelling_worker import (
        PriceImpactLabellingWorker,
    )

    settings = Settings()
    configure_logging(
        service_name="nlp-pipeline-price-impact-worker",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("nlp_pipeline.price_impact_worker_main")  # type: ignore[no-any-return]
    log.info("price_impact_worker_starting")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # ── Wire dependencies ─────────────────────────────────────────────────────
    try:
        nlp_engine, _read_engine, nlp_sf, _read_sf = _build_nlp_factories(settings)
    except Exception as exc:
        log.error("price_impact_worker_startup_failed", error=str(exc))
        sys.exit(1)

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        market_client = MarketDataClient(http_client, settings.market_data_internal_url)
        worker = PriceImpactLabellingWorker(
            nlp_session_factory=nlp_sf,
            market_data_client=market_client,
            cap_day_t0_pct=settings.price_impact_cap_day_t0_pct,
            cap_day_t1_pct=settings.price_impact_cap_day_t1_pct,
            cap_day_t2_pct=settings.price_impact_cap_day_t2_pct,
            cap_day_t5_pct=settings.price_impact_cap_day_t5_pct,
            cycle_seconds=settings.price_impact_cycle_seconds,
            min_age_hours=settings.price_impact_min_age_hours,
        )

        log.info(
            "price_impact_worker_ready",
            cycle_seconds=settings.price_impact_cycle_seconds,
            min_age_hours=settings.price_impact_min_age_hours,
        )
        await worker.run_forever(stop_event)

    await nlp_engine.dispose()
    log.info("price_impact_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
