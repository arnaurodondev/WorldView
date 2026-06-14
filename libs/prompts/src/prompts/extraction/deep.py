"""Deep LLM extraction prompt (S6 Block 10 — PRD §6.7)."""

from __future__ import annotations

from prompts._base import PromptTemplate

DEEP_EXTRACTION = PromptTemplate(
    name="deep_extraction",
    version="1.5",
    description=(
        "Structured financial intelligence extraction prompt for DeepSeek-V4-Flash / "
        "OpenAI-compatible models. Extracts events, claims, and relations from a document passage. "
        "v1.3: added few-shot examples for relations + inline predicate descriptions to reduce "
        "employs/has_executive confusion and improve direction accuracy. "
        "v1.4: added 5 new financial predicates (appointed_as, divested_from, downgraded_by, "
        "filed_lawsuit_against, reported_revenue_of) — PLAN-0089 Lever-4 taxonomy expansion. "
        "v1.5: per-fact temporal validity — relations may carry an optional valid_to "
        "(ISO date the relationship ended, copied verbatim from the text; null otherwise) "
        "that drives bitemporal step-decay in the knowledge graph — PLAN-0109 W5."
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
        "  polarity: positive | negative | neutral | mixed\n"
        "  predicate (relation type — pick the closest match, no other values allowed):\n"
        "    acquired_by      — A was acquired by B: subject=acquired company, object=acquirer\n"
        "    analyst_rating   — analyst/firm issued a rating on a company\n"
        "    appointed_as     — person was appointed to a formal role: subject=COMPANY, object=PERSON\n"
        "                       (use for new hires and role appointments; see also has_executive)\n"
        "    board_member_of  — person sits on board: subject=person, object=company\n"
        "    competes_with    — symmetric rivalry between two companies\n"
        "    corporate_action — dividend, buyback, spin-off, or split announced by company\n"
        "    credit_rating    — rating agency issued a credit rating on a company\n"
        "    divested_from    — company sold or spun off a stake: subject=divesting company,\n"
        "                       object=divested entity (asset, business unit, or company)\n"
        "    downgraded_by    — company was downgraded: subject=company,\n"
        "                       object=analyst firm or rating agency\n"
        "    earnings_guidance — company issued forward earnings guidance\n"
        "    earnings_released — company reported quarterly/annual earnings\n"
        "    employs          — ongoing employment relationship: subject=COMPANY, object=PERSON\n"
        "                       (NEVER use 'employs' when subject is a person — use has_executive)\n"
        "    filed_lawsuit_against — entity filed legal action: subject=plaintiff, object=defendant\n"
        "    has_executive    — named executive role: subject=COMPANY, object=PERSON\n"
        "                       (CEO, CFO, CTO, President, COO, MD, Chairman)\n"
        "                       CRITICAL: subject MUST be the company, object MUST be the person\n"
        "    headquartered_in — company's primary headquarters location (city or country)\n"
        "    investment_in    — fund or company made an investment: subject=investor, object=investee\n"
        "    is_in_industry   — company belongs to a GICS industry (e.g. Semiconductors)\n"
        "    is_in_sector     — company belongs to a broad GICS sector (e.g. Technology)\n"
        "    issues_debt      — company issued bonds or took on a loan\n"
        "    listed_on        — company's shares trade on an exchange\n"
        "    market_share_claim — claim about market share percentage in a segment\n"
        "    operates_in_country — company has significant business in a country\n"
        "    owns_stake_in    — company/person owns equity: subject=owner, object=investee\n"
        "    partner_of       — formal partnership, JV, or alliance between two parties\n"
        "    price_target     — analyst set a price target on a company's stock\n"
        "    produces         — company makes a product or service\n"
        "    regulates        — government body regulates a company or sector\n"
        "    reported_revenue_of — company reported revenue for a specific segment or geography:\n"
        "                       subject=company, object=segment/geography entity\n"
        "    revenue_from_country — company derives material revenue from a country\n"
        "    sentiment_signal — general sentiment expression not captured by other types\n"
        "    subsidiary_of    — A is a subsidiary of B: subject=subsidiary, object=parent\n"
        "    supplier_of      — A supplies goods/services to B: subject=supplier, object=buyer\n\n"
        "DIRECTION RULE FOR PERSON-COMPANY RELATIONS:\n"
        "  'Apple employs Tim Cook'   → subject='Apple', predicate='employs', object='Tim Cook'\n"
        "  'Tim Cook is CEO of Apple' → subject='Apple', predicate='has_executive', object='Tim Cook'\n"
        "  'Tim Cook leads Apple'     → subject='Apple', predicate='has_executive', object='Tim Cook'\n"
        "  'Apple named Tim Cook CEO' → subject='Apple', predicate='appointed_as', object='Tim Cook'\n"
        "  The person is ALWAYS the object. The company is ALWAYS the subject.\n\n"
        "DATES: valid_from / valid_to must be ISO-8601 (YYYY-MM-DD) copied verbatim from the "
        "text. If no date appears in the text, set to null. Never estimate or calculate a date.\n"
        "RELATION valid_to: for a relation, set valid_to ONLY when the text states the "
        "relationship ENDED (e.g. 'stepped down in 2023', 'sold its stake in March 2024', "
        "'until 2021'). Otherwise set it to null. Never infer an end date that is not stated.\n\n"
        "NUMERICAL VALUES: financial figures (percentages, amounts, counts) must appear "
        "verbatim in the document. Never extrapolate or round. Use evidence_text to quote "
        "the exact sentence.\n\n"
        "CONFIDENCE CALIBRATION:\n"
        "  0.90-1.00 = explicitly and unambiguously stated in the text\n"
        "  0.70-0.89 = stated with hedging language ('expected', 'projected', 'may', 'could')\n"
        "  0.50-0.69 = clearly implied — the inference is the only reasonable reading\n"
        "  Below 0.50 = do not include; omit the item entirely\n\n"
        "EXAMPLES (correct extraction):\n"
        "  Text: 'TSMC supplies chips to Apple and Nvidia.'\n"
        '  Correct: [{{"subject_ref": "TSMC", "predicate": "supplier_of", "object_ref": "Apple", '
        '"confidence": 0.95, "evidence_text": "TSMC supplies chips to Apple and Nvidia."}},\n'
        '           {{"subject_ref": "TSMC", "predicate": "supplier_of", "object_ref": "Nvidia", '
        '"confidence": 0.95, "evidence_text": "TSMC supplies chips to Apple and Nvidia."}}]\n\n'
        "  Text: 'Satya Nadella, CEO of Microsoft, announced the deal.'\n"
        '  Correct: [{{"subject_ref": "Microsoft", "predicate": "has_executive", '
        '"object_ref": "Satya Nadella", "confidence": 0.97, '
        '"evidence_text": "Satya Nadella, CEO of Microsoft"}}]\n'
        '  WRONG (inverted direction): {{"subject_ref": "Satya Nadella", '
        '"predicate": "has_executive", "object_ref": "Microsoft"}}\n\n'
        "  Text: 'Google competes with Microsoft in cloud infrastructure.'\n"
        '  Correct: [{{"subject_ref": "Google", "predicate": "competes_with", '
        '"object_ref": "Microsoft", "confidence": 0.92, '
        '"evidence_text": "Google competes with Microsoft in cloud infrastructure."}}]\n\n'
        "  Text: 'ARM Holdings is a subsidiary of SoftBank.'\n"
        '  Correct: [{{"subject_ref": "ARM Holdings", "predicate": "subsidiary_of", '
        '"object_ref": "SoftBank", "confidence": 0.96, '
        '"evidence_text": "ARM Holdings is a subsidiary of SoftBank."}}]\n\n'
        "Output schema (JSON only — no text before or after the object):\n"
        "{{\n"
        '  "events": [{{"event_type": "...", "description": "...", "entity_refs": [...],'
        ' "valid_from": "YYYY-MM-DD|null", "valid_to": "YYYY-MM-DD|null",'
        ' "evidence_text": "...", "confidence": 0.0}}],\n'
        '  "claims": [{{"entity_ref": "...", "claim_type": "...", "polarity":'
        ' "positive|negative|neutral|mixed", "confidence": 0.0, "evidence_text": "..."}}],\n'
        '  "relations": [{{"subject_ref": "...", "predicate": "...", "object_ref": "...",'
        ' "confidence": 0.0, "evidence_text": "...", "valid_to": "YYYY-MM-DD|null"}}]\n'
        "}}\n\n"
        "Document:\n{text}\n\n"
        "Return the JSON object above. Each array may be empty if nothing qualifies. "
        "Output the JSON object only — no markdown fences, no explanation, no preamble."
    ),
    parameters=frozenset({"entities", "text"}),
)
