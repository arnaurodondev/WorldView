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

# BP-728: httpx's own client logs every request at INFO — `logger.info('HTTP
# Request: %s %s "%s %d %s"', request.method, request.url, ...)` — and
# `request.url`'s str() includes the full query string. probe_deepinfra_key
# sends its key via an Authorization header (never in the URL) so this never
# mattered before, but probe_eodhd_key's EODHD auth scheme puts api_token in
# the query string (matches every other EODHD client in this repo). Without
# this, basicConfig's root INFO level would let httpx's own request log leak
# the live key to stdout/Loki on every real (non-throttled) probe tick,
# completely bypassing the exception-message redaction in probe_eodhd_key()
# below. Raising this one logger's level is enough — nothing in this file
# relies on httpx's own request/response logging.
logging.getLogger("httpx").setLevel(logging.WARNING)

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


# ── EODHD key freshness ───────────────────────────────────────────────────────
# Same single-key fragility class as DeepInfra above: EODHD_API_KEY is one shared
# account key used across content-ingestion (news), market-ingestion (OHLCV,
# fundamentals), and market-data. If it is rotated/revoked with no freshness
# probe, news/market-data ingestion would silently starve exactly like the
# DeepInfra incident this pattern was built to prevent (MEMORY: "no freshness
# alert"). We probe GET /api/internal-user — EODHD's account-details endpoint,
# used ONLY here (content-ingestion/market-ingestion do NOT poll it in any live
# code path today; the config.py comments citing it document a one-off manual
# `curl` verification of `dailyRateLimit`, not a running call site).
#
# Cost: per EODHD's own docs (docs/references/eodhd-endpoints-reference.md,
# "User Details API" section) this endpoint bills **1 API call per request** —
# it is NOT free, just the cheapest authenticated call EODHD exposes (every
# data endpoint bills 5-100 credits/request via `credits_per_request`). To keep
# this probe's cost negligible against the shared 100k-calls/UTC-day cap
# (already running ~75k/day per the 2026-07-03 incident notes) and invisible-
# to-`daily_budget_tracker.py` since it bypasses that Valkey-based accounting
# entirely, the probe throttles its OWN real HTTP calls to at most once per
# EODHD_PROBE_MIN_INTERVAL_S (default 900s/15min) regardless of the main
# PROBE_INTERVAL_S loop cadence — 96 calls/day (~0.1% of the daily cap) vs.
# 1,440/day if it fired every 60s tick. Between real checks the probe replays
# the last known result so synthetic_probe_success still reflects the last
# observed state on every tick (SyntheticProbeDown's `for: 5m` window is
# unaffected — a real failure still holds the gauge at 0 continuously).
#
# Trade-offs this throttle introduces (accepted, documented here so nobody
# assumes EODHD key-dead detection has the same latency as DeepInfra's):
# - Any failure (401/403 dead-key, 5xx, network error) is cached and replayed
#   for up to EODHD_PROBE_MIN_INTERVAL_S — a transient blip does NOT
#   self-heal on "the next 60s tick" the way probe_deepinfra_key does; it
#   self-heals on the next REAL check, up to ~15 minutes later.
# - The one exception: if EODHD_API_KEY's *value* changes (a live key
#   rotation) the throttle is bypassed and a real check runs immediately —
#   see the key-change check below — so a bad rotation is never masked by a
#   stale cached success from the old key.
# - synthetic_probe_duration_seconds{probe_name="probe_eodhd_key"} reads
#   near-zero on throttled ticks (no real HTTP call happened) and only
#   reflects genuine network latency on the ~1-in-15 ticks that perform a
#   real check — expected, not a bug, but relevant if a duration-based
#   alert/dashboard panel is ever built on this metric.
EODHD_API_KEY = os.environ.get("EODHD_API_KEY", "")
EODHD_USER_URL = os.environ.get("EODHD_USER_URL", "https://eodhd.com/api/internal-user")
EODHD_PROBE_MIN_INTERVAL_S = float(os.environ.get("EODHD_PROBE_MIN_INTERVAL_S", "900"))

# Module-level throttle state: monotonic timestamp of the last REAL HTTP
# check, the key value that check was performed against (so a rotation mid-
# window forces an immediate real recheck instead of replaying the old key's
# cached result), and the outcome to replay on ticks that fall inside the
# throttle window. `None` = no real check has run yet this process lifetime
# (first tick always performs a real check regardless of interval).
_eodhd_last_check_monotonic: float | None = None
_eodhd_last_check_key: str | None = None
_eodhd_last_check_error: Exception | None = None


