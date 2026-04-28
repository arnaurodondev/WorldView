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
