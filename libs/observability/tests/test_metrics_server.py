"""Tests for observability.metrics_server.start_metrics_server."""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
import structlog
from prometheus_client import CollectorRegistry, Counter

from observability.metrics_server import start_metrics_server


async def _wait_until_ready(port: int, *, timeout_s: float = 5.0) -> None:
    """Poll the bound port until uvicorn accepts connections."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_err: Exception | None = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                resp = await client.get(f"http://127.0.0.1:{port}/healthz")
                if resp.status_code in (200, 503):
                    return
        except Exception as exc:
            last_err = exc
            await asyncio.sleep(0.05)
    raise AssertionError(f"server never became ready on port {port}: {last_err}")


@pytest.mark.asyncio
async def test_start_metrics_server_serves_healthz_and_metrics() -> None:
    # Use an isolated registry so prometheus_client doesn't bleed counter
    # state across other tests in the suite.
    registry = CollectorRegistry()
    Counter("test_counter_total", "test", registry=registry).inc()

    handle = start_metrics_server(
        service_name="pytest-worker",
        port=0,
        registry=registry,
    )
    try:
        port = handle.bound_port
        await _wait_until_ready(port)
        async with httpx.AsyncClient(timeout=2.0) as client:
            health = await client.get(f"http://127.0.0.1:{port}/healthz")
            assert health.status_code == 200
            assert health.json() == {"status": "ok", "service": "pytest-worker"}

            metrics = await client.get(f"http://127.0.0.1:{port}/metrics")
            assert metrics.status_code == 200
            assert "# HELP" in metrics.text
            assert "test_counter_total" in metrics.text
    finally:
        await handle.aclose()


@pytest.mark.asyncio
async def test_liveness_probe_false_returns_503() -> None:
    handle = start_metrics_server(
        service_name="pytest-worker",
        port=0,
        registry=CollectorRegistry(),
        liveness_probe=lambda: False,
    )
    try:
        port = handle.bound_port
        await _wait_until_ready(port)
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://127.0.0.1:{port}/healthz")
            assert resp.status_code == 503
            assert resp.json()["status"] == "unhealthy"
    finally:
        await handle.aclose()


@pytest.mark.asyncio
async def test_aclose_stops_server_within_timeout() -> None:
    handle = start_metrics_server(
        service_name="pytest-worker",
        port=0,
        registry=CollectorRegistry(),
    )
    port = handle.bound_port
    await _wait_until_ready(port)

    await handle.aclose(timeout_s=5.0)

    # Once aclose() returns, a fresh TCP connection MUST fail — this
    # proves the listener is truly down (not just refusing HTTP).
    with pytest.raises(OSError):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect(("127.0.0.1", port))
        finally:
            s.close()


@pytest.mark.asyncio
async def test_started_event_reports_families() -> None:
    """``metrics_server_started`` event must report the family count + sample (PLAN-0107 B-1)."""
    registry = CollectorRegistry()
    # Register one Counter BEFORE start so the boot-time enumeration
    # sees it.  The exposition format strips the ``_total`` suffix in
    # the family name, so we assert on the metric base name.
    Counter("plan0107_b1_demo_total", "demo metric for B-1 test", registry=registry)

    with structlog.testing.capture_logs() as cap:
        handle = start_metrics_server(
            service_name="pytest-worker",
            port=0,
            registry=registry,
        )
    try:
        port = handle.bound_port
        await _wait_until_ready(port)

        started = [e for e in cap if e.get("event") == "metrics_server_started"]
        assert len(started) == 1, f"expected 1 started event, got {len(started)}: {cap}"
        event = started[0]
        assert event["registered_families"] >= 1
        # ``registered_sample`` is a sorted slice of up to 5 family names.
        # prometheus_client family names drop the ``_total`` suffix.
        assert any("plan0107_b1_demo" in name for name in event["registered_sample"])
    finally:
        await handle.aclose()


@pytest.mark.asyncio
async def test_bind_failure_raises_oserror() -> None:
    # Hold an OS-assigned port hostage so the metrics server tries to
    # bind on top of it and fails.
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    busy_port = blocker.getsockname()[1]
    try:
        with pytest.raises(OSError):
            start_metrics_server(
                service_name="pytest-worker",
                port=busy_port,
                addr="127.0.0.1",
                registry=CollectorRegistry(),
            )
    finally:
        blocker.close()
