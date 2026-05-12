"""Synthetic-provisional-on-demand helpers (PLAN-0052 platform-QA round 9).

When Block 10 deep extraction references UNRESOLVED mentions (mining companies,
geo locations, novel orgs not yet canonicalised), the downstream
``_build_raw_*`` helpers would silently drop every relation/event/claim
referencing them.

``synthesize_provisional_refs`` scans the LLM output, finds matching UNRESOLVED
mentions, and inserts a ``provisional_entity_queue`` row inline
(SAVEPOINT-guarded, churn-guard applied).  The stashed ``provisional_queue_id``
on the mention is then picked up by ``_build_raw_*`` which emits rows with
``entity_provisional=True``.  KG's ``enriched_consumer`` accepts and persists
these; the ``UnresolvedResolutionWorker`` later canonicalises the queue entry,
at which point KG promotes the relation evidence to a real ``relation_id``.
"""

from __future__ import annotations

import uuid
from typing import Any

from nlp_pipeline.infrastructure.messaging.consumers.blocks.helpers import _normalize_ref_variants
from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _collect_extraction_refs(extraction_result: dict[str, Any]) -> set[str]:
    """Return the set of normalized entity surface forms the LLM referenced.

    Walks the extraction result and yields every ``subject_ref``/``object_ref``
    on relations, every ``entity_refs`` element on events, and every
    ``entity_ref`` on claims. Each is normalized through ``_normalize_ref_variants``
    and the union of all variants is returned. The article-consumer uses this
    to find UNRESOLVED mentions that the LLM has actually used; those are
    promoted to PROVISIONAL inline so ``_build_raw_*`` can address them.
    """
    refs: set[str] = set()

    def _ingest(raw: object) -> None:
        if not isinstance(raw, str):
            return
        for variant in _normalize_ref_variants(raw):
            refs.add(variant)

    for rel in extraction_result.get("relations", []):
        if isinstance(rel, dict):
            _ingest(rel.get("subject_ref"))
            _ingest(rel.get("object_ref"))

    for evt in extraction_result.get("events", []):
        if isinstance(evt, dict):
            ents = evt.get("entity_refs")
            if isinstance(ents, list):
                for e in ents:
                    _ingest(e)

    for clm in extraction_result.get("claims", []):
        if isinstance(clm, dict):
            _ingest(clm.get("entity_ref"))

    return refs


async def synthesize_provisional_refs(
    *,
    mentions: list[Any],
    extraction_result: dict[str, Any],
    intelligence_session: object,
) -> int:
    """Promote LLM-referenced UNRESOLVED mentions to PROVISIONAL inline.

    Called after Block 10 deep extraction completes and BEFORE
    ``_enqueue_enriched`` builds the Kafka payload. For every entity surface
    the LLM referenced (via ``relations.subject_ref`` / ``relations.object_ref``
    / ``events.entity_refs`` / ``claims.entity_ref``), find the matching
    UNRESOLVED mention in the local ``mentions`` list. If found and not
    already queued, call ``ensure_provisional_for_mention`` which inserts a
    ``provisional_entity_queue`` row inline (SAVEPOINT-guarded, churn-guard
    applied) and stashes the queue_id on the mention.

    The downstream ``_build_raw_relations`` / ``_build_raw_events`` /
    ``_build_raw_claims`` then see the new ``provisional_queue_id`` and emit
    rows with ``entity_provisional=True`` and ``provisional_queue_id=<uuid>``.
    KG ``enriched_consumer`` already accepts and persists these.

    Returns the number of mentions promoted (for observability).
    """
    if not extraction_result:
        return 0

    # Lazy-import the helper so the consumer module's import-time graph stays
    # compatible with unit tests that mock entity_resolution at the module level.
    from nlp_pipeline.application.blocks.entity_resolution import ensure_provisional_for_mention

    referenced = _collect_extraction_refs(extraction_result)
    if not referenced:
        return 0

    # Build a quick lookup of UNRESOLVED mentions by their normalised variants
    # so a single LLM ref can match against any surface form.
    candidate_index: dict[str, Any] = {}
    for m in mentions:
        if m.resolved_entity_id is not None or m.provisional_queue_id is not None:
            continue
        for variant in _normalize_ref_variants(m.mention_text):
            candidate_index.setdefault(variant, m)

    promoted = 0
    seen_mentions: set[uuid.UUID] = set()
    for ref in referenced:
        m = candidate_index.get(ref)
        if m is None:
            continue
        if m.mention_id in seen_mentions:
            continue
        seen_mentions.add(m.mention_id)
        queue_id = await ensure_provisional_for_mention(m, intelligence_session)
        if queue_id is not None:
            promoted += 1

    if promoted:
        logger.info(  # type: ignore[no-any-return]
            "synthesize_provisional_refs.complete",
            promoted=promoted,
            referenced=len(referenced),
        )
    return promoted
