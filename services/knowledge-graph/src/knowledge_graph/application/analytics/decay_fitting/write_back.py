"""Gated, provenance-stamped write-back of fitted alphas — PLAN-0123 Wave 3, T-A-3-02.

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL (same
convention as every other intelligence_db repository in this service).

Shadow mode (PRD-0120 §10 rollout step 3, FR-6 default): logs the fit and
writes nothing. Write mode sets the five Wave-1 ``relation_type_registry``
columns (``decay_alpha``, ``half_life_days``, ``alpha_fit_n``,
``alpha_fit_method``, ``alpha_fit_at``) — but ONLY for a fit whose
``method != "pooled_prior"``. A ``pooled_prior`` fit is left NULL by design:
writing the prior value explicitly would be behaviorally identical to
leaving the column NULL (the Wave-1 COALESCE already falls back to the
class prior), so leaving it NULL is simpler and strictly safer — there is
nothing to revert later for a type that was never actually fit.

Idempotent: re-running write-back with the same DecayFit input produces
byte-identical column values, since every value is a deterministic function
of the fit itself (no randomness, no incrementing counters).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

from sqlalchemy import text

from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from knowledge_graph.domain.decay_fit import DecayFit

WriteBackMode = Literal["shadow", "write"]

_UPDATE_SQL = """
UPDATE relation_type_registry
SET decay_alpha      = :decay_alpha,
    half_life_days   = :half_life_days,
    alpha_fit_n      = :alpha_fit_n,
    alpha_fit_method = :alpha_fit_method,
    alpha_fit_at     = :alpha_fit_at
WHERE canonical_type = :canonical_type
"""


async def write_back_fit(fit: DecayFit, session: AsyncSession, *, mode: WriteBackMode) -> bool:
    """Write *fit* to ``relation_type_registry`` if gated conditions allow.

    Args:
    ----
        fit: A pooled :class:`DecayFit` (``alpha_final``/``shrinkage_weight``
            already populated by ``pooling.pool_type_fit``).
        session: A session bound to the **write** path (this is the one
            legitimately-write step in the whole feature — everything
            upstream, extraction and fitting, is read-only).
        mode: ``"shadow"`` performs zero writes; ``"write"`` performs the
            UPDATE (still gated on ``fit.method != "pooled_prior"``).

    Returns:
    -------
        ``True`` if a write was performed, ``False`` otherwise (shadow mode,
        or a ``pooled_prior``-method fit that is intentionally left NULL).

    Raises:
    ------
        ValueError: if *fit* has no ``alpha_final`` (i.e. it was never
            pooled — callers must run ``pool_type_fit`` first).

    """
    if fit.alpha_final is None:
        raise ValueError(
            f"fit for {fit.canonical_type!r} has no alpha_final — run pool_type_fit() before write_back_fit()",
        )

    if mode == "shadow":
        return False

    if fit.method == "pooled_prior":
        # Intentionally left NULL — the Wave-1 COALESCE already falls back
        # to the class prior; writing it explicitly adds a revert-surface
        # for no behavioral benefit.
        return False

    # half_life_days must reflect the POOLED/shrunk alpha_final, not
    # fit.half_life_days (a property derived from the raw pre-shrinkage
    # lambda_hat) — otherwise the stored half-life would silently disagree
    # with the stored decay_alpha.
    await session.execute(
        text(_UPDATE_SQL),
        {
            "decay_alpha": fit.alpha_final,
            "half_life_days": math.log(2) / fit.alpha_final,
            "alpha_fit_n": fit.n,
            "alpha_fit_method": fit.method,
            "alpha_fit_at": utc_now(),
            "canonical_type": fit.canonical_type,
        },
    )
    return True
