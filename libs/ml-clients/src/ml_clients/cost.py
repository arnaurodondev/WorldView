"""LLM cost estimation utilities (PLAN-0033 Wave 1, T-A-1-02).

Provides:
  - ``PRICING``                   — provider → model → input/output cost per 1M tokens
  - ``estimate_cost()``           — USD cost from token counts; 0.0 for unknowns
  - ``estimate_tokens_from_text()`` — word-count heuristic for Ollama (no token API)

Design notes:
  - No external imports — this module depends only on stdlib so it can be
    imported anywhere without pulling in heavyweight dependencies.
  - Prices are approximate and should be reviewed periodically; they serve
    as reasonable cost *estimates* for admin dashboards, not billing records.
  - Ollama models have zero external cost; the wildcard ``"*"`` key handles
    any model string without requiring an exhaustive list.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Pricing table: provider → model_id → {"input": $, "output": $} per 1M tokens
# ---------------------------------------------------------------------------

PRICING: dict[str, dict[str, dict[str, float]]] = {
    # DeepInfra — primary chat completion + extraction + description provider
    # Qwen3-235B-A22B-Instruct-2507: chat completion + extraction + descriptions (MoE 235B / 22B active)
    # Qwen3-32B: description fallback ($0.08 in / $0.28 out per 1M)
    # DeepSeek-V4-Flash: kept for reference; replaced by Qwen3-235B on all slots
    "deepinfra": {
        "Qwen/Qwen3-235B-A22B-Instruct-2507": {"input": 0.071, "output": 0.10},
        "Qwen/Qwen3-32B": {"input": 0.08, "output": 0.28},
        "deepseek-ai/DeepSeek-V4-Flash": {"input": 0.14, "output": 0.28},
    },
    # OpenRouter — secondary chat completion provider (fallback path)
    "openrouter": {
        "deepseek/deepseek-r1-distill-qwen-32b": {"input": 0.69, "output": 2.19},
    },
    # Google Gemini — used by GeminiDescriptionAdapter (entity descriptions)
    # Model ID matches _DEFAULT_MODEL_ID in gemini_description.py
    "gemini": {
        "gemini-3.1-flash-lite": {"input": 0.075, "output": 0.30},
    },
    # Ollama — all models run locally, zero external cost
    # The wildcard key "*" matches any model_id (see estimate_cost below)
    "ollama": {
        "*": {"input": 0.0, "output": 0.0},
    },
}


def estimate_cost(provider: str, model_id: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost for one LLM call from token counts.

    Lookup order:
      1. Exact match on provider + model_id.
      2. Wildcard "*" within the provider (used for Ollama).
      3. Returns 0.0 if neither found — never raises.

    Args:
    ----
        provider:   Provider name (e.g. "ollama", "gemini").
        model_id:   Model string (e.g. "qwen2.5:3b").
        tokens_in:  Number of input (prompt) tokens.
        tokens_out: Number of output (completion) tokens.

    Returns:
    -------
        Estimated USD cost as a float; 0.0 for unknown providers/models.

    """
    provider_table = PRICING.get(provider)
    if provider_table is None:
        return 0.0

    # Try exact model match first, then wildcard
    rates = provider_table.get(model_id) or provider_table.get("*")
    if rates is None:
        return 0.0

    # Cost = (tokens / 1_000_000) * price_per_million
    input_cost = (tokens_in / 1_000_000) * rates["input"]
    output_cost = (tokens_out / 1_000_000) * rates["output"]
    return input_cost + output_cost


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
