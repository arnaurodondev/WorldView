"""LLM cost estimation utilities (PLAN-0033 W1; unified PLAN-0117 W1, T-A-1-04).

Provides:
  - ``estimate_cost()``           — USD cost from token counts (float); DELEGATES
                                    to :func:`ml_clients.pricing.compute_cost` so
                                    there is exactly ONE price source of truth.
  - ``estimate_tokens_from_text()`` — word-count heuristic for Ollama (no token API)

Design notes:
  - **PLAN-0117 FR-4a (unification DONE)**: the independent ``PRICING`` map that
    used to live here has been RETIRED. ``estimate_cost`` now drops the
    ``provider`` argument (a ``model_id`` uniquely determines pricing — provider
    is pure transport) and returns ``float(compute_cost(model_id, ...))``. The
    ``provider`` parameter is retained ONLY for signature compatibility with
    existing S6/S7/S8 call sites and is ignored.
  - Prices are approximate and should be reviewed periodically; see
    :data:`ml_clients.pricing.MODEL_PRICING` (the single source of truth).
  - Callers stamp ``cost_source`` ("provider"/"pricematrix"/"local") at the call
    site — it is NOT inferred here.
"""

from __future__ import annotations

import math

from ml_clients.pricing import compute_cost


def estimate_cost(provider: str, model_id: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost for one LLM call — delegates to the canonical matrix.

    PLAN-0117 FR-4a: this is a thin compatibility shim over
    :func:`ml_clients.pricing.compute_cost`. The ``provider`` argument is
    accepted but IGNORED (a ``model_id`` uniquely determines pricing); it is kept
    so existing four-argument call sites keep compiling. Unknown/local models
    resolve to ``0.0`` (``compute_cost`` warns on unknown paid models). Never
    raises.

    Args:
    ----
        provider:   Transport provider name — IGNORED (kept for compatibility).
        model_id:   Model string (e.g. "Qwen/Qwen3-32B"); must match a
                    :data:`ml_clients.pricing.MODEL_PRICING` key for a non-zero
                    cost.
        tokens_in:  Number of input (prompt) tokens.
        tokens_out: Number of output (completion) tokens.

    Returns:
    -------
        Estimated USD cost as a float; 0.0 for unknown/local models.

    """
    # Delegate to the single Decimal-based calculator, then narrow to float for
    # the legacy float-typed callers/dashboards. float() of a small Decimal is
    # exact enough for display (billing-grade totals accumulate in Decimal via
    # compute_cost directly, not through this shim).
    return float(compute_cost(model_id, tokens_in, tokens_out))


def estimate_tokens_from_text(text: str) -> int:
    """Estimate token count from raw text using a word-count heuristic.

    Uses the rule-of-thumb that 1 token ≈ 0.75 words (i.e. tokens = words / 0.75).
    This is appropriate for Ollama-served models where the server does not return
    exact token counts in its response.

    Returns at least 1 to avoid division-by-zero issues in cost computation.

    Args:
    ----
        text: The raw text whose token count is needed.

    Returns:
    -------
        Estimated token count (integer, min 1).

    """
    if not text:
        return 1
    word_count = len(text.split())
    # tokens = ceil(word_count / 0.75) — consistent with OpenAI's heuristic
    return max(1, math.ceil(word_count / 0.75))
