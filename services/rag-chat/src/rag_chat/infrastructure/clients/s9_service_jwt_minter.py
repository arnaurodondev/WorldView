"""S9-backed concrete implementation of :class:`IJwtMinter`.

Mirrors the production-safe service-token flow that the nlp-pipeline price-impact
worker uses (BP-303 / PLAN-0057 Wave A-1):

  1. When ``service_account_token`` is configured → ``POST /internal/v1/service-token``
     with the shared secret.  This works in production.
  2. Otherwise → ``POST /v1/auth/dev-login`` with a fixed dev email.  Works in dev,
     hard-blocked in production by S9 (returns 403) — kept as a convenience for
     local-dev workflows where ``service_account_token`` may not be wired up yet.

The minted token is cached for :data:`_TOKEN_REFRESH_S` (4 minutes — well under
S9's 5-minute TTL).  An ``asyncio.Lock`` serialises concurrent mints so a 50-user
batch fans out into a single mint round-trip rather than 50.

On any error (network, 4xx, 5xx after retry budget exhausted) the method returns
``None``; the caller then degrades to the pre-fix unauthenticated path rather
than crashing.  This matches the contract documented in :class:`IJwtMinter`.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from rag_chat.application.ports.jwt_minter import IJwtMinter

if TYPE_CHECKING:
    import httpx

_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Refresh well under the 5-minute S9 TTL so we never serve an about-to-expire
# token. 4 minutes gives a 1-minute safety margin against clock skew.
_TOKEN_REFRESH_S: float = 4 * 60

# Exponential backoff for transient mint failures. First attempt fires
# immediately; subsequent attempts sleep first. Matches the nlp-pipeline
# pattern (5 attempts; ~65 s total wall-clock) so a brief boot-storm against
# api-gateway recovers within the compose ``service_healthy`` grace window.
_TOKEN_MINT_RETRY_DELAYS: tuple[float, ...] = (0.0, 0.5, 2.0, 5.0, 15.0)


class S9ServiceJwtMinter(IJwtMinter):
    """Mint internal JWTs via S9's ``/internal/v1/service-token`` endpoint."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_gateway_url: str,
        service_account_token: str | None,
        service_name: str = "rag-chat-brief-scheduler",
    ) -> None:
        self._client = client
        # Strip trailing slash so URL joins are unambiguous regardless of how
        # the operator configured ``RAG_CHAT_API_GATEWAY_URL``.
        self._api_gateway_url = (api_gateway_url or "").rstrip("/")
        # Empty string is normalised to ``None`` so callers can pass either
        # SecretStr.get_secret_value() (which returns "" when unset) or a real
        # secret without an extra ``or None`` at every call site.
        self._service_account_token: str | None = service_account_token or None
        self._service_name = service_name
        self._token: str | None = None
        self._token_minted_at: float = 0.0
        self._token_lock = asyncio.Lock()

    async def mint(self) -> str | None:
        """Return a fresh signed internal JWT, or ``None`` if the mint failed.

        Caches the token for ~4 minutes (well under S9's 5-minute TTL) under
        an ``asyncio.Lock`` so concurrent callers share a single mint.
        """
        if not self._api_gateway_url:
            return None

        async with self._token_lock:
            now = time.monotonic()
            if self._token and (now - self._token_minted_at) < _TOKEN_REFRESH_S:
                return self._token

            # Pick the auth path based on configuration. Both endpoints
            # respond with the same ``{"access_token": "...", ...}`` shape.
            if self._service_account_token:
                url = f"{self._api_gateway_url}/internal/v1/service-token"
                payload = {
                    "service_name": self._service_name,
                    "secret": self._service_account_token,
                }
                mint_path = "service-token"
            else:
                # Dev-only fallback. S9 hard-blocks this in production
                # (app_env=='production' returns 403), so a missing
                # service_account_token in prod surfaces as a clean 403 +
                # ``None`` return rather than a silent token reuse.
                url = f"{self._api_gateway_url}/v1/auth/dev-login"
                payload = {"email": "brief-scheduler@worldview.local"}
                mint_path = "dev-login"

            for attempt, delay_before in enumerate(_TOKEN_MINT_RETRY_DELAYS):
                if delay_before > 0:
                    await asyncio.sleep(delay_before)
                try:
                    resp = await self._client.post(url, json=payload, timeout=5.0)
                except Exception as exc:
                    is_last = attempt == len(_TOKEN_MINT_RETRY_DELAYS) - 1
                    _log.warning(  # type: ignore[no-any-return]
                        "brief_scheduler_token_mint_error",
                        mint_path=mint_path,
                        attempt=attempt + 1,
                        max_attempts=len(_TOKEN_MINT_RETRY_DELAYS),
                        error=str(exc),
                        will_retry=not is_last,
                    )
                    if is_last:
                        return None
                    continue

                if resp.status_code == 200:
                    token = resp.json().get("access_token")
                    if not isinstance(token, str) or not token:
                        _log.warning(  # type: ignore[no-any-return]
                            "brief_scheduler_token_mint_invalid_payload",
                            mint_path=mint_path,
                        )
                        return None
                    self._token = token
                    self._token_minted_at = now
                    _log.info(  # type: ignore[no-any-return]
                        "brief_scheduler_token_minted",
                        mint_path=mint_path,
                        attempt=attempt + 1,
                    )
                    return token

                # 4xx is non-transient (auth misconfig — won't fix itself on
                # retry). 5xx is worth retrying once or twice.
                is_last = attempt == len(_TOKEN_MINT_RETRY_DELAYS) - 1
                if 400 <= resp.status_code < 500:
                    _log.warning(  # type: ignore[no-any-return]
                        "brief_scheduler_token_mint_rejected",
                        mint_path=mint_path,
                        status=resp.status_code,
                        body_preview=resp.text[:200],
                    )
                    return None
                # 5xx — log + retry
                _log.warning(  # type: ignore[no-any-return]
                    "brief_scheduler_token_mint_transient",
                    mint_path=mint_path,
                    attempt=attempt + 1,
                    status=resp.status_code,
                    will_retry=not is_last,
                )
                if is_last:
                    return None
            return None


__all__ = ["S9ServiceJwtMinter"]
