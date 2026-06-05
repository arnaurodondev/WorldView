"""Canonical LLM pricing matrix + cost calculator (PLAN-0107 follow-up).

This is the **single source of truth** for worldview LLM USD-cost calculations.
It is consumed today by ``rag-chat`` (per call site via ``CostRecorder``); the
intention is for ``nlp-pipeline`` and ``knowledge-graph`` to adopt this same
matrix in follow-up waves so every service estimates cost the same way.

Why a separate module from the existing ``cost.py``?
--------------------------------------------------
``cost.py`` uses ``float`` arithmetic (acceptable for legacy dashboards) and
buckets prices by ``provider`` + ``model_id``. This module is the *new*
canonical entry point:

  * keys solely on ``model_id`` (a model uniquely identifies pricing — the
    provider is purely transport),
  * uses :class:`decimal.Decimal` so accumulated per-thread totals never
    suffer float-rounding drift when persisted to ``Numeric(12, 6)`` columns,
  * returns ``Decimal("0")`` and logs a structured warning for unknown
    models instead of silently masking the gap.

Prices are approximate and *MUST* be reviewed periodically. Each entry tags
the "as of" date so operators can spot stale numbers and update them when
provider pricing changes (DeepInfra in particular has reduced prices
multiple times in 2025-2026). All prices are USD per 1,000,000 tokens
unless stated otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import structlog

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


# A sentinel string used by ``ModelPricing.UNKNOWN`` entries so operators
# scanning the matrix know "we have not priced this yet" vs "this model is
# genuinely free". Treated identically to a missing entry by ``compute_cost``.
_UNKNOWN_MARKER = "UNKNOWN"


@dataclass(frozen=True)
class ModelPricing:
    """Immutable pricing record for a single model.

    Attributes:
        model_id: The canonical model identifier as it appears in the
            provider API (e.g. ``"deepseek-ai/DeepSeek-V4-Flash"``).
        input_per_million: USD cost for 1,000,000 input/prompt tokens.
            ``Decimal("0")`` indicates a free or locally-hosted model;
            ``Decimal("-1")`` is reserved for the UNKNOWN sentinel.
        output_per_million: USD cost for 1,000,000 output/completion tokens.
        currency: Settlement currency (always ``"USD"`` today, but
            preserved for future multi-currency reporting).
        notes: Free-form human note for operators (e.g. pricing date).
    """

    # Why ``frozen=True``: pricing entries are constants — accidental
    # mutation would silently corrupt every downstream cost calculation.
    model_id: str
    input_per_million: Decimal
    output_per_million: Decimal
    currency: str = "USD"
    notes: str = ""

    @classmethod
    def UNKNOWN(cls, model_id: str, *, notes: str = "") -> ModelPricing:  # noqa: N802 — sentinel constructor mirrors typing.Final convention
        """Construct a sentinel pricing entry for a model we have not yet priced.

        Why expose this as a constructor: when a new model appears in the
        chain (e.g. a fallback we added but haven't researched), we want the
        matrix to *acknowledge* it rather than silently fall through to the
        "unknown model" warning path on every call.
        """
        return cls(
            model_id=model_id,
            # Negative sentinel value — ``compute_cost`` detects this and
            # returns Decimal("0") + emits the same ``model_pricing_unknown``
            # warning as a missing entry.
            input_per_million=Decimal("-1"),
            output_per_million=Decimal("-1"),
            notes=notes or _UNKNOWN_MARKER,
        )


# ----------------------------------------------------------------------------
# Pricing matrix.
# ----------------------------------------------------------------------------
# Prices below are "as of 2026-06" and reflect publicly-listed provider rates.
# When updating: bump the trailing date in the ``notes`` field so operators
# scanning Grafana cost panels know which deploy refreshed the matrix.
#
# Naming convention: the dict key MUST match the ``model_id`` exactly as the
# provider's OpenAI-compat ``model`` field expects it. Mismatched casing or
# trailing whitespace = silent zero cost.

MODEL_PRICING: dict[str, ModelPricing] = {
    # ── DeepInfra — primary chat completion + tool-use provider ────────────
    # Pricing source: DeepInfra public price list (2026-06). DeepInfra
    # frequently bumps prices DOWN for the Qwen/Meta family; review quarterly.
    "deepseek-ai/DeepSeek-V4-Flash": ModelPricing(
        model_id="deepseek-ai/DeepSeek-V4-Flash",
        # V4-Flash sits at the "small fast" tier on DeepInfra; same price as
        # 2025-Q4 listing — last verified 2026-06.
        input_per_million=Decimal("0.14"),
        output_per_million=Decimal("0.28"),
        notes="as of 2026-06; DeepInfra fast tier",
    ),
    "meta-llama/Meta-Llama-3.1-8B-Instruct": ModelPricing(
        model_id="meta-llama/Meta-Llama-3.1-8B-Instruct",
        # 8B Instruct is used for intent + safety classification + judge —
        # cheap by design (we make many small calls per conversation).
        input_per_million=Decimal("0.055"),
        output_per_million=Decimal("0.055"),
        notes="as of 2026-06; intent + safety + judge",
    ),
    "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": ModelPricing(
        # Turbo variant has the same pricing on DeepInfra as the standard
        # 8B-Instruct (Turbo = vLLM-optimised serving, not a different SKU).
        model_id="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        input_per_million=Decimal("0.055"),
        output_per_million=Decimal("0.055"),
        notes="as of 2026-06; same SKU as 8B-Instruct (Turbo = serving variant)",
    ),
    "Qwen/Qwen3-235B-A22B-Instruct-2507": ModelPricing(
        # 235B MoE / 22B active — primary synthesis model.
        model_id="Qwen/Qwen3-235B-A22B-Instruct-2507",
        input_per_million=Decimal("0.071"),
        output_per_million=Decimal("0.10"),
        notes="as of 2026-06; primary chat synthesis",
    ),
    "Qwen/Qwen3-32B": ModelPricing(
        model_id="Qwen/Qwen3-32B",
        input_per_million=Decimal("0.08"),
        output_per_million=Decimal("0.28"),
        notes="as of 2026-06; description fallback",
    ),
    # ── DeepInfra — reasoning / R1-distill ─────────────────────────────────
    "deepseek-r1-distill-qwen-32b": ModelPricing(
        # Per PRD-0016: R1 distill 32B chat completion. DeepInfra list price.
        model_id="deepseek-r1-distill-qwen-32b",
        input_per_million=Decimal("0.12"),
        output_per_million=Decimal("0.18"),
        notes="as of 2026-06; reasoning model",
    ),
    # ── DeepInfra — embeddings ─────────────────────────────────────────────
    # Embeddings are billed per input token; output tokens are always 0.
    # We track them through the same recorder so the total cost panel
    # includes them, but operators can split with the ``call_site`` label.
    "BAAI/bge-large-en-v1.5": ModelPricing(
        model_id="BAAI/bge-large-en-v1.5",
        input_per_million=Decimal("0.010"),
        output_per_million=Decimal("0"),  # embeddings have no output token billing
        notes="as of 2026-06; embedding (input-only billed)",
    ),
    # ── OpenRouter — fallback chain ────────────────────────────────────────
    "deepseek/deepseek-r1-distill-qwen-32b": ModelPricing(
        # OpenRouter charges noticeably more than DeepInfra direct for the
        # same model — we fall back here only when DeepInfra is unhealthy.
        model_id="deepseek/deepseek-r1-distill-qwen-32b",
        input_per_million=Decimal("0.69"),
        output_per_million=Decimal("2.19"),
        notes="as of 2026-06; OpenRouter fallback",
    ),
    # ── Reranker ───────────────────────────────────────────────────────────
    # Cohere Rerank v3 is billed per search (not per token); we model the
    # call_site for visibility but the cost is approximate — operators using
    # Cohere reranker should override this entry with their negotiated rate.
    "rerank-english-v3.0": ModelPricing.UNKNOWN(
        "rerank-english-v3.0",
        notes="Cohere billed per-search not per-token; operator must override",
    ),
    # ── Common providers we may fall back to but have not priced ───────────
    # These are intentional UNKNOWNs so the matrix is *honest* about coverage
    # rather than silently returning 0. Operators see the warning + know to
    # add real pricing when adoption grows.
    "gpt-4o-mini": ModelPricing.UNKNOWN("gpt-4o-mini", notes="OpenAI; pending operator override"),
    "claude-3-5-sonnet": ModelPricing.UNKNOWN("claude-3-5-sonnet", notes="Anthropic; pending operator override"),
    "gemini-3.1-flash-lite": ModelPricing(
        model_id="gemini-3.1-flash-lite",
        input_per_million=Decimal("0.075"),
        output_per_million=Decimal("0.30"),
        notes="as of 2026-06; Google Gemini Flash Lite",
    ),
}


def compute_cost(model_id: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Compute USD cost for one LLM call using exact :class:`Decimal` arithmetic.

    Behaviour:
      * If ``model_id`` is in :data:`MODEL_PRICING` AND the entry is not the
        ``UNKNOWN`` sentinel: returns ``(tokens_in/1M)*input_per_million +
        (tokens_out/1M)*output_per_million`` as a Decimal.
      * If ``model_id`` is missing OR the entry is ``UNKNOWN``: returns
        ``Decimal("0")`` and emits a single ``model_pricing_unknown`` warning
        per call. We *never* raise — a pricing gap must not break the
        request path; the warning + cost==0 surfaces the gap on dashboards
        without taking the service down.
      * Zero token counts produce ``Decimal("0")`` (e.g. failed calls).
      * Very large token counts are safe — Decimal has arbitrary precision,
        unlike float which would lose digits past ~15 significant figures.

    Args:
        model_id: Canonical model identifier (must match
            :data:`MODEL_PRICING` keys exactly).
        tokens_in: Prompt/input token count from the provider response.
        tokens_out: Completion/output token count from the provider response.

    Returns:
        USD cost as a :class:`decimal.Decimal`.
    """
    # Negative-token sanity check — providers occasionally return -1 on error
    # paths. Clamp to 0 so we never compute a negative cost.
    if tokens_in < 0:
        tokens_in = 0
    if tokens_out < 0:
        tokens_out = 0

    entry = MODEL_PRICING.get(model_id)
    # Treat both "not present" and "UNKNOWN sentinel" as the same case so
    # operators get one warning shape regardless of which gap they hit.
    if entry is None or entry.input_per_million < 0 or entry.output_per_million < 0:
        log.warning(  # type: ignore[no-any-return]
            "model_pricing_unknown",
            model_id=model_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            # Help operators discover the matrix when they hit this warning.
            hint="add an entry to libs/ml-clients/src/ml_clients/pricing.MODEL_PRICING",
        )
        return Decimal("0")

    # Cost = (tokens / 1,000,000) * price_per_million — use Decimal end-to-end
    # so the final per-thread aggregate is exact (no float-drift over many
    # accumulations to ``chat_threads.estimated_cost_usd``).
    one_million = Decimal("1000000")
    input_cost = (Decimal(tokens_in) / one_million) * entry.input_per_million
    output_cost = (Decimal(tokens_out) / one_million) * entry.output_per_million
    return input_cost + output_cost


__all__ = ["MODEL_PRICING", "ModelPricing", "compute_cost"]
