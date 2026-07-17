"""Cheap LLM claim/relation entailment pass — the semantic-mislabel fabrication cure.

Why this block exists
---------------------
The 2026-07-16 extraction-fabrication investigation
(``docs/audits/2026-07-16-extraction-fabrication.md``) found that fabrication is
**not** hallucinated text — the models quote VERBATIM — but **semantic MISLABELLING**:
a real sentence is tagged with the wrong ``claim_type`` / polarity ("refinanced $2B" →
``DEBT_CHANGE`` negative; a segment mention → ``REVENUE_GROWTH``; a Q4 earnings *call*
date → a product *release* date). 149/240 judged extractions carried ≥1 fabrication and
the dominant, entirely-UNGUARDED slice was CLAIMS — ``validate_relations`` and the
``relation_entailment`` gate touch relations only; claims flowed straight from the LLM
into ``raw_claims`` → KG with no post-extraction check.

A substring/structural check (the shipped ``evidence_grounding`` gate) CANNOT catch a
mislabel because the quote is genuine. Only a **semantic entailment** judgement can:
"the quote is verbatim — is the LABEL correct for these entities?"

What this block does
--------------------
For each extracted CLAIM whose ``claim_type`` is in the configured HIGH-FABRICATION set
(the audit's dominant buckets: ``DEBT_CHANGE``, ``REVENUE_GROWTH``, ``GUIDANCE_RAISE``,
``GUIDANCE_CUT``, ``HEADCOUNT_CHANGE``, ``EPS_BEAT``), it asks a cheap verifier LLM a
single binary question: does the EVIDENCE text ENTAIL that this ``claim_type`` (with this
polarity) holds for ``entity_ref``? Claims the model confidently marks NOT_ENTAILED are
dropped; everything else is kept untouched. Gating to high-fab types keeps this at
~1 call per gated claim (≈1-2 calls/doc on the live models), not one per item.

Design invariants (mirrors ``relation_entailment`` — the validated 0%-FP template)
---------------------------------------------------------------------------------
* **Default OFF** (``claim_entailment_check_enabled``). Enabling it changes extraction
  output, so it is opt-in and must be watched.
* **Scoped** to the configured ``claim_type`` set — every other claim skips the LLM call
  entirely (no added cost/latency).
* **Fail-OPEN**: any LLM/parse error, a missing-evidence claim, or a low-confidence
  verdict KEEPS the claim. The check can only ever *remove* a claim it is confident is
  mislabelled; it must never destroy a claim on infrastructure noise. This guarantees
  **zero true-positive yield loss from an API blip** — the operator's hard requirement.
* **Capped** at ``max_per_doc`` checks per document.
* Reuses the existing ``ExtractionClient`` abstraction (the same DeepInfra-backed client
  the extractor uses) — no new infrastructure. The verifier model is configurable;
  default is the cheap live-extraction-class model (``DeepSeek-V4-Flash``), which the
  audit qualified as adequate (it explicitly REJECTED gpt-oss-20b at 27.6% FP — a weak
  verifier kills good items, so the verifier MUST be ≥ V4-Flash / Qwen3-235B class).

The pass is wired AFTER the deterministic evidence-span gate (so ungrounded quotes are
already gone — fewer, cleaner LLM calls) and BEFORE the KG write.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from ml_clients.protocols import ExtractionClient  # type: ignore[import-not-found]

logger = structlog.get_logger(__name__)

# Default high-fabrication claim_type set (audit §1 "By kind" — claim-type mentions in
# fabrication justifications: DEBT_CHANGE x26, REVENUE_GROWTH x16, GUIDANCE_RAISE x15,
# HEADCOUNT_CHANGE x10, GUIDANCE_CUT x5, EPS_BEAT x4). Mirrors the config default; the
# runtime set comes from ``Settings.claim_entailment_check_claim_types``.
DEFAULT_HIGH_FAB_CLAIM_TYPES: frozenset[str] = frozenset(
    {
        "DEBT_CHANGE",
        "REVENUE_GROWTH",
        "GUIDANCE_RAISE",
        "GUIDANCE_CUT",
        "HEADCOUNT_CHANGE",
        "EPS_BEAT",
    }
)

# One-line claim_type meanings injected into the prompt (kept short — cost control).
# These arm the verifier against the exact confusions the audit catalogued (refinancing
# read as a debt CHANGE; a segment/backlog mention read as REVENUE_GROWTH; a plain
# earnings release read as a GUIDANCE raise/cut). Unknown types fall back to a
# humanised form of the string.
_CLAIM_TYPE_MEANING: dict[str, str] = {
    "DEBT_CHANGE": (
        "the entity's total DEBT LEVEL rose or fell (new borrowing / repayment / net "
        "change). Refinancing or rolling debt at the SAME level is NOT a debt change."
    ),
    "REVENUE_GROWTH": (
        "the entity's REVENUE grew (or shrank) versus a prior period. A segment/product "
        "mention, backlog, or bookings figure is NOT revenue growth unless growth is stated."
    ),
    "GUIDANCE_RAISE": "the entity RAISED its forward guidance/outlook. A plain results release is NOT a raise.",
    "GUIDANCE_CUT": "the entity CUT/lowered its forward guidance/outlook. A plain results release is NOT a cut.",
    "HEADCOUNT_CHANGE": "the entity's employee HEADCOUNT rose or fell (hiring / layoffs / job cuts).",
    "EPS_BEAT": "the entity's earnings-per-share BEAT expectations/consensus. Reporting EPS is NOT itself a beat.",
}

# Binary output schema for the cheap entailment client.
_ENTAILMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entailed": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["entailed", "confidence"],
}

# Strict prompt — tuned to MINIMISE FALSE POSITIVES (killing a good claim is the critical
# risk, exactly as for the relation gate). Default-towards-ENTAILED on any doubt; only
# confidently flag a genuine mislabel. The verbatim-quote framing is load-bearing: the
# verifier must judge only whether the LABEL fits the quote, never re-extract or re-quote.
_SYSTEM_PROMPT = (
    "You are a strict entailment checker for a financial knowledge graph. You receive a "
    "candidate CLAIM about an ENTITY: a CLAIM_TYPE, a one-line MEANING of that type, an "
    "optional POLARITY (positive/negative/neutral), and an EVIDENCE snippet quoted VERBATIM "
    "from the source article.\n\n"
    "The quote is known to be a real sentence from the article — do NOT question whether the "
    "text exists. Your ONLY job: does the EVIDENCE actually ENTAIL that this CLAIM_TYPE (in "
    "the stated direction/polarity) holds for THIS entity? I.e. is the LABEL correct for the "
    "quote?\n\n"
    "Rules:\n"
    "- ENTAILED means a reader of the EVIDENCE would agree the CLAIM_TYPE (and polarity) is "
    "what the sentence asserts about the entity.\n"
    "- NOT_ENTAILED means the sentence says something DIFFERENT from the claim_type (e.g. a "
    "refinancing labelled DEBT_CHANGE; a segment mention labelled REVENUE_GROWTH; a plain "
    "earnings release labelled GUIDANCE_RAISE), or the polarity/direction is inverted, or the "
    "sentence does not support the claim for THIS entity.\n"
    "- CRITICAL: when in ANY doubt, answer ENTAILED. Only answer NOT_ENTAILED (entailed=false) "
    "when you are confident the label does NOT fit the quote. Do not demand exact wording — if "
    "the sentence reasonably supports the claim_type and direction, answer ENTAILED.\n\n"
    "Output STRICT JSON only:\n"
    '{"entailed": true|false, "confidence": 0.0-1.0, "reason": "<=14 words"}'
)


def _build_prompt(entity_ref: str, claim_type: str, polarity: str, evidence: str) -> str:
    meaning = _CLAIM_TYPE_MEANING.get(claim_type, claim_type.replace("_", " ").lower())
    polarity_line = f"POLARITY: {polarity}\n" if polarity else ""
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"ENTITY: {entity_ref}\n"
        f"CLAIM_TYPE: {claim_type} ({meaning})\n"
        f"{polarity_line}"
        f"EVIDENCE: {evidence}\n\n"
        "Does the EVIDENCE entail this claim_type (and polarity) for this ENTITY? Return the strict JSON."
    )


def _parse_verdict(output: Any) -> tuple[bool, float] | None:
    """Extract (entailed, confidence) from an ExtractionOutput. None on any parse failure.

    Reads ``output.result`` first (structured), falling back to parsing
    ``output.raw_response`` JSON. Returns None (=> fail-open keep) if neither yields a
    usable boolean ``entailed``.
    """
    payload: dict[str, Any] | None = None
    result = getattr(output, "result", None)
    if isinstance(result, dict) and "entailed" in result:
        payload = result
    else:
        raw = getattr(output, "raw_response", None)
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return None
            if isinstance(parsed, dict):
                payload = parsed
    if payload is None or not isinstance(payload.get("entailed"), bool):
        return None
    entailed = bool(payload["entailed"])
    # Fail-open on confidence too: a MISSING or non-numeric confidence is UNKNOWN
    # confidence, which must never trigger a drop. Default to 0.0 (below any sane
    # ``min_drop_confidence``) so a NOT_ENTAILED verdict with a malformed/absent
    # confidence (e.g. ``{"entailed": false, "confidence": null}`` or the field
    # omitted despite the schema) KEEPS the claim rather than destroying it. A
    # confident drop requires the verifier to emit a real high confidence value.
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return entailed, confidence


async def check_claim_entailment(
    claims: list[dict[str, Any]],
    *,
    entailment_client: ExtractionClient,
    model_id: str,
    high_fab_claim_types: frozenset[str] | set[str] = DEFAULT_HIGH_FAB_CLAIM_TYPES,
    min_drop_confidence: float = 0.7,
    max_per_doc: int = 20,
    doc_id: str | None = None,
) -> list[dict[str, Any]]:
    """Drop high-fabrication-type claims whose evidence does not entail their label.

    Args:
        claims: extracted claim dicts (``entity_ref``/``claim_type``/``polarity``/
            ``evidence_text``). Non-gated claim_types and claims without evidence are
            returned unchanged (no LLM call).
        entailment_client: an ExtractionClient (the cheap verifier). Reuses the
            extraction abstraction — pass a DeepInfra-backed adapter pointed at a model
            of at least DeepSeek-V4-Flash / Qwen3-235B class (the audit REJECTED weaker
            models: gpt-oss-20b scored 27.6% FP).
        model_id: model id to tag the ExtractionInput with (logging/telemetry only —
            the adapter's own configured model does the call).
        high_fab_claim_types: only these claim_types are checked.
        min_drop_confidence: a NOT_ENTAILED verdict below this confidence is IGNORED
            (the claim is kept) — second guard against false positives.
        max_per_doc: hard cap on LLM calls for this document.
        doc_id: for logging only.

    Returns:
        A new list with confidently-mislabelled claims removed. FAIL-OPEN: on any error
        the claim is kept. Order is preserved.
    """
    from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-not-found]

    gated = frozenset(high_fab_claim_types)
    kept: list[dict[str, Any]] = []
    checks_done = 0
    dropped = 0

    for claim in claims:
        claim_type = str(claim.get("claim_type", ""))
        evidence = str(claim.get("evidence_text", "") or "").strip()
        entity_ref = str(claim.get("entity_ref", ""))
        polarity = str(claim.get("polarity", "") or "").strip()

        # Skip the LLM entirely unless: gated type, has evidence, has an entity, under cap.
        if claim_type not in gated or not evidence or not entity_ref or checks_done >= max_per_doc:
            kept.append(claim)
            continue

        checks_done += 1
        try:
            output = await entailment_client.extract(
                ExtractionInput(
                    prompt=_build_prompt(entity_ref, claim_type, polarity, evidence),
                    context="",
                    output_schema=_ENTAILMENT_SCHEMA,
                    model_id=model_id,
                    template_id="claim_entailment_v1",
                )
            )
        except Exception:
            # Fail-open: infrastructure noise must never destroy a claim.
            logger.warning(
                "claim_entailment.check_failed",
                doc_id=doc_id,
                claim_type=claim_type,
                exc_info=True,
            )
            kept.append(claim)
            continue

        verdict = _parse_verdict(output)
        if verdict is None:
            # Unparseable verdict => keep (fail-open).
            kept.append(claim)
            continue

        entailed, confidence = verdict
        # Drop ONLY when confidently NOT entailed.
        if (not entailed) and confidence >= min_drop_confidence:
            dropped += 1
            logger.info(
                "claim_entailment.dropped_mislabel",
                doc_id=doc_id,
                claim_type=claim_type,
                entity_ref=entity_ref,
                polarity=polarity,
                confidence=confidence,
            )
            continue
        kept.append(claim)

    if checks_done:
        logger.info(
            "claim_entailment.complete",
            doc_id=doc_id,
            checked=checks_done,
            dropped=dropped,
            kept=len(kept),
            total=len(claims),
        )
    return kept
