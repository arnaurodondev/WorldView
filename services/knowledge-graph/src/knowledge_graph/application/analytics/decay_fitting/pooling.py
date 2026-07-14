"""Partial pooling / empirical-Bayes shrinkage — PLAN-0123 Wave 3, T-A-3-01.

Combines the two Wave-2 lifetime-definition fits (corroboration NHPP,
supersession MLE) into one final per-type alpha, per PRD-0120 §4 FR-4/FR-5
and P-7 ("prefer the truth signal").

Signal selection (P-7 / FR-5): supersession (a durability/truth signal) is
preferred over corroboration (an attention signal, confounded by entity
news-volume) whenever the type has enough supersession events
(``n >= min_n``); otherwise corroboration is used as the fallback.

Shrinkage (FR-4): ``alpha_final = w * alpha_raw + (1 - w) * prior_alpha``,
``w = n / (n + pooling_k)`` — pulls sparse types toward the class-prior
value; well-observed types move meaningfully away from it. The min-n gate
additionally forces the honest ``pooled_prior`` method label whenever
``n < min_n``, even though the shrinkage math alone already pulls the value
close to the prior at low n (belt-and-suspenders — provenance must never
overstate confidence in a tiny-n fit).
"""

from __future__ import annotations

from knowledge_graph.domain.decay_fit import DecayFit, FitMethod


def pool_type_fit(
    corroboration: DecayFit | None,
    supersession: DecayFit | None,
    prior_alpha: float,
    *,
    min_n: int = 30,
    pooling_k: int = 30,
) -> DecayFit:
    """Combine the two Wave-2 fits into one final per-type :class:`DecayFit`.

    Args:
    ----
        corroboration: The NHPP corroboration-decay fit, or ``None`` if the
            type had no mention data at all.
        supersession: The censored-exponential supersession fit, or ``None``
            if the type had no relation lifetimes at all.
        prior_alpha: The type's decay-class prior alpha (the empirical-Bayes
            shrinkage target).
        min_n: Minimum sample size to write a type's own fit rather than the
            prior (PRD §14 OQ-2 default: 30).
        pooling_k: Shrinkage pooling constant — ``w = n / (n + pooling_k)``.

    Returns:
    -------
        A new :class:`DecayFit` with ``alpha_final`` and ``shrinkage_weight``
        populated, ``method`` set to whichever signal was selected (or
        ``"pooled_prior"`` if neither fit has any data or ``n < min_n``).

    Raises:
    ------
        ValueError: if both *corroboration* and *supersession* are ``None``
            (nothing to pool — the caller should not have invoked this for
            a type with zero data at all; that case belongs to the
            "no data" report path in ``run_fitter.py``, not pooling).

    """
    if corroboration is None and supersession is None:
        raise ValueError("pool_type_fit requires at least one of corroboration/supersession")

    # _select_signal always returns a non-None `selected` given the guard
    # above (at least one input is non-None) — see its docstring/branches.
    selected, method = _select_signal(corroboration, supersession, min_n)
    assert selected is not None  # — invariant guaranteed by the guard above

    w = selected.n / (selected.n + pooling_k)
    alpha_final = w * selected.lambda_hat + (1 - w) * prior_alpha
    final_method: FitMethod = method if selected.n >= min_n else "pooled_prior"

    return DecayFit(
        canonical_type=selected.canonical_type,
        lifetime_definition=selected.lifetime_definition,
        lambda_hat=selected.lambda_hat,
        n=selected.n,
        exposure_time=selected.exposure_time,
        censoring_rate=selected.censoring_rate,
        prior_alpha=prior_alpha,
        method=final_method,
        shrinkage_weight=w,
        alpha_final=alpha_final,
    )


def _select_signal(
    corroboration: DecayFit | None,
    supersession: DecayFit | None,
    min_n: int,
) -> tuple[DecayFit | None, FitMethod]:
    """P-7: prefer supersession when it clears min_n; else fall back to corroboration."""
    if supersession is not None and supersession.n >= min_n:
        return supersession, "mle_supersession"
    if corroboration is not None:
        return corroboration, "nhpp_corroboration"
    if supersession is not None:
        # Only supersession data exists at all, but it's below min_n — still
        # the best available signal; the min-n gate in pool_type_fit will
        # relabel this pooled_prior if selected.n < min_n.
        return supersession, "mle_supersession"
    return None, "pooled_prior"
