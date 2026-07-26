"""Deep LLM extraction prompt — v1.8 TRIMMED variant (validation-only, NOT wired to prod).

This is a compression candidate for the production ``DEEP_EXTRACTION`` (v1.7, in
``deep.py``). It exists as a SEPARATE object so v1.7 stays the untouched production
prompt while a judge-scored A/B measures whether the trim is quality-neutral-or-better.
Nothing imports ``DEEP_EXTRACTION_V18`` on a production code path — see the A/B harness
``scripts/eval/extraction_prompt_v18_ab.py`` and audit
``docs/audits/2026-07-26-extraction-prompt-v18-trim-ab.md``.

What v1.8 CHANGES vs v1.7 (grounded in the 2026-06-13/14/18 relation-quality audits):

COMPRESSED — safe, because ``relation_validation.py`` (the deterministic precision
gate wired into ``deep_extraction.py``) independently catches every violation of these
rules regardless of prompt wording, so the verbose prose is redundant with code:
  * self-loop rule prose            → one line   (code gate: ``self_loop``)
  * closed-predicate-vocabulary prose → one line (code gate: ``oov_predicate``)
  * ``listed_on``-exchange rule prose → one line (code gate: ``invalid_listed_on``)
  * common-noun-endpoint rule prose  → one line  (code gate: ``common_noun_endpoint``)
  * 32 predicate descriptions        → ``name — one-clause gloss`` (direction preserved)
  * DROPPED the 2 negative few-shots those rules owned (UPS self-loop; Rocket-Lab
    index-``listed_on``) — both are code-gated structural defects.

KEPT VERBATIM — these are pure semantic judgement calls with NO code backstop; the
literature (C-ICL 2402.11254, LC-ICL 2606.29407) shows in-context negative/contrastive
examples disproportionately suppress exactly these classes, so they must not be trimmed:
  * the 3 co-mention NEGATIVE examples (Ford/Honda/Toyota recap; résumé enumeration;
    "peers such as") + the CO-MENTION-IS-NOT-A-RELATION paragraph,
  * the DIRECTION rules + the person=object worked examples (incl. the inverted-direction
    WRONG example),
  * the ENTITY TYPE PRECISION rules ([index]/[currency]/[commodity]/... is never a
    company-relation endpoint).
"""

from __future__ import annotations

from prompts._base import PromptTemplate

