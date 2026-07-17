"""Blocks 8-10: novelty gate, entity resolution, deep LLM extraction.

These three blocks run within the D-004 dual-session context (both ``nlp_session``
and ``intel_session`` must be open).  Extracted here so that the orchestrator
class remains a thin ≤300-line file.

Returns a ``MLPhaseResult`` dataclass carrying all outputs needed by the
subsequent persistence phase.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog  # type: ignore[import-untyped]

from nlp_pipeline.application.blocks.deep_extraction import run_deep_extraction_block
from nlp_pipeline.application.blocks.entity_resolution import run_entity_resolution_block
from nlp_pipeline.application.blocks.extraction_routing import (
    parse_source_types,
    select_extraction_model,
)
from nlp_pipeline.application.blocks.novelty import run_novelty_gate
from nlp_pipeline.application.blocks.routing import _AUTHORITATIVE_FILING_SOURCES
from nlp_pipeline.application.blocks.suppression import (
    ProcessingPath,
    apply_deep_extraction_value_gate,
    apply_suppression_gate,
    should_run_deep_extraction,
    should_run_entity_resolution,
)
from nlp_pipeline.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import (
    EntityAliasRepository,
)
from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_profile_embedding import (
    EntityProfileEmbeddingRepository,
)
from nlp_pipeline.infrastructure.messaging.consumers.blocks.provisional import (
    synthesize_provisional_refs,
)
from nlp_pipeline.infrastructure.metrics.adapter import PrometheusNlpMetrics
from nlp_pipeline.infrastructure.metrics.prometheus import (
    record_entity_resolved,
    s6_claims_extracted_total,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.mention_resolution import (
    MentionResolutionRepository,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ml_clients.protocols import EmbeddingClient, ExtractionClient  # type: ignore[import-not-found]
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.application.ports.canonical_entity import CanonicalEntityPort
    from nlp_pipeline.config import Settings
    from nlp_pipeline.domain.models import Chunk, EntityMention, RoutingDecision


# Concrete metrics adapter injected into the deep-extraction block (R25): the
# application block records the window-timeout counter via this port instead of
# importing the Prometheus singleton itself.
_NLP_METRICS = PrometheusNlpMetrics()

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


@dataclass
class MLPhaseResult:
    """Outputs from Blocks 8-10 needed by the artifact-persistence phase."""

    routing_decision: RoutingDecision
    final_path: ProcessingPath
    final_mentions: list[EntityMention]
    pending_resolution_audit: list[Any]
    extraction_result: dict[str, Any]
    signals: list[Any] = field(default_factory=list)
    # Hybrid-routing provenance (2026-07-17): the model slug that ACTUALLY ran deep
    # extraction for this doc (DeepSeek-V4-Flash for short/medium, Qwen3-235B for
    # filings/long docs), or None when deep extraction did not run (HALT/SUPPRESS).
    # The article consumer stamps this onto ``nlp.article.enriched.v1`` so KG
    # provenance reflects the real extractor — replacing the stale hardcoded
    # ``settings.extraction_model_id`` (``qwen2.5:7b-instruct`` legacy default) that
    # mis-attributed every claim regardless of the true model.
    extraction_model_id: str | None = None


async def run_ml_phase(
    *,
    nlp_session: AsyncSession,
    intel_session: AsyncSession,
    doc_id: uuid.UUID,
    chunks: list[Chunk],
    mentions: list[EntityMention],
    routing_decision: RoutingDecision,
    initial_path: ProcessingPath,
    source_type: str | None,
    # VALUE-signal override (2026-07-18): precomputed by the article consumer from the
    # title + lede (cheap deterministic event-type match, NO extra LLM call). Threaded
    # in — rather than recomputed here — so both gate call sites use the SAME decision.
    high_value_event: bool = False,
    published_at: datetime | None,
    extracted_at: datetime,
    settings: Settings,
    emb: EmbeddingClient,
    ext: ExtractionClient,
    watchlist_client: Any,
    # Hybrid extraction-model routing (2026-07-17). ``source_type`` (already a required
    # kwarg above, shared with the VALUE-signal gate) + ``word_count`` feed the per-doc
    # router (see application/blocks/extraction_routing.py). ``ext`` is the primary
    # (DeepSeek) client; ``ext_high_recall`` is the optional Qwen3-235B client used for
    # SEC/long-filing docs. ``ext_model_id`` is the primary's REAL DeepInfra/Ollama slug
    # (used for provenance + as the router's primary model). These default to the
    # pre-hybrid behaviour: no high-recall client, so the single primary model runs on
    # every doc (existing unit tests unchanged).
    word_count: int = 0,
    ext_model_id: str | None = None,
    ext_high_recall: ExtractionClient | None = None,
    usage_logger: LlmUsageLogProtocol | None = None,
    # ENHANCEMENT #6: optional co-mention entailment check (cheap Qwen3-235B client +
    # config). Both default None → the check is a no-op (the prior behaviour). Forwarded
    # verbatim to run_deep_extraction_block, which gates on entailment_config.enabled.
    entailment_client: ExtractionClient | None = None,
    entailment_config: Any = None,
    # 2026-07-16 fabrication filter: deterministic evidence-span grounding gate config.
    # Forwarded verbatim to run_deep_extraction_block; None → block applies its own
    # default (present_only), so the gate is active unless explicitly turned off.
    evidence_grounding_config: Any = None,
    # 2026-07-16 claim entailment pass: cheap verifier client + config. Both default None
    # → the pass is a no-op (the prior behaviour). Forwarded verbatim to
    # run_deep_extraction_block, which gates on claim_entailment_config.enabled.
    claim_entailment_client: ExtractionClient | None = None,
    claim_entailment_config: Any = None,
    # Injected callable for Block 10 — defaults to the real implementation.
    # article_consumer._run_pipeline passes ``run_deep_extraction_block`` from
    # the article_consumer namespace so unit tests can patch it there.
    _deep_extraction_fn: Any = None,
    # P0-A liveness heartbeat (prod review 2026-07-15): the article consumer's
    # ``_record_progress`` bound method, threaded down into Block 10 so each
    # completed extraction WINDOW refreshes the Kafka liveness gauge. Keeps a
    # slow-but-progressing article's ``/healthz`` alive during a long in-flight
    # handler while a truly hung call still goes stale. None (default) = no
    # heartbeat (the pre-fix behaviour; safe for unit tests that omit it).
    on_window_done: Any = None,
    # Injected repo instances — constructed in article_consumer._run_pipeline
    # so unit tests can patch them at the article_consumer module namespace.
    _alias_repo: Any = None,
    _profile_emb_repo: Any = None,
    _canonical_repo: Any = None,
    _mention_resolution_repo: Any = None,
) -> MLPhaseResult:
    """Execute Blocks 8-10 within the caller's open nlp/intel sessions.

    Block 8: Novelty gate — may downgrade the routing tier.
    Block 9: Entity resolution — resolves surface forms to canonical entity IDs.
    Block 10: Deep LLM extraction — extracts relations/events/claims.

    Returns an ``MLPhaseResult`` with all outputs needed for DB persistence.
    """

    # ── Block 8: Novelty gate ─────────────────────────────────────────────────
    final_path = initial_path
    if initial_path != ProcessingPath.HALT:
        _pemb8 = _profile_emb_repo if _profile_emb_repo is not None else EntityProfileEmbeddingRepository(intel_session)
        routing_decision, _ = await run_novelty_gate(
            doc_id=doc_id,
            routing_decision=routing_decision,
            valkey_client=watchlist_client,
            entity_profile_embedding_repo=_pemb8,
            resolved_entity_ids=[],
            entity_embeddings={},
            minhash_threshold=settings.novelty_minhash_threshold,
            embedding_threshold=settings.novelty_embedding_threshold,
        )
        final_path = apply_suppression_gate(routing_decision)
        # Backlog-drain lever (docs/audits/2026-07-17-article-backlog-lever.md):
        # re-apply the low-value gate AFTER the novelty gate so this is the
        # authoritative decision for entity resolution + deep extraction below.
        # (apply_suppression_gate re-derives FULL_PIPELINE from the MEDIUM/DEEP tier,
        # so any downgrade the article-consumer applied to ``initial_path`` must be
        # recomputed here from the same routing score + source_type.)
        final_path = apply_deep_extraction_value_gate(
            final_path,
            routing_decision,
            source_type,
            enabled=settings.deep_extraction_value_gate_enabled,
            score_floor=settings.deep_extraction_score_floor,
            filing_sources=_AUTHORITATIVE_FILING_SOURCES,
            high_value_event=high_value_event,
        )

    extraction_result: dict[str, Any] = {"events": [], "claims": [], "relations": []}
    final_mentions = list(mentions)
    pending_resolution_audit: list[Any] = []

    # ── Block 9: Entity resolution ────────────────────────────────────────────
    if should_run_entity_resolution(final_path):
        _canon: CanonicalEntityPort = (
            _canonical_repo if _canonical_repo is not None else CanonicalEntityRepository(intel_session)
        )
        _alias = _alias_repo if _alias_repo is not None else EntityAliasRepository(intel_session)
        _pemb = _profile_emb_repo if _profile_emb_repo is not None else EntityProfileEmbeddingRepository(intel_session)
        _mrr = (
            _mention_resolution_repo
            if _mention_resolution_repo is not None
            else MentionResolutionRepository(nlp_session)
        )
        resolved_mentions, resolution_audit = await run_entity_resolution_block(
            mentions=mentions,
            alias_repo=_alias,
            embedding_repo=_pemb,
            canonical_entity_repo=_canon,
            resolution_audit_repo=_mrr,
            embedding_client=emb,
            intelligence_session=intel_session,
            model_id=settings.embedding_model_id,
            instruction_prefix=settings.embedding_instruction_prefix,
            auto_resolve_threshold=settings.entity_resolution_auto_resolve_threshold,
            provisional_threshold=settings.entity_resolution_provisional_threshold,
        )
        final_mentions = resolved_mentions
        _stage_map = {1: "exact", 2: "ticker", 3: "fuzzy", 4: "ann"}
        for res in resolution_audit:
            if res.is_winner:
                record_entity_resolved(_stage_map.get(res.stage, "unknown"))
        pending_resolution_audit = resolution_audit

    # ── Block 10: Deep LLM extraction ─────────────────────────────────────────
    signals: list[Any] = []
    extraction_model_id: str | None = None
    _extract_fn = _deep_extraction_fn if _deep_extraction_fn is not None else run_deep_extraction_block
    if should_run_deep_extraction(final_path):
        # Hybrid extraction-model routing (2026-07-17 DeepSeek recall regression).
        # Pick the model for THIS doc: SEC filings / long docs → high-recall Qwen3-235B
        # (grounded filing facts DeepSeek drops as []); short/medium → cheaper DeepSeek
        # primary. The DeepInfra adapter binds its model at construction (it ignores
        # ExtractionInput.model_id), so routing selects the matching CLIENT, not just a
        # slug. When the high-recall client is unavailable (routing disabled, no API
        # key → Ollama path, or misconfig) we fall back to the primary and stamp the
        # primary's slug — never silently mis-route.
        _primary_model_id = ext_model_id or settings.extraction_api_model_id
        route = select_extraction_model(
            source_type=source_type,
            word_count=word_count,
            primary_model_id=_primary_model_id,
            high_recall_model_id=settings.extraction_high_recall_model_id,
            high_recall_source_types=parse_source_types(settings.extraction_high_recall_source_types),
            word_count_threshold=settings.extraction_high_recall_word_count_threshold,
            enabled=settings.hybrid_extraction_routing_enabled,
        )
        if route.high_recall and ext_high_recall is not None:
            _ext_client: ExtractionClient = ext_high_recall
            extraction_model_id = route.model_id
        else:
            _ext_client = ext
            # High-recall was chosen but no dedicated client is wired → run on the
            # primary and record the primary's slug so provenance stays truthful.
            extraction_model_id = _primary_model_id if route.high_recall else route.model_id
        # BP-719 Mode B word cap is a RECALL TAX on the high-recall filing path
        # (grounded facts live in later windows — see the audit §4), so disable it
        # whenever the recall model actually serves this doc. Short/medium docs keep
        # the configured cap (0 in prod anyway).
        _use_high_recall = route.high_recall and ext_high_recall is not None
        _max_words = 0 if _use_high_recall else getattr(settings, "deep_extraction_max_words", 0)
        logger.info(
            "deep_extraction.model_routed",
            doc_id=str(doc_id),
            source_type=source_type,
            word_count=word_count,
            route_reason=route.reason,
            high_recall=_use_high_recall,
            model_id=extraction_model_id,
        )
        extraction_result, signals = await _extract_fn(
            doc_id=doc_id,
            chunks=chunks,
            mentions=final_mentions,
            processing_path=final_path,
            extraction_client=_ext_client,
            # Provenance fix (2026-07-17): pass the ACTUAL routed slug (DeepSeek or
            # Qwen), not the stale ``settings.extraction_model_id`` legacy Ollama tag,
            # so usage-log rows + downstream stamps carry the real model.
            model_id=extraction_model_id,
            published_at=published_at,
            extracted_at=extracted_at,
            outbox_topic_signal=settings.topic_signal_detected,
            usage_logger=usage_logger,
            # Fabrication guards run INSIDE run_deep_extraction_block for BOTH models
            # (deterministic relation gate always; the optional co-mention entailment
            # check when wired) — the block is model-agnostic, so nothing bypasses the
            # guards on the Qwen path. The entailment client/config are forwarded
            # unchanged for both routes.
            entailment_client=entailment_client,
            entailment_config=entailment_config,
            evidence_grounding_config=evidence_grounding_config,
            claim_entailment_client=claim_entailment_client,
            claim_entailment_config=claim_entailment_config,
            metrics=_NLP_METRICS,
            max_words=_max_words,
            # P0-A: per-article window budget + per-window liveness heartbeat.
            max_windows=getattr(settings, "extraction_max_windows_per_doc", 0),
            on_window_done=on_window_done,
        )
        s6_claims_extracted_total.inc(len(list(extraction_result.get("claims", []))))
        await synthesize_provisional_refs(
            mentions=final_mentions,
            extraction_result=extraction_result,
            intelligence_session=intel_session,
        )

    return MLPhaseResult(
        routing_decision=routing_decision,
        final_path=final_path,
        final_mentions=final_mentions,
        pending_resolution_audit=pending_resolution_audit,
        extraction_result=extraction_result,
        signals=signals,
        extraction_model_id=extraction_model_id,
    )
