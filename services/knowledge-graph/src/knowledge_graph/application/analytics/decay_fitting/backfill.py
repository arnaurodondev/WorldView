"""Explicit relations backfill after write-back — PLAN-0123 Wave 3, T-A-3-03.

Closes the review's elevated OQ-7 finding (docs/audits/2026-07-03-prd-0120-
review.md, "Backfill gap"): ``relations.decay_alpha`` is denormalized
**only on upsert** (``relation.py:79``, ``ON CONFLICT ... EXCLUDED.
decay_alpha``) — a relation that receives no new evidence after a type's
alpha is fitted would otherwise never re-resolve its alpha, contradicting
the PRD's assumption of a "lazy confidence-stale refresh".

This module runs immediately after a successful write-back for a type: it
sets ``decay_alpha`` directly and flips ``confidence_stale = true`` (an
existing column) so the relation's ``confidence`` is recomputed with the
new alpha on its next natural refresh cycle — without needing new evidence.

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_BACKFILL_SQL = """
UPDATE relations
SET decay_alpha = :decay_alpha,
    confidence_stale = true
WHERE canonical_type = :canonical_type
  AND decay_alpha IS DISTINCT FROM :decay_alpha
"""


async def backfill_relations_for_type(canonical_type: str, decay_alpha: float, session: AsyncSession) -> int:
    """Backfill every existing ``relations`` row of *canonical_type* to *decay_alpha*.

    Scoped to a single type (never a blind full-table scan) — call this only
    immediately after a successful write-back for that type
    (``write_back.write_back_fit`` returning ``True``).

    Args:
    ----
        canonical_type: The relation type whose alpha was just fitted.
        decay_alpha: The newly written per-type alpha (``fit.alpha_final``).
        session: A session bound to the **write** path.

    Returns:
    -------
        The number of ``relations`` rows updated (``rowcount``).

    """
    result = await session.execute(
        text(_BACKFILL_SQL),
        {"decay_alpha": decay_alpha, "canonical_type": canonical_type},
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined,no-any-return]
