"""Offline decay-fitter entrypoint — PLAN-0123 Wave 2, T-A-2-05 (shadow-only).

Runs both lifetime-definition estimators for every target ``TEMPORAL_CLAIM``
type (PRD-0120 §4 FR-3) and emits a structured per-type report via
structlog (R10). **Writes nothing to the database** — this module only
extracts and fits; pooling/write-back/backfill/metrics (Wave 3/4) are
separate, independently-tested functions in this package that a future
scheduled orchestrator composes with this module's output (see the
package-level ``.claude-context.md`` note — the composition itself is not
yet wired, a known and documented gap, not an oversight).

Not yet invocable as a CLI or ``-m`` entrypoint — call ``run_shadow_fit``
as a library function with a read-replica-bound session. A future
orchestrator will add the ``-m`` entrypoint alongside the wiring above.

The ~14 target types are the seeded ``TEMPORAL_CLAIM`` set (PRD §4 FR-3):
analyst_rating, market_share_claim, price_target, earnings_guidance,
sentiment_signal, credit_rating, issues_debt, earnings_released,
corporate_action, revenue_from_country, divested_from, downgraded_by,
filed_lawsuit_against, reported_revenue_of.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from knowledge_graph.application.analytics.decay_fitting.lifetime_extraction import (
    RelationStateNotFittableError,
    extract_mention_series,
    extract_supersession_lifetimes,
)
from knowledge_graph.application.analytics.decay_fitting.nhpp_estimator import fit_nhpp
from knowledge_graph.application.analytics.decay_fitting.supersession_estimator import fit_supersession
from knowledge_graph.domain.decay_fit import DecayFit
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)  # type: ignore[no-any-return]

# The seeded TEMPORAL_CLAIM types (PRD §4 FR-3) — the fitter's target set.
TARGET_TEMPORAL_CLAIM_TYPES: tuple[str, ...] = (
    "analyst_rating",
    "market_share_claim",
    "price_target",
    "earnings_guidance",
    "sentiment_signal",
    "credit_rating",
    "issues_debt",
    "earnings_released",
    "corporate_action",
    "revenue_from_country",
    "divested_from",
    "downgraded_by",
    "filed_lawsuit_against",
    "reported_revenue_of",
)

# Class-prior alphas (decay_class_config seed, migration 0001).
_CLASS_PRIOR_ALPHAS: dict[str, float] = {
    "PERMANENT": 0.0,
    "DURABLE": 0.000950,
    "SLOW": 0.003851,
    "MEDIUM": 0.011552,
    "FAST": 0.049510,
    "EPHEMERAL": 0.231049,
}

# Each target type's SEEDED decay_class (relation_type_registry, migration
# 0001/0004/0041 — verified live against intelligence_db 2026-07-14). QA
# review (2026-07-14) found every DecayFit was being stamped with a single
# hardcoded MEDIUM prior regardless of the type's real class — this map
# fixes that: `_type_prior_alpha(canonical_type)` resolves the CORRECT
# class-prior per type instead of one constant for all ~14 types.
_TYPE_DECAY_CLASS: dict[str, str] = {
    "analyst_rating": "FAST",
    "market_share_claim": "MEDIUM",
    "price_target": "FAST",
    "earnings_guidance": "MEDIUM",
    "sentiment_signal": "EPHEMERAL",
    "credit_rating": "DURABLE",
    "issues_debt": "MEDIUM",
    "earnings_released": "MEDIUM",
    "corporate_action": "DURABLE",
    "revenue_from_country": "MEDIUM",
    "divested_from": "PERMANENT",
    "downgraded_by": "FAST",
    "filed_lawsuit_against": "SLOW",
    "reported_revenue_of": "MEDIUM",
}


def _type_prior_alpha(canonical_type: str) -> float:
    """Resolve *canonical_type*'s real decay-class prior (falls back to MEDIUM if unmapped)."""
    decay_class = _TYPE_DECAY_CLASS.get(canonical_type, "MEDIUM")
    return _CLASS_PRIOR_ALPHAS[decay_class]


