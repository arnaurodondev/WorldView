"""Tests for observability.error_capture."""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestUnhandledExceptionHandler:
    def test_returns_500_status(self) -> None:
        import asyncio

        from starlette.requests import Request

        from observability.error_capture import unhandled_exception_handler

        async def _call() -> None:
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/boom",
                "query_string": b"",
                "headers": [],
            }
            request = Request(scope)
            response = await unhandled_exception_handler(request, ValueError("oops"))
            assert response.status_code == 500

        asyncio.run(_call())

    def test_returns_json_body(self) -> None:
        import asyncio
        import json

        from starlette.requests import Request

        from observability.error_capture import unhandled_exception_handler

        async def _call() -> None:
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/thing",
                "query_string": b"",
                "headers": [],
            }
            request = Request(scope)
            response = await unhandled_exception_handler(request, RuntimeError("fail"))
            body = json.loads(response.body)
            assert body == {"detail": "internal server error"}

        asyncio.run(_call())

    def test_register_error_handlers_does_not_raise(self) -> None:
        from fastapi import FastAPI

        from observability.error_capture import register_error_handlers

        app = FastAPI()
        register_error_handlers(app)  # must not raise

    def test_register_error_handlers_intercepts_exception(self) -> None:
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from observability.error_capture import register_error_handlers

        app = FastAPI()
        register_error_handlers(app)

        @app.get("/boom")
        async def _boom() -> None:
            raise ValueError("unexpected")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/boom")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "internal server error"}


@pytest.mark.unit
class TestUnhandledExceptionHandlerSentry:
    """Verify Sentry capture integration in unhandled_exception_handler (T-C-02)."""

    def _make_request(self) -> object:
        from starlette.requests import Request

        scope = {"type": "http", "method": "GET", "path": "/boom", "query_string": b"", "headers": []}
        return Request(scope)  # type: ignore[return-value]

    def test_calls_sentry_capture_when_initialised(self) -> None:
        import asyncio
        from unittest.mock import MagicMock, patch

        from observability.error_capture import unhandled_exception_handler

        exc = RuntimeError("boom")
        mock_client = MagicMock()
        mock_client.is_active.return_value = True

        with (
            patch("sentry_sdk.get_client", return_value=mock_client) as _gc,
            patch("sentry_sdk.capture_exception") as mock_cap,
        ):
            asyncio.run(unhandled_exception_handler(self._make_request(), exc))  # type: ignore[arg-type]

        mock_cap.assert_called_once_with(exc)

    def test_skips_sentry_when_not_initialised(self) -> None:
        import asyncio
        from unittest.mock import MagicMock, patch

        from observability.error_capture import unhandled_exception_handler

        exc = ValueError("no sentry")
        mock_client = MagicMock()
        mock_client.is_active.return_value = False

        with (
            patch("sentry_sdk.get_client", return_value=mock_client),
            patch("sentry_sdk.capture_exception") as mock_cap,
        ):
            asyncio.run(unhandled_exception_handler(self._make_request(), exc))  # type: ignore[arg-type]

        mock_cap.assert_not_called()

    def test_swallows_sentry_failure_returns_500(self) -> None:
        import asyncio
        from unittest.mock import MagicMock, patch

        from observability.error_capture import unhandled_exception_handler

        exc = ValueError("real error")
        mock_client = MagicMock()
        mock_client.is_active.return_value = True

        with (
            patch("sentry_sdk.get_client", return_value=mock_client),
            patch("sentry_sdk.capture_exception", side_effect=RuntimeError("sentry down")),
        ):
            response = asyncio.run(unhandled_exception_handler(self._make_request(), exc))  # type: ignore[arg-type]

        assert response.status_code == 500
        import json

        assert json.loads(response.body) == {"detail": "internal server error"}
