"""S7EntityResolver — concrete EntityNameResolverPort using S7 + Valkey cache.

WHY THIS ADAPTER EXISTS (PLAN-0048 Wave B-1):
``AlertFanoutUseCase`` needs ``(entity_name, ticker)`` for every signal alert
so the frontend can render rich rows like ``AAPL: Bullish guidance`` instead
of bare ``SIGNAL`` text (BP-263 follow-up). Doing an HTTP call inside the fan-out
hot path would be too slow under burst load — we cache aggressively in Valkey.

DESIGN NOTES:
- Calls S7 ``POST /api/v1/entities/batch`` with a single-element list. WHY batch
  endpoint (not a per-id GET): S7 already exposes batch as the canonical lookup
  shape returning ``{entity_id, ticker, canonical_name}``. There is no
  ``GET /entities/{id}`` route on S7 today, so reusing batch keeps us within
  the existing public API surface (no S7 contract changes).
- 15-minute TTL: canonical entity names/tickers rarely change. Even on a rename,
  a stale cache entry is harmless — the next 15-min expiry refreshes it.
- Negative caching: on a successful S7 response with no entity, we still cache
  ``(None, None)`` so we don't hammer S7 for unresolvable entity_ids (e.g.
  events that reference deleted entities). On a network/HTTP error we DON'T
  cache — the upstream may recover.
- ``X-Internal-JWT`` header is required (PRD-0025); without it S7 returns 401.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from httpx import AsyncClient, HTTPStatusError, RequestError

from alert.application.ports.entity_resolver import EntityNameResolverPort

if TYPE_CHECKING:
    from uuid import UUID

    from alert.config import Settings
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)

# WHY this prefix shape: namespace under ``s10:`` (alert service) and version it
# (``v1``) so we can change the cached value shape without colliding with
# old entries (just bump to ``v2``). ``alert:entity_resolver:`` is the spec
# key per PLAN-0048 — we keep it as the suffix for grep-ability.
_KEY_PREFIX = "s10:v1:alert:entity_resolver"


class S7EntityResolver(EntityNameResolverPort):
    """HTTP-backed entity resolver with cache-aside Valkey lookup.

    Args:
    ----
        settings: Alert service settings (provides S7 base URL + JWT + TTL).
        valkey: Async Valkey client for cache-aside.
        client: Optional pre-built httpx ``AsyncClient`` (mainly for tests).

    """

    def __init__(
        self,
        settings: Settings,
        valkey: ValkeyClient,
        client: AsyncClient | None = None,
    ) -> None:
        self._base_url = settings.s7_knowledge_graph_base_url.rstrip("/")
        self._jwt = settings.s7_internal_jwt
        self._ttl = settings.entity_resolver_cache_ttl_seconds
        self._valkey = valkey
        # WHY explicit timeout: BP-235 — never rely on httpx default (5s) when
        # this code may be wrapped in asyncio.wait_for; pin a Timeout instance
        # so the inner timeout fires predictably.
        self._client = client or AsyncClient(timeout=5.0)

    async def close(self) -> None:
        """Close the underlying HTTP client. Safe to call once at shutdown."""
        await self._client.aclose()

    # ── Public port ───────────────────────────────────────────────────────────

    async def resolve(self, entity_id: UUID) -> tuple[str | None, str | None]:
        """Resolve ``entity_id`` → ``(canonical_name, ticker)``.

        Cache-aside flow:
            1. GET cache. Hit → return parsed value.
            2. Miss → POST S7 ``/entities/batch``.
            3. Cache the result (positive AND negative) on success.
            4. Network/HTTP error → return ``(None, None)`` (no caching).
        """
        key = f"{_KEY_PREFIX}:{entity_id}"

        # ── 1. Cache lookup ──────────────────────────────────────────────
        cached = await self._cache_get(key)
        if cached is not None:
            return cached

        # ── 2. Cache miss → S7 lookup ────────────────────────────────────
        # WHY POST batch (not a hypothetical GET): S7 only exposes batch +
        # ticker-lookup endpoints today. Single-element batch is the cheapest
        # path and uses an established contract.
        url = f"{self._base_url}/api/v1/entities/batch"
        try:
            resp = await self._client.post(
                url,
                json={"entity_ids": [str(entity_id)]},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        except (RequestError, HTTPStatusError) as exc:
            # Best-effort: never raise. Logging level is WARNING because a
            # missing enrichment is a soft failure — the alert still fans out.
            logger.warning(
                "s7_entity_resolver_lookup_failed",
                entity_id=str(entity_id),
                url=url,
                error=str(exc),
            )
            return (None, None)

        # ── 3. Parse + cache ─────────────────────────────────────────────
        # S7 returns {"entities": [{"entity_id": ..., "ticker": ..., "canonical_name": ...}]}.
        # Missing entity_ids are silently omitted (per S7 contract) — len==0 is
        # legitimate negative-cache case.
        entities = data.get("entities", []) if isinstance(data, dict) else []
        if entities:
            row = entities[0]
            name = row.get("canonical_name")
            ticker = row.get("ticker")
            result: tuple[str | None, str | None] = (
                str(name) if name else None,
                str(ticker) if ticker else None,
            )
        else:
            # Negative cache: avoid retry storm for unknown entity_ids.
            result = (None, None)

        await self._cache_set(key, result)
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """Build request headers — ``X-Internal-JWT`` only (PRD-0025)."""
        headers: dict[str, str] = {}
        if self._jwt:
            # WHY conditional: tests / dev environments may not set the JWT;
            # let the request go through and let S7 return 401 (logged above).
            headers["X-Internal-JWT"] = self._jwt
        return headers

    async def _cache_get(self, key: str) -> tuple[str | None, str | None] | None:
        """Fetch + decode a cached ``(name, ticker)`` JSON tuple, or ``None``."""
        try:
            raw = await self._valkey.get(key)
        except Exception:
            # Cache outage MUST NOT block resolution — fall through to S7.
            logger.warning("s7_entity_resolver_cache_get_failed", key=key, exc_info=True)
            return None

        if raw is None:
            return None

        # ValkeyClient always returns str (decode_responses=True); cast for safety.
        text = str(raw)
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            # Corrupt cache entry — treat as miss.
            return None

        if not isinstance(obj, list) or len(obj) != 2:
            return None
        name = obj[0] if isinstance(obj[0], str) else None
        ticker = obj[1] if isinstance(obj[1], str) else None
        return (name, ticker)

    async def _cache_set(self, key: str, value: tuple[str | None, str | None]) -> None:
        """Store ``(name, ticker)`` JSON-serialised with TTL."""
        try:
            await self._valkey.set(key, json.dumps(list(value)), ex=self._ttl)
        except Exception:
            # Non-fatal — caching is opportunistic.
            logger.warning("s7_entity_resolver_cache_set_failed", key=key, exc_info=True)
