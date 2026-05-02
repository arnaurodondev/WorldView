"""Deep LLM extraction prompt (S6 Block 10 — PRD §6.7)."""

from __future__ import annotations

from prompts._base import PromptTemplate

DEEP_EXTRACTION = PromptTemplate(
    name="deep_extraction",
    version="1.1",
    description=(
        "Structured financial intelligence extraction prompt for DeepSeek-V4-Flash / "
        "OpenAI-compatible models. Extracts events, claims, and relations from a document passage."
    ),
    template=(
        "You are a financial intelligence extraction engine. Your task is to extract "
        "structured data from the document passage below.\n\n"
        "FABRICATION IS PROHIBITED. Every value you write must be directly traceable to a "
        "verbatim phrase in the document. If you cannot point to the exact words, do not "
        "include the item. An empty array is a correct and expected output when nothing "
        "qualifies.\n\n"
        "ENTITY CONSTRAINT — THIS IS STRICT:\n"
        "  entity_ref / subject_ref / object_ref values MUST be an exact string from this "
        "list: {entities}\n"
        "  If a name appears in the text but is NOT in this list, you MUST omit it entirely. "
        "Do NOT paraphrase, abbreviate, or guess a close match. "
        "Do NOT invent a ref that looks similar.\n\n"
        "FIELD VOCABULARIES (use exact strings only — no substitutions):\n"
        "  event_type: EARNINGS_RELEASE | M_AND_A | REGULATORY_ACTION | MANAGEMENT_CHANGE"
        " | PRODUCT_LAUNCH | LEGAL | MACRO | ANALYST_RATING | CAPITAL_RAISE | OTHER\n"
        "  claim_type: REVENUE_GROWTH | MARGIN_CHANGE | EPS_BEAT | EPS_MISS | GUIDANCE_RAISE"
        " | GUIDANCE_CUT | HEADCOUNT_CHANGE | DEBT_CHANGE | OTHER\n"
        "  polarity: positive | negative | neutral | mixed\n\n"
        "DATES: valid_from / valid_to must be ISO-8601 (YYYY-MM-DD) copied verbatim from the "
        "text. If no date appears in the text, set to null. Never estimate or calculate a date.\n\n"
        "NUMERICAL VALUES: financial figures (percentages, amounts, counts) must appear "
        "verbatim in the document. Never extrapolate or round. Use evidence_text to quote "
        "the exact sentence.\n\n"
        "CONFIDENCE CALIBRATION:\n"
        "  0.90-1.00 = explicitly and unambiguously stated in the text\n"
        "  0.70-0.89 = stated with hedging language ('expected', 'projected', 'may', 'could')\n"
        "  0.50-0.69 = clearly implied — the inference is the only reasonable reading\n"
        "  Below 0.50 = do not include; omit the item entirely\n\n"
        "Output schema (JSON only — no text before or after the object):\n"
        "{{\n"
        '  "events": [{{"event_type": "...", "description": "...", "entity_refs": [...],'
        ' "valid_from": "YYYY-MM-DD|null", "valid_to": "YYYY-MM-DD|null",'
        ' "evidence_text": "...", "confidence": 0.0}}],\n'
        '  "claims": [{{"entity_ref": "...", "claim_type": "...", "polarity":'
        ' "positive|negative|neutral|mixed", "confidence": 0.0, "evidence_text": "..."}}],\n'
        '  "relations": [{{"subject_ref": "...", "predicate": "...", "object_ref": "...",'
        ' "confidence": 0.0, "evidence_text": "..."}}]\n'
        "}}\n\n"
        "Document:\n{text}\n\n"
        "Return the JSON object above. Each array may be empty if nothing qualifies. "
        "Output the JSON object only — no markdown fences, no explanation, no preamble."
    ),
    parameters=frozenset({"entities", "text"}),
)
