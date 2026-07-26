"""Co-mention entailment check for extracted relations (ENHANCEMENT #6 — prototype).

Why this block exists
---------------------
The trustworthy stored-relation re-measurement
(``docs/audits/2026-06-20-stored-relation-quality-remeasurement.md``) found the
DOMINANT relation defect is the extractor promoting a CO-MENTION — two entities
merely appearing in the same text — into an asserted relation. This is a *semantic*
defect: every co-mention relation is STRUCTURALLY valid, so the deterministic gate
(``relation_validation.py``) cannot catch it. It is concentrated in loose/symmetric
predicates: ``competes_with`` (33% supported), ``regulates`` (18%), ``produces``
(27%), ``partner_of`` (54%), ``supplier_of``.

What this block does
--------------------
For each relation whose predicate is in the configured HIGH-RISK set, it asks a cheap
LLM a single binary question: does the evidence ASSERT this relation with a
relation-bearing verb/phrase, or do the entities only CO-OCCUR? Relations the model
confidently marks NOT_ASSERTED are dropped; everything else is kept untouched.

Measurement (BEFORE wiring — see prototype harness
``scripts/eval/prototype_entailment_check.py`` and audit
``docs/audits/2026-06-21-relation-entailment-check-prototype.md``):
  * Gold set: 443 real stored relations, strong-judge (Qwen3-235B + direction
    conventions) labelled SUPPORTED / CO_MENTION / WRONG_DIRECTION /
    WRONG_PREDICATE / UNSUPPORTED.
  * Qwen3-235B as the cheap check: on the 5 high-risk predicates, **0% false-positive
    rate** (zero good relations killed), **88.6% recall** of co-mention/unsupported
    defects, ~$0.07 per 1k checks (~412 in / 32 out tokens/call).
  * gpt-oss-20b was REJECTED: 27.6% false-positive on the same predicates — it kills
    ~1 in 4 good relations. Cheaper is not good enough here.

Design invariants
-----------------
* **Default OFF** (``relation_entailment_check_enabled``). Enabling it changes
  extraction output, so it is opt-in and must be watched.
* **Scoped** to the configured predicate set — every other relation skips the LLM
  call entirely (no added cost/latency).
* **Fail-OPEN**: any LLM/parse error, a missing-evidence relation, or a low-confidence
  verdict KEEPS the relation. The check can only ever *remove* a relation it is
  confident is a co-mention; it must never destroy a relation on infrastructure noise.
* **Capped** at ``max_per_doc`` checks per document.
* Reuses the existing ``ExtractionClient`` abstraction (same client the extractor
  uses) — no new infrastructure.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from ml_clients.protocols import ExtractionClient  # type: ignore[import-not-found]
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]

    from nlp_pipeline.application.ports.entailment_cache import EntailmentCachePort

logger = structlog.get_logger(__name__)

# Default cache TTL for verifier verdicts (30 days) — see claim_entailment.py's
# ``DEFAULT_CACHE_TTL_S`` for the full rationale: the verifier call is
# deterministic (temperature=0.0), so the only staleness vector is a PROMPT
# change, which is handled by bumping ``template_id`` (part of the cache key),
# not by TTL expiry. 30 days bounds an abandoned entry's lifetime while still
# covering the redundant-verification window (duplicate/updated articles).
DEFAULT_CACHE_TTL_S: int = 30 * 24 * 3600

# Default high-risk predicate set (audit ENHANCEMENT #6). Mirrors the config default;
# the runtime set comes from ``Settings.relation_entailment_check_predicates``.
DEFAULT_HIGH_RISK_PREDICATES: frozenset[str] = frozenset(
    {"competes_with", "regulates", "produces", "partner_of", "supplier_of"}
)

# One-line predicate meanings injected into the prompt (kept short — cost control).
_PREDICATE_MEANING: dict[str, str] = {
    "competes_with": "SUBJECT is a competitor/rival of OBJECT (symmetric)",
    "regulates": "SUBJECT (a regulator/government body) regulates OBJECT",
    "produces": "SUBJECT (a company) makes/manufactures OBJECT (a product/service)",
    "partner_of": "SUBJECT has a formal partnership/JV/alliance with OBJECT (symmetric)",
    "supplier_of": "SUBJECT supplies goods/services TO OBJECT",
}

# Binary output schema for the cheap entailment client.
_ENTAILMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "asserted": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["asserted", "confidence"],
}

# Strict prompt — tuned to MINIMISE FALSE POSITIVES (killing a good relation is the
# critical risk). Default-towards-ASSERTED on any doubt; only confidently flag pure
# co-mention. Validated at 0% false-positive on high-risk predicates with Qwen3-235B.
_SYSTEM_PROMPT = (
    "You are a strict entailment checker for a knowledge graph. You receive a candidate "
    "relation triple (SUBJECT, PREDICATE, OBJECT), a one-line MEANING of the predicate, and "
    "an EVIDENCE snippet. Your ONLY job: does the evidence ASSERT this relation with a "
    "relation-bearing verb or phrase that connects THIS subject to THIS object — or do the "
    "two entities merely CO-OCCUR (listed together, adjacent, both mentioned) without the "
    "relation being stated?\n\n"
    "Rules:\n"
    "- ASSERTED requires a verb/phrase that actually expresses the relation between the two "
    "named entities (e.g. 'X acquired Y', 'X, a supplier to Y', 'X competes with Y'). "
    "Apposition and titles count. Hedged verbs ('agreed to','plans to') count. For symmetric "
    "predicates (competes_with, partner_of) either order is fine.\n"
    "- NOT_ASSERTED means the snippet only co-mentions the entities, or talks about a "
    "DIFFERENT relation, or does not connect them at all.\n"
    "- CRITICAL: when in ANY doubt, answer ASSERTED. Only answer NOT_ASSERTED (asserted=false) "
    "when you are confident the relation is NOT stated. Do not penalise direction or a "
    "slightly-off predicate — if SOME relation-bearing language links the two entities, "
    "answer ASSERTED.\n\n"
    "Output STRICT JSON only:\n"
    '{"asserted": true|false, "confidence": 0.0-1.0, "reason": "<=14 words"}'
)


def _build_prompt(subject_ref: str, predicate: str, object_ref: str, evidence: str) -> str:
    meaning = _PREDICATE_MEANING.get(predicate, predicate.replace("_", " "))
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"SUBJECT: {subject_ref}\n"
        f"PREDICATE: {predicate} ({meaning})\n"
        f"OBJECT: {object_ref}\n"
        f"EVIDENCE: {evidence}\n\n"
        "Does the EVIDENCE assert this relation between SUBJECT and OBJECT, or do they only "
        "co-occur? Return the strict JSON."
    )


def _parse_verdict(output: Any) -> tuple[bool, float] | None:
    """Extract (asserted, confidence) from an ExtractionOutput. None on any parse failure.

    Reads ``output.result`` first (structured), falling back to parsing
    ``output.raw_response`` JSON. Returns None (=> fail-open keep) if neither yields a
    usable boolean ``asserted``.
    """
    payload: dict[str, Any] | None = None
    result = getattr(output, "result", None)
    if isinstance(result, dict) and "asserted" in result:
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
    if payload is None or not isinstance(payload.get("asserted"), bool):
        return None
    asserted = bool(payload["asserted"])
    try:
        confidence = float(payload.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 1.0
    return asserted, confidence


def _parse_verdict_dict(payload: dict[str, Any]) -> tuple[bool, float] | None:
    """Extract (asserted, confidence) from a cached verdict dict.

    Same semantics as ``_parse_verdict``: a missing/non-boolean ``asserted`` is an
    unusable payload (falls through to the normal miss/LLM path); a missing/
    non-numeric ``confidence`` defaults to 1.0 (matches the LLM-response parser's
    default — NOT_ASSERTED with no confidence is historically treated as fully
    confident here, unlike the claim-entailment gate's more conservative 0.0
    default; preserved for behavioural parity with cache-miss verdicts).
    """
    if not isinstance(payload.get("asserted"), bool):
        return None
    asserted = bool(payload["asserted"])
    try:
        confidence = float(payload.get("confidence", 1.0))
    except (TypeError, ValueError):
        confidence = 1.0
    return asserted, confidence


async def check_relation_entailment(
    relations: list[dict[str, Any]],
    *,
    entailment_client: ExtractionClient,
    model_id: str,
    high_risk_predicates: frozenset[str] | set[str] = DEFAULT_HIGH_RISK_PREDICATES,
    min_drop_confidence: float = 0.7,
    max_per_doc: int = 20,
    doc_id: str | None = None,
    usage_logger: LlmUsageLogProtocol | None = None,
    cache: EntailmentCachePort | None = None,
    cache_ttl_s: int = DEFAULT_CACHE_TTL_S,
) -> list[dict[str, Any]]:
    """Drop high-risk relations whose evidence merely co-mentions subject and object.

    Args:
        relations: extracted relation dicts (``subject_ref``/``predicate``/``object_ref``/
            ``evidence_text``). NON-risky predicates and relations without evidence are
            returned unchanged (no LLM call).
        entailment_client: an ExtractionClient (the cheap model). Reuses the extraction
            abstraction — pass the same DeepInfra-backed adapter, ideally pointed at the
            validated cheap model (Qwen3-235B).
        model_id: model id to tag the ExtractionInput with.
        high_risk_predicates: only these predicates are checked.
        min_drop_confidence: a NOT_ASSERTED verdict below this confidence is IGNORED
            (the relation is kept) — second guard against false positives.
        max_per_doc: hard cap on LLM CALLS for this document. Cache HITS are free and
            do not count against this cap (only a cache MISS spends an LLM call).
        doc_id: for logging only.
        usage_logger: optional cost-log repository. When provided, EVERY verifier
            call (success OR failure) appends one row to ``nlp_db.llm_usage_log``
            so this Qwen3-235B spend is visible on the cost dashboards instead of
            only incrementing an unscraped in-process counter. Fail-open: a
            logging error never affects the returned relations.
        cache: optional content-addressed result cache (see
            ``entailment_cache_key.py``). The verifier call is deterministic
            (temperature=0.0), so a HIT skips the LLM call entirely and reuses the
            cached verdict; a MISS calls the LLM as before and then writes the
            verdict back. None (default) = no caching (pre-existing behaviour).
            A cache error is fail-open: it is treated as a miss.
        cache_ttl_s: TTL (seconds) for newly-written cache entries. Ignored on a hit.

    Returns:
        A new list with confidently-co-mention relations removed. FAIL-OPEN: on any
        error the relation is kept. Order is preserved.
    """
    from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-not-found]

    from nlp_pipeline.application.blocks.entailment_cache_key import build_cache_key
    from nlp_pipeline.application.blocks.entailment_usage import log_entailment_usage

    risky = frozenset(high_risk_predicates)
    kept: list[dict[str, Any]] = []
    checks_done = 0
    dropped = 0
    cache_hits = 0

    for relation in relations:
        predicate = str(relation.get("predicate", ""))
        evidence = str(relation.get("evidence_text", "") or "").strip()
        subject_ref = str(relation.get("subject_ref", ""))
        object_ref = str(relation.get("object_ref", ""))

        # Skip the LLM (and the cache lookup) entirely unless: risky predicate, has
        # evidence, both refs. The per-doc LLM-call cap is checked separately, below
        # the cache lookup, so a cache HIT never consumes it.
        if predicate not in risky or not evidence or not subject_ref or not object_ref:
            kept.append(relation)
            continue

        template_id = "relation_entailment_v1"
        cache_key = (
            build_cache_key("relation", model_id, template_id, subject_ref, predicate, object_ref, evidence)
            if cache is not None
            else None
        )

        verdict: tuple[bool, float] | None = None
        served_from_cache = False
        if cache is not None and cache_key is not None:
            try:
                cached_payload = await cache.get(cache_key)
            except Exception:
                # Fail-open: a cache error is treated as a miss, never a failure.
                logger.warning("relation_entailment.cache_get_failed", doc_id=doc_id, exc_info=True)
                cached_payload = None
            if cached_payload is not None:
                cached_verdict = _parse_verdict_dict(cached_payload)
                if cached_verdict is not None:
                    verdict = cached_verdict
                    served_from_cache = True
                    cache_hits += 1
                    logger.info(
                        "relation_entailment.cache_hit",
                        doc_id=doc_id,
                        predicate=predicate,
                        subject_ref=subject_ref,
                        object_ref=object_ref,
                    )

        if not served_from_cache:
            if checks_done >= max_per_doc:
                kept.append(relation)
                continue

            checks_done += 1
            prompt = _build_prompt(subject_ref, predicate, object_ref, evidence)
            # Capture latency around the LLM call only (not the parse path) and record
            # the call in llm_usage_log so the verifier's Qwen3-235B spend is visible on
            # the cost dashboards — mirrors deep_extraction._run_extraction_window.
            t0 = time.perf_counter()
            output = None
            extract_succeeded = False
            try:
                output = await entailment_client.extract(
                    ExtractionInput(
                        prompt=prompt,
                        context="",
                        output_schema=_ENTAILMENT_SCHEMA,
                        model_id=model_id,
                        template_id=template_id,
                    )
                )
                extract_succeeded = True
            except Exception:
                # Fail-open: infrastructure noise must never destroy a relation.
                logger.warning(
                    "relation_entailment.check_failed",
                    doc_id=doc_id,
                    predicate=predicate,
                    exc_info=True,
                )
            finally:
                if usage_logger is not None:
                    await log_entailment_usage(
                        usage_logger,
                        entailment_client=entailment_client,
                        model_id=model_id,
                        prompt=prompt,
                        output=output,
                        latency_ms=int((time.perf_counter() - t0) * 1000),
                        success=extract_succeeded,
                        doc_id=doc_id,
                        event_name="relation_entailment.usage_log_failed",
                    )
            if not extract_succeeded:
                kept.append(relation)
                continue

            verdict = _parse_verdict(output)
            if verdict is None:
                # Unparseable verdict => keep (fail-open).
                kept.append(relation)
                continue

            if cache is not None and cache_key is not None:
                try:
                    await cache.set(cache_key, {"asserted": verdict[0], "confidence": verdict[1]}, cache_ttl_s)
                except Exception:
                    # Fail-open: a failed write only costs a future re-verification,
                    # never affects the verdict just computed.
                    logger.warning("relation_entailment.cache_set_failed", doc_id=doc_id, exc_info=True)

        if verdict is None:
            # Unreachable in practice (every path above either ``continue``s or sets
            # ``verdict``) — kept as a defensive fail-open guard + mypy narrowing.
            kept.append(relation)
            continue

        asserted, confidence = verdict
        # Drop ONLY when confidently NOT asserted.
        if (not asserted) and confidence >= min_drop_confidence:
            dropped += 1
            logger.info(
                "relation_entailment.dropped_co_mention",
                doc_id=doc_id,
                predicate=predicate,
                subject_ref=subject_ref,
                object_ref=object_ref,
                confidence=confidence,
            )
            continue
        kept.append(relation)

    if checks_done or cache_hits:
        logger.info(
            "relation_entailment.complete",
            doc_id=doc_id,
            checked=checks_done,
            cache_hits=cache_hits,
            dropped=dropped,
            kept=len(kept),
            total=len(relations),
        )
    return kept
