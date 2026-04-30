"""Display relevance score formula (PLAN-0055 C-3).

Pure function — no DB, no async, deterministic. Centralises the scoring formula
so the news read path, the fundamentals worker, and any future consumer all
agree on a single source of truth.

When the LLM score is missing (e.g. LIGHT-tier articles, replay in progress)
we **renormalize** the remaining weights instead of dropping the LLM term and
treating the missing value as 0. Dropping silently biased low-relevance LLM
scores indistinguishably from missing scores; renormalizing keeps the displayed
distribution comparable across articles regardless of LLM availability.
"""

from __future__ import annotations

# PRD-0026 §6.5 weights (also mirrored in nlp-pipeline.env). Kept as constants
# here so any future re-tuning happens in one place; tests pin them.
_WEIGHT_MARKET: float = 0.5
_WEIGHT_LLM: float = 0.4
_WEIGHT_ROUTING: float = 0.1


def compute_display_relevance_score(
    *,
    market_score: float,
    routing_score: float,
    llm_score: float | None,
) -> float:
    """Combine market + routing + (optional) LLM signals into the displayed score.

    With LLM score::

        display = 0.5 * market + 0.4 * llm + 0.1 * routing

    Without LLM score (renormalized — weights re-sum to 1.0)::

        display = (0.5 / 0.6) * market + (0.1 / 0.6) * routing
                ≈ 0.833 * market + 0.167 * routing

    The output is clamped to ``[0.0, 1.0]`` defensively — upstream signals
    should already be in-range but the clamp makes the contract explicit.
    """
    if llm_score is not None:
        raw = (_WEIGHT_MARKET * market_score) + (_WEIGHT_LLM * llm_score) + (_WEIGHT_ROUTING * routing_score)
    else:
        # Renormalize across the two remaining signals.
        remaining = _WEIGHT_MARKET + _WEIGHT_ROUTING
        raw = (_WEIGHT_MARKET / remaining) * market_score + (_WEIGHT_ROUTING / remaining) * routing_score

    return max(0.0, min(1.0, raw))
