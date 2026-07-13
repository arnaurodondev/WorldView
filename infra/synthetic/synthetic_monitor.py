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
        # P1-19 PLAN-0088: real route is /healthz (FastAPI standard), not /health.
        resp = await client.get(f"{API_BASE}/healthz")
        resp.raise_for_status()
        assert resp.status_code == 200


# P1-19 PLAN-0088: probe targets corrected to canonical S9 surface.
# - prefix is /v1, not /api/v1 (S9 mounts a single APIRouter(prefix="/v1") in proxy.py).
# - market-data quote is /v1/quotes/{instrument_id} (UUIDv7), not /market-data/{ticker}/quote.
# - portfolio holdings is /v1/holdings/{portfolio_id}, not /portfolio/holdings.
# Configurable via env vars so the probe targets can be redirected per environment
# (dev vs staging vs production) without code changes.
SYNTHETIC_QUOTE_INSTRUMENT_ID = os.environ.get(
    "SYNTHETIC_QUOTE_INSTRUMENT_ID",
    # Default: AAPL canonical UUIDv7 from the seeded instruments table.
    "01900000-0000-7000-8000-000000001001",
)
SYNTHETIC_PORTFOLIO_ID = os.environ.get("SYNTHETIC_PORTFOLIO_ID", "")

# ── DeepInfra key freshness ───────────────────────────────────────────────────
# The whole ML pipeline (chat, embedding, extraction, relevance, resolution, KG,
# NL screener) runs on ONE DeepInfra account key duplicated across ~8 env vars.
# History: when that key was silently revoked/rotated the pipeline died with 401s
# and NO alert fired (MEMORY: "no freshness alert"). This probe hits DeepInfra's
# cheapest authenticated endpoint (GET /models) and reports success=0 on 401 so
# the existing SyntheticProbeDown critical alert fires within 5 minutes.
# The key is injected via DEEPINFRA_API_KEY (single-source var — see the
# de-fragilization note in infra/gitops/docs/deepinfra-key-rotation.md). Empty =
# probe skips (treated as success) so non-ML environments don't false-alarm.
DEEPINFRA_API_KEY = os.environ.get("DEEPINFRA_API_KEY", "")
DEEPINFRA_MODELS_URL = os.environ.get("DEEPINFRA_MODELS_URL", "https://api.deepinfra.com/v1/openai/models")


async def probe_deepinfra_key() -> None:
    """Fail loudly when the shared DeepInfra API key is dead (401/403).

    A 401/403 means the account key has been revoked or rotated out from under the
    running containers — the exact silent-death that halted the ML pipeline before.
    2xx = healthy; 5xx / network blips raise and are reported as a transient probe
    failure (self-heals on the next tick). No key configured = skip (success).
    """
    if not DEEPINFRA_API_KEY:
        return
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            DEEPINFRA_MODELS_URL,
            headers={"Authorization": f"Bearer {DEEPINFRA_API_KEY}"},
        )
        if resp.status_code in (401, 403):
            # Explicit, unambiguous failure signal for the alert annotation/logs.
            raise RuntimeError(
                f"DeepInfra rejected the shared API key (HTTP {resp.status_code}) — "
                "the key is dead/rotated; update it in worldview-gitops and redeploy."
            )
        resp.raise_for_status()


async def probe_market_data_quote() -> None:
    """Check that market data quote endpoint returns a response."""
    async with httpx.AsyncClient(timeout=15.0, headers=_auth_headers()) as client:
        resp = await client.get(f"{API_BASE}/v1/quotes/{SYNTHETIC_QUOTE_INSTRUMENT_ID}")
        # 200 OK or 404 (no data) are both acceptable — 5xx is the failure.
        if resp.status_code >= 500:
            resp.raise_for_status()


async def probe_portfolio_holdings() -> None:
    """Check that portfolio holdings endpoint returns a response."""
    if not SYNTHETIC_JWT or not SYNTHETIC_PORTFOLIO_ID:
        # Skip auth-required probes when no JWT or no demo portfolio_id configured.
        return
    async with httpx.AsyncClient(timeout=15.0, headers=_auth_headers()) as client:
        resp = await client.get(f"{API_BASE}/v1/holdings/{SYNTHETIC_PORTFOLIO_ID}")
        if resp.status_code >= 500:
            resp.raise_for_status()


PROBES = [
    probe_api_gateway_health,
    probe_market_data_quote,
    probe_portfolio_holdings,
    probe_deepinfra_key,
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
