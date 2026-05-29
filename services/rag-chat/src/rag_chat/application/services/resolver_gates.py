"""Shared resolver-gate logic — F-LIVE-NEW-003 symmetric guard.

Background
----------
Two resolver paths exist in rag-chat:

* **IntelligenceHandler** (tool path): calls S7 alias-search per tool
  argument (e.g. ``search_claims(entity_name="Tesla")``). Already gated
  inline by stop-word strip + 0.75 absolute similarity floor + 0.15
  delta gate + tiebreaker rules.

* **ChatOrchestrator** (pre-prompt path): calls S6 ``/entities/resolve``
  on the user's raw query text once per turn, then surfaces the
  resolved entities directly in the LLM system prompt under
  ``Entities resolved from this query:``. **Until F-LIVE-NEW-003 this
  path bypassed all gates** — generic stop-word substrings (``space``,
  ``delta``, ``shell``, ``block``, ``square``) leaked through and
  bound to real public companies (SpaceX, Delta Air Lines, Shell plc,
  Block Inc., Square Inc.) at sim ~0.62. The LLM then hallucinated
  claims about those companies even when retrieval returned zero
  matching documents.

This module factors the *shared* gate primitives so both paths apply
identical stop-word + similarity-floor logic. The IntelligenceHandler
keeps its richer tiebreaker rules (rule 1 same-canonical collapse,
rule 2 exact-canonical match, rule 3 length-penalty) because they
require S7's ``alias_text`` field which S6's resolver does not return.

Behaviour contract — primary tests live in:
* ``tests/unit/application/pipeline/test_intelligence_name_resolution.py``
  (IntelligenceHandler path; must remain green after the refactor)
* ``tests/contract/test_resolver_gate_symmetry.py``
  (orchestrator path; new in F-LIVE-NEW-003)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ResolverGateConfig:
    """Immutable tuning surface for ``filter_resolver_candidates``.

    Identical defaults to ``rag_chat.config.Settings``:
      * ``top_similarity_min`` = 0.75
      * ``delta_min``          = 0.15

    Tests inject custom values directly; production wiring builds this
    from ``Settings`` once at startup and passes a single instance to
    every gate call.
    """

    stop_words: frozenset[str]
    top_similarity_min: float = 0.75
    delta_min: float = 0.15


class _GatedCandidate(Protocol):
    """Structural protocol — the minimal candidate shape the gate needs.

    Both ``rag_chat.domain.entities.chat.ResolvedEntity`` (orchestrator
    path, uses ``.confidence``) and the raw S7 dict candidates
    (IntelligenceHandler path, uses ``["similarity"]``) are adapted to
    this shape via :class:`GatedEntity` below.
    """

    entity_id: str
    canonical_name: str
    similarity: float


@dataclass(frozen=True)
class GatedEntity:
    """Path-agnostic candidate carrying the fields the gate inspects.

    The IntelligenceHandler path may later switch to this dataclass
    once its tiebreaker logic is moved here; today only the orchestrator
    path constructs ``GatedEntity`` values from ``ResolvedEntity`` rows.
    """

    entity_id: str
    canonical_name: str
    similarity: float
    # Carried opaquely so the caller can re-emit the original object
    # (e.g. ``ResolvedEntity``) instead of re-constructing it. Avoids
    # leaking the ResolvedEntity type into this domain-free module.
    payload: object | None = None
    # Set by ``filter_resolver_candidates`` on REJECTED entries so the
    # caller can label Prometheus counters with a stable reason. Always
    # ``""`` on accepted entries.
    rejection_reason: str = ""


# Rejection reason labels — keep in sync with the Prometheus
# ``entity_resolver_ambiguous_total{reason}`` label set.
REASON_STOP_WORD_STRIP = "stop_word_strip"
REASON_LOW_TOP_SIMILARITY = "low_top_similarity"
REASON_DELTA_BELOW_THRESHOLD = "delta_below_threshold"


def strip_stop_words(query: str, stop_words: frozenset[str]) -> str:
    """Return ``query`` with all-stop-word tokens removed (lowercased).

    Mirrors ``IntelligenceHandler._strip_stop_words`` byte-for-byte so
    the two paths agree on what counts as "no entity-shaped signal".

    Tokenises on whitespace and strips a small set of trailing
    punctuation so ``"AI semiconductor space."`` also matches.
    Returns the empty string when EVERY token is a stop word — the
    caller treats that as a resolver refusal.
    """
    if not query:
        return ""
    tokens = query.lower().split()
    kept = [t for t in tokens if t.strip(".,!?:;'\"()[]") not in stop_words]
    return " ".join(kept)


def filter_resolver_candidates(
    candidates: list[GatedEntity],
    *,
    config: ResolverGateConfig,
) -> tuple[list[GatedEntity], list[GatedEntity]]:
    """Apply 0.75 absolute floor + 0.15 delta gate.

    Returns ``(accepted, rejected)``. Every rejected entry carries a
    ``rejection_reason`` label so callers can emit per-cause metrics.

    Semantics
    ---------
    * **stop_word_strip** — set by the *caller* before invoking this
      function (the strip happens on the query text, not on
      candidates). Wired here as a symbolic constant so callers stay
      consistent.

    * **low_top_similarity** — candidate's ``similarity`` is strictly
      below ``config.top_similarity_min``. Applied per-candidate, not
      just to the top-1 row, because the orchestrator path emits ALL
      resolved entities to the prompt (not a single winner).

    * **delta_below_threshold** — when 2+ candidates pass the floor
      and the top-1/top-2 gap is below ``config.delta_min`` the
      whole result set is ambiguous; we reject everything. Matches
      the IntelligenceHandler bail-on-ambiguity behaviour and avoids
      surfacing two near-equal-similarity candidates as if they were
      both confident matches.
    """
    if not candidates:
        return [], []

    accepted: list[GatedEntity] = []
    rejected: list[GatedEntity] = []

    # ── Floor pass: drop any candidate below the absolute threshold ──
    for c in candidates:
        if c.similarity < config.top_similarity_min:
            rejected.append(
                # Re-emit with the rejection reason populated. Frozen
                # dataclass → replace via dataclasses.replace would
                # require importing dataclasses; cheaper to build new.
                GatedEntity(
                    entity_id=c.entity_id,
                    canonical_name=c.canonical_name,
                    similarity=c.similarity,
                    payload=c.payload,
                    rejection_reason=REASON_LOW_TOP_SIMILARITY,
                )
            )
        else:
            accepted.append(c)

    # ── Delta pass: top-1 vs top-2 gap on the survivors ─────────────
    # Only fires when at least two candidates survived the floor —
    # otherwise the gate is trivially unambiguous.
    if len(accepted) >= 2:
        # Survivors are not necessarily ordered; sort DESC by similarity
        # to inspect the real top-1/top-2.
        accepted_sorted = sorted(accepted, key=lambda x: x.similarity, reverse=True)
        top, second = accepted_sorted[0], accepted_sorted[1]
        if (top.similarity - second.similarity) < config.delta_min:
            # Ambiguous — reject EVERY survivor with delta reason. The
            # orchestrator path treats this as "no confident entity"
            # and proceeds without an entity map (the symmetric
            # behaviour to IntelligenceHandler returning None).
            for c in accepted_sorted:
                rejected.append(
                    GatedEntity(
                        entity_id=c.entity_id,
                        canonical_name=c.canonical_name,
                        similarity=c.similarity,
                        payload=c.payload,
                        rejection_reason=REASON_DELTA_BELOW_THRESHOLD,
                    )
                )
            return [], rejected

    return accepted, rejected


__all__ = [
    "REASON_DELTA_BELOW_THRESHOLD",
    "REASON_LOW_TOP_SIMILARITY",
    "REASON_STOP_WORD_STRIP",
    "GatedEntity",
    "ResolverGateConfig",
    "filter_resolver_candidates",
    "strip_stop_words",
]
