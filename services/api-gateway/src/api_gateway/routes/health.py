"""Health and readiness endpoints for the API Gateway."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness probe — returns 200 if process is running."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> Response:
    """Readiness probe — checks Valkey availability."""
    checks: dict[str, str] = {}
    ok = True

    valkey = request.app.state.valkey
    if valkey is not None:
        try:
            await valkey.ping()
            checks["valkey"] = "ok"
        except Exception as exc:
            checks["valkey"] = f"error: {exc}"
            ok = False
    else:
        # Valkey unavailable — fail-open (rate limiting degraded, not fatal)
        checks["valkey"] = "degraded (fail-open)"

    status = 200 if ok else 503
    return Response(
        content=json.dumps({"status": "ok" if ok else "degraded", **checks}),
        status_code=status,
        media_type="application/json",
    )
