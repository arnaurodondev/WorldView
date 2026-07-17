"""Hybrid extraction-model routing (2026-07-17 DeepSeek recall regression).

Pure, side-effect-free selection of the deep-extraction model to use for a single
document, based on its ``source_type`` and word count.

Rationale (docs/audits/2026-07-17-deepseek-recall-validation.md): after the prod
flip of the primary extraction model to ``deepseek-ai/DeepSeek-V4-Flash``, SEC
filings began extracting ~0 knowledge-graph facts (0 vs Qwen3-235B's 118 grounded
facts on identical 10-K/10-Q inputs). DeepSeek is competent on short/medium news but
intrinsically under-extracts long, dense filing prose. This function routes filings
(and any large doc) to the HIGH-RECALL model while keeping the cheaper DeepSeek
primary for everything else.

The function is intentionally infrastructure-free (R25 / domain-independence): it
takes plain strings/ints and returns a small dataclass, so it can be unit-tested in
isolation and called from either the application or infrastructure layer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionRoute:
    """Result of a per-document extraction-model routing decision.

    Attributes:
        model_id: The model slug to use for this document's deep extraction.
        high_recall: True when the high-recall (filing) model was selected.
        reason: Why the route was chosen — one of ``"disabled"`` (routing off or no
            high-recall model configured), ``"source_type"`` (matched a filing
            source), ``"word_count"`` (met the large-doc threshold), or ``"default"``
            (short/medium doc → primary model). Used for structured logging.
    """

    model_id: str
    high_recall: bool
    reason: str


def parse_source_types(raw: str) -> frozenset[str]:
    """Parse a comma-separated ``source_type`` allow-list into a lowercased set.

    Blank/whitespace entries are dropped. Matching is case-insensitive, so the set
    is normalised to lowercase here and callers must lowercase the candidate.
    """
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def select_extraction_model(
    *,
    source_type: str | None,
    word_count: int,
    primary_model_id: str,
    high_recall_model_id: str,
    high_recall_source_types: frozenset[str],
    word_count_threshold: int,
    enabled: bool,
) -> ExtractionRoute:
    """Choose the deep-extraction model for one document.

    Routing priority (first match wins):
      1. Routing disabled OR no high-recall model configured → ``primary_model_id``.
      2. ``source_type`` in ``high_recall_source_types`` → ``high_recall_model_id``
         (filings ALWAYS use the recall model, regardless of length).
      3. ``word_count_threshold > 0`` and ``word_count >= word_count_threshold`` →
         ``high_recall_model_id`` (catches long non-filing docs, e.g. big articles).
      4. Otherwise → ``primary_model_id`` (short/medium docs keep the cheap model).

    Args:
        source_type: The document's source type (e.g. ``"sec_edgar"``, ``"eodhd"``);
            may be None/empty for legacy events.
        word_count: The document's word count (computed from downloaded text).
        primary_model_id: The default (short/medium) model slug — DeepSeek-V4-Flash.
        high_recall_model_id: The filing/long-doc model slug — Qwen3-235B. Empty
            string disables high-recall routing (treated like ``enabled=False``).
        high_recall_source_types: Lowercased source types that force the recall model.
        word_count_threshold: Word count (>=) that routes a non-filing doc to the
            recall model; ``0`` disables the word-count arm.
        enabled: Master switch — False falls back to the single primary model.

    Returns:
        An :class:`ExtractionRoute` describing the chosen model and why.
    """
    if not enabled or not high_recall_model_id:
        return ExtractionRoute(model_id=primary_model_id, high_recall=False, reason="disabled")

    st = (source_type or "").strip().lower()
    if st and st in high_recall_source_types:
        return ExtractionRoute(model_id=high_recall_model_id, high_recall=True, reason="source_type")

    if word_count_threshold > 0 and word_count >= word_count_threshold:
        return ExtractionRoute(model_id=high_recall_model_id, high_recall=True, reason="word_count")

    return ExtractionRoute(model_id=primary_model_id, high_recall=False, reason="default")
