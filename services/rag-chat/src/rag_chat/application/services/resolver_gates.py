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

import re
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
    # BP-661: exchange ticker for the candidate (e.g. "AAPL") when the
    # upstream resolver knows it. Used by the query-ticker tiebreak so a
    # query that literally contains the ticker can break a delta-ambiguous
    # tie (the "what is AAPL?" case: "AAPL Stock" noise twin at 0.95 vs
    # "Apple Inc." at 0.90 → delta gate used to reject BOTH).
    ticker: str | None = None
    # Set by ``filter_resolver_candidates`` on accepted entries that were
    # admitted via a tiebreak rule (e.g. ``"query_ticker_exact_match"``).
    # ``""`` for ordinary unambiguous accepts — lets the caller log/metric
    # tiebreak resolutions without changing the return shape.
    accepted_reason: str = ""


# Rejection reason labels — keep in sync with the Prometheus
# ``entity_resolver_ambiguous_total{reason}`` label set.
REASON_STOP_WORD_STRIP = "stop_word_strip"
REASON_LOW_TOP_SIMILARITY = "low_top_similarity"
REASON_DELTA_BELOW_THRESHOLD = "delta_below_threshold"

# Acceptance reason label for tiebreak-admitted candidates (BP-661).
ACCEPTED_QUERY_TICKER_MATCH = "query_ticker_exact_match"

# BP-661: shape gate for "is this string a stock ticker?". Uppercase 1-6
# letters/digits with an optional exchange-style suffix ("BRK.B", "RDS-A").
# Lowercase strings ("Apple") fail the gate and go to name resolution —
# tickers are conventionally written in caps and the LLM follows that
# convention when echoing user input. Shared by IntelligenceHandler and
# NarrativeHandler so both tool paths agree on what "looks like a ticker".
TICKER_SHAPE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}([.\-][A-Z0-9]{1,4})?$")

# InputValidator XML wrapper: `<Q_8hexchars>message</Q_8hexchars>` (step 5 of
# validate()). The orchestrator resolves entities on the VALIDATED message,
# so the gate must unwrap before tokenising — otherwise the trailing token is
# "aapl?</q_abc123>" and the query-ticker tiebreak silently never matches
# (the exact live failure observed on 2026-06-10 during BP-661 verification).
_Q_WRAPPER_RE = re.compile(r"^<Q_([0-9a-fA-F]+)>(?P<inner>.*)</Q_\1>$", re.DOTALL)


def strip_query_wrapper(query_text: str) -> str:
    """Remove the InputValidator ``<Q_token>...</Q_token>`` wrapper if present.

    Returns the inner message when the wrapper matches; the input unchanged
    otherwise. Safe to call on already-unwrapped text.
    """
    m = _Q_WRAPPER_RE.match(query_text.strip())
    return m.group("inner") if m else query_text


def _name_tokens(name: str) -> set[str]:
    """Tokenise a canonical name on non-alphanumeric boundaries (lowercased).

    Used by the BP-661 phantom-shape filter: noise duplicates created by the
    extraction pipeline almost always EMBED the ticker in their canonical name
    ("AAPL Stock", "NasdaqGS:AAPL", "AAPL.US") while real canonicals do not
    ("Apple Inc."). Splitting on non-alphanumerics catches all three shapes;
    the whitespace pass additionally keeps dotted class-share tickers
    ("BRK.B Stock") intact so they too are recognised as ticker-derived.
    """
    lowered = name.lower()
    tokens = {t for t in re.split(r"[^a-z0-9]+", lowered) if t}
    tokens |= {t.strip(".,!?:;'\"()[]") for t in lowered.split()}
    return tokens


