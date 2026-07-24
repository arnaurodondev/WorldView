"""Shared offset-pagination termination rule for external-API adapter clients.

Extracted after the "short page == last page" heuristic was independently
disproven TWICE for the Polymarket Gamma ``/markets`` and ``/events`` clients
(``e1745828b`` introduced ``len(items) < limit`` as the stop condition;
``4b094c53e`` fixed it ~11 minutes later after live smoke-testing showed the
Gamma API silently caps pages at ~100 rows regardless of the requested
``limit`` — the very first page was already "short," so the old heuristic
terminated the walk after ~100 rows instead of covering the full universe).

Before this module existed, both Gamma clients carried the *fix* but
duplicated the logic inline with no shared invariant, so the identical bug
class reappeared unnoticed in ``polymarket_data_trades/client.py``
(``has_more = len(trades) >= limit``) — see
``docs/audits/2026-07-23-bottleneck-content-ingestion-pagination.md`` for the
full investigation. Every offset-paginated client in this adapter family
(and any future provider client) MUST derive its termination signal from
this helper instead of re-deriving it from ``len(items)`` vs. ``limit``.
"""

from __future__ import annotations


def next_offset_cursor(*, offset: int, returned_count: int) -> str | None:
    """Canonical offset-pagination termination rule for all providers in this
    client family.

    Terminates ONLY on an empty page (``returned_count == 0``). NEVER
    terminates on ``returned_count < requested_limit`` -- providers are free
    to silently cap page size below any requested limit (verified live for
    Polymarket Gamma 2026-07-16: limit=500 -> 100 rows), and doing so is not
    a signal of end-of-data. Advances the offset by the ACTUAL returned row
    count, never by the requested limit, so no rows are skipped when the
    provider under-fills a page.

    Args:
        offset: The offset that was requested for the page just fetched.
        returned_count: The number of items the provider actually returned
            for that page (NOT the requested ``limit``).

    Returns:
        ``str(offset + returned_count)`` — the next offset to request — when
        ``returned_count > 0``; ``None`` when the page was empty (no more
        data, terminate the pagination loop). A defensive negative
        ``returned_count`` (should never happen for a real provider response)
        is treated as empty (``None``) rather than propagating a negative
        offset.
    """
    if returned_count <= 0:
        return None
    return str(offset + returned_count)
