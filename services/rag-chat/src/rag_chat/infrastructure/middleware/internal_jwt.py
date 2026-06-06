"""InternalJWTMiddleware — rag-chat (S8) thin subclass.

REF-001 (W2-05): logic lives in ``observability.internal_jwt``.  S8 specifics:

* The skip_verification log is WARNING (not CRITICAL) — eval stack uses this.
* ``skip_verification=True`` ALWAYS takes the unverified-decode path
  (eval stack uses ``RAG_CHAT_INTERNAL_JWT_SKIP_VERIFICATION=true``).
* External 401 body is opaque ``"Unauthorized"`` (F-S001) to avoid leaking
  validation detail; structlog log lines preserve internal observability.
* On successful validation OR successful unverified decode, a ContextVar
  (``set_current_jwt``) is set so upstream service clients can include
  ``X-Internal-JWT`` in outgoing calls without threading the token through
  every method signature.
* ``F-S002`` — even in skip_verification mode, malformed JWTs with no sub
  AND no tenant_id are rejected so multi-tenant isolation does not fail
  silently downstream.
* On JTI fail-open, the ``rag_jti_check_bypass_total`` Prometheus counter
  is incremented (F-S004) so ops can alert on Valkey availability.
* ``S-010`` — JWKS-fetch failure logs hide HTTP response bodies (which may
  contain sensitive data) and log only the status code.

PRD-0025 §6.5 (InternalJWTMiddleware spec).
"""

from __future__ import annotations

import asyncio  # noqa: F401 — re-exported for test parity (tests patch internal_jwt.asyncio.sleep)
from typing import TYPE_CHECKING, Any

import httpx
import jwt

from observability.internal_jwt import (  # type: ignore[import-untyped]
    _DEFAULT_KID,  # noqa: F401 — re-exported for test parity
    _REFRESH_COOLDOWN_SECONDS,  # noqa: F401
    _last_refresh_ts,  # noqa: F401
    _refresh_lock,  # noqa: F401
)
from observability.internal_jwt import (  # type: ignore[import-untyped]
    InternalJWTMiddleware as _Shared,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from fastapi import Request, Response

logger = get_logger(__name__)


class InternalJWTMiddleware(_Shared):
    """S8 rag-chat InternalJWTMiddleware — opaque external errors, ContextVar token."""

    def __init__(
        self,
        app: Any,
        jwks_url: str,
        *,
        skip_verification: bool = False,
    ) -> None:
        super().__init__(
            app,
            jwks_url,
            skip_verification=skip_verification,
            # rag-chat uses WARNING (not CRITICAL) for skip-mode boot log so
            # the eval stack does not appear to be on fire.
            skip_verification_log_level="warning",
            # PLAN-0052: skip_verification ALWAYS takes the unverified path,
            # not only when JWKS load fails (matches eval-stack contract).
            skip_verification_takes_precedence=True,
        )

    # ── Opaque 401 bodies (F-S001) ───────────────────────────────────────────
    def _invalid_token_response(self) -> Response:
        """F-S001: external body is opaque "Unauthorized" — debug log carries detail."""
        from fastapi import Response

        return Response(
            content='{"detail":"Unauthorized"}',
            status_code=401,
            media_type="application/json",
        )

    def _expired_token_response(self) -> Response:
        """F-S001: same opaque body for expired tokens."""
        from fastapi import Response

        return Response(
            content='{"detail":"Unauthorized"}',
            status_code=401,
            media_type="application/json",
        )

    # ── Logging hooks ────────────────────────────────────────────────────────
    def _on_expired_token(self) -> None:
        """F-S001: log expired tokens at INFO so structlog preserves observability."""
        logger.info("internal_jwt_expired")

    def _log_startup_failure(self, attempt: int, exc: Exception) -> None:
        """S-010: hide HTTP response body (may contain sensitive data)."""
        err_detail = (
            f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
        )
        logger.warning(
            "internal_jwt_startup_fetch_failed",
            attempt=attempt + 1,
            error=err_detail,
        )

    def _log_background_refresh_failure(self, exc: Exception) -> None:
        """S-010: hide HTTP response body in background-refresh failures."""
        ref_err = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
        logger.warning("internal_jwt_public_key_refresh_failed", error=ref_err)

    def _on_jti_check_bypass(self, jti: str) -> None:
        """F-S004: increment the bypass counter so ops can alert on Valkey loss."""
        from rag_chat.application.metrics.prometheus import rag_jti_check_bypass_total

        rag_jti_check_bypass_total.inc()
        logger.warning("jti_check_valkey_unavailable", jti=jti)

    # ── skip_verification path (rejects malformed claims, sets ContextVar) ───
    async def _unverified_decode(self, request: Request, token: str) -> Response | None:
        """F-S002: enforce minimum claims even in skip_verification mode.

        A structurally valid but claim-free JWT must not pass through — empty
        sub+tenant_id means no identity context, which causes silent multi-
        tenant isolation failures downstream.
        """
        from rag_chat.infrastructure.clients.auth_context import set_current_jwt

        logger.debug(
            "internal_jwt_unverified_decode",
            detail="Decoding JWT WITHOUT signature verification (skip_verification=True).",
        )
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            if not payload.get("sub") and not payload.get("tenant_id"):
                logger.warning("internal_jwt_missing_claims_skip_verification")
                return self._invalid_token_response_with_message(
                    "Malformed JWT: missing required claims",
                )
            request.state.tenant_id = payload.get("tenant_id", "")
            request.state.user_id = payload.get("sub", "")
            request.state.role = payload.get("role", "")
        except jwt.DecodeError as exc:
            logger.warning("internal_jwt_malformed_skip_verification", error=str(exc))
            return self._invalid_token_response_with_message("Malformed JWT")

        set_current_jwt(token)
        return None

    def _invalid_token_response_with_message(self, msg: str) -> Response:
        """Helper for the rag-chat skip-mode malformed-claim rejection paths.

        These paths historically returned a richer external message than the
        verified-path 401 (which is opaque ``"Unauthorized"``).  We preserve
        that distinction to keep existing tests passing.
        """
        from fastapi import Response

        return Response(
            content=f'{{"detail":"{msg}"}}',
            status_code=401,
            media_type="application/json",
        )

    # ── Successful-validation hook: set the ContextVar ───────────────────────
    async def _post_validate(self, request: Request, token: str, payload: dict[str, Any]) -> None:
        """Set the ContextVar so upstream clients can forward ``X-Internal-JWT``."""
        from rag_chat.infrastructure.clients.auth_context import set_current_jwt

        set_current_jwt(token)


__all__ = ["InternalJWTMiddleware"]