def _query_ticker_tiebreak(
    survivors: list[GatedEntity],
    query_text: str | None,
) -> GatedEntity | None:
    """BP-661: break a delta-ambiguous tie via an exact query-token ↔ ticker match.

    When the user's query literally contains a candidate's exchange ticker as
    a standalone token (e.g. "what is AAPL?"), that is a strong, unambiguous
    signal which canonical the user means — far stronger than the embedding
    similarity spread the delta gate inspects.

    Selection rules (in order):
      1. Keep only survivors whose ``ticker`` appears as a token in the query.
      2. Among those, prefer candidates whose canonical_name does NOT embed
         the ticker itself — this filters BP-459-style phantom duplicates
         ("AAPL Stock", "AAPL.US") in favour of the real canonical
         ("Apple Inc."), which both carry ticker=AAPL in the DB.
      3. Highest similarity wins among the remaining pool (deterministic).

    Returns the winning candidate, or ``None`` when no ticker matches the
    query (caller falls through to the legacy reject-all-ambiguous path).
    """
    if not query_text:
        return None
    # Unwrap the InputValidator <Q_token> envelope first (the orchestrator
    # passes the VALIDATED message), then tokenise BOTH on non-alphanumeric
    # boundaries (so "aapl?" / "(AAPL," yield the bare token) AND on
    # whitespace with edge-punctuation stripped (so dotted class-share
    # tickers like "BRK.B" survive as a single token).
    unwrapped = strip_query_wrapper(query_text).lower()
    query_tokens = {t for t in re.split(r"[^a-z0-9]+", unwrapped) if t}
    query_tokens |= {t.strip(".,!?:;'\"()[]") for t in unwrapped.split()}
    matches = [c for c in survivors if c.ticker and c.ticker.strip().lower() in query_tokens]
    if not matches:
        return None
    clean = [
        c for c in matches if c.ticker is not None and c.ticker.strip().lower() not in _name_tokens(c.canonical_name)
    ]
    pool = clean or matches
    return max(pool, key=lambda c: c.similarity)


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
    query_text: str | None = None,
) -> tuple[list[GatedEntity], list[GatedEntity]]:
    """Apply 0.75 absolute floor + 0.15 delta gate (+ BP-661 ticker tiebreak).

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

    * **query_ticker_exact_match (BP-661)** — BEFORE the delta gate
      rejects everything, when ``query_text`` is supplied and exactly
      one best candidate's ticker appears verbatim as a query token,
      that candidate is accepted (others rejected with the delta
      reason). This rescues ticker-only queries like "what is AAPL?"
      where a BP-459 phantom twin ("AAPL Stock") and the real canonical
      ("Apple Inc.") sit within the delta window and the gate would
      otherwise refuse to resolve anything.
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
            # ── BP-661: query-ticker tiebreak before the ambiguous bail ──
            # When the user's query literally names a candidate's ticker
            # ("what is AAPL?"), resolve to that candidate instead of
            # refusing — see _query_ticker_tiebreak for the full rules.
            winner = _query_ticker_tiebreak(accepted_sorted, query_text)
            if winner is not None:
                losers = [c for c in accepted_sorted if c.entity_id != winner.entity_id]
                for c in losers:
                    rejected.append(
                        GatedEntity(
                            entity_id=c.entity_id,
                            canonical_name=c.canonical_name,
                            similarity=c.similarity,
                            payload=c.payload,
                            rejection_reason=REASON_DELTA_BELOW_THRESHOLD,
                            ticker=c.ticker,
                        )
                    )
                return [
                    GatedEntity(
                        entity_id=winner.entity_id,
                        canonical_name=winner.canonical_name,
                        similarity=winner.similarity,
                        payload=winner.payload,
                        ticker=winner.ticker,
                        accepted_reason=ACCEPTED_QUERY_TICKER_MATCH,
                    )
                ], rejected
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
                        ticker=c.ticker,
                    )
                )
            return [], rejected

    return accepted, rejected


__all__ = [
    "ACCEPTED_QUERY_TICKER_MATCH",
    "REASON_DELTA_BELOW_THRESHOLD",
    "REASON_LOW_TOP_SIMILARITY",
    "REASON_STOP_WORD_STRIP",
    "TICKER_SHAPE_RE",
    "GatedEntity",
    "ResolverGateConfig",
    "filter_resolver_candidates",
    "strip_query_wrapper",
    "strip_stop_words",
]
