"""Ticker / UUID → instrument_id resolution shim (PRD-0089 F2).

After F2 the platform standardises on a single canonical ``instrument_id``
per tradable security. URLs are ticker-first (``/instruments/AAPL``) but
the gateway must continue accepting raw UUIDs from internal callers and
from any cached deep-link. ``resolve_security_id`` is the choke point
that turns either input form into a canonical ``instrument_id`` UUID,
performing:

  1. UUID short-circuit. If the identifier is already a valid UUID it
     is returned as-is — no network call, no cache write. This keeps
     the existing UUID-only callsites at zero overhead.
  2. Ticker lookup against S3 market-data
     (``/api/v1/instruments/lookup?symbol=<TICKER>&extra_info=true``).
     Tickers are upper-cased before lookup; the S3-side unique index is
     ``(upper(symbol), exchange) WHERE status = 'active'`` (F2 plan §2.3).
  3. Alias fallback against S7 knowledge-graph
     (``/api/v1/entities/lookup?ticker=<TICKER>``). The future
     ``ticker_aliases`` table lives in kg_db (F2 plan §2.2); until that
     migration runs, the KG-side ``entities/lookup`` already resolves
     historical-name → current-entity for the cases we have seeded data
     for, and returns the canonical ``entity_id`` (which equals the
     ``instrument_id`` post-F2 per M-017).
  4. Unknown identifier → raises ``InstrumentNotFoundError`` so the
     route handler can turn it into a 404 with a frontend-friendly UX
     hook.

# WHY cachetools.TTLCache (in-process, not Valkey):
# The lookup is hot — every page load on a ticker URL fans out to the
# bundle composer which already issues 4-6 downstream calls. Adding a
# Valkey round-trip per request would double the gateway latency budget.
# An in-process 1-hour LRU is appropriate because:
#   - Tickers very rarely change instrument_id (corporate actions are
#     surfaced via ``entity.dirtied.v1`` Kafka events; we invalidate
#     the relevant entry there — see TODO at module bottom).
#   - The cache is bounded (maxsize=10000) so a malicious caller cannot
#     exhaust memory by probing random tickers.
#   - Gateway pods are typically replicated 2-3x; cache divergence
#     across pods is acceptable because the TTL bounds drift to 1h.

# WHY return a dataclass (not bare UUID):
# Ticker aliases need a 301-redirect signal so the frontend canonicalises
# the URL (``/instruments/FB`` → ``/instruments/META``). Returning
# ``ResolvedSecurity(instrument_id, redirect_to_ticker=None|"META")`` lets
# the caller decide how to surface that — REST routes raise an HTTP 301,
# WebSocket routes ignore it, internal use cases pass it through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from cachetools import TTLCache  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from api_gateway.clients import ServiceClients

# Module-level logger — structlog only (CLAUDE.md R10).
logger = structlog.get_logger()  # type: ignore[no-any-return]


# Accept any RFC 4122 UUID form (v1, v4, v7). The platform mints UUIDv7
# but historical seed data and external references may use other versions.
# Case-insensitive, hyphen-delimited 8-4-4-4-12 hex.
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class InstrumentNotFoundError(Exception):
    """Raised when neither the UUID, the S3 ticker lookup, nor the KG
    alias fallback finds a matching instrument.

    Route handlers should catch this and return HTTP 404 with a body the
    ``InstrumentNotFound.tsx`` component can render (attempted ticker +
    suggestion list).
    """

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        super().__init__(f"No instrument found for identifier: {identifier!r}")


@dataclass(frozen=True)
class ResolvedSecurity:
    """Result of ``resolve_security_id``.

    ``instrument_id`` is always populated on a successful resolution.
    ``redirect_to_ticker`` is non-None only when the caller passed an
    alias (e.g. ``"FB"``) and the canonical ticker is different (``"META"``).
    Route handlers should respond with HTTP 301 to ``/instruments/<ticker>``
    in that case so the URL bar is canonicalised; non-routing callers
    (e.g. WebSocket subscription) can ignore the field.
    """

    instrument_id: UUID
    redirect_to_ticker: str | None = None


# In-process LRU/TTL cache keyed on the *lowercased* raw identifier so
# ``"aapl"`` and ``"AAPL"`` share an entry. maxsize=10000 comfortably
# covers the active universe (~6k US tickers) plus tail (ADRs, ETFs,
# crypto, alias entries). ttl=3600s gives us a 1-hour staleness ceiling
# without a manual flush.
#
# # WHY module-level (not per-request): the cache must survive across
# # FastAPI route invocations. The gateway runs as a long-lived asyncio
# # process so a single TTLCache instance shared by all coroutines is
# # safe — TTLCache itself is not thread-safe but our single-threaded
# # event loop means we never have concurrent mutations.
_resolution_cache: TTLCache[str, ResolvedSecurity] = TTLCache(maxsize=10000, ttl=3600)


def _is_uuid(identifier: str) -> bool:
    """Pre-validate without raising — ``UUID(identifier)`` is slower than
    a regex and throws on invalid input. We just want a fast boolean."""
    return bool(_UUID_RE.match(identifier))


async def resolve_security_id(
    identifier: str,
    *,
    clients: ServiceClients,
    headers: dict[str, str] | None = None,
) -> ResolvedSecurity:
    """Resolve a UUID-or-ticker identifier to a canonical instrument_id.

    Args:
        identifier: Either a UUID string (returned as-is) or a ticker
            symbol like ``"AAPL"``, ``"BRK.B"``, ``"META"``. Case-insensitive.
        clients: ServiceClients dataclass containing market_data and
            knowledge_graph httpx clients.
        headers: Optional ``X-Internal-JWT`` header dict to forward to
            downstream services. The caller must produce a fresh JWT per
            request (the gateway's ``_auth_headers()`` helper does this).

    Returns:
        ``ResolvedSecurity(instrument_id=<UUID>, redirect_to_ticker=<str|None>)``.

    Raises:
        InstrumentNotFoundError: when the identifier matches no instrument
            via either the S3 lookup or the KG alias fallback.

    Caching:
        Successful resolutions are cached for 1h keyed on the lowercased
        identifier. ``InstrumentNotFoundError`` is NOT cached — a misspelled
        ticker today may become a real ticker tomorrow (IPOs), and the
        per-request cost is minimal. ``entity.dirtied.v1`` Kafka events
        should call ``resolve_security_id.cache.pop(...)`` to invalidate
        on corporate actions; see TODO below.
    """
    # Empty / whitespace identifier is always a 404 — no point hitting
    # the cache or downstream services.
    if not identifier or not identifier.strip():
        raise InstrumentNotFoundError(identifier)

    cache_key = identifier.lower().strip()

    # Cache hit short-circuit. The cache stores the full ResolvedSecurity
    # so a cached alias still emits its 301 redirect signal.
    cached: ResolvedSecurity | None = _resolution_cache.get(cache_key)
    if cached is not None:
        return cached

    # ── Case 1: UUID input ────────────────────────────────────────────
    # # WHY no network call: a UUID is already the canonical instrument_id
    # # post-F2 (M-017 guarantees ce.entity_id == instruments.id for
    # # tradable kinds). The gateway has no need to verify existence
    # # because the downstream call (e.g. /fundamentals/{uuid}) will
    # # return 404 if the UUID is truly unknown — no point double-spending
    # # the latency budget.
    if _is_uuid(identifier):
        resolved = ResolvedSecurity(instrument_id=UUID(identifier))
        _resolution_cache[cache_key] = resolved
        return resolved

    # ── Case 2: ticker lookup via S3 market-data ──────────────────────
    # Normalise to uppercase before lookup — the unique index on
    # instruments is upper(symbol).
    ticker = identifier.strip().upper()
    try:
        resp = await clients.market_data.get(
            "/api/v1/instruments/lookup",
            params={"symbol": ticker, "extra_info": "true"},
            headers=headers or {},
        )
        if resp.status_code == 200:
            data = resp.json()
            iid_str = data.get("id")
            if isinstance(iid_str, str) and _is_uuid(iid_str):
                resolved = ResolvedSecurity(instrument_id=UUID(iid_str))
                _resolution_cache[cache_key] = resolved
                return resolved
    except Exception as exc:
        # # WHY swallow: S3 may be transiently down. We fall through to
        # # the KG alias path; if that also fails the InstrumentNotFoundError
        # # at the bottom surfaces a 404, which is the right UX response
        # # (the frontend renders InstrumentNotFound.tsx). Log at INFO so
        # # transient blips are visible without alarming on-call.
        logger.info(
            "resolve_security_id_s3_lookup_failed",
            ticker=ticker,
            exc=str(exc),
        )

    # ── Case 3: alias fallback via S7 knowledge-graph ─────────────────
    # KG's /entities/lookup?ticker=X resolves historical aliases (e.g.
    # FB → META) when the kg_db.ticker_aliases table is populated
    # (F2 plan §2.2 introduces the table; this code path is the
    # consumer). The KG returns the canonical entity_id which equals
    # the instrument_id post-F2 per M-017.
    try:
        kg_resp = await clients.knowledge_graph.get(
            "/api/v1/entities/lookup",
            params={"ticker": ticker},
            headers=headers or {},
        )
        if kg_resp.status_code == 200:
            kg_data = kg_resp.json()
            eid_str = kg_data.get("entity_id")
            canonical_ticker = kg_data.get("ticker")
            if isinstance(eid_str, str) and _is_uuid(eid_str):
                # # WHY redirect_to_ticker only when canonical_ticker
                # # differs from the input: if the caller typed "AAPL"
                # # and KG returns "AAPL" we don't need a 301; if they
                # # typed "FB" and KG returns "META" we DO need a 301
                # # so the URL bar canonicalises.
                redirect = (
                    canonical_ticker
                    if isinstance(canonical_ticker, str) and canonical_ticker and canonical_ticker.upper() != ticker
                    else None
                )
                resolved = ResolvedSecurity(
                    instrument_id=UUID(eid_str),
                    redirect_to_ticker=redirect,
                )
                _resolution_cache[cache_key] = resolved
                return resolved
    except Exception as exc:
        # Same rationale as the S3 swallow above.
        logger.info(
            "resolve_security_id_kg_lookup_failed",
            ticker=ticker,
            exc=str(exc),
        )

    # ── Unknown ──────────────────────────────────────────────────────
    raise InstrumentNotFoundError(identifier)


# Expose the cache on the function object so callers (and tests) can
# inspect / invalidate without reaching into module internals:
#   resolve_security_id.cache.pop(entity_id_str.lower(), None)
# is the documented invalidation entry point for the future
# entity.dirtied.v1 Kafka consumer.
resolve_security_id.cache = _resolution_cache  # type: ignore[attr-defined]


# ── TODO: entity.dirtied.v1 consumer hook ────────────────────────────
# The gateway is currently HTTP-only — no Kafka consumer infrastructure
# is wired up. When a corporate action invalidates a ticker→instrument_id
# mapping (e.g. a ticker change or a merger), the upstream service emits
# ``entity.dirtied.v1`` with the affected entity_id. A consumer in S9
# would call:
#
#   resolve_security_id.cache.pop(entity_id_lower, None)
#   resolve_security_id.cache.pop(old_ticker.lower(), None)
#
# Until that consumer is built (tracked as PLAN-0089 F2 step 6), stale
# entries self-evict via the 1h TTL. This is acceptable for the dev /
# pre-prod environment where corporate actions are seeded manually
# (no_backfill: true). Re-evaluate before any production deployment.


__all__ = [
    "InstrumentNotFoundError",
    "ResolvedSecurity",
    "resolve_security_id",
]
