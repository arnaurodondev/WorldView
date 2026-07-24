"""Platform-wide LLM model registry + priceability guardrail (PLAN-0117 FR-7a).

This module is the **single source of truth** for "every ``model_id`` the
platform can emit, and the transport provider it is emitted through". It exists
so the FR-7 guardrail can answer one question deterministically:

    Is every configured model *priceable*? (i.e. does it have a cost path — a
    :data:`ml_clients.pricing.MODEL_PRICING` entry, a provider-cost provider such
    as DeepInfra, or a :data:`ml_clients.pricing.LOCAL_FREE_MODELS` entry?)

If ANY configured model is not priceable, a call to it would be logged at ``$0``
even though it burned tokens — the exact RC-1/RC-2/RC-3 silent-zero regression
that PLAN-0117 closes. The CI test :func:`unpriceable_models` (run over
:data:`PLATFORM_MODEL_REGISTRY`) FAILS the build when that happens; each service
also calls :func:`warn_unpriceable_models` at startup to log a best-effort
warning for its *actually-configured* model ids (which may differ from the
defaults below when overridden via env).

Keeping this list in sync (drift guard)
----------------------------------------
The entries below MUST mirror the model-id defaults in each service's
``config.py`` (and the ml-clients ``config.py`` defaults). When a service adds or
changes a configured model id, add/update the corresponding row here — the CI
priceability test is the tripwire that a *new* model shipped without a price.
The ``field`` column names the settings attribute so the source is greppable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from ml_clients.pricing import is_priceable

if TYPE_CHECKING:
    from collections.abc import Iterable

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class ConfiguredModel:
    """One (model_id, provider) the platform can emit, tagged with its origin.

    Attributes:
        service: Owning service ("nlp-pipeline" | "knowledge-graph" | "rag-chat"
            | "api-gateway" | "ml-clients").
        field: The settings attribute (or constant) that configures this id, for
            greppability when the CI test flags it.
        model_id: The canonical model identifier sent to the provider.
        provider: Transport provider ("deepinfra" | "ollama" | "gliner" |
            "gemini" | "openrouter" | "cohere").
    """

    service: str
    field: str
    model_id: str
    provider: str


# ── The registry (mirrors service config.py defaults — see module docstring) ──
# Verified 2026-07-24 against each service's config.py + libs/ml-clients/config.py
# (re-verified by tests/architecture/test_model_registry_completeness.py, which
# independently re-derives this list from config.py and fails CI on drift).
PLATFORM_MODEL_REGISTRY: tuple[ConfiguredModel, ...] = (
    # ── S6 nlp-pipeline ──────────────────────────────────────────────────────
    ConfiguredModel("nlp-pipeline", "embedding_model_id", "bge-large", "ollama"),
    ConfiguredModel("nlp-pipeline", "ner_model_id", "urchade/gliner_large-v2.1", "gliner"),
    ConfiguredModel("nlp-pipeline", "extraction_model_id", "qwen2.5:7b-instruct", "ollama"),
    ConfiguredModel("nlp-pipeline", "embedding_api_model_id", "BAAI/bge-large-en-v1.5", "deepinfra"),
    ConfiguredModel("nlp-pipeline", "extraction_api_model_id", "Qwen/Qwen3-235B-A22B-Instruct-2507", "deepinfra"),
    ConfiguredModel("nlp-pipeline", "extraction_fallback_model_id", "deepseek-ai/DeepSeek-V4-Flash", "deepinfra"),
    ConfiguredModel("nlp-pipeline", "relevance_scoring_model", "qwen3:0.6b", "ollama"),
    ConfiguredModel(
        "nlp-pipeline",
        "relevance_scoring_api_model_id",
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "deepinfra",
    ),
    ConfiguredModel("nlp-pipeline", "unresolved_resolution_classification_model", "qwen3:0.6b", "ollama"),
    ConfiguredModel(
        "nlp-pipeline",
        "unresolved_resolution_api_model_id",
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "deepinfra",
    ),
    ConfiguredModel(
        "nlp-pipeline",
        "EntailmentCheckConfig.model_id",
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
        "deepinfra",
    ),
    # extraction_high_recall_model_id (2026-07-24): HIGH-RECALL model slug for
    # SEC/long-filing extraction (hybrid_extraction_routing_enabled). Same
    # model_id as extraction_api_model_id above but a distinct config field —
    # enrolled separately so tests/architecture/test_model_registry_completeness.py
    # can verify (service, field) coverage independently of value dedup.
    ConfiguredModel(
        "nlp-pipeline",
        "extraction_high_recall_model_id",
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
        "deepinfra",
    ),
    # claim_entailment_check_model_id (2026-07-24): opt-in claim-entailment
    # verifier (claim_entailment_check_enabled, default OFF). Same model_id as
    # extraction_fallback_model_id above.
    ConfiguredModel(
        "nlp-pipeline",
        "claim_entailment_check_model_id",
        "deepseek-ai/DeepSeek-V4-Flash",
        "deepinfra",
    ),
    # ── S7 knowledge-graph ───────────────────────────────────────────────────
    ConfiguredModel("knowledge-graph", "embedding_model_id", "bge-large:latest", "ollama"),
    ConfiguredModel("knowledge-graph", "embedding_api_model_id", "BAAI/bge-large-en-v1.5", "deepinfra"),
    # polarity_classifier_model_id (2026-07-24): KG "against a company"
    # bullish/bearish exposure classifier (DeepInfra-served — see the field's
    # own config.py comment for the 404-on-smaller-model history).
    ConfiguredModel(
        "knowledge-graph",
        "polarity_classifier_model_id",
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "deepinfra",
    ),
    ConfiguredModel(
        "knowledge-graph",
        "deepinfra_extraction_model_id",
        "deepseek-ai/DeepSeek-V4-Flash-Thinking",
        "deepinfra",
    ),
    ConfiguredModel(
        "knowledge-graph",
        "description_deepinfra_model_id",
        "deepseek-ai/DeepSeek-V4-Flash-Thinking",
        "deepinfra",
    ),
    ConfiguredModel(
        "knowledge-graph",
        "description_deepinfra_fallback_model_id",
        "Qwen/Qwen3.5-9B",
        "deepinfra",
    ),
    ConfiguredModel("knowledge-graph", "narrative_llm_model_id", "deepseek-ai/DeepSeek-V4-Flash", "deepinfra"),
    ConfiguredModel("knowledge-graph", "summary_fallback_model_id", "deepseek-ai/DeepSeek-V4-Flash", "deepinfra"),
    ConfiguredModel("knowledge-graph", "summary_embedding_model_id", "BAAI/bge-large-en-v1.5", "deepinfra"),
    ConfiguredModel(
        "knowledge-graph",
        "path_insight_explanation_model_id",
        "deepseek-ai/DeepSeek-V4-Flash",
        "deepinfra",
    ),
    ConfiguredModel("knowledge-graph", "description_gemini (adapter default)", "gemini-3.1-flash-lite", "gemini"),
    # ── S8 rag-chat ──────────────────────────────────────────────────────────
    # ollama_classification_model removed with the intent-classifier retirement.
    ConfiguredModel("rag-chat", "ollama_completion_model", "deepseek-r1:32b", "ollama"),
    ConfiguredModel("rag-chat", "ollama_reranker_model", "bge-reranker-v2-m3", "ollama"),
    ConfiguredModel("rag-chat", "deepinfra_classification_model", "Qwen/Qwen3.5-9B", "deepinfra"),
    # completion_model (updated 2026-07-24 / DEF-035): the previous default
    # "deepseek-ai/DeepSeek-V4-Flash-Thinking" does NOT exist on DeepInfra
    # (404) — prod only survived via the RAG_CHAT_COMPLETION_MODEL env
    # override. config.py's default now points at the real, live-verified
    # model ("openai/gpt-oss-120b"); this entry was stale (still recording the
    # retired 404 slug) until test_model_registry_completeness.py's
    # REG-VALUE-STALE check caught the drift.
    ConfiguredModel("rag-chat", "completion_model", "openai/gpt-oss-120b", "deepinfra"),
    # planning_model (2026-07-24 / DEF-036): planner/synthesis model split —
    # drives ONLY the tool-loop planning turn (chat_with_tools). Defaults to
    # the SAME value as completion_model (see config.py DEF-036 comment).
    ConfiguredModel("rag-chat", "planning_model", "openai/gpt-oss-120b", "deepinfra"),
    ConfiguredModel(
        "rag-chat",
        "openrouter_completion_model",
        "deepseek/deepseek-r1-distill-qwen-32b",
        "openrouter",
    ),
    ConfiguredModel(
        "rag-chat",
        "deepinfra_stream_chat_fallback_model",
        "deepseek-ai/DeepSeek-V4-Flash",
        "deepinfra",
    ),
    ConfiguredModel("rag-chat", "citation_judge_model", "deepseek-ai/DeepSeek-V4-Flash", "deepinfra"),
    ConfiguredModel("rag-chat", "reranker (Cohere adapter)", "rerank-english-v3.0", "cohere"),
    # ── S9 api-gateway ───────────────────────────────────────────────────────
    ConfiguredModel("api-gateway", "_NL_SCREENER_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct", "deepinfra"),
    # ── libs/ml-clients shared defaults ──────────────────────────────────────
    ConfiguredModel("ml-clients", "embedding_model_id", "bge-large-en-v1.5", "ollama"),
    ConfiguredModel("ml-clients", "extraction_model_id", "qwen2.5:7b-instruct", "ollama"),
    ConfiguredModel("ml-clients", "ner_model_path", "urchade/gliner_large-v2.1", "gliner"),
    ConfiguredModel("ml-clients", "router_embedding_model_id", "google/embeddinggemma-300m", "deepinfra"),
)


def unpriceable_models(
    models: Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Return the ``(model_id, provider)`` pairs that have NO cost path.

    A pair is *unpriceable* when :func:`ml_clients.pricing.is_priceable` returns
    False — i.e. it is not in the price matrix, not served by a provider-cost
    provider (DeepInfra), and not a known local/free model. Such a call would be
    logged at ``$0`` and trip the FR-7b silent-zero guard.

    Args:
        models: Iterable of ``(model_id, provider)`` pairs.

    Returns:
        The subset with no pricing path (empty list = all priceable).
    """
    return [(model_id, provider) for (model_id, provider) in models if not is_priceable(model_id, provider=provider)]


