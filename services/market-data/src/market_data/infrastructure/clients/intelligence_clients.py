"""HTTP clients for pulling intelligence rollup data from upstream services.

PLAN-0089 Wave L-5b (T-WL5B-02).

Four thin async clients — one per upstream service — used by
``SyncIntelligenceRollupUseCase`` to materialise intelligence fields into
``instrument_fundamentals_snapshot`` every night at 04:00 UTC.

SERVICES:
  S6 (content-store)   — news rollup (3 fields, 7-day window)
  S7 (knowledge-graph) — intelligence rollup (1 field, 7-day window)
  S10 (alert)          — active-alert flag (1 boolean)
  S8  (rag-chat)       — AI-brief flag (1 boolean)

BP-235 GUARD: every client sets ``timeout=httpx.Timeout(10)`` explicitly on
the ``httpx.AsyncClient`` constructor.  The httpx default timeout is 5 s —
which fires before any ``asyncio.wait_for`` wrapper — so we must always set
it explicitly.  See memory: [httpx asyncio timeout shadowing (BP-235)].

RETRY POLICY: on 5xx / timeout, each client retries ONCE.  If the second
attempt also fails the method returns ``None`` so the caller can preserve the
last-known snapshot value (keep-last-known semantics).  A single DEBUG log is
emitted per failure to avoid alert noise from transient upstream hiccups.

INTERNAL JWT: every request includes an ``X-Internal-JWT`` header signed with
the RS256 key configured in ``MARKET_DATA_INTERNAL_JWT_PRIVATE_KEY`` (or a
dev HS256 fallback when the key is empty).  This mirrors the pattern used by
``FundamentalsRefreshWorker._sign_internal_jwt``.
"""

from __future__ import annotations

import time

import httpx

from market_data.application.ports.intelligence_clients import (
    S6NewsRollupClientPort,
    S7IntelligenceClientPort,
    S8BriefClientPort,
    S10AlertClientPort,
)

# Response value objects now live in the domain layer (R25).  Re-exported here
# under their historical names so existing importers (tests, other infra) keep
# working unchanged.
from market_data.domain.intelligence_rollup import (
    S6NewsRollup as S6NewsRollup,
)
from market_data.domain.intelligence_rollup import (
    S7IntelligenceRollup as S7IntelligenceRollup,
)
from market_data.domain.intelligence_rollup import (
    S8BriefFlag as S8BriefFlag,
)
from market_data.domain.intelligence_rollup import (
    S10AlertFlag as S10AlertFlag,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


# ── Internal-JWT helper (shared across all 4 clients) ────────────────────────


def _make_internal_jwt(private_key_pem: str) -> str:
    """Sign a short-lived (5-minute) internal JWT for system-to-system calls.

    Mirrors ``FundamentalsRefreshWorker._sign_internal_jwt`` exactly —
    RS256 when ``private_key_pem`` is non-empty; HS256 dev fallback otherwise.
    """
    try:
        import jwt  # PyJWT
    except ImportError:
        import PyJWT as jwt  # type: ignore[no-redef]  # noqa: N813

    now = int(time.time())
    payload = {
        "iss": "worldview-gateway",
        "sub": "system:intelligence-rollup-worker",
        "user_id": "00000000-0000-0000-0000-000000000000",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "role": "system",
        "iat": now,
        "exp": now + 300,
    }

    if private_key_pem:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        private_key = load_pem_private_key(private_key_pem.encode(), password=None)
        return str(jwt.encode(payload, private_key, algorithm="RS256"))  # type: ignore[arg-type]

    # Dev fallback — same shared secret as other workers so market-data
    # skip_verification=True path accepts it transparently.
    return str(
        jwt.encode(
            payload,
            "dev-skip-verification-key-for-kg-structured-enrichment",
            algorithm="HS256",
        )
    )


# ── Base class ────────────────────────────────────────────────────────────────


class _BaseIntelligenceClient:
    """Shared HTTP plumbing for all 4 intelligence clients.

    BP-235: ``timeout`` is always set explicitly (``httpx.Timeout(10)``).
    Retry: one automatic retry on 5xx or ``httpx.TimeoutException``.
    """

    # Per-request timeout in seconds.  10 s is conservative but not too tight
    # — internal endpoints should respond in <500 ms under normal load.
    _TIMEOUT_SECONDS = 10

    def __init__(self, base_url: str, private_key_pem: str = "") -> None:
        # WHY explicit timeout: httpx default is 5 s total, which races with
        # any asyncio.wait_for wrapper at the caller level (BP-235).
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(self._TIMEOUT_SECONDS),
        )
        self._private_key_pem = private_key_pem

    def _auth_headers(self) -> dict[str, str]:
        """Return ``X-Internal-JWT`` header dict, freshly signed."""
        return {"X-Internal-JWT": _make_internal_jwt(self._private_key_pem)}

    async def _get(self, url: str) -> httpx.Response | None:
        """GET ``url`` with one retry on 5xx / timeout; return ``None`` on failure."""
        for attempt in range(2):
            try:
                resp = await self._client.get(url, headers=self._auth_headers())
                if resp.status_code < 500:
                    # 2xx, 3xx, 4xx — don't retry (4xx is caller error, not transient)
                    return resp
                # 5xx — retry once
                if attempt == 0:
                    logger.debug(
                        "intelligence_client_5xx_retry",
                        url=url,
                        status=resp.status_code,
                    )
                    continue
                # Second 5xx — give up
                logger.warning(
                    "intelligence_client_5xx_exhausted",
                    url=url,
                    status=resp.status_code,
                )
                return None
            except httpx.TimeoutException as exc:
                if attempt == 0:
                    logger.debug("intelligence_client_timeout_retry", url=url, error=str(exc))
                    continue
                logger.warning("intelligence_client_timeout_exhausted", url=url, error=str(exc))
                return None
            except Exception as exc:
                logger.warning("intelligence_client_unexpected_error", url=url, error=str(exc))
                return None
        return None  # pragma: no cover — unreachable but satisfies type-checker

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()


