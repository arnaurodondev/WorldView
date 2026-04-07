"""Shared test fixtures for market-data service."""

import os
import socket

import pytest

# Required fields with no defaults (security hardening C-001) — must be set
# before Settings() is instantiated in create_app() or any test fixture.
os.environ.setdefault("MARKET_DATA_STORAGE_ACCESS_KEY", "minioadmin-test")
os.environ.setdefault("MARKET_DATA_STORAGE_SECRET_KEY", "minioadmin-test")
from httpx import ASGITransport, AsyncClient
from market_data.app import create_app

_LIVE_BASE_URL = os.getenv("MARKET_DATA_E2E_BASE_URL", "http://localhost:8003")


def _is_live_service_up() -> bool:
    """Check if the live market-data service is reachable."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(("localhost", 8003))
        sock.close()
        return True
    except Exception:
        return False


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def e2e_live_client():
    """HTTP client pointing at the live market-data service on localhost:8003.

    Skips if the live service is not reachable.
    """
    if not _is_live_service_up():
        pytest.skip("Live market-data service not reachable at localhost:8003")
    async with AsyncClient(base_url=_LIVE_BASE_URL, timeout=10.0) as ac:
        yield ac