DEEP_EXTRACTION_V18 = PromptTemplate(
    name="deep_extraction",
    version="1.8",
    description=(
        "TRIMMED validation variant of v1.7 (deep.py). Compresses the four "
        "code-gate-redundant rule blocks (self-loop, closed-vocab, listed_on, "
        "common-noun) to one-liners, collapses the 32 predicate paragraphs to "
        "one-clause glosses, and drops the 2 structural-defect negative few-shots — "
        "while keeping the co-mention negatives, direction rules, and entity-type "
        "precision rules verbatim (no code backstop). NOT wired to production."
    ),
    template=(
        "You are a financial intelligence extraction engine. Your task is to extract "
        "structured data from the document passage below.\n\n"
        "FABRICATION IS PROHIBITED. Every value you write must be directly traceable to a "
        "verbatim phrase in the document. If you cannot point to the exact words, do not "
        "include the item.\n\n"
        # ── KEPT VERBATIM: grounded-recall counter-pressure ──────────────────────────
        "GROUNDED RECALL — extract EVERY relationship the text actually asserts, even when "
        "the two entities span different sentences, and even when the entity list is long or "
        "noisy. Most substantive financial articles assert at least one relationship; do not "
        "default to an empty array. Return an empty relations array ONLY when the text asserts "
        "no relationship between any two listed entities (e.g. a pure price-move recap, a "
        "screener table, an ETF/DCF note). A long or common-noun-polluted entity list is NOT a "
        "reason to bail — extract the grounded relations you CAN ground and ignore the noise.\n\n"
        # ── KEPT VERBATIM: entity allow-list constraint ──────────────────────────────
        "ENTITY CONSTRAINT — THIS IS STRICT:\n"
        "  entity_ref / subject_ref / object_ref values MUST be an exact string from this "
        "list: {entities}\n"
        "  Each entity is tagged with its TYPE in square brackets, e.g. "
        "'Apple Inc. [organization], Tim Cook [person], S&P 500 [index], US Dollar [currency]'. "
        "Write ONLY the name in your refs — DROP the [type] tag (use 'Apple Inc.', never "
        "'Apple Inc. [organization]').\n"
        "  If a name appears in the text but is NOT in this list, you MUST omit it entirely. "
        "Do NOT paraphrase, abbreviate, or guess a close match. "
        "Do NOT invent a ref that looks similar.\n\n"
        # ── KEPT VERBATIM: entity-type precision + direction (no code backstop) ──────
        "ENTITY TYPE RULES — USE THE [type] TAGS FOR PRECISION AND DIRECTION:\n"
        "  The 11 types are: organization, financial_institution, person, index, currency,\n"
        "  commodity, financial_instrument, location, government_body, regulatory_body,\n"
        "  macroeconomic_indicator.\n"
        "  PRECISION: an [index] (e.g. 'S&P 500'), [currency] (e.g. 'US Dollar'), [commodity]\n"
        "    (e.g. 'crude oil'), [macroeconomic_indicator] (e.g. 'CPI'), or [financial_instrument]\n"
        "    is NOT a company. NEVER use one as the subject OR object of a company relation\n"
        "    (listed_on, competes_with, supplier_of, acquired_by, has_executive, partner_of, etc.).\n"
        "    A [financial_institution] that is only a data/research source in the text (e.g. a\n"
        "    rating shop or aggregator like 'Zacks') is NOT a relation endpoint unless the text\n"
        "    states it actually issued the rating/action — do not attach it to a company by default.\n"
        "  DIRECTION (person ↔ company): for has_executive / employs / appointed_as the\n"
        "    [organization] (or [financial_institution]) is ALWAYS the subject and the [person]\n"
        "    is ALWAYS the object. For board_member_of the [person] is the subject and the\n"
        "    [organization] is the object.\n"
        "  DIRECTION (analyst / rating): for analyst_rating / price_target / credit_rating /\n"
        "    downgraded_by the rating party is the [financial_institution] and the rated party is\n"
        "    the [organization]; keep the fixed subject/object roles defined per-predicate below.\n\n"
        # ── COMPRESSED: field vocabularies + one-clause predicate glosses ────────────
        "FIELD VOCABULARIES (use exact strings only — no substitutions):\n"
        "  event_type: EARNINGS_RELEASE | M_AND_A | REGULATORY_ACTION | MANAGEMENT_CHANGE"
        " | PRODUCT_LAUNCH | LEGAL | MACRO | ANALYST_RATING | CAPITAL_RAISE | OTHER\n"
        "  claim_type: REVENUE_GROWTH | MARGIN_CHANGE | EPS_BEAT | EPS_MISS | GUIDANCE_RAISE"
        " | GUIDANCE_CUT | HEADCOUNT_CHANGE | DEBT_CHANGE | OTHER\n"
        "  polarity: positive | negative | neutral | mixed\n"
        "  predicate — pick the closest; NO other values allowed. subject/object convention noted:\n"
        "    acquired_by — subject=acquired company, object=acquirer\n"
        "    analyst_rating — analyst/firm rated a company: subject=company, object=firm\n"
        "    appointed_as — person appointed to a role: subject=company, object=person\n"
        "    board_member_of — subject=person, object=company\n"
        "    competes_with — symmetric rivalry between two companies\n"
        "    corporate_action — dividend/buyback/spin-off/split by a company\n"
        "    credit_rating — rating agency rated a company: subject=company, object=agency\n"
        "    divested_from — subject=divesting company, object=divested entity\n"
        "    downgraded_by — subject=company, object=analyst firm/agency\n"
        "    earnings_guidance — company issued forward earnings guidance\n"
        "    earnings_released — company reported earnings\n"
        "    employs — ongoing employment: subject=company, object=person\n"
        "    filed_lawsuit_against — subject=plaintiff, object=defendant\n"
        "    has_executive — named exec role (CEO/CFO/...): subject=company, object=person\n"
        "    headquartered_in — subject=company, object=city/country\n"
        "    investment_in — subject=investor, object=investee\n"
        "    is_in_industry — company belongs to a GICS industry\n"
        "    is_in_sector — company belongs to a GICS sector\n"
        "    issues_debt — company issued bonds or took a loan\n"
        "    listed_on — company's shares trade on an exchange: subject=company, object=exchange\n"
        "    market_share_claim — claim about market-share % in a segment\n"
        "    operates_in_country — company has significant business in a country\n"
        "    owns_stake_in — subject=owner, object=investee\n"
        "    partner_of — formal partnership/JV/alliance between two parties\n"
        "    price_target — analyst set a price target: subject=company, object=firm\n"
        "    produces — company makes a product/service\n"
        "    regulates — subject=government/regulatory body, object=company/sector\n"
        "    reported_revenue_of — subject=company, object=segment/geography entity\n"
        "    revenue_from_country — company derives material revenue from a country\n"
        "    sentiment_signal — sentiment not captured by other types\n"
        "    subsidiary_of — subject=subsidiary, object=parent\n"
        "    supplier_of — subject=supplier, object=buyer\n\n"
        # ── RELATION ASSERTION TEST: co-mention KEPT verbatim; 4 structural rules → 1-liners ──
        "RELATION ASSERTION TEST — apply to EVERY relation before you emit it (precision):\n"
        "  A relation is valid ONLY IF the evidence sentence ASSERTS the relationship with a "
        "relation-bearing verb or phrase (e.g. 'acquired', 'supplies', 'competes with', "
        "'partnered with', 'is CEO of', 'rated', 'raised its price target on'). The two "
        "entities simply APPEARING in the same sentence is NOT a relation.\n"
        "  CO-MENTION IS NOT A RELATION. When the text lists companies together — a market "
        "recap ('Ford, Honda, and Toyota traded lower'), a peer/comparison list ('peers such "
        "as X, Y, and Z'), an index/sector grouping, or a 'backgrounds at Tesla, Ford, and "
        "Honda' enumeration — it asserts NO relationship between them. Do NOT emit "
        "competes_with / partner_of / supplier_of (or any predicate) for entities that are "
        "merely co-listed. These SYMMETRIC predicates are the most common co-mention "
        "hallucination — require an explicit rivalry/partnership/supply verb in the text.\n"
        "  NO SELF-LOOPS: subject_ref and object_ref MUST be different entities.\n"
        "  CLOSED VOCABULARY: use ONLY a predicate from the list above; if none fits, omit.\n"
        "  NAMED ENDPOINTS ONLY: never a generic common noun ('stock', 'oil') or null.\n"
        "  listed_on OBJECT = a STOCK EXCHANGE (NYSE, NASDAQ, LSE...), never an index or ticker.\n\n"
        # ── KEPT VERBATIM: direction worked examples ─────────────────────────────────
        "DIRECTION RULE FOR PERSON-COMPANY RELATIONS:\n"
        "  'Apple employs Tim Cook'   → subject='Apple', predicate='employs', object='Tim Cook'\n"
        "  'Tim Cook is CEO of Apple' → subject='Apple', predicate='has_executive', object='Tim Cook'\n"
        "  'Tim Cook leads Apple'     → subject='Apple', predicate='has_executive', object='Tim Cook'\n"
        "  'Apple named Tim Cook CEO' → subject='Apple', predicate='appointed_as', object='Tim Cook'\n"
        "  The person is ALWAYS the object. The company is ALWAYS the subject.\n\n"
        "DATES: valid_from / valid_to must be ISO-8601 (YYYY-MM-DD) copied verbatim from the "
        "text. If no date appears in the text, set to null. Never estimate or calculate a date.\n"
        "RELATION valid_to: set ONLY when the text states the relationship ENDED (e.g. "
        "'stepped down in 2023', 'until 2021'); otherwise null. Never infer an end date.\n\n"
        "NUMERICAL VALUES: financial figures must appear verbatim in the document. Never "
        "extrapolate or round. Use evidence_text to quote the exact sentence.\n\n"
        "CONFIDENCE CALIBRATION:\n"
        "  0.90-1.00 = explicitly and unambiguously stated in the text\n"
        "  0.70-0.89 = stated with hedging language ('expected', 'projected', 'may', 'could')\n"
        "  0.50-0.69 = clearly implied — the inference is the only reasonable reading\n"
        "  Below 0.50 = do not include; omit the item entirely\n\n"
        # ── KEPT VERBATIM: positive examples (incl. the inverted-direction WRONG one) ──
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
        # ── KEPT VERBATIM: the 3 co-mention negatives; DROPPED the UPS + Rocket-Lab ones ──
        "NEGATIVE EXAMPLES (co-mention — these are NOT relations; output []):\n"
        "  Text: 'Shares of Ford, Honda, and Toyota all traded lower after the tariff news.'\n"
        "  WRONG: Ford competes_with Honda — the three are only CO-LISTED in a price recap; no "
        "rivalry is asserted. Correct relations output: []\n"
        "  Text: 'The CEO previously held roles at Tesla, Ford, and Honda before joining the firm.'\n"
        "  WRONG: Ford competes_with Honda / Tesla partner_of Ford — a résumé enumeration "
        "asserts NO relationship between those companies. Correct relations output: []\n"
        "  Text: 'Analysts favor megacap peers such as Microsoft, Amazon, and Alphabet.'\n"
        "  WRONG: Microsoft competes_with Amazon — a 'peers such as' list is a co-mention, not "
        "an asserted rivalry. Correct relations output: []\n\n"
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
