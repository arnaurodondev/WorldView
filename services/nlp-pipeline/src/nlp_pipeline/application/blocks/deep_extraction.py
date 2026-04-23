"""Block 10 — Deep LLM extraction (PRD §6.7 Block 10).

Applies to MEDIUM and DEEP routing tiers (not LIGHT, not SUPPRESS).
Uses Qwen2.5-7B-Instruct via ExtractionClient for structured extraction.

Output:
  - events, claims, relations (structured per PRD §6.7 Block 10 schema)
  - Emits nlp.signal.detected.v1 for high-confidence (≥0.80) resolved entities
  - Claims written via nlp_db outbox (NEVER directly to intelligence_db)
  - Relations with provisional entities → entity_provisional=true + provisional_queue_id

Window strategy (PRD §6.7 Block 10):
  ≤24,000 tokens → single window
  >24,000 tokens → 6,000-token windows with 500-token overlap

evidence_date heuristic: coalesce(published_at, extracted_at) — NEVER use now().
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog  # type: ignore[import-untyped]

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from nlp_pipeline.application.blocks.suppression import should_run_deep_extraction
from nlp_pipeline.domain.models import SignalEvent

if TYPE_CHECKING:
    from ml_clients.protocols import ExtractionClient  # type: ignore[import-not-found]

    from nlp_pipeline.application.blocks.suppression import ProcessingPath
    from nlp_pipeline.domain.models import Chunk, EntityMention
    from nlp_pipeline.infrastructure.intelligence_db.repositories.claims import ClaimsRepository

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

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
                    "event_type": {"type": "string"},
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
                    "entity_provisional": {"type": "boolean"},
                    "provisional_queue_id": {"type": ["string", "null"]},
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
    """Build the extraction prompt for Qwen2.5-7B-Instruct."""
    entities_str = ", ".join(mention_names) if mention_names else "none identified"
    return (
        f"Extract structured financial intelligence from the following document passage.\n"
        f"Identified entities: {entities_str}\n\n"
        f"Document:\n{window_text}\n\n"
        f"Return JSON matching the schema with events, claims, and relations."
    )


async def _run_extraction_window(
    window_text: str,
    mentions: list[EntityMention],
    extraction_client: ExtractionClient,
    model_id: str,
) -> ExtractionResult:
    """Run extraction on a single window, return parsed result dict."""
    from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-not-found]

    mention_names = [m.mention_text for m in mentions]
    prompt = _build_prompt(window_text, mention_names)

    inp = ExtractionInput(
        prompt=prompt,
        context=window_text,
        output_schema=_EXTRACTION_SCHEMA,
        model_id=model_id,
    )

    output = await extraction_client.extract(inp)

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
    claims_repo: ClaimsRepository,
    model_id: str,
    published_at: datetime | None,
    extracted_at: datetime,
    outbox_topic_signal: str,
) -> tuple[ExtractionResult, list[SignalEvent]]:
    """Run Block 10: Deep LLM extraction for MEDIUM and DEEP tiers.

    For LIGHT/SUPPRESS tiers returns empty results immediately — callers
    must guard via ``should_run_deep_extraction(processing_path)``.

    evidence_date = coalesce(published_at, extracted_at) — NEVER uses now().

    Args:
        doc_id: Document being processed.
        chunks: All chunks (used to build text windows).
        mentions: Resolved entity mentions for context injection.
        processing_path: Current routing path (HALT/SECTION_EMBEDDINGS_ONLY/FULL_PIPELINE).
        extraction_client: Injected ExtractionClient (OllamaExtractionAdapter).
        claims_repo: Writes claims via nlp_db outbox.
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

    # evidence_date = coalesce(published_at, extracted_at) — NEVER now()
    evidence_date = published_at if published_at is not None else extracted_at

    # Build text windows
    windows = _build_windows(chunks, max_tokens=WINDOW_SIZE_TOKENS, overlap_tokens=WINDOW_OVERLAP_TOKENS)

    # Run extraction per window
    window_results: list[ExtractionResult] = []
    for window_text in windows:
        try:
            result = await _run_extraction_window(
                window_text=window_text,
                mentions=mentions,
                extraction_client=extraction_client,
                model_id=model_id,
            )
            window_results.append(result)
        except Exception:
            logger.warning("deep_extraction.window_failed", doc_id=str(doc_id))
            window_results.append({"events": [], "claims": [], "relations": []})

    # Merge deduplicated results
    merged = _merge_results_safe(window_results)

    # Build entity_id lookup from resolved mentions
    entity_id_by_ref: dict[str, UUID] = {}
    for mention in mentions:
        if mention.resolved_entity_id is not None:
            entity_id_by_ref[mention.mention_text.lower()] = mention.resolved_entity_id

    # Write claims via outbox (never directly to intelligence_db)
    for claim in merged.get("claims", []):
        claim_d = dict(claim)  # type: ignore[call-overload]
        entity_ref = str(claim_d.get("entity_ref", "")).lower()
        entity_id = entity_id_by_ref.get(entity_ref)
        if entity_id is None:
            continue  # skip unresolved claims

        try:
            await claims_repo.write_via_outbox(
                doc_id=doc_id,
                entity_id=entity_id,
                claim_type=str(claim_d.get("claim_type", "")),
                polarity=str(claim_d.get("polarity", "")),
                confidence=float(claim_d.get("confidence", 0.0)),
                evidence_text=str(claim_d.get("evidence_text", "")),
                evidence_date=evidence_date,
            )
        except Exception:
            logger.warning("deep_extraction.claim_write_failed", doc_id=str(doc_id))

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
    )

    return merged, signal_events
