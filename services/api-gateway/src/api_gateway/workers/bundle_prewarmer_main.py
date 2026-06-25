"""Bundle pre-warmer worker (PLAN-0099 R3).

Periodically re-fetches the Intelligence-tab composite bundle for a configured
set of hot entity IDs (typically the S&P 500). The bundle endpoint itself does
not cache, but the underlying legs (S7 intel: 60 s, S7 paths: 300 s) do — by
forcing a fan-out call every ``PREWARM_INTERVAL_SECONDS`` we keep those caches
populated so the first real user request hits a warm path (~88 ms) instead of
a cold 4-10 s fan-out.

Run with::

    python -m api_gateway.workers.bundle_prewarmer_main

The worker is opt-in. It refuses to start unless ``API_GATEWAY_PREWARM_ENABLED=true``
AND ``API_GATEWAY_PREWARM_ENTITY_IDS`` contains at least one UUID. Default
deployment posture is OFF so dev / test / CI never fires the loop.

Authentication: the worker mints a short-lived RS256 service-account JWT using
the gateway's own private key (same key the running api-gateway process uses
to sign user JWTs). It sends this in ``X-Internal-JWT`` AND in the
``Authorization: Bearer`` header so both the gateway's external auth path and
the internal-JWT middleware accept the request.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import TYPE_CHECKING

import httpx

from api_gateway.config import Settings
from api_gateway.jwt_utils import issue_service_jwt
from api_gateway.oidc import load_rsa_private_key
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

logger = get_logger(__name__)

_SERVICE_NAME = "api-gateway-bundle-prewarmer"
# TTL chosen so the JWT survives a full cycle even if early entities take the
# worst-case timeout. Re-minted every cycle.
_JWT_TTL_SECONDS = 600


class BundlePrewarmer:
    """Runs the prewarm loop with bounded concurrency and graceful shutdown.

    The instance is single-shot: ``run()`` returns once ``stop()`` is called
    (after the in-flight cycle drains).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stop_event = asyncio.Event()
        self._semaphore = asyncio.Semaphore(max(1, settings.prewarm_concurrency))
        # Pre-load the private key once so each cycle just re-signs (cheap).
        self._private_key: RSAPrivateKey = load_rsa_private_key(settings.internal_jwt_private_key.get_secret_value())
        self._kid = settings.jwt_key_version

    def stop(self) -> None:
        """Signal the loop to exit after the current cycle drains."""
        self._stop_event.set()

    def _mint_token(self) -> str:
        """Mint a fresh service-account RS256 JWT for the next cycle."""
        return issue_service_jwt(
            service_name=_SERVICE_NAME,
            private_key=self._private_key,
            kid=self._kid,
            ttl_seconds=_JWT_TTL_SECONDS,
        )

    async def _prewarm_one(
        self,
        client: httpx.AsyncClient,
        entity_id: str,
        token: str,
    ) -> None:
        """Issue a single bundle fetch; log outcome; never raise."""
        # Bound concurrency: only ``prewarm_concurrency`` requests can be
        # in-flight at any moment per cycle (DOS-protection for our own gateway).
        async with self._semaphore:
            url = f"/v1/entities/{entity_id}/intelligence-bundle"
            headers = {
                "X-Internal-JWT": token,
                "Authorization": f"Bearer {token}",
            }
            try:
                response = await client.get(url, headers=headers)
            except Exception as exc:
                logger.warning(
                    "bundle_prewarm_failed",
                    entity_id=entity_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return

            if 200 <= response.status_code < 300:
                logger.info(
                    "bundle_prewarm_ok",
                    entity_id=entity_id,
                    status=response.status_code,
                    elapsed_ms=int(response.elapsed.total_seconds() * 1000),
                )
            else:
                logger.warning(
                    "bundle_prewarm_failed",
                    entity_id=entity_id,
                    status=response.status_code,
                    # Truncate body so a verbose 5xx page does not flood logs.
                    body_preview=response.text[:200],
                )

    async def _run_cycle(self, client: httpx.AsyncClient) -> None:
        """Fan out a prewarm fetch for every configured entity_id."""
        token = self._mint_token()
        entity_ids = self._settings.prewarm_entity_ids
        logger.info(
            "bundle_prewarm_cycle_starting",
            entity_count=len(entity_ids),
            concurrency=self._settings.prewarm_concurrency,
        )
        # gather() with the semaphore inside _prewarm_one caps in-flight calls.
        # return_exceptions guarantees one bad entity never aborts the cycle —
        # plus _prewarm_one swallows exceptions itself for defence in depth.
        await asyncio.gather(
            *(self._prewarm_one(client, eid, token) for eid in entity_ids),
            return_exceptions=True,
        )
        logger.info("bundle_prewarm_cycle_complete", entity_count=len(entity_ids))

    async def run(self) -> None:
        """Main loop — repeats every ``prewarm_interval_seconds`` until stopped."""
        base_url = self._settings.prewarm_api_base_url
        timeout = httpx.Timeout(self._settings.prewarm_request_timeout_seconds)
        # One AsyncClient for the whole worker lifetime → HTTP/1.1 keep-alive
        # cuts handshake overhead vs new client per request.
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            while not self._stop_event.is_set():
                try:
                    await self._run_cycle(client)
                except Exception:
                    logger.exception("bundle_prewarm_cycle_crashed")

                # Wait for either the interval to elapse or stop() to fire,
                # whichever comes first. Avoids a long blocking sleep that
                # would delay SIGTERM-driven shutdown by up to 4 minutes.
                # Expected TimeoutError == interval elapsed; loop again.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._settings.prewarm_interval_seconds,
                    )


async def _run() -> None:
    """Async entrypoint — installs signal handlers and runs until SIGTERM."""
    settings = Settings()  # type: ignore[call-arg]

    configure_logging(
        service_name=_SERVICE_NAME,
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    log = get_logger("api_gateway.bundle_prewarmer_main")
    log.info("bundle_prewarmer_starting")

    # Opt-in guard — refuse to run by default. Logged explicitly so an
    # operator who mis-configures sees the reason in the container logs.
    if not settings.prewarm_enabled:
        log.warning("bundle_prewarmer_disabled", reason="prewarm_enabled=false")
        return
    if not settings.prewarm_entity_ids:
        log.warning("bundle_prewarmer_no_entities", reason="prewarm_entity_ids=[]")
        return

    metrics_handle = start_metrics_server(
        service_name=_SERVICE_NAME,
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    log_runtime_banner(
        _SERVICE_NAME,
        dependencies={
            "api_gateway_url": settings.prewarm_api_base_url,
            "entity_count": len(settings.prewarm_entity_ids),
            "interval_seconds": settings.prewarm_interval_seconds,
            "concurrency": settings.prewarm_concurrency,
        },
    )

    worker = BundlePrewarmer(settings=settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)

    try:
        await worker.run()
    finally:
        await metrics_handle.aclose()
        log.info("bundle_prewarmer_stopped")


def main() -> None:
    """Sync entrypoint used by ``python -m api_gateway.workers.bundle_prewarmer_main``."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