def registry_model_pairs() -> list[tuple[str, str]]:
    """Return every ``(model_id, provider)`` in :data:`PLATFORM_MODEL_REGISTRY`."""
    return [(m.model_id, m.provider) for m in PLATFORM_MODEL_REGISTRY]


def warn_unpriceable_models(
    service: str,
    models: Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Best-effort startup check: log a WARNING for each unpriceable configured model.

    Call this at service boot with the service's *actually-configured*
    ``(model_id, provider)`` pairs (read from live settings, so env overrides are
    covered). It NEVER raises — a guardrail must not take a service down — and
    returns the offending pairs for the caller/tests to assert on.

    Args:
        service: Emitting service name (for the log line + return context).
        models: Iterable of the service's configured ``(model_id, provider)`` pairs.

    Returns:
        The unpriceable pairs (empty = all configured models are priceable).
    """
    try:
        bad = unpriceable_models(models)
    except Exception as exc:  # — startup guard must never crash boot
        log.warning("priceability_startup_check_failed", service=service, error=str(exc))
        return []
    if bad:
        log.warning(
            "llm_models_unpriceable_at_startup",
            service=service,
            unpriceable=[f"{model_id} (via {provider})" for model_id, provider in bad],
            hint=(
                "add each to libs/ml-clients/pricing.MODEL_PRICING or "
                "LOCAL_FREE_MODELS — a call to it would log $0 (PLAN-0117 FR-7)"
            ),
        )
    return bad


__all__ = [
    "PLATFORM_MODEL_REGISTRY",
    "ConfiguredModel",
    "registry_model_pairs",
    "unpriceable_models",
    "warn_unpriceable_models",
]
