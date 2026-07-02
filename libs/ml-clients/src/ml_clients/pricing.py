"""Canonical LLM pricing matrix + cost calculator (PLAN-0107; unified PLAN-0117).

This is the **single source of truth** for worldview LLM USD-cost calculations.
It is consumed by ``rag-chat`` (per call site via ``CostRecorder``); as of
PLAN-0117 W1 the legacy ``cost.py`` estimator **delegates** to this module, so
there is exactly ONE price map platform-wide (FR-4a — unification DONE).

Cost provenance (PLAN-0117 FR-1/FR-2): DeepInfra returns ``usage.estimated_cost``
on responses. Adapters capture that verbatim (``cost_source="provider"``) and
only fall back to :func:`compute_cost` (``cost_source="pricematrix"``) when the
provider omits a cost. Genuinely-local models (Ollama/GLiNER, see
:data:`LOCAL_FREE_MODELS`) are ``$0`` with ``cost_source="local"``. A paid model
must NEVER be logged at ``$0`` — that is the silent-zero regression FR-7 guards.

The FR-7 guardrail (PLAN-0117 W5) that keeps this true has two arms, both built
on :func:`is_priceable`:
  * **Priceability CI test + startup log** — :mod:`ml_clients.model_registry`
    enumerates every configured ``(model_id, provider)`` and fails CI (and warns
    at each service's boot) if any has no cost path.
  * **Runtime silent-zero metric** — ``observability.metrics`` increments
    ``llm_usage_silent_zero_cost_total`` at every ``llm_usage_log`` write when a
    row has tokens>0, ``$0`` cost, and a PAID ``cost_source`` (not ``local`` /
    ``aggregate``). See docs/BUG_PATTERNS.md BP-715.

Why a separate module from the (now-delegating) ``cost.py``?
------------------------------------------------------------
``cost.py`` historically used ``float`` arithmetic (acceptable for legacy
dashboards) and bucketed prices by ``provider`` + ``model_id``. This module is
the canonical entry point:

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
from decimal import Decimal, InvalidOperation

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
    # WHY ``per_call_usd`` (PLAN-0107 follow-up): some providers bill
    # per-request rather than per-token — most notably Cohere Rerank, which
    # charges per "search" (≈$2/1000 searches for v3 as of 2026-06). Modelling
    # this as a token-equivalent (input_per_million=$2000 with tokens_in=1)
    # works arithmetically but lies semantically and makes the matrix harder
    # to read. When ``per_call_usd`` is set on an entry, ``compute_cost``
    # ignores token counts entirely and returns this flat per-call value.
    # ``None`` (default) preserves the original per-token math for every
    # existing entry — zero behavioural change for previously-registered
    # token-billed models.
    per_call_usd: Decimal | None = None

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
    "rerank-english-v3.0": ModelPricing(
        # Cohere Rerank v3.0 is billed PER SEARCH, not per token. Public list
        # price as of 2026-06: $2.00 per 1000 searches → $0.002 per call.
        # We model this via the ``per_call_usd`` field added in the same
        # PLAN-0107 follow-up so the per-token columns can stay at 0 and
        # callers can pass tokens_in=1/tokens_out=0 (or any value — they're
        # ignored when per_call_usd is set).
        model_id="rerank-english-v3.0",
        input_per_million=Decimal("0"),
        output_per_million=Decimal("0"),
        per_call_usd=Decimal("0.002"),
        notes="as of 2026-06; Cohere Rerank billed per-search ($2/1000)",
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
    # ── DeepInfra — OpenAI gpt-oss family (PLAN-0117 FR-5) ──────────────────
    # These became the live extraction/synthesis serving models in 2026-06
    # (gpt-oss-120b @ medium reasoning is the current S6/S7 extraction model),
    # yet were absent from the matrix — every call would have fallen through to
    # the provider-cost path or, if that was missing, logged $0. DeepInfra bills
    # these per-token; rates below are the published list price. When DeepInfra
    # returns ``usage.estimated_cost`` the adapter prefers that verbatim; these
    # entries are the matrix fallback + the FR-7 priceability guarantee.
    "openai/gpt-oss-120b": ModelPricing(
        model_id="openai/gpt-oss-120b",
        input_per_million=Decimal("0.09"),
        output_per_million=Decimal("0.45"),
        notes="as of 2026-07; DeepInfra list price (verify at OQ-1)",
    ),
    "openai/gpt-oss-20b": ModelPricing(
        model_id="openai/gpt-oss-20b",
        input_per_million=Decimal("0.04"),
        output_per_million=Decimal("0.16"),
        notes="as of 2026-07; DeepInfra list price (verify at OQ-1)",
    ),
    # Qwen3.5-9B — small Qwen used for relevance/classification when routed to
    # DeepInfra rather than local Ollama. Cheaper tier than Qwen3-32B.
    "Qwen/Qwen3.5-9B": ModelPricing(
        model_id="Qwen/Qwen3.5-9B",
        input_per_million=Decimal("0.04"),
        output_per_million=Decimal("0.09"),
        notes="as of 2026-07; DeepInfra list price (verify at OQ-1)",
    ),
    # ── DeepInfra — additional in-use models surfaced by the FR-7 audit ──────
    # These are configured serving defaults across S7/S8 (V4-Flash-Thinking is
    # the current KG extraction + description model and the S8 completion model;
    # embeddinggemma-300m is the ml-clients router embedding model). They are
    # already priceable via the DeepInfra provider-cost path (``is_priceable``
    # returns True for any deepinfra model), so these entries are purely the
    # matrix FALLBACK for the rare case DeepInfra omits ``usage.estimated_cost``
    # — without them such a call would fall through to $0 and (correctly) trip
    # the FR-7b silent-zero guard. DeepInfra self-reports authoritative cost.
    "deepseek-ai/DeepSeek-V4-Flash-Thinking": ModelPricing(
        model_id="deepseek-ai/DeepSeek-V4-Flash-Thinking",
        # Reasoning ("Thinking") variant of V4-Flash — same input tier, higher
        # output rate (reasoning tokens count as output). Matrix fallback only.
        input_per_million=Decimal("0.14"),
        output_per_million=Decimal("0.56"),
        notes="as of 2026-07; DeepInfra reasoning tier; matrix fallback (provider cost authoritative)",
    ),
    "google/embeddinggemma-300m": ModelPricing(
        model_id="google/embeddinggemma-300m",
        input_per_million=Decimal("0.005"),
        output_per_million=Decimal("0"),  # embeddings have no output token billing
        notes="as of 2026-07; DeepInfra-hosted embedding (input-only billed)",
    ),
}


# ----------------------------------------------------------------------------
# Local / free models (PLAN-0117 FR-5).
# ----------------------------------------------------------------------------
# Model ids served entirely on-prem (Ollama) or in-process (GLiNER) that
# legitimately cost $0 — a row with one of these ids + ``estimated_cost_usd == 0``
# is CORRECT (``cost_source="local"``) and must NOT trip the FR-7 silent-zero
# alarm. Every id below is a REAL configured id verified from service settings /
# infra, not invented:
#   * urchade/gliner_large-v2.1  — GLiNER NER (nlp-pipeline ner_model_id, infra/gliner)
#   * qwen3:0.6b                 — Ollama relevance/classification (S6) + KG ollama extraction
#   * qwen2.5:3b                 — rag-chat Ollama classification
#   * qwen2.5:7b-instruct        — optional Ollama DEEP extraction tier
#   * bge-reranker-v2-m3         — rag-chat Ollama reranker
#   * bge-large-en-v1.5 / bge-large — Ollama local embeddings (distinct from the
#                                 DeepInfra-hosted ``BAAI/bge-large-en-v1.5`` which IS priced)
#   * bge-large:latest           — S7 Ollama embedding tag (knowledge-graph
#                                 embedding_model_id; the ``:latest`` Ollama tag
#                                 variant of bge-large)
#   * deepseek-r1:32b            — rag-chat Ollama emergency completion fallback
#                                 (ollama_completion_model)
LOCAL_FREE_MODELS: frozenset[str] = frozenset(
    {
        "urchade/gliner_large-v2.1",
        "qwen3:0.6b",
        "qwen2.5:3b",
        "qwen2.5:7b-instruct",
        "bge-reranker-v2-m3",
        "bge-large-en-v1.5",
        "bge-large",
        "bge-large:latest",
        "deepseek-r1:32b",
    }
)

# Providers that return a verbatim ``usage.estimated_cost`` on their responses,
# so a model served through them is always priceable via the provider-cost path
# even if it is not (yet) in :data:`MODEL_PRICING`.
_PROVIDER_COST_PROVIDERS: frozenset[str] = frozenset({"deepinfra"})

# Transport providers that are ALWAYS locally-hosted / free regardless of the
# specific ``model_id`` (Ollama pulls arbitrary tags; GLiNER is in-process). A
# call routed through one of these is ``cost_source="local"`` at ``$0`` — and,
# crucially, must NOT be sent through :func:`compute_cost` (which would emit a
# spurious ``model_pricing_unknown`` warning for an un-catalogued local tag).
# This complements :data:`LOCAL_FREE_MODELS` (which lists specific ids): the
# provider check catches local model tags that were never added to that set.
_LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "gliner"})


def is_priceable(model_id: str, *, provider: str) -> bool:
    """Return True when a call to ``model_id`` has a defined cost path.

    A model is priceable when ANY of the following holds:
      * it has a non-UNKNOWN entry in :data:`MODEL_PRICING` (matrix path), OR
      * ``provider`` returns a verbatim provider cost (DeepInfra — provider path),
        so cost is captured even without a matrix entry, OR
      * ``model_id`` is a genuinely-free local model (:data:`LOCAL_FREE_MODELS`).

    Used by the FR-7 CI/startup guardrail: any configured model that returns
    False here would silently log ``$0`` and MUST be added to the matrix.

    Args:
        model_id: Canonical model identifier as sent to the provider.
        provider: Transport provider name ("deepinfra" | "openrouter" | "gemini"
            | "ollama" | …).

    Returns:
        True if a cost path exists; False if a call would be a silent zero.
    """
    entry = MODEL_PRICING.get(model_id)
    if entry is not None and entry.input_per_million >= 0 and entry.output_per_million >= 0:
        return True
    if provider in _PROVIDER_COST_PROVIDERS:
        return True
    return model_id in LOCAL_FREE_MODELS


def provider_cost_to_decimal(estimated_cost: object) -> Decimal | None:
    """Best-effort convert a provider-returned ``estimated_cost`` to ``Decimal``.

    DeepInfra reports ``usage.estimated_cost`` as a float (often in scientific
    notation, e.g. ``4.1e-07``). We bridge via ``Decimal(str(x))`` so no binary
    float artefact leaks into the ``Numeric(12, 6)`` cost columns (R11).

    Returns ``None`` for ``None`` input or any unparseable value — callers then
    fall back to the price matrix. NEVER raises (NFR-1 best-effort).

    Args:
        estimated_cost: The raw value from ``response.usage.estimated_cost``
            (float, int, str, or None).

    Returns:
        The cost as :class:`decimal.Decimal`, or ``None`` if absent/malformed.
    """
    if estimated_cost is None:
        return None
    try:
        # ``str(4.1e-07)`` → "4.1e-07"; Decimal parses scientific notation
        # exactly, avoiding the float→Decimal binary-expansion artefact of
        # ``Decimal(4.1e-07)``.
        value = Decimal(str(estimated_cost))
    except (InvalidOperation, ValueError, TypeError):
        return None
    # Guard against negative provider costs (error sentinels) — clamp to None so
    # the caller uses the matrix instead of persisting a negative cost.
    if value < 0:
        return None
    return value


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
    # operators get one warning shape regardless of which gap they hit. The
    # UNKNOWN sentinel uses negative per-token sentinels; the per-call branch
    # has no sentinel state because operators either set the flat price or
    # leave the entry as UNKNOWN. ``per_call_usd`` (when present) short-
    # circuits below.
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

    # Per-call billing short-circuit (Cohere Rerank, etc.). When an entry has
    # ``per_call_usd`` set the provider charges a flat per-request rate and
    # token counts are irrelevant — return the flat amount regardless of
    # tokens_in/tokens_out. We still treat zero/negative token counts as a
    # FAILED call (no cost charged) so a failed Cohere request doesn't bill —
    # callers wire token_in=1 on success and token_in=0 on failure.
    if entry.per_call_usd is not None:
        if tokens_in == 0 and tokens_out == 0:
            return Decimal("0")
        return entry.per_call_usd

    # Cost = (tokens / 1,000,000) * price_per_million — use Decimal end-to-end
    # so the final per-thread aggregate is exact (no float-drift over many
    # accumulations to ``chat_threads.estimated_cost_usd``).
    one_million = Decimal("1000000")
    input_cost = (Decimal(tokens_in) / one_million) * entry.input_per_million
    output_cost = (Decimal(tokens_out) / one_million) * entry.output_per_million
    return input_cost + output_cost


def resolve_cost(
    model_id: str,
    *,
    provider: str,
    tokens_in: int,
    tokens_out: int,
    provider_estimated_cost: object = None,
) -> tuple[Decimal, str]:
    """Resolve the persisted USD cost + its provenance for one LLM call.

    This is the **single implementation of the §2.2 cost-source priority**
    (PLAN-0117) so that S6, S7 and (in W4) S8/S9 never re-derive the ordering
    and can never drift into the silent-zero regression FR-7 guards. The rule:

      1. **Provider-returned cost wins.** If ``provider_estimated_cost`` parses to
         a non-negative Decimal (DeepInfra reports ``usage.estimated_cost``),
         persist it verbatim → ``cost_source="provider"``.
      2. **Local / free.** If the model is a known-free id
         (:data:`LOCAL_FREE_MODELS`) OR the transport provider is inherently
         local (:data:`_LOCAL_PROVIDERS` — Ollama/GLiNER), the call legitimately
         costs ``$0`` → ``cost_source="local"``. We short-circuit BEFORE
         :func:`compute_cost` so a local tag never trips ``model_pricing_unknown``.
      3. **Price-matrix fallback.** Otherwise compute from the canonical matrix
         → ``cost_source="pricematrix"``. For a genuinely-unknown *paid* model
         :func:`compute_cost` returns ``0`` and warns — that surfaces the gap
         (correct behaviour; FR-7 then flags it).

    Args:
        model_id: Canonical model identifier sent to the provider.
        provider: Transport provider ("deepinfra" | "ollama" | "gemini" | …).
        tokens_in: Prompt/input token count.
        tokens_out: Completion/output token count.
        provider_estimated_cost: Raw ``usage.estimated_cost`` from the provider
            response (float/int/str/None); ``None`` when the call path did not
            capture it (→ matrix or local fallback).

    Returns:
        ``(cost, cost_source)`` — cost as :class:`decimal.Decimal`, cost_source
        one of ``"provider"`` | ``"local"`` | ``"pricematrix"``.
    """
    # 1. Provider-returned cost is authoritative + self-updating.
    provider_cost = provider_cost_to_decimal(provider_estimated_cost)
    if provider_cost is not None:
        return provider_cost, "provider"
    # 2. Local / free — never route a local tag through the matrix (no warning).
    if model_id in LOCAL_FREE_MODELS or provider in _LOCAL_PROVIDERS:
        return Decimal("0"), "local"
    # 3. Price-matrix fallback (may warn on a genuinely-unknown paid model).
    return compute_cost(model_id, tokens_in, tokens_out), "pricematrix"


__all__ = [
    "LOCAL_FREE_MODELS",
    "MODEL_PRICING",
    "ModelPricing",
    "compute_cost",
    "is_priceable",
    "provider_cost_to_decimal",
    "resolve_cost",
]
