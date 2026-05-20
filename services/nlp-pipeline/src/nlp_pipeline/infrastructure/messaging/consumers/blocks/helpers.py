"""Shared normalization helpers used across multiple pipeline blocks.

These functions handle entity-surface-form normalization and lookup so that
LLM output (which may strip corporate suffixes or collapse whitespace) still
matches against the known-entity dict populated from NER mentions.

Kept in a dedicated module to avoid circular imports between the larger block
files that all depend on the same normalization logic.
"""

from __future__ import annotations

import re

# PLAN-0052 platform-QA fix (2026-05-01): symmetric normalization on the
# LLM-side ref. The lookup dict was widened with stripped suffixes /
# whitespace-collapsed variants of each mention, but the LLM may also
# output the OPPOSITE direction — e.g. mention is "NVIDIA Corp" (variant
# adds "nvidia") while LLM returns "NVIDIA Corporation". Without
# normalizing the LLM ref too, that miss persists. We try the raw ref
# first (cheapest), then fall back through the same variant list.
_BUILD_RAW_SUFFIX_RX = re.compile(
    r"\s+(inc|corp|corporation|ltd|llc|plc|co|holdings|group|ag|nv|sa|s\.a\.|s\.p\.a\.)\.?$",
    re.IGNORECASE,
)


def _normalize_ref_variants(text: str) -> list[str]:
    """Return all normalized lookup variants for a mention surface.

    Variants emitted (in priority order):
    1. Exact lowercase-stripped form.
    2. Whitespace-collapsed lowercase (multiple spaces → single).
    3. Corporate-suffix-stripped form (iterative, handles double suffixes).

    Used by both the lookup-population code (seeding ``entity_id_by_ref``) and
    the LLM-ref-resolution code so the normalization is perfectly symmetric.
    """
    out: list[str] = []
    lower = text.lower().strip()
    if not lower:
        return out
    out.append(lower)
    collapsed = " ".join(lower.split())
    if collapsed != lower:
        out.append(collapsed)
    # Iteratively strip corporate suffixes — guards against rare double-suffixes
    # like "Foo Holdings Inc" by stripping one suffix at a time until stable.
    stripped = _BUILD_RAW_SUFFIX_RX.sub("", collapsed).strip()
    while stripped and stripped != collapsed:
        if stripped not in out:
            out.append(stripped)
        collapsed = stripped
        stripped = _BUILD_RAW_SUFFIX_RX.sub("", collapsed).strip()
    return out


def _resolve_ref(
    raw_ref: str,
    entity_id_by_ref: dict[str, str],
) -> tuple[str | None, str | None]:
    """Return ``(entity_id, matched_key)`` for the first variant that hits.

    Walks the normalized variants of ``raw_ref`` in priority order and returns
    the first entry found in ``entity_id_by_ref``.  Returns ``(None, None)``
    when no variant matches (truly unknown entity surface).
    """
    for variant in _normalize_ref_variants(raw_ref):
        eid = entity_id_by_ref.get(variant)
        if eid is not None:
            return eid, variant
    return None, None