async def probe_eodhd_key() -> None:
    """Fail loudly when the shared EODHD API key is dead (401/403).

    A 401/403 means the account key has been revoked or rotated out from under
    the running containers — the exact silent-death class that halted the ML
    pipeline when the DeepInfra key rotated (probe_deepinfra_key above). 2xx =
    healthy. No key configured = skip (success).

    Real HTTP calls are throttled to EODHD_PROBE_MIN_INTERVAL_S (see module
    docstring above the globals) — this endpoint bills 1 EODHD API call per
    request, unlike DeepInfra's genuinely free GET /models, so hitting it on
    every 60s PROBE_INTERVAL_S tick would add unnecessary load against the
    shared daily quota. Between real checks, the last known outcome (2xx,
    401/403, 5xx, or a network error) is replayed so the exposed gauge always
    reflects the last real observation — this means a transient 5xx/network
    blip self-heals on the next REAL check (up to EODHD_PROBE_MIN_INTERVAL_S
    later), not on the next 60s tick the way probe_deepinfra_key's does. If
    EODHD_API_KEY's value changes mid-window (a live rotation), the throttle
    is bypassed and a real check runs immediately so a bad rotation can never
    hide behind a stale cached success from the old key.
    """
    global _eodhd_last_check_monotonic, _eodhd_last_check_key, _eodhd_last_check_error

    if not EODHD_API_KEY:
        return

    now = time.monotonic()
    key_unchanged = _eodhd_last_check_key == EODHD_API_KEY
    within_window = (
        _eodhd_last_check_monotonic is not None and (now - _eodhd_last_check_monotonic) < EODHD_PROBE_MIN_INTERVAL_S
    )
    if key_unchanged and within_window:
        # Throttled: replay the last real outcome rather than making a new
        # billed request.
        if _eodhd_last_check_error is not None:
            raise _eodhd_last_check_error
        return

    try:
        await _check_eodhd_key_live()
    except Exception as exc:
        _eodhd_last_check_error = exc
        _eodhd_last_check_monotonic = now
        _eodhd_last_check_key = EODHD_API_KEY
        raise
    else:
        _eodhd_last_check_error = None
        _eodhd_last_check_monotonic = now
        _eodhd_last_check_key = EODHD_API_KEY


async def _check_eodhd_key_live() -> None:
    """Perform the actual (billed) EODHD request. Split out from
    probe_eodhd_key() so the throttle bookkeeping above stays simple to read
    and test independently of the HTTP call itself."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        # api_token travels as a query param per EODHD's auth scheme (matches
        # every other EODHD client in this repo) — never logged or included in
        # any exception message below.
        resp = await client.get(EODHD_USER_URL, params={"api_token": EODHD_API_KEY, "fmt": "json"})
        if resp.status_code in (401, 403):
            # Explicit, unambiguous failure signal for the alert annotation/logs.
            # Deliberately omits the key value and the full response body.
            raise RuntimeError(
                f"EODHD rejected the shared API key (HTTP {resp.status_code}) — "
                "the key is dead/rotated; update it in worldview-gitops and redeploy."
            )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            # httpx's default HTTPStatusError message embeds the full request
            # URL — including the api_token query param — via
            # exc.request.url/exc.response.request.url. That string flows
            # straight into log.error(..., extra={"error": str(exc)}) in
            # run_probes(), so the raw exception must never propagate as-is.
            # Re-raise with a redacted message instead (status + endpoint host
            # only, no query string) so the key can never reach logs. Chained
            # `from None` (not `from exc`) deliberately severs `__cause__`: the
            # original HTTPStatusError (and its request, with the live
            # api_token in the query string) is cached in the module-level
            # throttle state below for up to EODHD_PROBE_MIN_INTERVAL_S, so it
            # must never be reachable via traceback/repr/APM exception-chain
            # serialization even though nothing today logs anything beyond
            # str(exc).
            raise RuntimeError(
                f"EODHD probe request failed (HTTP {resp.status_code}) against {EODHD_USER_URL} (query params redacted)"
            ) from None


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
    probe_eodhd_key,
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
