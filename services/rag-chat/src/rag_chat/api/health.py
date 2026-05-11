"""Health, readiness, metrics, and provider-status endpoints for S8.

Readiness checks (GET /readyz):
  1. rag_db   — SQLAlchemy SELECT 1 via write_factory
  2. ollama   — GET /api/tags (Ollama REST)
  3. valkey   — PING

Provider status (GET /api/v1/providers/status):
  Returns the current availability of LLM providers from the negative cache
  stored in app.state.provider_cache (populated by the LLM client in later waves).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import prometheus_client
from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import text

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from rag_chat.infrastructure.config.settings import RagChatSettings

router = APIRouter(tags=["health"])
_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — always 200 if the process is running."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    """Readiness probe — 503 if any critical dependency is unavailable."""
    checks: dict[str, str] = {}
    ok = True

    # 1. rag_db — SELECT 1
    try:
        async with request.app.state.write_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["rag_db"] = "ok"
    except Exception:
        _log.warning("readyz_rag_db_failed", exc_info=True)  # type: ignore[no-any-return]
        checks["rag_db"] = "error"
        ok = False

    # 2. Ollama — GET /api/tags
    try:
        settings: RagChatSettings = request.app.state.settings
        async with httpx.AsyncClient(timeout=3.0) as hc:
            r = await hc.get(f"{settings.ollama_base_url}/api/tags")
            r.raise_for_status()
        checks["ollama"] = "ok"
    except Exception:
        _log.warning("readyz_ollama_failed", exc_info=True)  # type: ignore[no-any-return]
        checks["ollama"] = "error"
        ok = False

    # 3. Valkey — PING
    try:
        await request.app.state.valkey.ping()
        checks["valkey"] = "ok"
    except Exception:
        _log.warning("readyz_valkey_failed", exc_info=True)  # type: ignore[no-any-return]
        checks["valkey"] = "error"
        ok = False

    status_code = 200 if ok else 503
    return Response(
        content=json.dumps({"status": "ok" if ok else "degraded", **checks}),
        status_code=status_code,
        media_type="application/json",
    )


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    data = prometheus_client.generate_latest()
    return Response(content=data, media_type=prometheus_client.CONTENT_TYPE_LATEST)


@router.get("/api/v1/providers/status")
async def providers_status(request: Request) -> dict[str, Any]:
    """Return LLM provider availability from the in-memory negative cache.

    The ``provider_cache`` dict is populated by the LLM client (implemented in
    a later wave).  Keys: ``"<name>_failed"`` (bool), ``"<name>_last_failure"``
    (ISO-8601 string | None).
    """
    settings: RagChatSettings = request.app.state.settings
    cache: dict[str, Any] = getattr(request.app.state, "provider_cache", {})

    providers = [
        {
            "name": "deepinfra",
            "available": (settings.deepinfra_api_key is not None) and not cache.get("deepinfra_failed", False),
            "last_failure_at": cache.get("deepinfra_last_failure"),
            "model": settings.completion_model,
        },
        {
            "name": "openrouter",
            "available": (settings.openrouter_api_key is not None) and not cache.get("openrouter_failed", False),
            "last_failure_at": cache.get("openrouter_last_failure"),
            "model": settings.openrouter_completion_model,
        },
        {
            "name": "ollama",
            "available": not cache.get("ollama_failed", False),
            "last_failure_at": cache.get("ollama_last_failure"),
            "model": settings.ollama_completion_model,
        },
    ]
    return {"providers": providers}
