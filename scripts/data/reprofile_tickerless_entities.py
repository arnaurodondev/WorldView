#!/usr/bin/env python3
"""FR-12 follow-up — re-classify tickerless ``financial_instrument`` canonicals.

ROOT CAUSE (see docs/audits/2026-06-13-fr12-hub-mistyping-investigation.md): the
provisional/news mint path (``provisional_enrichment_core.py``) typed any
"company"-class GLiNER fallback as ``financial_instrument`` even without a
ticker, and the small classifier mis-resolved ambiguous phrases.  The result is
~6,100 live ``entity_type='financial_instrument' AND ticker IS NULL`` rows that
are NOT tradable instruments: generic share/stock phrases ("Apple shares",
"Class A shares"), ETFs/index baskets, price literals ("$135"), exchanges, and a
large tail of private companies / orgs / research firms / non-profits.

The deterministic re-type (exchanges/countries) already shipped in
``retype_mishtyped_entities.py`` (migration 0053 added the ``exchange`` type).
THIS script handles the REMAINING fuzzy bulk via a two-stage pipeline:

  1. DETERMINISTIC PRE-PASS (no LLM, free) — high-confidence regex/lexicon rules
     for the cheap obvious cases so we never spend an LLM call on them:
       • pure generic phrases ("shares", "common stock", "Class A shares")  -> unknown
       • "<X> shares" / "<X> stock" / "<X> equity" phrases                  -> unknown
       • price literals ("$135", "RMB49", "US$15.20")                       -> unknown
       • obvious ETFs / funds ("... ETF", "... Index Fund")                 -> index
       • obvious index baskets ("S&P 500", "Nasdaq Composite", "... Index") -> index
       • high-confidence org markers ("... Foundation", "... Institute",
         "... University", "... Ventures", "... LLC", "... Inc" w/o ticker,
         agencies / non-profits)                                            -> organization

  2. LLM PASS — uses the SAME profiling path production uses
     (``provisional_enrichment_core.extract_entity_profile``): the DeepInfra
     extraction client (DeepSeek V4 Flash), the FULL ENTITY_PROFILE v2.2 prompt,
     and the FULL output_schema (canonical_name/entity_type/ticker/isin/aliases).
     The original version of this script passed a TRUNCATED output_schema
     (``{"entity_type": "string"}``) which does not match what the prompt asks
     the model to return — it must mirror the production request shape so the
     model reliably emits ``entity_type``.  The returned type is parsed +
     validated against the 13 canonical values (post migration 0055) and the
     entity_type is UPDATEd.  Anything that fails parse/validate is left UNCHANGED
     (never crash, never write an invalid type — the CHECK constraint rejects it).

SAFETY / DISCIPLINE:
  • DRY-RUN by DEFAULT.  Prints the deterministic re-types it WOULD apply and the
    COUNT of rows that WOULD hit the LLM (the cost) WITHOUT calling the LLM, then
    exits writing nothing.
  • ``--apply`` executes: deterministic UPDATEs + LLM calls + LLM-result UPDATEs,
    each in bounded transactions.
  • ``--limit N`` caps the number of candidate rows processed (safe sample run).
  • ``--batch-size`` controls the LLM concurrency window.
  • ``--deterministic-only`` skips the LLM stage entirely (free corrections).
  • IDEMPOTENT — only rows whose target type differs from the current type are
    written; a re-run after success is a no-op for the already-fixed rows.

Usage:
    python scripts/data/reprofile_tickerless_entities.py                 # DRY RUN (no LLM)
    python scripts/data/reprofile_tickerless_entities.py --limit 50      # sample, dry run
    python scripts/data/reprofile_tickerless_entities.py --deterministic-only --apply
    python scripts/data/reprofile_tickerless_entities.py --apply         # FULL run (LLM $$$)

The full ``--apply`` run costs real LLM calls — the orchestrator decides whether
to run it.  A dry run NEVER calls the LLM.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass

import psycopg

# Default DSN targets the local docker-compose Postgres.  Override via env.
_INTEL_DSN = os.environ.get(
    "INTELLIGENCE_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/intelligence_db",
)

# Model used for the LLM pass — the project's BUDGET classify model (per memory
# + knowledge-graph config ``deepinfra_extraction_model_id``).  DeepSeek V4 Flash,
# NOT Opus, to minimise cost.  Pricing for the estimate comes from the same
# ml_clients.cost table the live extraction path bills against.
_LLM_MODEL_ID = os.environ.get("KG_REPROFILE_MODEL_ID", "deepseek-ai/DeepSeek-V4-Flash")
_LLM_PROVIDER = "deepinfra"
_LLM_BASE_URL = os.environ.get("KG_REPROFILE_BASE_URL", "https://api.deepinfra.com/v1/openai")

# The 13 canonical entity_type values (post migration 0055).  MUST mirror the DB
# CHECK constraint ``ck_canonical_entities_entity_type`` exactly — a value not in
# this set is rejected by the DB, so the LLM-result validator forces "leave
# unchanged" rather than risk a constraint violation.
_VALID_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "financial_instrument",
        "person",
        "event",
        "sector",
        "industry",
        "macro_indicator",
        "place",
        "product",
        "index",
        "exchange",
        "organization",  # FR-12 / migration 0055: tickerless private cos / agencies / non-profits
        "currency",
        "unknown",
    }
)

# Map the LLM's legacy/invented type words onto the canonical set (mirrors the
# alias table in provisional_enrichment_core so the script and the live path
# agree).  Applied AFTER lower/strip/space->underscore normalisation.
_ENTITY_TYPE_ALIASES: dict[str, str] = {
    "company": "financial_instrument",
    "corp": "financial_instrument",
    "corporation": "financial_instrument",
    "enterprise": "financial_instrument",
    "firm": "financial_instrument",
    "business": "financial_instrument",
    "fund": "index",  # a fund/ETF is a basket -> index (closest canonical bucket)
    "etf": "index",
    # FR-12 / migration 0055: tickerless companies / agencies / NGOs now have a
    # dedicated canonical type.  Mirrors provisional_enrichment_core's alias map.
    "organization": "organization",
    "organisation": "organization",
    "regulator": "organization",
    "agency": "organization",
    "nonprofit": "organization",
    "non_profit": "organization",
    "foundation": "organization",
    "ngo": "organization",
    "institution": "organization",
    "university": "organization",
    "country": "place",
    "nation": "place",
    "region": "place",
    "location": "place",
    "city": "place",
    "commodity": "product",
    "other": "unknown",
    "concept": "unknown",
}


def normalize_llm_type(raw_type: str | None) -> str | None:
    """Normalise + alias-map an LLM-returned type to a canonical value.

    Returns the canonical type string, or ``None`` when the value cannot be
    safely mapped to one of the 12 valid types (caller must then leave the row
    UNCHANGED — never write an invalid type).  Pure + unit-tested.
    """
    if not raw_type or not isinstance(raw_type, str):
        return None
    norm = raw_type.lower().strip().replace(" ", "_")
    mapped = _ENTITY_TYPE_ALIASES.get(norm, norm)
    if mapped not in _VALID_ENTITY_TYPES:
        return None
    return mapped


# ── Deterministic pre-pass lexicon / patterns ────────────────────────────────
#
# All matching is on the lower-cased + whitespace-collapsed canonical_name.  The
# rules are intentionally CONSERVATIVE: a deterministic re-type only fires when
# the name is unambiguously a phrase / price / fund / index, so the LLM never
# wastes a call on these and we never mis-correct a real company.

# Generic finance boilerplate that, as a WHOLE name, denotes no distinct entity.
_PURE_PHRASE_NAMES: frozenset[str] = frozenset(
    {
        "shares",
        "stock",
        "stocks",
        "equity",
        "equities",
        "common stock",
        "ordinary shares",
        "preferred stock",
        "class a shares",
        "class b shares",
        "class c shares",
        "class a common stock",
        "class b common stock",
        "class c common stock",
        "common shares",
        "stock futures",
        "stock options",
        "share",
        "securities",
        "bonds",
        "notes",
        "warrants",
        "options",
        # Bare org-suffix words with no qualifier denote no distinct entity — they
        # must be caught here (rule 1) BEFORE the FR-12 organization rule so a lone
        # "Holdings" / "Capital" is 'unknown', not 'organization'.
        "holdings",
        "holding",
        "capital",
        "ventures",
        "partners",
        "associates",
        "group",
    }
)

# "<something> shares" / "<something> stock" / ... — a phrase referring to an
# underlying company (e.g. "Apple shares", "Microsoft Stock").  These should fold
# into the ticker-bearing canonical (a dedup concern, PLAN-0111) but are
# definitively NOT their own instrument, so we downgrade to ``unknown`` here.
_PHRASE_SUFFIX_RE = re.compile(r"\b(shares|stock|stocks|equity|equities|futures)$")

# Price literals captured by NER as "instruments": "$135", "RMB49", "US$15.20",
# "CHF330", "Rs20", "$0.0732".  A leading currency token/symbol immediately
# followed by digits.
_PRICE_LITERAL_RE = re.compile(
    r"^(?:\$|us\$|rmb|rs|chf|eur|gbp|jpy|cny|hk\$|£|€|¥)?\s*[\d][\d.,]*\s*$",
    re.IGNORECASE,
)

# Obvious ETFs / funds -> ``index`` (a basket, the closest canonical bucket).
_FUND_RE = re.compile(r"\b(etf|index fund|mutual fund|trust fund)\b", re.IGNORECASE)

# Obvious index baskets -> ``index``.  Named indices + a trailing " index".
_INDEX_RE = re.compile(
    r"(s&p\s?\d{2,4}|nasdaq composite|dow jones|russell\s?\d{3,4}|"
    r"ftse\s?\d{2,4}|nikkei|hang seng|\bindex$|composite index)",
    re.IGNORECASE,
)

# FR-12 — high-confidence ORGANISATION name signals -> ``organization``.
# A tickerless row whose name contains an unambiguous organisation marker
# (foundation, institute, university, ventures, capital, holdings, a private-co
# suffix like LLC/Inc/Ltd, or a clear agency/non-profit token) is almost
# certainly a private company / agency / non-profit / institution, NOT a
# tradeable instrument.  The markers are deliberately CONSERVATIVE — they only
# fire on tokens that essentially never appear in a generic finance phrase or a
# price literal, so the LLM never wastes a call on these obvious cases.
#
# WORD-BOUNDARY matters: "foundation"/"institute"/"university"/"ventures"/
# "capital"/"holdings"/"holding"/"associates"/"partners"/"laboratories"/"labs"/
# "council"/"commission"/"agency"/"bureau"/"authority"/"committee"/"federation"/
# "foundation"/"trust" (as an org, not a fund), plus the private-company legal
# suffixes that the FR-11 dedup does NOT strip (llc / inc / incorporated /
# corporation / ltd / limited / gmbh / s.a. / plc) when there is no ticker.
# CONSERVATIVE: only markers that almost never denote a publicly-tradeable
# security.  Generic corporate legal forms (holdings/plc/ltd/limited/incorporated/
# gmbh/s.a./partners/associates) are DELIBERATELY EXCLUDED — many tickerless
# PUBLIC companies carry them (e.g. "Alkane Resources Limited", "Active Energy
# Group PLC"), so those fall through to the LLM, which (with ENTITY_PROFILE v2.2)
# distinguishes tradeable company (financial_instrument) from private org.
_ORGANIZATION_RE = re.compile(
    r"\b("
    r"foundation|institute|institution|university|college|"
    r"ventures|venture\s+capital|capital\s+partners|capital\s+management|"
    r"laboratories|"
    r"council|commission|\bagency\b|bureau|authority|committee|"
    r"federation|consortium|alliance|coalition|society|"
    r"non-?profit|nonprofit|\bngo\b|charity|"
    r"\bllc\b|\bl\.l\.c\.|\bgmbh\b"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Retype:
    """A single planned re-type of one canonical_entities row."""

    entity_id: str
    canonical_name: str
    old_type: str  # always "financial_instrument" for this script
    new_type: str
    rule: str  # which deterministic rule fired (or "llm")


def classify_deterministic(entity_id: str, canonical_name: str) -> Retype | None:
    """Apply the deterministic pre-pass to one tickerless-FI row.

    Returns a planned :class:`Retype` for the cheap obvious cases, or ``None``
    when the row is ambiguous and must be handed to the LLM stage.  Pure +
    deterministic — this is the unit-tested core.  ``old_type`` is fixed at
    ``financial_instrument`` because the caller only feeds rows of that type.
    """
    norm = re.sub(r"\s+", " ", (canonical_name or "").lower().strip())
    if not norm:
        return None

    # 1. Pure generic phrase (whole name is boilerplate)        -> unknown
    if norm in _PURE_PHRASE_NAMES:
        return Retype(entity_id, canonical_name, "financial_instrument", "unknown", "pure_phrase")

    # 2. Price literal ("$135", "RMB49")                        -> unknown
    if _PRICE_LITERAL_RE.match(norm):
        return Retype(entity_id, canonical_name, "financial_instrument", "unknown", "price_literal")

    # 3. Obvious ETF / fund                                     -> index
    #    (checked before the "<X> shares" rule so "X Equity Fund" lands as index)
    if _FUND_RE.search(norm):
        return Retype(entity_id, canonical_name, "financial_instrument", "index", "fund")

    # 4. Obvious index basket                                   -> index
    if _INDEX_RE.search(norm):
        return Retype(entity_id, canonical_name, "financial_instrument", "index", "index")

    # 5. "<X> shares" / "<X> stock" / ... phrase                -> unknown
    #    Only when there IS a leading qualifier (multi-token), so a bare "shares"
    #    was already caught by rule 1 and a real one-word company is not hit.
    if " " in norm and _PHRASE_SUFFIX_RE.search(norm):
        return Retype(entity_id, canonical_name, "financial_instrument", "unknown", "phrase_suffix")

    # 6. High-confidence ORGANISATION name signal               -> organization
    #    Foundation / Institute / University / Ventures / Capital / Holdings /
    #    LLC / Inc-private / agency / non-profit markers.  Runs LAST among the
    #    deterministic rules — AFTER the fund/index rules so an "X Capital ETF"
    #    lands as index (fund), not organization, and AFTER the phrase rules so
    #    "Holdings" alone (a pure generic phrase, rule 1) is not mistaken for an
    #    org.  These markers essentially never appear in a real tradeable-ticker
    #    instrument name, so the re-type is high-confidence.
    if _ORGANIZATION_RE.search(norm):
        return Retype(entity_id, canonical_name, "financial_instrument", "organization", "organization")

    # Ambiguous — defer to the LLM stage.
    return None


@dataclass(frozen=True)
class Candidate:
    """A tickerless-FI row pulled from the DB for (re)classification."""

    entity_id: str
    canonical_name: str
    description: str | None


def _fetch_candidates(intel: psycopg.Connection, limit: int | None) -> list[Candidate]:
    """Fetch tickerless ``financial_instrument`` rows (optionally capped).

    Ordered by ``enrichment_attempts ASC`` so the never-enriched rows (the bulk
    of the contamination) are processed first when ``--limit`` is in effect.
    """
    sql = """
