"""Reusable OpenAPI contract test base class."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient


class OpenAPIContractTestBase:
    """Base helpers for OpenAPI endpoint contract checks.

    Subclasses should provide:
    - app_factory() -> FastAPI
    - endpoint_cases: list of request/expected status dictionaries
    """

    endpoint_cases: list[dict[str, Any]] = []

    @classmethod
    def app_factory(cls) -> FastAPI:
        raise NotImplementedError("Subclasses must implement app_factory")

    def build_client(self) -> TestClient:
        return TestClient(self.app_factory())

    def test_openapi_schema_is_present(self) -> None:
        with self.build_client() as client:
            response = client.get("/openapi.json")
            assert response.status_code == 200
            payload = response.json()
            assert "openapi" in payload
            assert "paths" in payload

    def test_endpoint_cases(self) -> None:
        with self.build_client() as client:
            for case in self.endpoint_cases:
                method = case["method"].lower()
                path = case["path"]
                body = case.get("json")
                params = case.get("params")
                expected_status = case["status"]

                request_fn = getattr(client, method)
                response = request_fn(path, json=body, params=params)
                assert response.status_code == expected_status
