"""Layered recovery for deep-extraction endpoint refs that miss the doc-local lookup.

Background (2026-06-14 audit ``entity-ref-matching-and-mitigation.md``)
----------------------------------------------------------------------
``_build_raw_relations`` / ``_build_raw_events`` / ``_build_raw_claims`` resolve a
relation/event/claim endpoint ONLY against ``entity_id_by_ref`` — a dict built
exclusively from THIS document's NER mentions (resolved canonical UUIDs +
synthesized-provisional queue UUIDs). Any ref the LLM legitimately emits whose
surface is not one of this doc's mentions resolves to ``None`` and the whole row
was previously ``continue``-dropped. The dominant miss-reason is the *opposite*
endpoint of a relation being a real entity GLiNER never minted a mention for
(the "Jackery counterparty" case): it is in neither the prompt allow-list nor
``entity_id_by_ref``, and ``synthesize_provisional_refs`` (which only promotes
existing mentions) cannot reach it.

This module closes that asymmetry with the chat-side strategy, BEFORE any drop,
applied uniformly to relations, events and claims (they share the matcher):

  **M1 — precision-safe canonical-store fall-back (cheap, batched).**
  Resolve every missed ref against the canonical store via the SAME components
  the chat path uses — ``EntityAliasRepository`` exact-alias + ticker/ISIN
  (the audit's simulation showed the 84% recovery is ALL exact-alias, so the
  cheap path suffices), behind the existing resolver gate (0.75 absolute floor
  + 0.15 delta). ALL missed refs are resolved in ONE batched query per stage
  (``batch_exact_match`` / ``batch_ticker_isin_match``) — never per-ref
  round-trips. A hit binds to a REAL canonical (``entity_provisional=False``).

  **M2 — mint a provisional for the still-unresolved LLM endpoint.**
  For refs still unresolved after M1, mint a ``provisional_entity_queue`` row
  via the EXISTING provisional pipeline (``ensure_provisional_for_ref``) so the
  row PERSISTS with ``entity_provisional=True`` + ``provisional_queue_id`` and
  is canonicalized later by the ``UnresolvedResolutionWorker`` → KG promotion
  (the proven path that already lands 4,834 provisional relations). A junk guard
  (``_is_junk_ref``) blocks common-noun / empty / too-short / non-alpha refs so
  we never mint garbage provisional shells.

The genuine final drop is now reserved for refs that are empty/junk/hallucinated
*after both* M1 and M2. ``record_extraction_endpoint_recovery`` increments a
per-outcome counter so the lift is observable.

Hexagonal layering (R12): this is INFRASTRUCTURE — it does the DB work via the
injected ``EntityAliasRepository`` + ``intelligence_session`` (reusing the
provisional-queue machinery in ``application/blocks/entity_resolution.py``). No
infra import leaks into the domain layer.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from nlp_pipeline.domain.enums import MentionClass
from nlp_pipeline.infrastructure.messaging.consumers.blocks.helpers import _normalize_ref_variants
from nlp_pipeline.infrastructure.metrics.prometheus import record_extraction_endpoint_recovery
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from nlp_pipeline.infrastructure.intelligence_db.repositories.entity_alias import EntityAliasRepository

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── M1 precision gate (mirrors rag-chat resolver_gates semantics) ─────────────
#
# The chat path gates every store-global candidate through a 0.75 absolute
# similarity floor + a 0.15 top-1/top-2 delta. We replicate those two numbers
# here rather than importing rag-chat's ``filter_resolver_candidates`` because
# that lives in a SIBLING service (frontend-only / R14 + cross-service import
# boundary): S6 must not import from S8. The gate is just two thresholds, so the
# duplication is trivial and keeps the precision contract identical.
#
# Exact-alias (conf 1.0) and ticker/ISIN (conf 0.95) hits are deterministic and
# sail over the floor — the gate only matters for the optional fuzzy tier. We do
# NOT run fuzzy/embedding NN in this hot consumer path by default (the audit
# showed exact-alias alone delivers the full 84% recall); fuzzy is left as a
# documented follow-up.
M1_SIMILARITY_FLOOR: float = 0.75
M1_DELTA_MIN: float = 0.15

# ── M2 junk-ref guard ─────────────────────────────────────────────────────────
#
# We only mint a provisional for a ref that plausibly names a real entity. This
# mirrors the hallucination-guard intent behind
# ``s6_extraction_entity_ref_hallucinated_total`` — never create provisional
# shells for GLiNER-free noise nouns ("analysts", "investors", "management") or
# malformed/empty surfaces.
_M2_MIN_LEN: int = 3

# Common-noun blocklist — the recurring GLiNER/LLM noise tokens the audit's
# top-frequency sample flagged ("analysts" 290x, "management" 90x, etc.). These
# are generic roles/collectives, never canonical entities, so minting a
# provisional for them is pure junk. Lower-cased; matched after normalization.
_M2_COMMON_NOUN_BLOCKLIST: frozenset[str] = frozenset(
    {
        "analysts",
        "analyst",
        "management",
        "investors",
        "investor",
        "shareholders",
        "shareholder",
        "patients",
        "developers",
        "operators",
        "women",
        "men",
        "customers",
        "users",
        "employees",
        "executives",
        "regulators",
        "consumers",
        "the company",
        "the bank",
        "the group",
        "the firm",
        "company",
        "bank",
        "group",
        "firm",
        "government",
        "officials",
        "authorities",
    }
)

# A ref must contain at least one alphanumeric character (reject pure
# punctuation / whitespace surfaces) AND not be purely numeric (reject bare
# numbers / percentages the LLM occasionally emits as an "entity").
_HAS_ALNUM_RX = re.compile(r"[0-9a-zA-Z]")
_PURELY_NUMERIC_RX = re.compile(r"^[\d\s.,%$+\-]+$")


def _is_junk_ref(raw_ref: str) -> bool:
    """Return True when *raw_ref* is too junky to mint a provisional for.

    Junk = empty / too short / no alphanumeric / purely numeric / a common-noun
    role token from the blocklist. Used as the M2 precision guard so the live
    provisional path never creates garbage shells.
    """
    stripped = raw_ref.strip()
    if len(stripped) < _M2_MIN_LEN:
        return True
    if not _HAS_ALNUM_RX.search(stripped):
        return True
    if _PURELY_NUMERIC_RX.match(stripped):
        return True
    # Strip surrounding punctuation/quotes the LLM occasionally wraps a surface
    # in ("The Company.", '"analysts"') before the blocklist check so those
    # still match.
    lowered = stripped.strip("\"'.,;:!?()[]{} ").lower()
    if lowered in _M2_COMMON_NOUN_BLOCKLIST:
        return True
    # Also reject the suffix-stripped/whitespace-collapsed normalized forms so
    # "The Company Inc." or "Analysts" still hit the blocklist.
    return any(variant in _M2_COMMON_NOUN_BLOCKLIST for variant in _normalize_ref_variants(lowered))


def _collect_missed_refs(
    extraction_result: dict[str, Any],
    entity_id_by_ref: dict[str, str],
) -> dict[str, str]:
    """Return ``{normalized_ref: original_surface}`` for every LLM endpoint ref
    that misses the document-local ``entity_id_by_ref`` lookup.

    Walks relations (subject_ref / object_ref), events (entity_refs[]) and
    claims (entity_ref) — the same surfaces ``_build_raw_*`` resolve. A ref is
    "missed" when NONE of its normalized variants is already a key in
    ``entity_id_by_ref``. We key the result by the FIRST normalized variant
    (the canonical lookup key) and remember the original surface so M1's batched
    alias query and M2's provisional mint both see the real text.

    Returning a dict (not a list) deduplicates refs that appear on multiple
    relations, so the batched M1 query and M2 mint each touch a surface once.
    """
    missed: dict[str, str] = {}
    # Track every variant already collected so refs that differ only by suffix
    # ("Foo Corp" vs "Foo") dedup to a single batched lookup / mint.
    seen_variants: set[str] = set()

    def _ingest(raw: object) -> None:
        if not isinstance(raw, str):
            return
        surface = raw.strip()
        if not surface:
            return
        variants = _normalize_ref_variants(surface)
        if not variants:
            return
        # Already resolvable against the doc-local lookup → not missed.
        if any(v in entity_id_by_ref for v in variants):
            return
        # Already collected under one of its variants → dedup.
        if any(v in seen_variants for v in variants):
            return
        seen_variants.update(variants)
        # Key by the primary normalized variant; keep the original surface.
        missed.setdefault(variants[0], surface)

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

    return missed


async def _run_m1_canonical_fallback(
    missed: dict[str, str],
    alias_repo: EntityAliasRepository,
) -> dict[str, UUID]:
    """M1 — batched canonical-store fall-back for missed refs.

    Issues ONE ``batch_exact_match`` query and (for ticker-shaped surfaces) ONE
    ``batch_ticker_isin_match`` query for ALL missed refs — never per-ref
    round-trips. Both stages are deterministic and clear the 0.75 floor (exact =
    1.0, ticker/ISIN = 0.95), so the gate is satisfied by construction; the
    explicit floor constant documents the precision contract and guards a future
    fuzzy tier.

    Returns ``{normalized_ref: entity_id}`` for refs that bound to a REAL
    canonical. Refs absent from the result fall through to M2.
    """
    if not missed:
        return {}

    surfaces = list(missed.values())

    # ── Stage 1: exact alias (1 query for all surfaces) ──────────────────────
    # batch_exact_match keys its result by ``lower(trim(surface))`` — the same
    # normalization our primary variant uses, so we map results back via the
    # missed-key index.
    exact_by_norm: dict[str, UUID] = await alias_repo.batch_exact_match(surfaces)

    # ── Stage 2: ticker/ISIN for ticker-shaped surfaces (1-2 queries) ────────
    tickers: list[str] = []
    isins: list[str] = []
    for surface in surfaces:
        s = surface.strip()
        if s.isupper() and 1 <= len(s) <= 6:
            tickers.append(s)
        if len(s) == 12 and s[:2].isalpha() and s[2:].isalnum():
            isins.append(s)
    ticker_isin_by_raw: dict[str, UUID] = {}
    if tickers or isins:
        ticker_isin_by_raw = await alias_repo.batch_ticker_isin_match(tickers, isins)

    resolved: dict[str, UUID] = {}
    for norm_key, surface in missed.items():
        # Exact-alias hit (conf 1.0 ≥ floor) — keyed by lower(trim(surface)).
        eid = exact_by_norm.get(surface.lower().strip())
        if eid is None:
            # Ticker/ISIN hit (conf 0.95 ≥ floor) — keyed by the raw surface.
            eid = ticker_isin_by_raw.get(surface.strip())
        if eid is not None:
            resolved[norm_key] = eid
    return resolved


async def recover_missed_endpoints(
    *,
    extraction_result: dict[str, Any],
    entity_id_by_ref: dict[str, str],
    provisional_refs: set[str],
    alias_repo: EntityAliasRepository | None,
    intelligence_session: object | None,
    doc_id: Any,
) -> None:
    """Layered M1+M2 recovery of LLM endpoint refs that miss the doc-local lookup.

    MUTATES ``entity_id_by_ref`` and ``provisional_refs`` IN PLACE so the
    subsequent ``_build_raw_relations`` / ``_build_raw_events`` /
    ``_build_raw_claims`` calls see the recovered refs and emit the rows instead
    of dropping them:

      * M1 hit  → ``entity_id_by_ref[ref] = canonical_uuid`` (NOT added to
                  ``provisional_refs`` → row carries ``entity_provisional=False``).
      * M2 mint → ``entity_id_by_ref[ref] = queue_uuid`` AND
                  ``provisional_refs.add(ref)`` → row carries
                  ``entity_provisional=True`` + ``provisional_queue_id``.

    No-ops safely when there are no missed refs, or when ``alias_repo`` /
    ``intelligence_session`` are not supplied (e.g. unit tests that exercise the
    legacy doc-local path) — in that case it simply records the still-dropped
    junk count for observability and returns.

    Called from ``_enqueue_enriched`` AFTER ``entity_id_by_ref`` is built and
    BEFORE the ``_build_raw_*`` helpers run.
    """
    missed = _collect_missed_refs(extraction_result, entity_id_by_ref)
    if not missed:
        return

    # ── M1: canonical-store fall-back (cheap, batched, precision-safe) ────────
    m1_resolved: dict[str, UUID] = {}
    if alias_repo is not None:
        try:
            m1_resolved = await _run_m1_canonical_fallback(missed, alias_repo)
        except Exception as exc:  # pragma: no cover - defensive; never break the pipeline
            logger.warning(  # type: ignore[no-any-return]
                "endpoint_recovery.m1_failed",
                doc_id=str(doc_id),
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )
            m1_resolved = {}

    for norm_key, eid in m1_resolved.items():
        # Bind to the REAL canonical — resolved, NOT provisional.
        entity_id_by_ref.setdefault(norm_key, str(eid))
        provisional_refs.discard(norm_key)  # defensive: never flag an M1 bind provisional
    if m1_resolved:
        record_extraction_endpoint_recovery("m1_recovered", len(m1_resolved))

    # ── M2: mint provisionals for the residual (live first-touch) ────────────
    residual = {k: v for k, v in missed.items() if k not in m1_resolved}
    minted = 0
    dropped_junk = 0
    if residual and intelligence_session is not None:
        # Lazy import: keeps the consumer import graph compatible with unit
        # tests that patch entity_resolution at the module level, and avoids a
        # circular import (entity_resolution → ... → this module).
        from nlp_pipeline.application.blocks.entity_resolution import ensure_provisional_for_ref

        for norm_key, surface in residual.items():
            if _is_junk_ref(surface):
                dropped_junk += 1
                continue
            queue_id = await ensure_provisional_for_ref(
                surface=surface,
                # The LLM does not tell us the GLiNER class for a non-mention
                # endpoint; ORGANIZATION is the safe default (it dominates
                # relation endpoints and the provisional queue is class-keyed
                # only for dedup, not for resolution correctness — the
                # UnresolvedResolutionWorker canonicalizes by surface).
                mention_class=MentionClass.ORGANIZATION,
                doc_id=doc_id,
                intelligence_session=intelligence_session,
            )
            if queue_id is not None:
                entity_id_by_ref[norm_key] = str(queue_id)
                provisional_refs.add(norm_key)
                minted += 1
            else:
                # Churn-guard hit or insert failure → genuine drop.
                dropped_junk += 1
    else:
        # No session (or no residual) → everything residual is a genuine drop.
        dropped_junk += len(residual)

    if minted:
        record_extraction_endpoint_recovery("m2_minted", minted)
    if dropped_junk:
        record_extraction_endpoint_recovery("dropped_junk", dropped_junk)

    if m1_resolved or minted or dropped_junk:
        logger.info(  # type: ignore[no-any-return]
            "endpoint_recovery.complete",
            doc_id=str(doc_id),
            missed=len(missed),
            m1_recovered=len(m1_resolved),
            m2_minted=minted,
            dropped_junk=dropped_junk,
        )
