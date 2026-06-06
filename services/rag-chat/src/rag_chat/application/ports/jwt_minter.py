"""ABC port for minting an internal JWT outside a request context.

The brief pre-generation worker (PLAN-0094 W2) runs in a standalone scheduler
process — no incoming request, no user JWT to propagate. Without an internal
JWT every upstream call (S1 portfolio, S5 alerts, S6 NLP, S7 KG) returns 401
and the BriefingContextGatherer degrades silently to an empty brief, which
the worker still records as a success and writes to lastgood — meaning the
handler later serves an empty brief with ``is_stale=true``. This was the live
failure mode caught by PLAN-0094 live-QA round 2.

The fix (this port + a concrete S9-backed adapter) lets the worker mint a
short-lived RS256 service JWT before each user's generation, matching the
pattern already used by the nlp-pipeline price-impact worker (BP-303).

The port is intentionally minimal — one async method, no caching surface
(adapters cache internally), no error class (concrete impls return ``None``
on transient failure so callers degrade to the pre-fix behaviour rather than
crashing the scheduler).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class IJwtMinter(ABC):
    """Mints an X-Internal-JWT for non-request-context callers (e.g. cron jobs)."""

    @abstractmethod
    async def mint(self) -> str | None:
        """Return a fresh signed internal JWT, or ``None`` if the mint failed.

        Implementations must:
        - Cache the token for its lifetime (rag-chat brief worker may call
          this hundreds of times per run; the underlying S9 endpoint mints
          5-minute tokens — caching is essential).
        - Never raise — return ``None`` and log on transient failure so the
          worker continues with degraded auth (matches the pre-fix behaviour
          for any user whose mint happens to fail).
        - Be safe under concurrent calls — the worker fans out per-user
          generation behind an ``asyncio.Semaphore`` so the same token will
          be requested in parallel.
        """


__all__ = ["IJwtMinter"]
