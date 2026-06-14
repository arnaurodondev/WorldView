"""Block 10 — Deep LLM extraction (PRD §6.7 Block 10).

Applies to MEDIUM and DEEP routing tiers (not LIGHT, not SUPPRESS).
Uses Qwen2.5-7B-Instruct via ExtractionClient for structured extraction.

Output:
  - events, claims, relations (structured per PRD §6.7 Block 10 schema)
  - Emits nlp.signal.detected.v1 for high-confidence (≥0.80) resolved entities
  - Claims flow downstream via the enriched event's ``raw_claims`` array.
    PLAN-0057 D-1 (F-CRIT-08): the legacy ``claim.extracted`` outbox topic
    was an orphan — no consumer group ever subscribed (verified via
    ``kafka-consumer-groups --describe``). KG ingests claims via
    ``nlp.article.enriched.v1.raw_claims`` (see KG enriched_consumer).
    The ClaimsRepository + per-claim outbox write loop have been removed.
  - Relations with provisional entities → entity_provisional=true + provisional_queue_id

Window strategy (PRD §6.7 Block 10):
  ≤24,000 tokens → single window
  >24,000 tokens → 6,000-token windows with 500-token overlap
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog  # type: ignore[import-untyped]
from ml_clients.errors import RetryableError  # type: ignore[import-not-found]

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from nlp_pipeline.application.blocks.suppression import should_run_deep_extraction
from nlp_pipeline.domain.models import SignalEvent

if TYPE_CHECKING:
    from ml_clients.protocols import ExtractionClient  # type: ignore[import-not-found]
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]

    from nlp_pipeline.application.blocks.suppression import ProcessingPath
    from nlp_pipeline.domain.models import Chunk, EntityMention

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


def _record_window_timeout() -> None:
    """Increment the deep-extraction window-timeout Prometheus counter.

    Task #22 (BP-677): makes the per-window transient-failure (timeout) rate
    observable in Prometheus, not just logs. Uses a lazy import (matching the
    PrometheusNlpMetrics adapter style) so the application layer does not import
    the infrastructure metrics singleton at module load, and so pure-function
    callers/tests work even when prometheus_client is unavailable.
    """
    try:
        from nlp_pipeline.infrastructure.metrics.prometheus import deep_extraction_window_timeout_total

        deep_extraction_window_timeout_total.inc()
    except Exception:  # metrics must never break extraction
        logger.debug("deep_extraction.metric_inc_failed", metric="deep_extraction_window_timeout_total")


# ── Window configuration (PRD §6.7 Block 10) ─────────────────────────────────

SINGLE_WINDOW_TOKEN_LIMIT: int = 24_000
WINDOW_SIZE_TOKENS: int = 6_000
WINDOW_OVERLAP_TOKENS: int = 500

#: Minimum confidence for a signal to be emitted as nlp.signal.detected.v1
SIGNAL_CONFIDENCE_THRESHOLD: float = 0.80

# ── Extraction output schema (PRD §6.7 Block 10) ─────────────────────────────

_EXTRACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "enum": [
                            "EARNINGS_RELEASE",
                            "M_AND_A",
                            "REGULATORY_ACTION",
                            "MACRO",
                            "MANAGEMENT_CHANGE",
                            "PRODUCT_LAUNCH",
                            "CAPITAL_RAISE",
                            "LEGAL",
                            "ANALYST_RATING",
                            "GUIDANCE_RAISE",
                            "NATURAL_DISASTER",
                            "GEOPOLITICAL",
                            "SANCTIONS",
                            "OTHER",
                        ],
                    },
                    "description": {"type": "string"},
                    "entity_refs": {"type": "array", "items": {"type": "string"}},
                    "valid_from": {"type": ["string", "null"]},
                    "valid_to": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                },
                "required": ["event_type", "description", "confidence"],
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity_ref": {"type": "string"},
                    "claim_type": {"type": "string"},
                    "polarity": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence_text": {"type": "string"},
                },
                "required": ["entity_ref", "claim_type", "polarity", "confidence", "evidence_text"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject_ref": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object_ref": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence_text": {"type": "string"},
                    "entity_provisional": {"type": "boolean"},
                    "provisional_queue_id": {"type": ["string", "null"]},
                    # PLAN-0109 W5: optional per-fact end-of-validity date (ISO).
                    "valid_to": {"type": ["string", "null"]},
                },
                "required": ["subject_ref", "predicate", "object_ref", "confidence"],
            },
        },
    },
    "required": ["events", "claims", "relations"],
}

# ── Window splitting ──────────────────────────────────────────────────────────


def _build_windows(chunks: list[Chunk], max_tokens: int, overlap_tokens: int) -> list[str]:
    """Build text windows from chunks respecting token limits.

    Consecutive windows share ``overlap_tokens`` worth of trailing text.
    """
    if not chunks:
        return []

    full_text = " ".join(c.text for c in chunks)
    words = full_text.split()
    total_tokens = len(words)

    if total_tokens <= SINGLE_WINDOW_TOKEN_LIMIT:
        return [full_text]

    windows: list[str] = []
    start = 0
    while start < total_tokens:
        end = min(start + max_tokens, total_tokens)
        window_words = words[start:end]
        windows.append(" ".join(window_words))
        if end >= total_tokens:
            break
        start = end - overlap_tokens

    return windows


# ── Extraction helpers ────────────────────────────────────────────────────────


def _build_prompt(window_text: str, mention_names: list[str]) -> str:
    """Build the extraction prompt for Qwen2.5-7B-Instruct.

    Delegates to the centralised DEEP_EXTRACTION template in libs/prompts.
    """
    from prompts.extraction.deep import DEEP_EXTRACTION  # type: ignore[import-untyped]

    entities_str = ", ".join(mention_names) if mention_names else "none identified"
    return DEEP_EXTRACTION.render(entities=entities_str, text=window_text)  # type: ignore[no-any-return]


async def _run_extraction_window(
    window_text: str,
    mentions: list[EntityMention],
    extraction_client: ExtractionClient,
    model_id: str,
    *,
    doc_id: UUID | None = None,
    usage_logger: LlmUsageLogProtocol | None = None,
) -> ExtractionResult:
    """Run extraction on a single window, return parsed result dict.

    PLAN-0057 A-5 / F-CRIT-03: when ``usage_logger`` is provided, every call
    to ``extraction_client.extract()`` (success OR failure) appends one row
    to ``nlp_db.llm_usage_log``. Latency is captured around the LLM call
    only — not the JSON-parse path.
    """
    from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-not-found]

    # PLAN-0057 B-1: dedup mention_names while preserving order. The prompt
    # tells the LLM to pick entity_ref values from this list; duplicate
    # surfaces (same text appearing in multiple mention rows) waste prompt
    # tokens and don't add signal. ``dict.fromkeys`` preserves insertion order.
    #
    # PLAN-0052 platform-QA round 9 (2026-05-01): pass ALL mentions back to
    # the LLM (reverting round-8's resolved-only filter). Round 9 added
    # ``synthesize_provisional_refs`` in the article-consumer that creates
    # an inline ``provisional_entity_queue`` row for any LLM-referenced
    # UNRESOLVED mention BEFORE ``_build_raw_*`` runs. With that wired,
    # the consumer's ``entity_id_by_ref`` lookup gets a synthetic UUID for
    # every referenced surface, so filtering here is no longer necessary —
    # and is harmful, because a mining article is mostly UNRESOLVED entities
    # that should still surface as ``entity_provisional=True`` relations
    # with ``provisional_queue_id`` set. KG enriched_consumer already
    # promotes those to canonicals when the unresolved-resolution-worker
    # canonicalises the queue row.
    mention_names = list(dict.fromkeys(m.mention_text for m in mentions))
    prompt = _build_prompt(window_text, mention_names)

    inp = ExtractionInput(
        prompt=prompt,
        context=window_text,
        output_schema=_EXTRACTION_SCHEMA,
        model_id=model_id,
    )

    # PLAN-0057 A-5: capture latency for the LLM call. We log success based on
    # whether extract() returns without raising; the JSON-parse outcome is
    # independent (a model can return text that we fail to parse — that is
    # still a successful HTTP round-trip from the LLM provider's POV).
    t0 = time.perf_counter()
    output = None
    extract_succeeded = False
    try:
        output = await extraction_client.extract(inp)
        extract_succeeded = True
    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if usage_logger is not None:
            try:
                await usage_logger.log(
                    model_id=model_id,
                    # The deep-extraction provider is selected at consumer
                    # wiring time (DeepInfra when extraction_api_key set,
                    # Ollama otherwise). Without a hint on the client we tag
                    # generically; tokens_in/out are word-split estimates per
                    # protocol guidance.
                    provider=getattr(extraction_client, "provider", "unknown"),
                    capability="extraction",
                    tokens_in=len(prompt.split()) + len(window_text.split()),
                    tokens_out=len(str(getattr(output, "raw_response", "") or "").split()),
                    latency_ms=latency_ms,
                    estimated_cost_usd=0.0,
                    success=extract_succeeded,
                    error_code=None if extract_succeeded else "model_error",
                    doc_id=doc_id,
                )
            except Exception as exc:  # protocol forbids raising; belt-and-braces
                logger.warning(
                    "deep_extraction.usage_log_failed",
                    doc_id=str(doc_id) if doc_id is not None else None,
                    error=str(exc),
                    exc_info=True,
                )

    if output is None:
        return {"events": [], "claims": [], "relations": []}

    # Parse the structured result
    raw = output.result
    if isinstance(raw, dict):
        return raw

    # Fallback: parse from raw_response
    try:
        parsed = json.loads(output.raw_response)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        logger.warning("deep_extraction.json_parse_failed", raw_response=output.raw_response[:200])

    return {"events": [], "claims": [], "relations": []}


ExtractionResult = dict[str, Any]


def _merge_results_safe(windows_results: list[ExtractionResult]) -> ExtractionResult:
    """Merge extraction results from multiple windows."""
    events: list[Any] = []
    claims: list[Any] = []
    relations: list[Any] = []
    seen_events: set[str] = set()
    seen_claims: set[str] = set()
    seen_relations: set[str] = set()

    for result in windows_results:
        for event in result.get("events", []):
            event_d = dict(event)  # type: ignore[call-overload]
            key = f"{event_d.get('event_type')}:{str(event_d.get('description', ''))[:80]}"
            if key not in seen_events:
                seen_events.add(key)
                events.append(event)
        for claim in result.get("claims", []):
            claim_d = dict(claim)  # type: ignore[call-overload]
            key = f"{claim_d.get('entity_ref')}:{claim_d.get('claim_type')}:{claim_d.get('polarity')}"
            if key not in seen_claims:
                seen_claims.add(key)
                claims.append(claim)
        for relation in result.get("relations", []):
            relation_d = dict(relation)  # type: ignore[call-overload]
            key = f"{relation_d.get('subject_ref')}:{relation_d.get('predicate')}:{relation_d.get('object_ref')}"
            if key not in seen_relations:
                seen_relations.add(key)
                relations.append(relation)

    return {"events": events, "claims": claims, "relations": relations}


# ── Main block entry point ────────────────────────────────────────────────────


async def run_deep_extraction_block(
    doc_id: UUID,
    chunks: list[Chunk],
    mentions: list[EntityMention],
    processing_path: ProcessingPath,
    *,
    extraction_client: ExtractionClient,
    model_id: str,
    published_at: datetime | None,
    extracted_at: datetime,
    outbox_topic_signal: str,
    usage_logger: LlmUsageLogProtocol | None = None,
) -> tuple[ExtractionResult, list[SignalEvent]]:
    """Run Block 10: Deep LLM extraction for MEDIUM and DEEP tiers.

    For LIGHT/SUPPRESS tiers returns empty results immediately — callers
    must guard via ``should_run_deep_extraction(processing_path)``.

    PLAN-0057 D-1 (F-CRIT-08): the per-claim outbox write loop that produced
    to the orphan ``claim.extracted`` topic has been removed. Claims still
    leave this function via the returned ``extraction_result["claims"]``;
    the article consumer wraps them as ``raw_claims`` inside the
    ``nlp.article.enriched.v1`` payload, which KG's enriched_consumer reads.

    Args:
        doc_id: Document being processed.
        chunks: All chunks (used to build text windows).
        mentions: Resolved entity mentions for context injection.
        processing_path: Current routing path (HALT/SECTION_EMBEDDINGS_ONLY/FULL_PIPELINE).
        extraction_client: Injected ExtractionClient (OllamaExtractionAdapter).
        model_id: Extraction model ID (e.g. "qwen2.5:7b-instruct").
        published_at: Article publication datetime (UTC or None).
        extracted_at: Extraction datetime (UTC).
        outbox_topic_signal: Topic name for nlp.signal.detected.v1.

    Returns:
        (extraction_result, signal_events)
        - extraction_result: merged dict with events/claims/relations
        - signal_events: SignalEvent list for outbox dispatch
    """
    # Guard: non-FULL_PIPELINE tiers get empty result
    _empty: ExtractionResult = {"events": [], "claims": [], "relations": []}
    if not should_run_deep_extraction(processing_path):
        return _empty, []

    if not chunks:
        return _empty, []

    # PLAN-0057 D-1 (F-CRIT-08): the previous code path used
    # ``evidence_date = coalesce(published_at, extracted_at)`` to populate the
    # per-claim ``claim.extracted`` outbox payload. That topic had ZERO
    # subscribers (verified) so the value was dropped on the floor. Claims
    # downstream (KG enriched_consumer reading raw_claims) take their evidence
    # date from the article's published_at carried in the enriched envelope —
    # so we no longer compute it here.

    # Build text windows
    windows = _build_windows(chunks, max_tokens=WINDOW_SIZE_TOKENS, overlap_tokens=WINDOW_OVERLAP_TOKENS)

    # Run extraction per window.
    #
    # Task #22 (BP-677): we MUST distinguish a transient/timeout failure from a
    # genuinely empty extraction. The extraction adapter (DeepSeekExtractionAdapter
    # et al.) raises ``RetryableError`` for every transient condition — wall-clock
    # timeout, ``APITimeoutError``, ``APIConnectionError``, 429 rate-limit and 5xx
    # (see ml_clients/adapters/deepseek_extraction.py). The previous code caught
    # ``except Exception`` and substituted an empty result, so a timed-out window
    # merged to all-zero and was logged as a NORMAL ``deep_extraction.complete``.
    # Downstream could not tell "model found nothing" from "model timed out" — the
    # ~16% timeout rate was hidden as fake "0 events/0 claims/0 relations".
    #
    # New behaviour:
    #   * A RetryableError on a window is counted (``timed_out_windows``) and NOT
    #     silently treated as a successful empty result.
    #   * A genuine parse/empty result (the adapter returned, but with no content)
    #     is a *successful* window — it contributes a real (possibly empty) dict.
    #   * After the loop, retry semantics are decided (see below).
    window_results: list[ExtractionResult] = []
    timed_out_windows = 0
    total_windows = len(windows)
    for window_text in windows:
        try:
            result = await _run_extraction_window(
                window_text=window_text,
                mentions=mentions,
                extraction_client=extraction_client,
                model_id=model_id,
                doc_id=doc_id,
                usage_logger=usage_logger,
            )
            window_results.append(result)
        except RetryableError:
            # Transient/timeout failure — DO NOT substitute an empty result as if
            # the window succeeded. Track it so the completion event/return value
            # can flag the doc as degraded, and so a timed-out doc is retried
            # rather than persisted as a clean zero.
            timed_out_windows += 1
            _record_window_timeout()
            logger.warning(
                "deep_extraction.window_timeout",
                doc_id=str(doc_id),
                timed_out_windows=timed_out_windows,
                total_windows=total_windows,
                exc_info=True,
            )
        except Exception:
            # Non-retryable / unexpected failure for this window. This is NOT a
            # transient timeout (those are caught above), so we preserve the
            # historical behaviour of recording an empty window and continuing —
            # the doc is not flagged degraded for a non-transient parse-shaped
            # failure. (FatalError-class problems propagate from the adapter and
            # are not caught here.)
            logger.warning("deep_extraction.window_failed", doc_id=str(doc_id), exc_info=True)
            window_results.append({"events": [], "claims": [], "relations": []})

    degraded = timed_out_windows > 0

    # Retry semantics (Task #22):
    #   * If EVERY window timed out (no successful window produced a result), there
    #     is nothing real to persist — raising ``RetryableError`` makes the article
    #     consumer re-deliver / dead-letter the whole doc (its batch handler treats
    #     ConsumerError as retryable; see article_consumer._process_one). This is
    #     strictly better than committing an empty-but-fake extraction.
    #   * If SOME windows succeeded and some timed out (partial), we PERSIST the
    #     good windows but flag ``degraded=true`` + ``timed_out_windows`` so the
    #     loss is visible and the doc is re-queueable, rather than silently dropping
    #     the timed-out windows' content. We prefer keeping the good windows over
    #     re-running the whole doc (which would re-pay for the successful windows).
    if timed_out_windows > 0 and len(window_results) == 0:
        logger.warning(
            "deep_extraction.all_windows_timed_out",
            doc_id=str(doc_id),
            timed_out_windows=timed_out_windows,
            total_windows=total_windows,
        )
        raise RetryableError(
            f"deep extraction timed out on all {timed_out_windows}/{total_windows} " f"windows for doc {doc_id}",
        )

    # Merge deduplicated results
    merged = _merge_results_safe(window_results)
    # Surface degradation on the merged result so the caller (and any persistence
    # path) can carry it forward. Kept as plain dict keys to avoid changing the
    # ExtractionResult shape consumed by _merge_results_safe / downstream readers,
    # which only ever look up events/claims/relations.
    merged["degraded"] = degraded
    merged["timed_out_windows"] = timed_out_windows

    # Build entity_id lookup from resolved mentions
    entity_id_by_ref: dict[str, UUID] = {}
    for mention in mentions:
        if mention.resolved_entity_id is not None:
            entity_id_by_ref[mention.mention_text.lower()] = mention.resolved_entity_id

    # PLAN-0057 D-1 (F-CRIT-08): claims used to be enqueued to the orphan
    # ``claim.extracted`` outbox topic here. Removed — the topic had zero
    # subscribers and KG already consumes claims via the ``raw_claims`` array
    # built from ``merged["claims"]`` in the article consumer.

    # Build SignalEvent list for high-confidence signals
    now = common.time.utc_now()  # type: ignore[no-any-return]
    signal_events: list[SignalEvent] = []

    for event in merged.get("events", []):
        event_d = dict(event)  # type: ignore[call-overload]
        confidence = float(event_d.get("confidence", 0.0))
        if confidence < SIGNAL_CONFIDENCE_THRESHOLD:
            continue

        # Attach to first resolved entity referenced
        entity_refs = event_d.get("entity_refs", [])
        entity_id_for_signal: UUID | None = None
        for ref in entity_refs:  # type: ignore[union-attr]
            entity_id_for_signal = entity_id_by_ref.get(str(ref).lower())
            if entity_id_for_signal is not None:
                break

        if entity_id_for_signal is None:
            continue

        signal_events.append(
            SignalEvent(
                signal_id=common.ids.new_uuid7(),
                doc_id=doc_id,
                entity_id=entity_id_for_signal,
                signal_type=str(event_d.get("event_type", "")),
                confidence=confidence,
                evidence_text=str(event_d.get("description", "")),
                detected_at=now,
            ),
        )

    logger.info(
        "deep_extraction.complete",
        doc_id=str(doc_id),
        events=len(merged.get("events", [])),
        claims=len(merged.get("claims", [])),
        relations=len(merged.get("relations", [])),
        signals=len(signal_events),
        # Task #22 (BP-677): degraded=true means at least one window timed out and
        # its content was lost — an all-zero result here is NOT a truly empty
        # article. timed_out_windows quantifies the loss. A fully-successful doc
        # logs degraded=false, timed_out_windows=0 (unchanged from before).
        degraded=degraded,
        timed_out_windows=timed_out_windows,
    )

    return merged, signal_events
