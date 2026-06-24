"""Unit tests for the bundle pre-warmer worker (PLAN-0099 R3).

Verifies:
- A cycle issues one bundle fetch per configured entity_id.
- A 5xx / network failure for one entity does NOT crash the loop or block
  the remaining entities.
- The asyncio.Semaphore caps the number of concurrently in-flight requests
  to ``prewarm_concurrency``.

Tests construct ``BundlePrewarmer`` directly with a Settings instance that
carries a real (test-generated) RSA private key, and inject a fake httpx
AsyncClient so no real HTTP traffic is issued.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from api_gateway.config import Settings
from api_gateway.workers.bundle_prewarmer_main import BundlePrewarmer
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

pytestmark = pytest.mark.unit


def _gen_keypair() -> tuple[str, str]:
    """Generate a throwaway RSA-2048 PEM pair for tests."""
    pk = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    private_pem = pk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        pk.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _make_settings(entity_ids: list[str], concurrency: int = 3) -> Settings:
    """Construct a Settings object with prewarm fields populated."""
    private_pem, public_pem = _gen_keypair()
    return Settings(
        valkey_url="redis://localhost:6379/0",
        oidc_issuer_url="https://example.zitadel.cloud",
        oidc_client_id="test-client",
        oidc_client_secret="test-secret",
        oidc_audience="test-client",
        internal_jwt_private_key=private_pem,
        internal_jwt_public_key=public_pem,
        prewarm_enabled=True,
        prewarm_entity_ids=entity_ids,
        prewarm_concurrency=concurrency,
    )


def _ok_response(status: int = 200, body: str = "{}") -> httpx.Response:
    """Build an httpx.Response with the elapsed attribute populated.

    The worker reads ``response.elapsed`` for logging; httpx.Response sets it
    only on real network calls, so tests must populate it manually.
    """
    req = httpx.Request("GET", "http://test/v1/entities/x/intelligence-bundle")
    resp = httpx.Response(status_code=status, text=body, request=req)
    resp.elapsed = __import__("datetime").timedelta(milliseconds=10)
    return resp


@pytest.mark.asyncio
async def test_cycle_fetches_every_entity_once() -> None:
    """Each configured entity_id receives exactly one GET per cycle."""
    entity_ids = [f"00000000-0000-0000-0000-00000000000{i}" for i in range(1, 4)]
    worker = BundlePrewarmer(settings=_make_settings(entity_ids))

    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=_ok_response(200))

    await worker._run_cycle(client)

    # One call per entity_id, all targeted at /v1/entities/<id>/intelligence-bundle.
    assert client.get.await_count == len(entity_ids)
    called_urls = {call.args[0] for call in client.get.await_args_list}
    for eid in entity_ids:
        assert f"/v1/entities/{eid}/intelligence-bundle" in called_urls


@pytest.mark.asyncio
async def test_failed_request_does_not_crash_loop() -> None:
    """A network exception for one entity is logged but does NOT abort the cycle."""
    entity_ids = ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]
    worker = BundlePrewarmer(settings=_make_settings(entity_ids))

    client = MagicMock(spec=httpx.AsyncClient)
    # First call raises (simulating a connection error), second succeeds.
    client.get = AsyncMock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            _ok_response(200),
        ]
    )

    # Must NOT raise — log-and-continue policy.
    await worker._run_cycle(client)

    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_non_2xx_response_logged_but_not_raised() -> None:
    """A 5xx response is logged at warning level but the loop continues."""
    entity_ids = ["cccccccc-cccc-cccc-cccc-cccccccccccc"]
    worker = BundlePrewarmer(settings=_make_settings(entity_ids))

    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=_ok_response(503, body="upstream down"))

    await worker._run_cycle(client)

    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_semaphore_caps_in_flight_requests() -> None:
    """At most ``prewarm_concurrency`` requests are in-flight at any time."""
    # 10 entities, concurrency cap = 2 → max simultaneous = 2.
    entity_ids = [f"dddddddd-dddd-dddd-dddd-dddddddddd{i:02d}" for i in range(10)]
    worker = BundlePrewarmer(settings=_make_settings(entity_ids, concurrency=2))

    in_flight = 0
    max_observed = 0
    lock = asyncio.Lock()

    async def slow_get(*_args: Any, **_kwargs: Any) -> httpx.Response:
        nonlocal in_flight, max_observed
        async with lock:
            in_flight += 1
            max_observed = max(max_observed, in_flight)
        # Yield long enough that the next request would queue if the semaphore
        # were not enforcing the cap.
        await asyncio.sleep(0.02)
        async with lock:
            in_flight -= 1
        return _ok_response(200)

    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(side_effect=slow_get)

    await worker._run_cycle(client)

    assert client.get.await_count == len(entity_ids)
    # Semaphore must cap concurrency at the configured value.
    assert max_observed <= 2, f"max in-flight {max_observed} exceeds cap of 2"


@pytest.mark.asyncio
async def test_stop_event_exits_run_loop() -> None:
    """Calling ``stop()`` causes ``run()`` to return after the current cycle."""
    worker = BundlePrewarmer(settings=_make_settings(["eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"]))
    # Stop immediately — the loop should run at most one cycle then exit.
    worker.stop()

    # Patch the AsyncClient context manager so no real network is opened.
    # We monkey-patch the bound httpx.AsyncClient inside the worker call by
    # using a tiny stub via asyncio.wait_for safety net.
    import api_gateway.workers.bundle_prewarmer_main as mod

    class _StubClient:
        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def get(self, *_args: Any, **_kwargs: Any) -> httpx.Response:
            return _ok_response(200)

    orig = mod.httpx.AsyncClient
    mod.httpx.AsyncClient = lambda *a, **kw: _StubClient()  # type: ignore[assignment,misc]
    try:
        # Bounded wait — if stop() does not unblock the loop, the test fails.
        await asyncio.wait_for(worker.run(), timeout=5.0)
    finally:
        mod.httpx.AsyncClient = orig  # type: ignore[assignment]
