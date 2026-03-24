"""Health and readiness endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness probe — returns 200 if process is running."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    """Readiness probe — returns 200 only when all dependencies are reachable."""
    checks: dict[str, str] = {}
    ok = True

    # Database check
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        ok = False

    # Valkey check
    try:
        await request.app.state.valkey.ping()
        checks["valkey"] = "ok"
    except Exception as exc:
        checks["valkey"] = f"error: {exc}"
        ok = False

    status = 200 if ok else 503
    return Response(
        content=json.dumps({"status": "ok" if ok else "degraded", **checks}),
        status_code=status,
        media_type="application/json",
    )
