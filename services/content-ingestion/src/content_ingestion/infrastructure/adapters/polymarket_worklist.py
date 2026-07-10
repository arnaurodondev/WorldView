"""Shared parser for the unified Polymarket ``markets`` work-list (PLAN-0056 B4).

WHY (Wave B4): Wave B1/B3 drove the CLOB ``/prices-history`` and Data ``/trades``
adapters from *flat* source-config lists — ``token_ids`` (CLOB, per outcome) and
``condition_ids`` (trades, per market).  Neither carried the mapping from a child
CLOB ``token_id`` to its PARENT market ``conditionId``, so the outbox payloads set
``market_id = token_id`` as a surrogate and the resulting S3
``prediction_market_prices`` / ``prediction_market_trades`` rows did NOT JOIN to
``prediction_markets`` (keyed on ``conditionId``).

Wave B4 replaces those flat lists with a single ``markets`` work-list that pairs
each parent market ``condition_id`` with its child CLOB ``token_ids``::

    {"markets": [{"condition_id": "0x..", "token_ids": ["t1", "t2"]}, ...]}

The condition_id → [token_ids] mapping is derivable from the Gamma ``/markets``
response (``clobTokenIds`` / ``outcomes``) that content-ingestion already ingests.

This helper parses that shape (tolerating camelCase aliases) so both the CLOB and
trades adapters can stamp the parent ``condition_id`` onto every fetch-result.
Legacy flat lists are handled by each adapter's own fallback (parent unknown →
``condition_id = None`` → payload falls back to the ``token_id`` surrogate).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MarketWorkItem:
    """One parent market and the CLOB outcome tokens that belong to it.

    Attributes:
        condition_id: The parent Polymarket ``conditionId`` (S3 ``market_id``), or
            ``None`` when the config predates the B4 work-list (legacy fallback).
        token_ids: The child CLOB outcome token ids for this market (possibly empty
            for the trades feed, which keys only on ``condition_id``).
    """

    condition_id: str | None
    token_ids: list[str]


def parse_markets(config: dict[str, Any]) -> list[MarketWorkItem]:
    """Parse ``config['markets']`` into a list of :class:`MarketWorkItem`.

    Returns an empty list when the ``markets`` key is absent or malformed — callers
    then apply their own legacy (flat-list) fallback.  Individual malformed entries
    are skipped rather than failing the whole parse.

    Args:
        config: The source ``config`` dict (from the ``sources`` row).

    Returns:
        One :class:`MarketWorkItem` per well-formed ``markets`` entry.
    """
    raw = config.get("markets")
    if not isinstance(raw, list):
        return []

    items: list[MarketWorkItem] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        # Accept snake_case (our canonical) and camelCase (raw Gamma) aliases.
        cid = entry.get("condition_id") or entry.get("conditionId")
        condition_id = str(cid) if cid else None
        toks_raw = entry.get("token_ids") or entry.get("clobTokenIds") or []
        token_ids = [str(t) for t in toks_raw if t] if isinstance(toks_raw, list) else []
        items.append(MarketWorkItem(condition_id=condition_id, token_ids=token_ids))
    return items
