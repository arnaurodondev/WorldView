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
import contextlib
import os
import signal
import sys

from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    import httpx

    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.http.market_data_client import MarketDataClient
    from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories
    from nlp_pipeline.infrastructure.workers.price_impact_labelling_worker import (
        PriceImpactLabellingWorker,
    )

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="nlp-pipeline-price-impact-worker",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("nlp_pipeline.price_impact_worker_main")  # type: ignore[no-any-return]
    log.info("price_impact_worker_starting")

    # ── FAIL-LOUD startup guard (2026-07-21) ──────────────────────────────────
    # Root cause of the globally-empty ``article_impact_windows`` table: in
    # production this worker needs ``NLP_PIPELINE_SERVICE_ACCOUNT_TOKEN`` to mint
    # an X-Internal-JWT via S9's ``POST /internal/v1/service-token``. When it is
    # unset, ``MarketDataClient`` falls back to ``POST /v1/auth/dev-login`` — which
    # S9 hard-blocks when APP_ENV=production — so every OHLCV call 401s and the
    # table stays empty forever, silently. Surface that misconfiguration at
    # startup instead of discovering an empty table weeks later.
    _app_env = os.getenv("APP_ENV", "").strip().lower()
    if _app_env in {"production", "prod"} and not (settings.service_account_token or "").strip():
        log.error(
            "price_impact_worker_missing_service_account_token",
            app_env=_app_env,
            impact=(
                "NLP_PIPELINE_SERVICE_ACCOUNT_TOKEN is unset in production; dev-login "
                "fallback is blocked, so every market-data OHLCV call will 401 and "
                "article_impact_windows will stay empty. Set it from the same sealed "
                "secret as API_GATEWAY_SERVICE_ACCOUNT_TOKEN."
            ),
        )

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics.
    metrics_handle = start_metrics_server(
        service_name="nlp-pipeline-price-impact-worker",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

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
        # F-101 / BP-303: pass api_gateway_url + (optionally) service-account
        # secret so MarketDataClient can mint a valid X-Internal-JWT.
        # When ``service_account_token`` is set, the client calls
        # ``POST /internal/v1/service-token`` (production-safe). When unset,
        # it falls back to ``POST /v1/auth/dev-login`` (local-dev convenience).
        # Without either, every OHLCV call returns 401 and
        # article_impact_windows stays empty.
        market_client = MarketDataClient(
            http_client,
            settings.market_data_internal_url,
            api_gateway_url=settings.api_gateway_url,
            service_account_token=settings.service_account_token or None,
            service_name="nlp-pipeline-price-impact",
        )
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
    with contextlib.suppress(Exception):
        await metrics_handle.aclose()
    log.info("price_impact_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
