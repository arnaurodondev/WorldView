"""Helpers for building and enqueuing the ``nlp.article.enriched.v1`` outbox event.

Contains:
- ``_enqueue_enriched``   — assembles and writes the main enriched-article event.
- ``_build_raw_relations`` — converts LLM relation dicts into S7-compatible format.
- ``_build_raw_events``    — converts LLM event dicts into S7-compatible format.
- ``_build_raw_claims``    — converts LLM claim dicts into S7-compatible format.

All ``_build_raw_*`` helpers share the same entity-ref resolution strategy:
resolved canonical IDs win over provisional IDs, and truly unknown surfaces are
dropped.  The PLAN-0057 B-1 (F-CRIT-07) fix ensures that provisional mentions
are also included so ~80% of extracted output is not silently dropped.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import common.time  # type: ignore[import-untyped]
from common.ids import uuid5_from_parts  # type: ignore[import-untyped]
from contracts.events.nlp.article_enriched import encode_raw_array  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import serialize_confluent_avro  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.messaging.consumers.blocks.helpers import (
    _BUILD_RAW_SUFFIX_RX,
    _resolve_ref,
)
from nlp_pipeline.infrastructure.metrics.prometheus import s6_extraction_entity_ref_hallucinated_total

if TYPE_CHECKING:
    from nlp_pipeline.domain.models import Chunk, EntityMention, RoutingDecision, Section
    from nlp_pipeline.infrastructure.nlp_db.repositories.outbox import OutboxRepository


async def _enqueue_enriched(
    *,
    outbox_repo: OutboxRepository,
    settings: Any,
    doc_id: uuid.UUID,
    source_type: str,
    # D-INIT-6: human-readable source label (RSS feed name, EODHD provider, etc.).
    # Travels in the enriched.v1 payload so KG can stamp evidence-row provenance
    # without a cross-service DB query (the previous fallback queried
    # document_source_metadata from intelligence_db — wrong DB, R7 violation).
    # Default None keeps existing unit tests that call _enqueue_enriched
    # directly working; the production caller in _run_pipeline always supplies
    # the value pulled off the inbound event.
    source_name: str | None = None,
    published_at: datetime | None,
    is_backfill: bool,
    routing_decision: RoutingDecision,
    sections: list[Section],
    chunks: list[Chunk],
    mentions: list[EntityMention],
    extraction_result: dict[str, Any],
    correlation_id: str | None,
    extraction_model_id: str | None = None,
    schema_dir: Any = None,
) -> None:
    """Assemble and write the ``nlp.article.enriched.v1`` outbox event.

    Builds the entity_id_by_ref lookup from BOTH resolved and provisional
    mentions (PLAN-0057 B-1 / F-CRIT-07), constructs raw_relations/events/claims
    dicts, and serializes the payload as Confluent Avro before writing to the
    outbox.

    PLAN-0084 B-3 (T-B-3-02): the outbox ``event_id`` is a deterministic UUID5
    from ``(doc_id, "article_enriched_v1")`` so replays produce the same PK and
    the INSERT ON CONFLICT DO NOTHING guard prevents duplicate outbox rows.
    """
    # Import schema path lazily — avoids import-time side effects in unit tests.
    if schema_dir is None:
        from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]

        schema_dir = find_schema_dir()

    effective_tier = routing_decision.final_routing_tier or routing_decision.routing_tier
    resolved_ids = [str(m.resolved_entity_id) for m in mentions if m.resolved_entity_id is not None]

    # PLAN-0057 B-1 (F-CRIT-07): the prior version of this lookup was built only
    # from RESOLVED mentions, but the deep-extraction prompt told the LLM to use
    # entity_refs drawn from the FULL mention list. The LLM correctly followed
    # the prompt and picked unresolved-but-mentioned surfaces; the
    # ``_build_raw_*`` helpers below silently dropped every relation/event/claim
    # whose ref didn't appear in this dict. Empirically that destroyed ~80% of
    # extracted output.
    #
    # The fix: include both RESOLVED mentions (real canonical UUID) AND
    # PROVISIONAL mentions that have a ``provisional_queue_id``. Track which keys
    # are provisional so we can tag downstream raw_* rows with
    # ``entity_provisional=True`` and ``provisional_queue_id=<queue UUID>``.
    entity_id_by_ref: dict[str, str] = {}
    provisional_refs: set[str] = set()

    # PLAN-0052 platform-QA fix (2026-05-01): seed the lookup with multiple
    # normalized variants of each mention surface so the LLM's slightly
    # different rendering still matches.
    def _ref_variants(text: str) -> list[str]:
        """Return all normalized lookup variants for a mention surface."""
        out: list[str] = []
        lower = text.lower().strip()
        out.append(lower)
        # whitespace-collapsed (multiple spaces → single)
        collapsed = " ".join(lower.split())
        if collapsed != lower:
            out.append(collapsed)
        # suffix-stripped (try until the regex no longer matches; defensive
        # against rare double-suffixes like "Foo Holdings Inc")
        stripped = _BUILD_RAW_SUFFIX_RX.sub("", collapsed).strip()
        while stripped != collapsed:
            if stripped and stripped not in out:
                out.append(stripped)
            collapsed = stripped
            stripped = _BUILD_RAW_SUFFIX_RX.sub("", collapsed).strip()
        return out

    for m in mentions:
        if m.resolved_entity_id is not None:
            value = str(m.resolved_entity_id)
            for variant in _ref_variants(m.mention_text):
                entity_id_by_ref.setdefault(variant, value)
        elif m.provisional_queue_id is not None:
            value = str(m.provisional_queue_id)
            for variant in _ref_variants(m.mention_text):
                if variant not in entity_id_by_ref:
                    entity_id_by_ref[variant] = value
                    provisional_refs.add(variant)
        # else: UNRESOLVED with no queue id — excluded from lookup

    # Hallucination detection: count entity_refs produced by the LLM that are NOT
    # in the known-entities lookup. A non-zero count indicates model drift.
    _all_llm_refs: set[str] = set()
    for _rel in extraction_result.get("relations", []):
        if isinstance(_rel, dict):
            _all_llm_refs.add(str(_rel.get("subject_ref", "")).lower().strip())
            _all_llm_refs.add(str(_rel.get("object_ref", "")).lower().strip())
    for _evt in extraction_result.get("events", []):
        if isinstance(_evt, dict):
            for _ref in _evt.get("entity_refs") or []:
                _all_llm_refs.add(str(_ref).lower().strip())
    for _clm in extraction_result.get("claims", []):
        if isinstance(_clm, dict):
            _all_llm_refs.add(str(_clm.get("entity_ref", "")).lower().strip())
    _all_llm_refs.discard("")
    _hallucinated = sum(1 for _r in _all_llm_refs if _r not in entity_id_by_ref)
    if _hallucinated > 0:
        s6_extraction_entity_ref_hallucinated_total.inc(_hallucinated)

    # SA-3 fix (2026-05-10): pass published_at so each relation row gets
    # evidence_date = published_at (or None → KG falls back to utc_now()).
    raw_relations = _build_raw_relations(
        extraction_result.get("relations", []),
        entity_id_by_ref,
        provisional_refs,
        published_at=published_at,
        # P0 chunk-provenance fix (2026-06-11): thread the persisted chunks so
        # each relation dict carries a REAL nlp_db chunk_id. KG's
        # relation_evidence_raw.chunk_id is NOT NULL (migration 0047) and the
        # writer guard rejects rows without it — omitting this key killed the
        # entire news-path evidence flow since 2026-05-23.
        chunks=chunks,
    )
    raw_events = _build_raw_events(extraction_result.get("events", []), entity_id_by_ref, provisional_refs)
    raw_claims = _build_raw_claims(extraction_result.get("claims", []), entity_id_by_ref, provisional_refs)

    # PLAN-0084 B-3 (T-B-3-02): deterministic event_id for the enriched event.
    enriched_event_id = uuid5_from_parts(str(doc_id), "article_enriched_v1")

    payload: dict[str, Any] = {
        "event_id": enriched_event_id,
        "event_type": "nlp.article.enriched",
        "schema_version": 1,
        "occurred_at": common.time.utc_now().isoformat(),
        "doc_id": str(doc_id),
        "source_type": source_type,
        # D-INIT-6: ride-along provenance label
        "source_name": source_name,
        "published_at": published_at.isoformat() if published_at else None,
        "is_backfill": is_backfill,
        "routing_tier": effective_tier.value,
        "routing_score": routing_decision.composite_score,
        "section_count": len(sections),
        "chunk_count": len(chunks),
        "mention_count": len(mentions),
        "resolved_entity_ids": resolved_ids,
        "relation_count": len(list(extraction_result.get("relations", []))),
        "claim_count": len(list(extraction_result.get("claims", []))),
        "event_count": len(list(extraction_result.get("events", []))),
        "raw_relations_json": encode_raw_array(raw_relations),
        "raw_events_json": encode_raw_array(raw_events),
        "raw_claims_json": encode_raw_array(raw_claims),
        "provisional_entity_count": sum(1 for m in mentions if m.resolved_entity_id is None),
        "extraction_model_id": extraction_model_id,
        "correlation_id": correlation_id,
    }
    schema_path = str(schema_dir / "nlp.article.enriched.v1.avsc")
    await outbox_repo.add(
        topic=settings.topic_article_enriched,
        partition_key=str(doc_id),
        payload_avro=serialize_confluent_avro(schema_path, payload),
        # Pass deterministic event_id so the outbox PK INSERT ON CONFLICT DO NOTHING
        # deduplicates replay deliveries at the outbox-table level as well.
        event_id=uuid.UUID(enriched_event_id),
    )


def _match_chunk_id(evidence_text: str | None, chunks: list[Chunk] | None) -> str | None:
    """Resolve the chunk that contains *evidence_text* (chunk provenance).

    P0 fix (2026-06-11): KG's ``relation_evidence_raw.chunk_id`` is NOT NULL
    (intelligence-migrations 0047, PLAN-0093 T-B-3-01) and references real
    ``nlp_db.chunks`` rows (no DB-level FK — cross-database — so THIS function
    is the app-level invariant). Strategy:

    1. Whitespace-normalized substring match of evidence_text inside each
       chunk's text (the LLM quotes evidence verbatim from the chunk window,
       but may collapse newlines/double spaces).
    2. Fallback: the FIRST chunk of the document — weaker provenance but still
       a real chunk row belonging to the same doc.
    3. ``None`` only when the document has no chunks at all (KG then mints its
       own fallback; see knowledge-graph graph_write.materialize_graph).
    """
    if not chunks:
        return None
    if evidence_text:
        needle = " ".join(evidence_text.split()).lower()
        if needle:
            for chunk in chunks:
                haystack = " ".join(chunk.text.split()).lower()
                if needle in haystack:
                    return str(chunk.chunk_id)
    # No substring hit — anchor to the document's first chunk (real row).
    return str(chunks[0].chunk_id)


def _build_raw_relations(
    relations: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_refs: set[str],
    *,
    published_at: datetime | None = None,
    chunks: list[Chunk] | None = None,
) -> list[dict[str, Any]]:
    """Convert LLM extraction relations into the dict format S7 expects.

    S7's ``_parse_raw_relations`` requires ``subject_entity_id``, ``object_entity_id``,
    and ``raw_type``. Skips relations where either entity ref cannot be resolved
    (truly unknown surface). When a ref points to a PROVISIONAL mention, sets
    ``entity_provisional=True`` and emits the corresponding queue id as
    ``provisional_queue_id`` so KG can promote the row once a canonical entity
    is later created (PLAN-0057 B-1, F-CRIT-07).

    SA-3 fix (2026-05-10): ``published_at`` is now included in each relation dict as
    ``evidence_date``.  KG's ``_parse_dt`` falls back to ``now()`` when the field is
    absent, which stamps all rows with today's date and breaks the confidence trend chart.
    """
    # ISO string once — all rows in this batch share the same article date
    evidence_date_iso: str | None = published_at.isoformat() if published_at else None

    result: list[dict[str, Any]] = []
    for rel in relations:
        rel_d: dict[str, Any] = dict(rel) if not isinstance(rel, dict) else rel  # type: ignore[call-overload]
        subject_ref = str(rel_d.get("subject_ref", ""))
        object_ref = str(rel_d.get("object_ref", ""))
        subject_id, subject_match = _resolve_ref(subject_ref, entity_id_by_ref)
        object_id, object_match = _resolve_ref(object_ref, entity_id_by_ref)
        if subject_id is None or object_id is None:
            continue  # skip truly unresolved — neither resolved nor provisional
        # Provisional flag uses the matched-key (post-normalization) so the
        # provisional_refs set lookup stays consistent with the lookup we
        # actually used.
        subject_is_provisional = subject_match in provisional_refs
        object_is_provisional = object_match in provisional_refs
        # Pick whichever endpoint is provisional as the queue_id reference.
        # If both endpoints are provisional we surface the SUBJECT queue id —
        # KG promotes by queue_id so either is fine; subject is the conventional
        # primary endpoint of a relation.
        provisional_qid: str | None = None
        if subject_is_provisional:
            provisional_qid = subject_id
        elif object_is_provisional:
            provisional_qid = object_id
        evidence_text = str(rel_d.get("evidence_text", "")) or None
        result.append(
            {
                "subject_entity_id": subject_id,
                "object_entity_id": object_id,
                "raw_type": str(rel_d.get("predicate", "")),
                "extraction_confidence": float(rel_d.get("confidence", 0.5)),
                "evidence_text": evidence_text,
                "entity_provisional": subject_is_provisional or object_is_provisional,
                "provisional_queue_id": provisional_qid,
                # SA-3 (2026-05-10): carry article publication date into each relation row.
                "evidence_date": evidence_date_iso,
                # P0 fix (2026-06-11): real chunk provenance. KG's evidence
                # writer requires a non-NULL chunk_id (migration 0047); this
                # key was previously never emitted, so the KG-side guard added
                # by PLAN-0093 T-B-3-01 rejected EVERY news-path evidence row.
                # claim_id is intentionally NOT emitted here: claims are not
                # persisted in nlp_db (legacy topic removed in PLAN-0057 D-1),
                # so KG mints the backing claims row itself (graph_write).
                "chunk_id": _match_chunk_id(evidence_text, chunks),
                # PLAN-0109 W5: optional per-fact end-of-validity date the LLM
                # extracted from the text (ISO string or None). Drives bitemporal
                # step-decay in the knowledge graph (relations.valid_to).
                "valid_to": rel_d.get("valid_to"),
            }
        )
    return result


def _build_raw_events(
    events: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_refs: set[str],
) -> list[dict[str, Any]]:
    """Convert LLM extraction events into the dict format S7 expects.

    S7's ``_parse_raw_events`` requires ``subject_entity_id`` and ``event_type``.
    Uses the first resolvable entity_ref as subject. Skips events with no
    resolvable entity. When the subject ref is PROVISIONAL, sets
    ``entity_provisional=True`` and ``provisional_queue_id`` per PLAN-0057 B-1.
    """
    result: list[dict[str, Any]] = []
    for evt in events:
        evt_d: dict[str, Any] = dict(evt) if not isinstance(evt, dict) else evt  # type: ignore[call-overload]
        # Find the first resolvable entity ref from the entity_refs list.
        # PLAN-0052 platform-QA fix: use _resolve_ref so suffix-stripped /
        # whitespace-collapsed LLM output still matches.
        entity_refs = evt_d.get("entity_refs", [])
        subject_id: str | None = None
        subject_ref_lower: str | None = None
        participant_ids: list[str] = []
        for ref in entity_refs:  # type: ignore[union-attr]
            eid, matched = _resolve_ref(str(ref), entity_id_by_ref)
            if eid is not None:
                if subject_id is None:
                    subject_id = eid
                    subject_ref_lower = matched
                participant_ids.append(eid)
        if subject_id is None:
            continue  # skip truly unresolved
        is_provisional = (subject_ref_lower or "") in provisional_refs
        result.append(
            {
                "subject_entity_id": subject_id,
                "event_type": str(evt_d.get("event_type", "")).upper(),
                "event_text": str(evt_d.get("description", "")),
                "extraction_confidence": float(evt_d.get("confidence", 0.5)),
                "participant_entity_ids": participant_ids,
                "entity_provisional": is_provisional,
                "provisional_queue_id": subject_id if is_provisional else None,
            }
        )
    return result


def _build_raw_claims(
    claims: list[Any],
    entity_id_by_ref: dict[str, str],
    provisional_refs: set[str],
) -> list[dict[str, Any]]:
    """Convert LLM extraction claims into the dict format S7 expects.

    S7's ``_parse_raw_claims`` requires ``subject_entity_id`` and ``claim_type``.
    Skips claims where the entity ref cannot be resolved. PLAN-0057 B-1: when
    the subject_ref is a PROVISIONAL surface, emit ``entity_provisional=True``
    and the queue UUID so KG can promote the claim once a canonical lands.
    """
    result: list[dict[str, Any]] = []
    for claim in claims:
        claim_d: dict[str, Any] = dict(claim) if not isinstance(claim, dict) else claim  # type: ignore[call-overload]
        # PLAN-0052 platform-QA fix: same suffix-stripping / whitespace-
        # collapsed lookup as the relations + events helpers above.
        entity_ref_raw = str(claim_d.get("entity_ref", ""))
        subject_id, matched_key = _resolve_ref(entity_ref_raw, entity_id_by_ref)
        if subject_id is None:
            continue  # skip truly unresolved
        is_provisional = (matched_key or "") in provisional_refs
        result.append(
            {
                "subject_entity_id": subject_id,
                "claim_type": str(claim_d.get("claim_type", "")),
                "polarity": str(claim_d.get("polarity", "neutral")),
                "claim_text": str(claim_d.get("evidence_text", "")),
                "extraction_confidence": float(claim_d.get("confidence", 0.5)),
                "entity_provisional": is_provisional,
                "provisional_queue_id": subject_id if is_provisional else None,
            }
        )
    return result
