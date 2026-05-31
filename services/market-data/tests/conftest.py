"""Shared test fixtures for market-data service."""

import os
import socket

import pytest

# Required fields with no defaults (security hardening C-001) — must be set
# before Settings() is instantiated in create_app() or any test fixture.
os.environ.setdefault("MARKET_DATA_STORAGE_ACCESS_KEY", "minioadmin-test")
os.environ.setdefault("MARKET_DATA_STORAGE_SECRET_KEY", "minioadmin-test")
# PLAN-0093 T-A-1-03: the new observability.assert_app_env_or_die() boot guard
# aborts startup when ``internal_jwt_skip_verification`` is True and APP_ENV is
# unset.  Tests routinely enable skip_verification, so pin APP_ENV=test here
# before any settings/create_app() call so test runs do not trip the guard.
os.environ.setdefault("APP_ENV", "test")
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


# PLAN-0103 W16 (BP-635): the screener introspects information_schema once
# per process to discover which snap-field columns exist. Captured-session
# tests don't simulate that query, so the cache would default to "no
# columns present" and strip the projection (breaking pre-existing
# WHERE/ORDER BY assertions). Pre-fill the cache to the full ORM set here
# so existing tests continue to assert against the complete projection.
# Tests that specifically exercise the introspection path (see
# test_screener_snap_field_introspection.py) reset the cache themselves.
@pytest.fixture(autouse=True)
def _prefill_snap_field_cache() -> None:
    """Pre-populate the snap-field cache to the full ORM set for unit tests."""
    try:
        from market_data.infrastructure.db.repositories import fundamental_metrics_query as _fmq

        _fmq._AVAILABLE_SNAP_FIELDS = _fmq._SNAP_FIELDS
    except ImportError:
        # Module not yet importable in environments without the deps loaded.
        pass
    yield
    try:
        from market_data.infrastructure.db.repositories import fundamental_metrics_query as _fmq

        _fmq._AVAILABLE_SNAP_FIELDS = None
    except ImportError:
        pass


@pytest.fixture
async def e2e_live_client():
    """HTTP client pointing at the live market-data service on localhost:8003.

    Skips if the live service is not reachable.
    """
    if not _is_live_service_up():
        pytest.skip("Live market-data service not reachable at localhost:8003")
    async with AsyncClient(base_url=_LIVE_BASE_URL, timeout=10.0) as ac:
        yield ac
