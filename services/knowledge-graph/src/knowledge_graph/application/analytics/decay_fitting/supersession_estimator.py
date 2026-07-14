"""Supersession/contradiction censored-exponential estimator.

PLAN-0123 Wave 2 (PRD-0120 §4 FR-3(b), review SS-3 "competing risks").

Unlike the corroboration-decay definition (``nhpp_estimator.py``), time-to-
supersession genuinely is a "time to first terminal event" problem, so the
textbook right-censored exponential MLE applies directly — no NHPP
correction is needed here.

Right-censored exponential MLE::

    lambda_hat = (number of observed terminal events) / (sum of all
                  duration_days, censored + uncensored)

A relation's terminal event is whichever of ``latest_contra_at`` (a
contradiction) or ``valid_to`` (a validity-window closure) occurs **first**
(review SS-3's competing-risks convention: censor the risk that did not
fire first, rather than conflating both hazards into one event count). A
relation with neither observed is right-censored at "now".

Per PRD §6.6 / plan Wave 1 codebase-state finding: ``relations_history``
carries ``decay_class`` but has **no** ``decay_alpha`` column and is not
needed here — everything this estimator requires
(``first_evidence_at``, ``latest_contra_at``, ``valid_to``) is already
denormalized directly on ``relations``.
"""

from __future__ import annotations

from knowledge_graph.domain.decay_fit import Lifetime

_MIN_EXPOSURE = 1e-9


def fit_supersession(lifetimes: list[Lifetime]) -> float:
    """Right-censored exponential MLE: events / total exposure time.

    Args:
    ----
        lifetimes: One :class:`Lifetime` per relation instance of a single
            canonical_type, built via the competing-risks rule (earliest of
            ``latest_contra_at``/``valid_to`` wins as the terminal event;
            neither present => right-censored at "now").

    Returns:
    -------
        ``lambda_hat`` — the estimated decay/hazard rate.

    Raises:
    ------
        ValueError: if *lifetimes* is empty, or if every lifetime has
            ``duration_days == 0`` (zero total exposure — undefined MLE).

    """
    if not lifetimes:
        raise ValueError("fit_supersession requires at least one Lifetime")

    total_events = sum(1 for lt in lifetimes if lt.event_observed)
    total_exposure = sum(lt.duration_days for lt in lifetimes)

    if total_exposure < _MIN_EXPOSURE:
        raise ValueError("fit_supersession requires positive total exposure time")

    if total_events == 0:
        # All-censored: no terminal events observed at all. The MLE would be
        # exactly 0 (undefined for exp(-lambda*age) purposes) — return a
        # small positive floor instead of 0/undefined so callers (Wave 3
        # pooling) can still treat this as "very sparse, near-zero rate"
        # rather than crashing. This case is expected to be flagged sparse
        # by the Wave 3 min-n gate regardless (n=0 events).
        return _MIN_EXPOSURE

    return total_events / total_exposure


def build_lifetime(
    observation_age_days: float,
    contra_duration_days: float | None,
    valid_to_duration_days: float | None,
) -> Lifetime:
    """Build one relation's :class:`Lifetime` via the competing-risks rule (SS-3).

    All durations are measured **from the relation's ``first_evidence_at``**
    (the lifetime clock's origin) — this keeps the competing-risks
    comparison a simple ``min()`` instead of an error-prone "days ago"
    framing.

    Args:
    ----
        observation_age_days: Days from ``first_evidence_at`` to "now" — the
            right-censoring duration used when no terminal event has fired.
        contra_duration_days: Days from ``first_evidence_at`` to
            ``latest_contra_at``, or ``None`` if never contradicted.
        valid_to_duration_days: Days from ``first_evidence_at`` to
            ``valid_to``, or ``None`` if still open.

    Returns:
    -------
        A :class:`Lifetime` with ``duration_days`` measured to whichever
        terminal event fired **first** (smallest duration — the
        competing-risks convention: the other risk is censored, not
        double-counted), or to "now" if neither has fired.

    """
    candidates = [d for d in (contra_duration_days, valid_to_duration_days) if d is not None]
    if candidates:
        # The event that fired FIRST (smallest duration since founding) wins;
        # the other risk is treated as censored, not double-counted (SS-3).
        terminal_duration = min(candidates)
        return Lifetime(duration_days=max(terminal_duration, 0.0), event_observed=True)

    return Lifetime(duration_days=max(observation_age_days, 0.0), event_observed=False)
