"""Alpha Vantage OVERVIEW fundamentals fallback adapter.

WHY THIS EXISTS (PLAN-0053 T-C-3-02):
  The fundamentals backfill (``scripts/backfill_fundamentals.py``) derives
  10 frontend-displayed fields from EODHD JSONB sections.  Two of those —
  ``eps_ttm`` and ``beta`` — are commonly NULL in EODHD's response for
  smaller-cap or recently-listed instruments, leading to "—" placeholders
  in FundamentalsTab.tsx.  Alpha Vantage's free OVERVIEW endpoint returns
  ``EarningsShare`` and ``Beta`` reliably for ~90% of US equities.  This
  adapter is a *narrow* fallback: only those two fields, only when EODHD
  is NULL.

DESIGN DECISIONS:
  - **Narrow scope**: not a full ``ProviderAdapter`` — see
    ``infrastructure/external/__init__.py`` for the rationale.
  - **httpx async**: matches the rest of the codebase; allows seamless
    use from ``asyncio.run`` in the backfill script.
  - **Explicit timeout**: BP-235 requires ``httpx.Timeout(...)`` whenever the
    adapter is wrapped by ``asyncio.wait_for`` (or might be in the future).
    Using ``Timeout(10.0)`` instead of relying on httpx's 5s default ensures
    AV's frequently-slow free tier doesn't false-fail under load.
  - **Free-tier rate limit**: AV's free tier permits 25 calls/day with
    ~5 req/min throttle.  This adapter does NOT implement client-side
    rate limiting — the backfill runs nightly across ~100 tickers and
    operators are expected to upgrade or skip if the tier is exceeded.
    A 429 response surfaces as ``AlphaVantageRateLimited`` so callers
    can degrade gracefully.

USAGE:
    adapter = AlphaVantageFundamentalsAdapter(api_key="...")
    overview = await adapter.fetch_overview("AAPL")
    if overview and overview.eps_ttm is not None:
        ...
    await adapter.close()  # release the underlying httpx client
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


# ── Public errors ──────────────────────────────────────────────────────────────


class AlphaVantageError(Exception):
    """Base for AV adapter failures (caller may catch broadly)."""


class AlphaVantageRateLimited(AlphaVantageError):  # noqa: N818
    """AV returned 429 or signalled the free-tier quota.

    Free tier returns a 200 with a ``{"Note": "Thank you ..."}`` body when the
    daily limit is hit — we map that to this exception so callers can treat
    "out of credits" the same as a 429.
    """


# ── DTO ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AlphaVantageOverview:
    """Subset of OVERVIEW response fields used by the backfill fallback.

    WHY ``frozen=True``: prevents downstream code from mutating returned data;
    ensures the adapter remains a pure fetch boundary.

    WHY ``slots=True``: smaller memory footprint when the backfill processes
    100+ tickers in sequence.
    """

    symbol: str
    eps_ttm: float | None
    beta: float | None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _safe_float(raw: object) -> float | None:
    """Coerce an AV string field to float, returning None on failure.

    AV returns numeric fields as strings ("1.95"), and uses "None" or empty
    string for missing values — both must coerce to None rather than raising.
    """
    if raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        cleaned = raw.strip()
        if not cleaned or cleaned.lower() in {"none", "null", "n/a", "-"}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


# ── Adapter ────────────────────────────────────────────────────────────────────


class AlphaVantageFundamentalsAdapter:
    """Narrow OVERVIEW fetcher for backfill fallback (eps_ttm + beta only)."""

    _BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Construct the adapter.

        Args:
            api_key: Alpha Vantage API key (use ``ALPHA_VANTAGE_API_KEY`` env).
            timeout_seconds: total timeout for AV calls (BP-235: explicit, not
                relying on httpx's 5s default).
            client: optional pre-built ``httpx.AsyncClient`` — primarily for
                tests that need to inject a mock transport.  When ``None``,
                a new client is created with the explicit timeout (BP-235).
        """
        if not api_key:
            # WHY ValueError (not None-default): the script's caller checks
            # for empty key BEFORE constructing the adapter, so a blank key
            # reaching this constructor is a bug worth crashing on.
            raise ValueError("AlphaVantageFundamentalsAdapter requires a non-empty api_key")
        self._api_key = api_key
        # BP-235: always set httpx.Timeout explicitly when the call site might
        # be wrapped by asyncio.wait_for(); the default 5s otherwise fires
        # before the outer wait_for has a chance to apply.
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    async def fetch_overview(self, symbol: str) -> AlphaVantageOverview | None:
        """Return ``AlphaVantageOverview`` or ``None`` when AV has no data.

        Returns ``None`` for unknown symbols (AV responds with an empty JSON
        object ``{}``) so the caller can keep its NULL value.

        Raises:
            AlphaVantageRateLimited: when AV returns 429 or the free-tier note.
            AlphaVantageError: any other unexpected payload shape.
            httpx.HTTPError: network-level failure (caller is expected to
                catch and degrade — see backfill script's broad-except).
        """
        params = {
            "function": "OVERVIEW",
            "symbol": symbol,
            "apikey": self._api_key,
        }

        response = await self._client.get(self._BASE_URL, params=params)

        # WHY explicit 429 check (and not just raise_for_status): AV often
        # returns 200 with a Note body even when rate-limited; we want a
        # consistent exception type either way.
        if response.status_code == 429:
            raise AlphaVantageRateLimited(f"AV 429 for {symbol}")

        # Network-level errors (5xx, malformed responses) raise via the next
        # call.  We deliberately don't catch — the backfill script wraps the
        # whole adapter call in a broad except.
        response.raise_for_status()

        # AV returns ``application/json`` even on errors; parse before deciding.
        try:
            payload = response.json()
        except ValueError as exc:
            raise AlphaVantageError(f"AV returned non-JSON for {symbol}: {exc}") from exc

        # Free-tier "out of credits" path — surfaces as a 200 with a Note key.
        if isinstance(payload, dict) and "Note" in payload and "thank" in str(payload["Note"]).lower():
            raise AlphaVantageRateLimited(f"AV note: {payload['Note']!r}")

        # Premium-key "Information" path (different message but same effect).
        if isinstance(payload, dict) and "Information" in payload:
            info = str(payload["Information"]).lower()
            if "rate limit" in info or "premium" in info:
                raise AlphaVantageRateLimited(f"AV info: {payload['Information']!r}")

        # Empty object → unknown symbol, caller keeps original NULL.
        if not payload or not isinstance(payload, dict):
            logger.debug("alpha_vantage.empty_response", symbol=symbol)
            return None

        eps_raw = payload.get("EPS")  # AV's preferred field name (was "EarningsShare" historically)
        if eps_raw is None:
            eps_raw = payload.get("EarningsShare")  # legacy/backup field

        return AlphaVantageOverview(
            symbol=symbol,
            eps_ttm=_safe_float(eps_raw),
            beta=_safe_float(payload.get("Beta")),
        )

    async def close(self) -> None:
        """Close the underlying httpx client when this adapter owns it.

        WHY only when owned: tests pass a shared client (via ``client=``) and
        manage its lifecycle externally; closing here would break those tests.
        """
        if self._owns_client:
            await self._client.aclose()