SELECT entity_id, canonical_name, description
FROM canonical_entities
WHERE entity_type = 'financial_instrument' AND ticker IS NULL
ORDER BY enrichment_attempts ASC, canonical_name ASC
"""
    if limit is not None:
        sql += "\nLIMIT %(limit)s"
        rows = intel.execute(sql, {"limit": limit}).fetchall()
    else:
        rows = intel.execute(sql).fetchall()
    return [Candidate(str(r[0]), r[1], r[2]) for r in rows]


def _apply_retypes(intel: psycopg.Connection, planned: list[Retype]) -> int:
    """Execute planned re-types in ONE transaction. Returns rows updated.

    The UPDATE re-checks the current type AND the still-NULL ticker in its WHERE
    clause so a concurrent change (or a stale plan) can never blindly overwrite —
    it only updates if the row still holds the type we planned to change FROM and
    is still tickerless.
    """
    updated = 0
    for r in planned:
        res = intel.execute(
            """
UPDATE canonical_entities
SET entity_type = %(new)s, updated_at = now()
WHERE entity_id = %(eid)s
  AND entity_type = %(old)s
  AND ticker IS NULL
""",
            {"new": r.new_type, "eid": r.entity_id, "old": r.old_type},
        )
        updated += res.rowcount or 0
    return updated


# ── LLM pass ─────────────────────────────────────────────────────────────────


def parse_llm_retype(entity_id: str, canonical_name: str, llm_result: dict | None) -> Retype | None:  # type: ignore[type-arg]
    """Map an LLM extraction result to a planned re-type, or ``None``.

    Returns ``None`` (leave unchanged) when:
      • the LLM call failed (``llm_result is None``),
      • the result has no usable ``entity_type``,
      • the type cannot be normalised to one of the 12 valid values, OR
      • the normalised type is still ``financial_instrument`` (no change — the
        LLM agrees it is a tradable instrument; we don't re-affirm).

    Pure + unit-tested.  Never returns an invalid type.
    """
    if not llm_result or not isinstance(llm_result, dict):
        return None
    new_type = normalize_llm_type(llm_result.get("entity_type"))
    if new_type is None:
        return None
    if new_type == "financial_instrument":
        # The LLM confirms it as an instrument — no re-type. (Without a ticker
        # this is still suspect, but the script's job is re-typing, not deleting;
        # leave it for the dedup pass / a human.)
        return None
    return Retype(entity_id, canonical_name, "financial_instrument", new_type, "llm")


async def _run_llm_stage(
    candidates: list[Candidate],
    batch_size: int,
) -> list[Retype]:
    """Call the PRODUCTION profiling path for each ambiguous candidate; return re-types.

    REWORK (FR-12 follow-up): this stage now mirrors the EXACT request shape the
    live enrichment path uses in
    ``provisional_enrichment_core.extract_entity_profile``:

      • the DeepInfra extraction client (``DeepSeekExtractionAdapter`` — DeepSeek
        V4 Flash, the same client the ``FallbackChainClient`` primary slot wraps),
      • the FULL ``ENTITY_PROFILE`` v2.2 prompt rendered with the same
        ``entity_class`` the worker passes,
      • the FULL ``output_schema`` (canonical_name / entity_type / ticker / isin /
        aliases) — the previous version sent a TRUNCATED ``{"entity_type":
        "string"}`` schema that did NOT match what the prompt asks the model to
        return, which is why entity_type came back missing and 0 rows re-typed,
      • the same injection-safe ``<article_context>...</article_context>`` wrapping.

    Parsing then mirrors ``persist_enrichment``: pull ``entity_type`` from the
    returned dict and alias-map + validate it against the 13 canonical values
    (``parse_llm_retype`` → ``normalize_llm_type``).  Calls are bounded by an
    ``asyncio.Semaphore`` so at most ``batch_size`` are in flight.  A failed/empty
    call leaves the row unchanged.  Only reached on ``--apply``.
    """
    api_key = os.environ.get("KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY") or os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        print(
            "ERROR: no DeepInfra API key found "
            "(set KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY or DEEPINFRA_API_KEY). "
            "LLM stage cannot run.",
            file=sys.stderr,
        )
        return []

    # Imported lazily so a dry run never needs ml-clients / openai installed.
    from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter  # type: ignore[import-untyped]
    from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-untyped]
    from prompts.knowledge.entity_profile import ENTITY_PROFILE  # type: ignore[import-untyped]

    semaphore = asyncio.Semaphore(batch_size)
    adapter = DeepSeekExtractionAdapter(
        api_key=api_key,
        model_id=_LLM_MODEL_ID,
        base_url=_LLM_BASE_URL,
        semaphore=semaphore,
    )

    async def _classify_one(c: Candidate) -> Retype | None:
        # Build the request EXACTLY as the production path does (full schema +
        # injection-safe context wrapping); see extract_entity_profile().
        context = f"<article_context>{(c.description or '')[:500]}</article_context>"
        inp = ExtractionInput(
            prompt=ENTITY_PROFILE.render(name=c.canonical_name, entity_class="financial_instrument"),
            context=context,
            output_schema={
                "canonical_name": "string",
                "entity_type": "string",
                "ticker": "string|null",
                "isin": "string|null",
                "aliases": "list[string]",
            },
            model_id=_LLM_MODEL_ID,
        )
        try:
            out = await adapter.extract(inp)
            result = out.result
        except Exception as exc:  # — never let one row crash the batch
            print(f"  [llm-fail] {c.entity_id} {c.canonical_name!r}: {exc}", file=sys.stderr)
            return None
        return parse_llm_retype(c.entity_id, c.canonical_name, result)

    try:
        results = await asyncio.gather(*[_classify_one(c) for c in candidates])
    finally:
        await adapter.aclose()
    return [r for r in results if r is not None]


# ── Orchestration ────────────────────────────────────────────────────────────


def _summarise_deterministic(planned: list[Retype]) -> dict[str, int]:
    """Count planned deterministic re-types grouped by rule (for the report)."""
    counts: dict[str, int] = {}
    for r in planned:
        counts[r.rule] = counts.get(r.rule, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Re-classify tickerless financial_instrument canonical entities (FR-12 follow-up).",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Execute re-types (deterministic + LLM). WITHOUT this flag the script is DRY-RUN and never calls the LLM.",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of candidate rows processed (safe sample run).",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Max concurrent LLM calls in the LLM stage (default 5).",
    )
    ap.add_argument(
        "--deterministic-only",
        action="store_true",
        help="Run ONLY the free deterministic pre-pass; skip the LLM stage entirely.",
    )
    args = ap.parse_args(argv)
    dry_run = not args.apply

    with psycopg.connect(_INTEL_DSN) as intel:
        candidates = _fetch_candidates(intel, args.limit)

        # ── Stage 1: deterministic pre-pass (pure, no LLM) ──
        det_planned: list[Retype] = []
        llm_candidates: list[Candidate] = []
        for c in candidates:
            retype = classify_deterministic(c.entity_id, c.canonical_name)
            if retype is not None:
                det_planned.append(retype)
            else:
                llm_candidates.append(c)

        det_counts = _summarise_deterministic(det_planned)
        mode = "DRY RUN — no writes, no LLM calls" if dry_run else "APPLY"
        print(f"FR-12 tickerless-FI reprofile ({mode}).")
        print(f"Candidates scanned: {len(candidates)}")
        print(f"  deterministic re-types planned: {len(det_planned)}")
        for rule in sorted(det_counts):
            print(f"    [{rule}] -> {det_counts[rule]}")
        print(f"  rows that WOULD hit the LLM: {len(llm_candidates)}")

        # ── Cost estimate for the LLM stage (no calls made to compute it) ──
        # Heuristic token sizing: the ENTITY_PROFILE system prompt is ~600
        # tokens; the per-row user context is ≤500 chars (~150 tokens); output
        # is a small JSON object (~40 tokens).  With DeepInfra prompt-prefix
        # caching the system prompt is billed once-ish, but we estimate the
        # conservative (uncached) upper bound here.
        from ml_clients.cost import estimate_cost  # type: ignore[import-untyped]

        est_in_per_call = 750  # ~600 system + ~150 user
        est_out_per_call = 40
        n_llm = 0 if args.deterministic_only else len(llm_candidates)
        est_cost = estimate_cost(_LLM_PROVIDER, _LLM_MODEL_ID, est_in_per_call * n_llm, est_out_per_call * n_llm)
        print(f"\nLLM stage model: {_LLM_MODEL_ID} (provider={_LLM_PROVIDER})")
        if args.deterministic_only:
            print("  --deterministic-only: LLM stage SKIPPED (0 calls).")
        else:
            print(f"  estimated LLM calls (full): {n_llm}")
            print(
                f"  estimated cost (uncached upper bound): ${est_cost:.4f} "
                f"(~{est_in_per_call} in / {est_out_per_call} out tokens per call)"
            )

        # Show a sample of the deterministic plan for eyeballing.
        if det_planned:
            print("\nSample deterministic re-types (first 20):")
            for r in det_planned[:20]:
                print(f"  [{r.rule}] {r.canonical_name!r}: {r.old_type} -> {r.new_type}")

        if dry_run:
            print("\nDRY RUN complete — no writes, no LLM calls. Re-run with --apply to execute.")
            return 0

        # ── APPLY: stage 1 deterministic writes (one transaction) ──
        det_updated = _apply_retypes(intel, det_planned)
        intel.commit()
        print(f"\nAPPLIED deterministic — {det_updated} row(s) re-typed and committed.")

        if args.deterministic_only:
            print("--deterministic-only: done (LLM stage skipped).")
            return 0

        # ── APPLY: stage 2 LLM pass ──
        print(f"Running LLM stage over {len(llm_candidates)} row(s) (batch-size={args.batch_size})...")
        llm_planned = asyncio.run(_run_llm_stage(llm_candidates, args.batch_size))
        print(f"  LLM proposed {len(llm_planned)} re-type(s) (the rest left unchanged).")
        llm_updated = _apply_retypes(intel, llm_planned)
        intel.commit()
        print(f"APPLIED LLM — {llm_updated} row(s) re-typed and committed.")
        print(f"\nTOTAL re-typed: {det_updated + llm_updated}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
