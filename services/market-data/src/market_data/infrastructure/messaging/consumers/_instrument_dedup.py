"""Shared "reuse an existing instrument regardless of exchange" dedup guard.

WHY THIS MODULE EXISTS (2026-07 NFLX-duplicate-instrument incident):

``ohlcv_consumer``, ``quotes_consumer``, and ``fundamentals_consumer`` each
run a "resolve-or-create instrument" step keyed on ``(symbol, exchange)``.
The ``exchange`` value comes from the Kafka message payload, which in turn
was forwarded (possibly as ``""``) from market-ingestion's
``TriggerIngestionUseCase`` / ``IngestionTask.exchange`` — a field that is
``NULL``-able and, on at least one call path
(``FundamentalsRefreshWorker._refresh_one`` enqueues tasks from a bare symbol
list with no exchange info at all), is genuinely unknown at enqueue time.

Root cause of the NFLX incident: ``FundamentalsRefreshWorker`` triggered a
fundamentals refresh for ``NFLX`` on 2026-07-15 before any OHLCV/quotes
ingestion had ever created an instrument row for it. With no ``exchange``
known, ``canonicalize.py`` forwarded ``""``, and
``fundamentals_consumer``'s resolve-or-create step — finding nothing via the
exact-match ``find_by_symbol_exchange(symbol, "")`` lookup — created a NEW
instrument row keyed at ``exchange=''``. The next day (2026-07-16), a
regular OHLCV/quotes ingestion cycle resolved NFLX's real exchange (``'US'``)
via the symbol_tier/polling_policy pipeline and, finding no exact match at
``exchange='US'`` either (the ``''`` row doesn't match), created a SECOND,
canonical instrument row. Both rows then coexisted indefinitely: the
resolver used by rag-chat's fundamentals tool
(``find_by_symbol_icase``, no ``ORDER BY`` before migration 046) picked
whichever row was physically first — the stale placeholder — serving stale
fundamentals data.

This is a LIVE, ONGOING risk for ANY symbol that reaches one of these three
consumers with an empty/unknown ``exchange`` BEFORE a row already exists for
it with a real exchange (not NFLX-specific, not a one-time historical
issue) — the resolve-or-create pattern in all three consumers has this gap.

THE FIX: before creating a brand-new instrument, check whether ANY row
already exists for the symbol (ignoring exchange) via
``find_by_symbol_icase``. If one does, reuse it instead of creating a
duplicate — and if we now know a real exchange while the existing row still
carries the empty placeholder, upgrade it in place. This makes the outcome
independent of which consumer (fundamentals vs. ohlcv/quotes) happens to run
first for a brand-new symbol.

A DB-level partial unique index (migration 047,
``uq_instruments_symbol_placeholder_exchange``) additionally caps the
placeholder-exchange duplication at one row per symbol as defense-in-depth
against races and any future code path that bypasses this helper.

RESIDUAL CONCURRENT-RACE WINDOW (known, accepted limitation):
This guard is a check-then-insert with no cross-consumer coordination, so it
closes the DAY-APART ordering that caused the observed NFLX incident but NOT
a true concurrent first-touch race: if the empty-exchange fundamentals
consumer and a real-exchange ohlcv/quotes consumer process the SAME
brand-new symbol at the SAME instant, both ``find_by_symbol_icase`` calls can
return None and both INSERT — recreating a ``'' + 'US'`` pair. Migration
047's partial index only rejects a SECOND ``''`` row, not one ``''`` plus one
real-exchange row. A hard unique constraint on ``symbol`` alone is NOT an
option (legitimate dual-listings share a symbol across real exchanges), so
this window is inherent to the resolve-or-create pattern. It is mitigated,
not eliminated: (a) it requires sub-transaction-window simultaneity for a
first-ever symbol (rare), and (b) the migration 046 merge is idempotent and
re-runnable, so any duplicate that does slip through is repaired by simply
re-running it in prod — keep it re-runnable, never one-shot.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.uow import UnitOfWork
    from market_data.domain.entities import Instrument


async def find_symbol_match_ignoring_exchange(
    uow: UnitOfWork,
    symbol: str,
    exchange: str,
) -> Instrument | None:
    """Return an existing instrument for ``symbol`` even if its exchange differs.

    Returns ``None`` only when no instrument exists for this symbol at all —
    the caller is then free to create one. When a match IS found and the
    caller supplied a real (non-empty) ``exchange`` while the existing row
    still carries the placeholder ``''``, the row is upgraded in place so the
    placeholder does not linger once the real exchange becomes known.
    """
    existing = await uow.instruments.find_by_symbol_icase(symbol)
    if existing is None:
        return None
    if exchange and not existing.exchange:
        await uow.instruments.update_metadata(existing.id, {"exchange": exchange})
        existing = replace(existing, exchange=exchange)
    return existing
