"""Health and readiness endpoints for the API Gateway."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness probe — returns 200 if process is running."""
    return {"status": "ok"}


@router.get("/v1/healthz")
async def healthz_v1() -> dict:
    """Versioned alias for /healthz.

    Dashboard Regression #5 follow-up (2026-06-05): the strip middleware
    rewrites ``/api/v1/healthz`` → ``/v1/healthz``. Without this route the
    rewritten path 404'd. Kept as an explicit alias so existing health-check
    configs that target ``/healthz`` continue to work.
    """
    return await healthz()  # type: ignore[no-any-return]


@router.get("/v1/health")
async def health_v1() -> dict:
    """External uptime monitor probe — alias for /healthz.

    PLAN-0088 fix P2-D (2026-05-10): external uptime monitors expect
    GET /v1/health returning {"status": "ok"}.  This route is intentionally
    unauthenticated (no OIDCAuthMiddleware bypass needed — the middleware
    checks request.state.user which health checks never set, but health is
    already excluded from auth in OIDCAuthMiddleware._is_public_path).
    """
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
