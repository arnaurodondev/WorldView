"""Unit tests for app robustness — exception handlers + dispatcher supervision (Wave 3)."""

from __future__ import annotations

import pytest
from content_ingestion.domain.exceptions import AdapterError, ConfigurationError, QuotaExhaustedError, StorageError
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def _make_app_with_exception_route(exc_type: type[Exception], exc_msg: str = "test error") -> FastAPI:
    """Create a minimal FastAPI app with exception handlers and a route that raises."""
    from content_ingestion.app import _register_exception_handlers

    app = FastAPI()
    _register_exception_handlers(app)

    @app.get("/raise")
    async def raise_exc() -> None:
        raise exc_type(exc_msg)

    return app


class TestExceptionHandlers:
    def test_adapter_error_returns_502(self) -> None:
        app = _make_app_with_exception_route(AdapterError, "upstream down")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/raise")
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"] == "bad_gateway"
        # Must not leak internal error details
        assert "upstream down" not in body.get("detail", "")

    def test_quota_exhausted_returns_429(self) -> None:
        app = _make_app_with_exception_route(QuotaExhaustedError, "rate limited")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/raise")
        assert resp.status_code == 429
        assert resp.json()["error"] == "too_many_requests"

    def test_configuration_error_returns_500(self) -> None:
        app = _make_app_with_exception_route(ConfigurationError, "bad config")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/raise")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"] == "internal_error"
        assert "bad config" not in body.get("detail", "")

    def test_storage_error_returns_503(self) -> None:
        app = _make_app_with_exception_route(StorageError, "minio dead")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/raise")
        assert resp.status_code == 503
        assert resp.json()["error"] == "service_unavailable"

    def test_unhandled_exception_returns_500_generic(self) -> None:
        app = _make_app_with_exception_route(RuntimeError, "secret internal details")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/raise")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"] == "internal_error"
        # Must not leak internal details
        assert "secret internal details" not in str(body)
