"""Gateway middleware — auth, rate limiting, CORS."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any, cast

import jwt
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

# ── Auth ──────────────────────────────────────────────────


def decode_jwt(token: str, secret: str, algorithm: str = "HS256") -> dict:
    """Decode and validate a JWT. Returns the payload dict.

    Raises ``jwt.InvalidTokenError`` on any failure.
    """
    return cast("dict[str, Any]", jwt.decode(token, secret, algorithms=[algorithm]))


def get_current_user(request: Request) -> dict | None:
    """Extract user from request state (set by auth middleware).

    Returns ``None`` if no user is authenticated (public route).
    """
    return getattr(request.state, "user", None)


class AuthMiddleware(BaseHTTPMiddleware):
    """Extract and validate JWT from Authorization header.

    Sets ``request.state.user`` to the decoded payload, or ``None`` for
    unauthenticated requests. Does NOT enforce auth — individual routes
    use ``Depends(require_auth)`` for protected endpoints.
    """

    def __init__(self, app: FastAPI, secret: str, algorithm: str = "HS256") -> None:
        super().__init__(app)
        self.secret = secret
        self.algorithm = algorithm

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request.state.user = None
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            with suppress(jwt.InvalidTokenError):
                request.state.user = decode_jwt(token, self.secret, self.algorithm)
        return cast("Response", await call_next(request))


# ── Rate Limiting ─────────────────────────────────────────


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter backed by Valkey.

    If Valkey is unavailable, requests are allowed (fail-open).
    """

    def __init__(
        self,
        app: FastAPI,
        valkey_client: Any,  # redis.asyncio.Redis | None
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.valkey = valkey_client
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self.valkey is None:
            return cast("Response", await call_next(request))

        # Key by IP (production should use user ID if authenticated)
        client_ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{client_ip}"

        try:
            current = await self.valkey.incr(key)
            if current == 1:
                await self.valkey.expire(key, self.window_seconds)
            if current > self.max_requests:
                return Response(
                    content='{"detail":"Rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                )
        except Exception:
            return cast("Response", await call_next(request))

        return cast("Response", await call_next(request))


# ── CORS setup ────────────────────────────────────────────


def add_cors(app: FastAPI, origins: str) -> None:
    """Add CORS middleware from a comma-separated origins string."""
    origin_list = [o.strip() for o in origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