async def run_shadow_fit(
    session: AsyncSession,
    *,
    target_types: tuple[str, ...] = TARGET_TEMPORAL_CLAIM_TYPES,
) -> list[DecayFit]:
    """Run both estimators for every *target_types*, log a per-type report, write nothing.

    Args:
    ----
        session: A session bound to the **read replica** (R27) — this
            function performs zero writes.
        target_types: Override for tests; defaults to the full ~14-type set.

    Returns:
    -------
        Every :class:`DecayFit` produced (one or two per type — corroboration
        and/or supersession, whichever have data). A type with no lifetime
        data at all for BOTH definitions is logged and skipped (not silently
        dropped — the caller sees it in the log, matching the "no silent
        caps" convention).

    """
    fits: list[DecayFit] = []
    for canonical_type in target_types:
        try:
            type_fits = await _fit_one_type(canonical_type, session)
        except RelationStateNotFittableError:
            logger.warning(  # type: ignore[no-any-return]
                "decay_fit_skipped_relation_state",
                canonical_type=canonical_type,
            )
            continue
        if not type_fits:
            logger.info(  # type: ignore[no-any-return]
                "decay_fit_no_data",
                canonical_type=canonical_type,
            )
            continue
        for fit in type_fits:
            logger.info(  # type: ignore[no-any-return]
                "decay_fit_shadow_report",
                canonical_type=fit.canonical_type,
                lifetime_definition=fit.lifetime_definition,
                lambda_hat=fit.lambda_hat,
                half_life_days=fit.half_life_days,
                n=fit.n,
                exposure_time=fit.exposure_time,
                censoring_rate=fit.censoring_rate,
            )
        fits.extend(type_fits)
    return fits


async def _fit_one_type(canonical_type: str, session: AsyncSession) -> list[DecayFit]:
    fits: list[DecayFit] = []
    prior_alpha = _type_prior_alpha(canonical_type)

    mention_series = await extract_mention_series(canonical_type, session)
    events_with_mentions = [s for s in mention_series if s.mention_ages_days]
    if mention_series:
        lambda0_hat, alpha_hat = fit_nhpp(mention_series)
        total_mentions = sum(len(s.mention_ages_days) for s in mention_series)
        fits.append(
            DecayFit(
                canonical_type=canonical_type,
                lifetime_definition="corroboration_nhpp",
                lambda_hat=alpha_hat,
                n=total_mentions,
                exposure_time=sum(s.observation_window_days for s in mention_series),
                censoring_rate=1.0 - (len(events_with_mentions) / len(mention_series)),
                prior_alpha=prior_alpha,
                method="nhpp_corroboration",
            ),
        )
        # lambda0_hat (the baseline intensity) is part of the fit but not
        # carried on DecayFit today — DecayFit.lambda_hat is the DECAY rate
        # (alpha), which is what confidence.py consumes. lambda0_hat is
        # logged for shadow-report completeness only.
        logger.debug("decay_fit_nhpp_lambda0", canonical_type=canonical_type, lambda0_hat=lambda0_hat)  # type: ignore[no-any-return]

    lifetimes = await extract_supersession_lifetimes(canonical_type, session)
    if lifetimes:
        events = [lt for lt in lifetimes if lt.event_observed]
        try:
            lambda_hat = fit_supersession(lifetimes)
        except ValueError:
            lambda_hat = None
        if lambda_hat is not None:
            fits.append(
                DecayFit(
                    canonical_type=canonical_type,
                    lifetime_definition="supersession_mle",
                    lambda_hat=lambda_hat,
                    n=len(events),
                    exposure_time=sum(lt.duration_days for lt in lifetimes),
                    censoring_rate=1.0 - (len(events) / len(lifetimes)),
                    prior_alpha=prior_alpha,
                    method="mle_supersession",
                ),
            )

    return fits