# ── S6: content-store news rollup ─────────────────────────────────────────────


class S6NewsRollupClient(_BaseIntelligenceClient, S6NewsRollupClientPort):
    """S6 client: ``GET /internal/v1/instruments/{id}/news-rollup-7d``.

    Returns ``S6NewsRollup`` on success, ``None`` on failure.
    """

    async def get_news_rollup(self, instrument_id: str) -> S6NewsRollup | None:
        """Fetch the 7-day news rollup for one instrument."""
        url = f"/internal/v1/instruments/{instrument_id}/news-rollup-7d"
        resp = await self._get(url)
        if resp is None or resp.status_code != 200:
            return None
        try:
            data = resp.json()
            return S6NewsRollup(
                news_count_7d=int(data.get("news_count_7d", 0)),
                llm_relevance_7d_max=_float_or_none(data.get("llm_relevance_7d_max")),
                display_relevance_7d_weighted=_float_or_none(data.get("display_relevance_7d_weighted")),
            )
        except Exception as exc:
            logger.warning("s6_news_rollup_parse_error", instrument_id=instrument_id, error=str(exc))
            return None


# ── S7: knowledge-graph intelligence rollup ───────────────────────────────────


class S7IntelligenceClient(_BaseIntelligenceClient, S7IntelligenceClientPort):
    """S7 client: ``GET /internal/v1/instruments/{id}/intelligence-rollup-7d``.

    Returns ``S7IntelligenceRollup`` on success, ``None`` on failure.
    """

    async def get_intelligence_rollup(self, instrument_id: str) -> S7IntelligenceRollup | None:
        """Fetch the 7-day intelligence rollup for one instrument."""
        url = f"/internal/v1/instruments/{instrument_id}/intelligence-rollup-7d"
        resp = await self._get(url)
        if resp is None or resp.status_code != 200:
            return None
        try:
            data = resp.json()
            return S7IntelligenceRollup(
                recent_contradiction_count=int(data.get("recent_contradiction_count", 0)),
            )
        except Exception as exc:
            logger.warning("s7_intelligence_rollup_parse_error", instrument_id=instrument_id, error=str(exc))
            return None


# ── S10: alert active-flag ────────────────────────────────────────────────────


class S10AlertClient(_BaseIntelligenceClient, S10AlertClientPort):
    """S10 client: ``GET /internal/v1/instruments/{id}/active-alert-flag``.

    Returns ``S10AlertFlag`` on success, ``None`` on failure.
    """

    async def get_active_alert_flag(self, instrument_id: str) -> S10AlertFlag | None:
        """Fetch whether this instrument has an active flash alert."""
        url = f"/internal/v1/instruments/{instrument_id}/active-alert-flag"
        resp = await self._get(url)
        if resp is None or resp.status_code != 200:
            return None
        try:
            data = resp.json()
            return S10AlertFlag(
                has_active_alert=bool(data.get("has_active_alert", False)),
            )
        except Exception as exc:
            logger.warning("s10_alert_flag_parse_error", instrument_id=instrument_id, error=str(exc))
            return None


# ── S8: rag-chat AI-brief flag ────────────────────────────────────────────────


class S8BriefClient(_BaseIntelligenceClient, S8BriefClientPort):
    """S8 client: ``GET /internal/v1/instruments/{id}/ai-brief-flag``.

    Returns ``S8BriefFlag`` on success, ``None`` on failure.
    """

    async def get_ai_brief_flag(self, instrument_id: str) -> S8BriefFlag | None:
        """Fetch whether this instrument has a current AI intelligence brief."""
        url = f"/internal/v1/instruments/{instrument_id}/ai-brief-flag"
        resp = await self._get(url)
        if resp is None or resp.status_code != 200:
            return None
        try:
            data = resp.json()
            return S8BriefFlag(
                has_ai_brief=bool(data.get("has_ai_brief", False)),
            )
        except Exception as exc:
            logger.warning("s8_brief_flag_parse_error", instrument_id=instrument_id, error=str(exc))
            return None


# ── Utilities ──────────────────────────────────────────────────────────────────


def _float_or_none(v: object) -> float | None:
    """Coerce a JSON value to float, returning None for None / unparseable."""
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
