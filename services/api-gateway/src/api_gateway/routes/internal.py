"""Internal routes — JWKS endpoint for backend service JWT verification."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/internal")


@router.get(
    "/jwks",
    summary="Internal JWKS — public key for RS256 internal JWT verification",
    tags=["internal"],
)
async def get_jwks(request: Request) -> JSONResponse:
    """Return the JWKS for S9's internal RS256 signing key.

    Backend services fetch this endpoint at startup to verify X-Internal-JWT tokens.
    Response is cached for 1 hour (``Cache-Control: public, max-age=3600``).
    """
    jwks: dict[str, Any] | None = getattr(request.app.state, "internal_jwks", None)
    if jwks is None:
        return JSONResponse(
            content={"detail": "JWKS not available — service not fully initialized"},
            status_code=503,
        )
    return JSONResponse(content=jwks, headers={"Cache-Control": "public, max-age=3600"})
