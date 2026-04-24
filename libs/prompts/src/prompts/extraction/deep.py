"""Deep LLM extraction prompt (S6 Block 10 — PRD §6.7)."""

from __future__ import annotations

from prompts._base import PromptTemplate

DEEP_EXTRACTION = PromptTemplate(
    name="deep_extraction",
    version="1.0",
    description=(
        "Structured financial intelligence extraction prompt for Qwen2.5-7B-Instruct. "
        "Extracts events, claims, and relations from a document passage."
    ),
    template=(
        "You are extracting structured financial intelligence from the document passage below.\n"
        "Only extract information that is EXPLICITLY STATED in the text — do not infer.\n\n"
        "ENTITY CONSTRAINT: entity_ref values must be drawn ONLY from this list: {entities}\n"
        "If a mention does not match any entity in the list, do not include it.\n\n"
        "FIELD VOCABULARIES (use exact strings only):\n"
        "  event_type: EARNINGS_RELEASE | M_AND_A | REGULATORY_ACTION | MANAGEMENT_CHANGE"
        " | PRODUCT_LAUNCH | LEGAL | MACRO | ANALYST_RATING | CAPITAL_RAISE | OTHER\n"
        "  claim_type: REVENUE_GROWTH | MARGIN_CHANGE | EPS_BEAT | EPS_MISS | GUIDANCE_RAISE"
        " | GUIDANCE_CUT | HEADCOUNT_CHANGE | DEBT_CHANGE | OTHER\n"
        "  polarity: positive | negative | neutral | mixed\n\n"
        "DATES: valid_from / valid_to must be ISO-8601 (YYYY-MM-DD) extracted verbatim from the text.\n"
        "If no date is stated, set to null — never infer or estimate a date.\n\n"
        "CONFIDENCE CALIBRATION:\n"
        "  0.90-1.00 = explicitly and unambiguously stated in the text\n"
        "  0.70-0.89 = stated but with hedging language ('expected', 'projected', 'may')\n"
        "  0.50-0.69 = implied or inferred from context\n"
        "  Below 0.50 = do not include; omit the item entirely\n\n"
        "Output schema:\n"
        "{{\n"
        '  "events": [{{"event_type": "...", "description": "...", "entity_refs": [...],'
        ' "valid_from": "YYYY-MM-DD|null", "valid_to": "YYYY-MM-DD|null", "confidence": 0.0}}],\n'
        '  "claims": [{{"entity_ref": "...", "claim_type": "...", "polarity":'
        ' "positive|negative|neutral|mixed", "confidence": 0.0, "evidence_text": "..."}}],\n'
        '  "relations": [{{"subject_ref": "...", "predicate": "...", "object_ref": "...",'
        ' "confidence": 0.0}}]\n'
        "}}\n\n"
        "Document:\n{text}\n\n"
        "Return JSON with keys: events, claims, and relations."
        " Each array may be empty. No explanatory text outside JSON."
    ),
    parameters=frozenset({"entities", "text"}),
)
