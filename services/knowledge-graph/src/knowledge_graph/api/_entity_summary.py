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

    return EntitySummary(
        entity_id=row["entity_id"],
        canonical_name=str(row["canonical_name"]),
        entity_type=str(row["entity_type"]),
        isin=str(row["isin"]) if row.get("isin") else None,
        ticker=str(row["ticker"]) if row.get("ticker") else None,
        exchange=str(row["exchange"]) if row.get("exchange") else None,
        description=str(row["description"]) if row.get("description") else None,
        sector=str(row["sector"]) if row.get("sector") else None,
    )
