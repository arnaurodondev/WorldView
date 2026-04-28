"""Synthetic monitoring — simulates real user journeys every 60 seconds.

Pushes results to Prometheus Pushgateway so alerts fire when probes fail.
Probe names are used as alert labels in the SyntheticProbeDown alert rule.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "http://pushgateway:9091")
API_BASE = os.environ.get("API_BASE_URL", "http://api-gateway:8000")
SYNTHETIC_JWT = os.environ.get("SYNTHETIC_JWT", "")
PROBE_INTERVAL_S = int(os.environ.get("PROBE_INTERVAL_S", "60"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

registry = CollectorRegistry()
probe_success = Gauge(
    "synthetic_probe_success",
    "1 if the synthetic probe succeeded, 0 if it failed",
    ["probe_name"],
    registry=registry,
)
probe_duration_seconds = Gauge(
    "synthetic_probe_duration_seconds",
    "Duration of the synthetic probe in seconds",
    ["probe_name"],
    registry=registry,
)


def _auth_headers() -> dict[str, str]:
    if SYNTHETIC_JWT:
        return {"Authorization": f"Bearer {SYNTHETIC_JWT}"}
    return {}


async def probe_api_gateway_health() -> None:
    """Check API gateway health endpoint returns 200."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{API_BASE}/health")
        resp.raise_for_status()
        assert resp.status_code == 200


async def probe_market_data_quote() -> None:
    """Check that market data quote endpoint returns a response."""
    async with httpx.AsyncClient(timeout=15.0, headers=_auth_headers()) as client:
        resp = await client.get(f"{API_BASE}/api/v1/market-data/AAPL/quote")
        # 200 OK or 404 (no data) are both acceptable — 5xx is the failure
        if resp.status_code >= 500:
            resp.raise_for_status()


async def probe_portfolio_holdings() -> None:
    """Check that portfolio holdings endpoint returns a response."""
    if not SYNTHETIC_JWT:
        # Skip auth-required probes when no JWT configured
        return
    async with httpx.AsyncClient(timeout=15.0, headers=_auth_headers()) as client:
        resp = await client.get(f"{API_BASE}/api/v1/portfolio/holdings")
        if resp.status_code >= 500:
            resp.raise_for_status()


PROBES = [
    probe_api_gateway_health,
    probe_market_data_quote,
    probe_portfolio_holdings,
]


async def run_probes() -> None:
    for probe_fn in PROBES:
        name = probe_fn.__name__
        start = time.perf_counter()
        try:
            await probe_fn()
            probe_success.labels(probe_name=name).set(1.0)
            log.info("probe_ok", extra={"probe": name})
        except Exception as exc:
            probe_success.labels(probe_name=name).set(0.0)
            log.error("probe_failed", extra={"probe": name, "error": str(exc)})
        finally:
            probe_duration_seconds.labels(probe_name=name).set(time.perf_counter() - start)

    try:
        push_to_gateway(PUSHGATEWAY_URL, job="synthetic_monitor", registry=registry)
        log.info("pushed_to_gateway")
    except Exception as exc:
        log.error("push_failed", extra={"error": str(exc)})


async def main() -> None:
    log.info("synthetic_monitor_started", extra={"interval_s": PROBE_INTERVAL_S, "api_base": API_BASE})
    while True:
        await run_probes()
        await asyncio.sleep(PROBE_INTERVAL_S)


if __name__ == "__main__":
    asyncio.run(main())
