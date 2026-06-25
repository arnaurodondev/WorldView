"""Shared helper for building :class:`EntitySummary` from a row dict.

PLAN-0093 Wave B-4 T-B-4-02 / F-607 follow-up: the same conversion existed
in two places — ``api/cypher.py`` and ``api/routes.py`` — with identical
field mapping but slightly different value-type annotations.  Living in two
places meant a future field addition (e.g. ``market_cap``) had to be
mirrored or the two routes would drift.

The function is module-private (single underscore prefix) because
``EntitySummary`` itself is a KG-service-local Pydantic schema and we don't
want to leak it through ``libs/contracts`` (the rest of the platform sees
``EntitySummary`` only via the S9 BFF JSON response).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from knowledge_graph.api.schemas import EntitySummary


def entity_summary_from_row(row: dict[str, Any]) -> EntitySummary:
    """Build an :class:`EntitySummary` from a canonical_entity row dict.

    Tolerant to rows that omit ``description`` / ``sector`` (e.g. AGE
    Cypher result rows which only carry graph topology fields) — uses
    ``.get()`` with ``None`` fallback so callers do not need to pre-fill
    missing keys.

    Args:
    ----
        row: a row dict from ``canonical_entities`` (any of the SELECT
            variants in ``repositories/canonical_entity.py``).

    Returns:
    -------
        A populated ``EntitySummary``.

    """
    # Import inside the function so this module has no import-time dependency
    # on the schemas module (avoids a circular-import risk between cypher.py /
    # routes.py and this helper at import time).
    from knowledge_graph.api.schemas import EntitySummary

    # PLAN-0099: industry / market_cap come either from dedicated SELECT
    # aliases (canonical_entity.get / get_batch) or, as a fallback, from the
    # metadata JSONB when the row variant only carries `metadata`.
    metadata = row.get("metadata")
    meta: dict[str, Any] = metadata if isinstance(metadata, dict) else {}
    industry = row.get("industry") or meta.get("industry")
    market_cap_raw = row.get("market_cap") if row.get("market_cap") is not None else meta.get("market_cap")
    try:
        market_cap = float(market_cap_raw) if market_cap_raw is not None else None
    except (TypeError, ValueError):
        # Defensive: metadata JSONB is free-form; a non-numeric market_cap
        # must never 500 the graph endpoint.
        market_cap = None

    return EntitySummary(
        entity_id=row["entity_id"],
        canonical_name=str(row["canonical_name"]),
        entity_type=str(row["entity_type"]),
        isin=str(row["isin"]) if row.get("isin") else None,
        ticker=str(row["ticker"]) if row.get("ticker") else None,
        exchange=str(row["exchange"]) if row.get("exchange") else None,
        description=str(row["description"]) if row.get("description") else None,
        sector=str(row["sector"]) if row.get("sector") else None,
        industry=str(industry) if industry else None,
        market_cap=market_cap,
    )
