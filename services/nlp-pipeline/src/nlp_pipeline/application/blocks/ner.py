"""Block 4 — GLiNER Entity Detection Per Section (PRD §6.7 Block 4).

11-class ontology with per-class thresholds, NMS deduplication, and an
explicit invariant: zero mentions NEVER suppresses a document.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import common.ids  # type: ignore[import-untyped]
from nlp_pipeline.domain.enums import MentionClass
from nlp_pipeline.domain.models import DocumentEntityStats, EntityMention, Section

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from ml_clients.protocols import NERClient  # type: ignore[import-not-found]


# ── NER class ontology ────────────────────────────────────────────────────────

#: All 11 class labels passed to GLiNER. Order determines priority in NMS.
NER_CLASS_LABELS: list[str] = [
    MentionClass.ORGANIZATION,
    MentionClass.GOVERNMENT_BODY,
    MentionClass.REGULATORY_BODY,
    MentionClass.FINANCIAL_INSTITUTION,
    MentionClass.PERSON,
    MentionClass.FINANCIAL_INSTRUMENT,
    MentionClass.LOCATION,
    MentionClass.COMMODITY,
    MentionClass.INDEX,
    MentionClass.CURRENCY,
    MentionClass.MACROECONOMIC_INDICATOR,
]

assert len(NER_CLASS_LABELS) == 11, "NER_CLASS_LABELS must have exactly 11 entries"

#: Routing-level threshold (lower, broader signal)
GLINER_THRESHOLD: float = 0.35

#: Resolution-cascade threshold (higher, precise)
GLINER_RESOLUTION_THRESHOLD: float = 0.45

#: Max section token length before truncation
SECTION_TOKEN_LIMIT: int = 450

#: Non-Maximum Suppression IoU threshold for overlapping spans
NMS_IOU_THRESHOLD: float = 0.5


# ── Helpers ───────────────────────────────────────────────────────────────────


def _iou(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    """Character-level Intersection over Union for two spans."""
    inter_start = max(a_start, b_start)
    inter_end = min(a_end, b_end)
    if inter_end <= inter_start:
        return 0.0
    intersection = inter_end - inter_start
    union = (a_end - a_start) + (b_end - b_start) - intersection
    if union == 0:
        return 0.0
    return intersection / union


def _nms(mentions: list[EntityMention]) -> list[EntityMention]:
    """Non-maximum suppression: remove overlapping spans (IoU > NMS_IOU_THRESHOLD).

    Keeps the higher-confidence span when two spans overlap.
    """
    # Sort by confidence descending
    sorted_mentions = sorted(mentions, key=lambda m: m.confidence, reverse=True)
    kept: list[EntityMention] = []
    for candidate in sorted_mentions:
        suppressed = False
        for kept_mention in kept:
            if (
                _iou(candidate.char_start, candidate.char_end, kept_mention.char_start, kept_mention.char_end)
                > NMS_IOU_THRESHOLD
            ):
                suppressed = True
                break
        if not suppressed:
            kept.append(candidate)
    return kept


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Approximate token truncation (space-based word count proxy).

    A proper tokenizer would be used in production; this approximation
    is sufficient for section-level NER batching.
    """
    words = text.split()
    if len(words) <= max_tokens:
        return text
    return " ".join(words[:max_tokens])


# ── Main block entry point ────────────────────────────────────────────────────


async def run_ner_block(
    doc_id: UUID,
    sections: Sequence[Section],
    ner_client: NERClient,
    threshold: float = GLINER_THRESHOLD,
    batch_size: int = 32,
) -> tuple[list[EntityMention], DocumentEntityStats]:
    """Run GLiNER NER on all sections of a document.

    Critical invariant (PRD §6.7 Block 4):
        Zero GLiNER mentions NEVER suppresses the document.
        Returns an empty list without raising — callers must handle this case.

    Args:
        doc_id: The document being processed.
        sections: All sections from Block 3.
        ner_client: Injected NERClient (GLiNERLocalAdapter).
        threshold: GLiNER confidence threshold for routing signal.
        batch_size: Sections per NER call (GLiNER batching).

    Returns:
        Tuple of (mentions, document_entity_stats).
    """
    from ml_clients.dataclasses import NERInput  # type: ignore[import-not-found]

    all_mentions: list[EntityMention] = []

    # Process sections in batches
    for i in range(0, len(sections), batch_size):
        batch = sections[i : i + batch_size]
        for section in batch:
            truncated_text = _truncate_to_tokens(section.text, SECTION_TOKEN_LIMIT)
            if not truncated_text.strip():
                continue

            inp = NERInput(
                text=truncated_text,
                entity_classes=NER_CLASS_LABELS,
                threshold=threshold,
            )
            # OOM retry: attempt once with reduced text on failure
            try:
                output = await ner_client.extract_entities(inp)
            except MemoryError:
                # One retry with halved token budget
                inp_reduced = NERInput(
                    text=_truncate_to_tokens(truncated_text, SECTION_TOKEN_LIMIT // 2),
                    entity_classes=NER_CLASS_LABELS,
                    threshold=threshold,
                )
                output = await ner_client.extract_entities(inp_reduced)

            section_mentions: list[EntityMention] = []
            for ml_mention in output.mentions:
                # Filter < 2 chars
                if len(ml_mention.text.strip()) < 2:
                    continue
                try:
                    mention_class = MentionClass(ml_mention.label)
                except ValueError:
                    continue  # unknown class — skip

                section_mentions.append(
                    EntityMention(
                        mention_id=common.ids.new_uuid7(),
                        doc_id=doc_id,
                        section_id=section.section_id,
                        mention_text=ml_mention.text.strip(),
                        mention_class=mention_class,
                        confidence=ml_mention.score,
                        char_start=ml_mention.start,
                        char_end=ml_mention.end,
                    ),
                )

            # NMS per section
            section_mentions = _nms(section_mentions)
            all_mentions.extend(section_mentions)

    # Compute document-level stats (PRD §6.7 Block 4)
    stats = _compute_stats(doc_id, all_mentions)
    return all_mentions, stats


def _compute_stats(doc_id: UUID, mentions: list[EntityMention]) -> DocumentEntityStats:
    """Compute document_entity_stats from all NER mentions (PRD §6.4.3)."""
    type_dist: dict[str, int] = {}
    high_conf_count = 0
    for m in mentions:
        label = str(m.mention_class)
        type_dist[label] = type_dist.get(label, 0) + 1
        if m.confidence >= 0.70:
            high_conf_count += 1

    return DocumentEntityStats(
        doc_id=doc_id,
        distinct_mention_count=len(mentions),
        high_conf_mention_count=high_conf_count,
        type_distribution=type_dist,
    )
