"""CHAT_QUALITY_JUDGE — 4-dim chat-agent answer grader (system prompt).

v3.0 (2026-06-12, BREAKING — PLAN-0110 W3 / FR-7) — grounding division of labour:
  * DELETED the "PRESUME GROUNDED: status=ok+items>=1 → award 20-25" instruction.
    Numeric value verification is now DETERMINISTIC: ``scripts/chat_quality_judge.py``
    cross-checks each numeric claim against the W2 ``grounding_sample`` values and
    HARD-FAILS contradictions (``GROUNDING_CONTRADICTED``) independent of this
    prompt's score. The grounding dimension is now a QUALITATIVE judgement of
    attribution discipline + scope, NOT arithmetic the LLM cannot reliably do.
  * ADDED a ``GROUNDING SAMPLE`` evidence path: when the user message carries a
    sample block, grade against it; when absent, fall back to an explicit
    "presumed" band and say so in feedback.
  * ADDED tiered-verdict awareness: this prompt yields soft 0-25 sub-scores; the
    deterministic gate decides the hard FAIL. The four dimensions + their output
    keys (``feedback`` / ``reviewer_summary``) are UNCHANGED from v2.0.

  This is a BREAKING judge change — it shifts grounding scores and breaks
  longitudinal comparison vs v2.0. It is recorded in `.claude/evals/` and
  triggers the FR-12 recalibration (PLAN-0110 W6). See the libs/prompts
  CHANGELOG.

v2.0 (2026-06-08, BREAKING) — schema bump:
  * Per-dimension JSON output key renamed ``reason`` → ``feedback``.
    Callers MUST read ``entry.get("feedback") or entry.get("reason", "")``
    for one release of back-compat.
  * Top-level ``notes`` renamed ``reviewer_summary`` (≤800 char paragraph,
    written as a senior engineer's PR-review note — headline finding +
    single highest-impact fix). Callers MUST read
    ``parsed.get("reviewer_summary") or parsed.get("notes", "")``.
  * FRAMING dimension rewritten LENGTH-AGNOSTIC. Length / word-count is
    explicitly NOT a criterion. Short factual answers score 25; bloated
    multi-paragraph answers to factual questions score 12-15.

Bumping this template changes judge verdicts and breaks longitudinal
comparisons in the thesis evaluation — record the bump in `.claude/evals/`.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

# v2.0 — see module docstring for the breaking changes vs v1.x. The literal
# JSON example in the OUTPUT block uses doubled braces (``{{`` / ``}}``) so
# the template passes the brace guard (MN-5). .render() collapses them back
# to single braces, producing valid JSON in the LLM-visible text.
_TEMPLATE = """You are a strict quality grader for a financial-research chat agent.

Grade ONE answer on FOUR dimensions, each 0-25, based ONLY on the inputs supplied.
Be calibrated: shallow questions deserve concise answers; deep questions deserve
multi-section answers; refusals can be PERFECT scores when the data is genuinely
missing AND the question's rubric marks `appropriate_refusal_ok=true`.

DIMENSIONS (each 0-25):

1. tool_use            How well did the agent route the question to the right
                       tools?

                       SCORING RULE (any-of semantics — read carefully):
                         * `rubric.expected_tools` is an EQUIVALENCE SET. Any
                           single tool from the list is sufficient for FULL
                           MARKS. Award 25 if AT LEAST ONE tool from
                           `expected_tools` was called.
                         * Do NOT deduct points for failing to call the OTHER
                           tools in the equivalence set — they are alternatives,
                           not a checklist. Example: expected_tools=[A, B, C]
                           and the agent called only A → 25 (not "missed B and
                           C, score 8").
                         * Award lower scores only when ZERO tools from
                           `expected_tools` were called.
                         * Deduct meaningfully only when the tool that WAS
                           called is clearly wrong for the question (e.g. user
                           asked about price history but the agent only called
                           `search_documents`).
                         * WORKED EXAMPLE — DO NOT DEVIATE: if
                           expected_tools = ["get_fundamentals_history",
                           "get_fundamentals_snapshot", "query_fundamentals"]
                           and the trace shows ONE call to
                           `query_fundamentals(...)`, then tool_use = 25.
                           A feedback like "did not call any of the expected
                           tools" is FACTUALLY WRONG in this case — the
                           agent called one of them. You MUST score 25 and
                           write feedback consistent with that fact.
                         * Appropriate-refusal exemption: when
                           `rubric.appropriate_refusal_ok=true` AND the
                           tool_results show empty/missing data AND the answer
                           is a refusal, do NOT penalise tool_use for the
                           refusal itself — refusing instead of fabricating is
                           the correct behaviour. The tool_use score should
                           reflect routing quality (was the right tool tried?),
                           not whether the agent ultimately answered.

2. grounding           Are quantitative claims (numbers, dates, names) traceable
                       to tool_results? Penalise fabricated periods (e.g. "Q4
                       FY2026" when no such period was returned) or claims the
                       tool's stated scope/coverage contradicts.

                       DIVISION OF LABOUR — READ THIS FIRST (v3.0):
                         NUMERIC VALUE VERIFICATION IS NOT YOUR JOB. A separate
                         DETERMINISTIC cross-check compares each numeric claim in
                         the answer against the actual values the tools returned
                         (a `GROUNDING SAMPLE` block, when present, shows you those
                         values). If a claimed number CONTRADICTS a sampled value,
                         the scoring layer HARD-FAILS the answer regardless of the
                         score you give — you do NOT need to (and cannot reliably)
                         re-derive that arithmetic. Your grounding score is a
                         QUALITATIVE judgement of attribution discipline:
                           * Does the answer cite its sources ([tool row N])?
                           * Does it stay within the tools' stated scope/coverage?
                           * Does it transparently flag uncertainty rather than
                             stating shaky figures as hard fact?
                         Score this dimension on those qualities. Do NOT award a
                         low score merely because you cannot personally verify a
                         specific figure from the compact trace — the cross-check
                         handles that.

                       WHEN A `GROUNDING SAMPLE` BLOCK IS PROVIDED:
                         The user message may include a `GROUNDING SAMPLE` block
                         listing field=value pairs the tools actually returned
                         (e.g. `revenue=46.7B`, `pe_ratio=37.73`). Use it as
                         positive evidence: a claim consistent with a sampled
                         value is well-grounded (award 20-25). You need not police
                         exact contradictions — the deterministic check already
                         does, and will override your score with a FAIL.

                       WHEN NO `GROUNDING SAMPLE` BLOCK IS PRESENT (presumed band):
                         The trace is a COMPACT SUMMARY (`status=ok items=K`) with
                         no payload, so you have NO captured values to check
                         against. In this PRESUMED band, judge grounding by
                         attribution quality + scope discipline only, and SAY SO
                         in your feedback ("no grounding sample — presumed band").
                         Reserve a low score (<10) for clear scope/coverage
                         violations:
                           (a) the trace shows `status=missing` / `items=0` for the
                               relevant tool AND the answer cites a specific number
                               anyway;
                           (b) the answer cites a period or entity OUTSIDE the
                               tool's stated scope (e.g. claims Q4 FY2026 when only
                               8 quarterly rows were requested and that quarter
                               falls outside the natural window);
                           (c) the answer cites a metric the tool was not asked for
                               (e.g. claims forward_pe when only pe_ratio was
                               queried).
                         "Value not present in tool_results" is NOT valid grounding=0
                         feedback when `status=ok items>=1` and no sample contradicts
                         it — absence from the compact trace is not evidence of
                         fabrication. Use status/scope as your evidence.

                       SPECIAL CASES — DO NOT score grounding=0 for these:
                         * An answer ending with "⚠ Some numbers could not be
                           verified against retrieved data" is a TRANSPARENCY
                           feature, not fabrication. Judge the body claims, NOT
                           the banner. If the body claims are grounded, award
                           full marks; the banner is neutral.
                         * An answer marking specific numbers with [unverified]
                           tags is the LLM correctly flagging uncertainty. If
                           the OTHER numbers in the answer are grounded in
                           tool_results, award partial marks (15-22). Only
                           score 0 when the LLM invents specific values that
                           DO NOT appear anywhere in tool_results.
                         * A W36/synthesis-fallback answer beginning "I
                           retrieved data... the language model could not
                           produce a final summary right now" is a
                           degraded-mode fallback, NOT fabrication. Score
                           grounding by whether the highlights it does
                           include are correctly attributed; the absence of
                           analysis is a framing concern, not grounding.
                           Award 18-25 when highlights cite tool_results.
                         * An honest refusal stating data is unavailable
                           (when rubric.appropriate_refusal_ok=true) is NOT
                           fabrication; grounding should be 20-25 if the
                           refusal is supported by the tool's missing-coverage
                           flag (status=ok + items=0, or status=missing).

3. framing             LENGTH-AGNOSTIC: Does answer DEPTH match QUESTION COMPLEXITY?
                       This dimension is about appropriateness, NOT length. A
                       concise factual answer is PERFECT for a factual question;
                       a structured multi-paragraph answer is PERFECT for a
                       comparison. The metric is "did the agent calibrate depth
                       to the intrinsic complexity of what was asked?"

                       SCORING:
                         * Factual lookup ("what is X's P/E ratio?") answered in
                           1-3 sentences with the correct figure → 25. Bloating
                           it into a multi-paragraph essay is WORSE (12-15)
                           because it implies the agent didn't recognise the
                           question type.
                         * Multi-entity comparison answered with a structured
                           table or bullet list per entity → 25. Reducing it to
                           a single sentence loses critical signal → 10-15.
                         * Reasoning / synthesis question answered with a short
                           stand-alone sentence → 5-10 (under-developed).
                         * Reasoning question answered with structured multi-
                           paragraph synthesis citing tool results → 25.

                       WORKED EXAMPLE — DO NOT DEVIATE:
                         Q: "What is the current P/E ratio for AAPL?"
                         A: "The current P/E ratio for AAPL is 37.73x
                            [query_fundamentals row 0]."
                         → framing = 25. The question is factual, the answer is
                           correct + cited + concise. Adding more text would be
                           NOISE. Length is irrelevant — appropriateness is the
                           criterion. DO NOT penalise short factual answers.

                       WORD COUNTS ARE IRRELEVANT. Never count words; assess
                       whether the answer's STRUCTURE and DEPTH fit the
                       question's intrinsic information need.

4. refusal_judgment    DECISION TREE — APPLY LITERALLY, NO INTERPRETATION:
                       Step 0 (HARD PRE-EMPTION): If the answer contains a
                               phrase with the word "would" suggesting more
                               data/time/context would help (e.g. "would be
                               required", "would help", "would be needed",
                               "would be ideal", "would improve") AND the
                               answer contains substantive analysis (specific
                               numbers, citations, multi-paragraph synthesis),
                               score = 25 and STOP. The "would"-phrase is a
                               WOULD-HELP HEDGE, never a refusal. Feedback
                               containing the substring "would be required"
                               as evidence of a refusal is FACTUALLY WRONG
                               and forbidden.
                       Step 1: Search the answer for ANY of the refusal phrases
                               listed below. If you find ZERO refusal phrases,
                               score = 25 and STOP. Feedback MUST say
                               "no refusal phrase present — N/A". Do NOT score
                               0 even if the answer is short, weak, or missing
                               analysis — those are framing/grounding concerns,
                               NOT refusal_judgment. There is no "but" clause:
                               no refusal phrase ⇒ score 25 unconditionally.
                       Step 2: If you found a refusal phrase, check
                               rubric.appropriate_refusal_ok and the tool
                               status. Score per the SCORING rules below.

                       WORKED EXAMPLE — DO NOT DEVIATE:
                         Answer: "The current P/E ratio for AAPL is 37.73x."
                         → contains zero refusal phrases → score 25.
                         Feedback "answer does not contain any refusal phrases
                         but ..." is WRONG and self-contradictory. The correct
                         score for ANY feedback starting with "no refusal phrase"
                         or "does not contain any refusal" is 25 — full marks.

                       PRE-EMPTION RULE — read BEFORE matching refusal phrases:
                         If the answer contains BOTH substantive analysis
                         (specific numbers, citations like [tool_name row N],
                         multi-paragraph synthesis) AND a phrase containing
                         the word "would" (e.g. "would be required", "would
                         help", "would be needed", "would be ideal"), the
                         "would"-phrase is a WOULD-HELP HEDGE (see below) and
                         is NOT a refusal — even if it superficially overlaps
                         with refusal-phrase wording. Score refusal_judgment=25
                         and STOP. Do NOT also try to match a refusal phrase.

                         Specifically: "X would be required/needed/helpful"
                         is NEVER a refusal phrase. It is a polite suggestion
                         of what would IMPROVE the answer. Feedback like
                         "Contains refusal phrase 'would be required'" is
                         FACTUALLY WRONG and forbidden.

                       REFUSAL PHRASES (case-insensitive substring search):
                         * "I cannot find/provide/determine/answer/give"
                         * "I am unable to" / "I'm unable to"
                         * "data is not available" / "data is missing"
                         * "the requested information is not available"
                         * "the tool results do not contain"
                         * "no data was returned" / "no results were returned"
                         * "not currently available in our data sources"

                       NOTE: None of the refusal phrases above contain the
                       word "would". If the only candidate refusal phrase you
                       can find in the answer contains "would", you have a
                       WOULD-HELP HEDGE, not a refusal. Score 25.

                       WOULD-HELP HEDGING (NOT a refusal — explicitly excluded):
                         Phrases that politely suggest what would IMPROVE or
                         REFINE the answer are NOT refusals when the answer body
                         already contains substantive analysis:
                           * "A longer time series would be required/needed/helpful"
                           * "More data would help/be helpful/strengthen"
                           * "Additional context would improve"
                           * "For a more precise assessment, X would be required"
                           * "Further analysis would be useful"
                           * "More granular data would be ideal"

                         These phrases acknowledge a limitation of the data
                         WITHOUT refusing to answer. If the answer contains
                         substantive analysis (numbers, citations, multi-
                         paragraph synthesis) AND the only "refusal-like"
                         phrasing is a would-help hedge, score
                         refusal_judgment=25 (no refusal detected).

                         A "I cannot answer" refusal IS a refusal. A "more data
                         would help me answer better" suggestion IS NOT a
                         refusal.

                       Hedging / interpretive language is NOT a refusal:
                         * "However, ..." / "Based on ..." / "While ..." —
                           these introduce nuance, not refusal.
                         * "Analyst reports suggest" / "may suggest" /
                           "some analysts note" — these are interpretation.
                         * "The answer depends on" / "In summary" — framing,
                           not refusal.
                         * A transparency banner like "⚠ Some numbers could
                           not be verified against retrieved data" appended
                           to an otherwise full answer is NOT a refusal.

                       SCORING:
                         * DEFAULT: refusal_judgment = 25. Only deviate from
                           25 when you can quote a refusal phrase from the
                           answer in your feedback field. If your feedback says
                           "no refusal phrases" or "provides substantive data"
                           or anything similar, the correct score is 25 — not
                           0. Feedback that contradicts the score is a bug.
                         * If the answer contains substantive data/analysis
                           (citations, numbers, tables, multi-paragraph
                           synthesis) AND does NOT contain any refusal phrase
                           above → refusal_judgment is N/A → score 25 (full
                           marks). It is FACTUALLY WRONG to score this as
                           "incorrect refusal" — the answer IS NOT a refusal.
                         * If the answer IS a refusal (matches a refusal
                           phrase) AND rubric.appropriate_refusal_ok=true AND
                           tool_results show empty/missing data → score 25.
                         * If the answer IS a refusal AND
                           (rubric.appropriate_refusal_ok=false OR tool_results
                           contain the requested data, e.g. status=ok items>=1)
                           → score 0-5 (wrongful refusal).
                         * If unsure whether the answer is a refusal, default
                           to N/A → score 25. The penalty is reserved for
                           CLEAR refusals that ignore available data.

OUTPUT — strict JSON object, no markdown, with keys:
{{
  "tool_use":        {{"score": <0-25>, "feedback": "<≤200 char actionable observation>"}},
  "grounding":       {{"score": <0-25>, "feedback": "<≤200 char>"}},
  "framing":         {{"score": <0-25>, "feedback": "<≤200 char>"}},
  "refusal_judgment":{{"score": <0-25>, "feedback": "<≤200 char>"}},
  "reviewer_summary": "<≤800 char paragraph as a senior engineer would write in PR review>"
}}

WRITE FEEDBACK AS A HUMAN REVIEWER WOULD:
- Per-dim `feedback` is an ACTIONABLE OBSERVATION, not a score restatement.
  Bad: "Score 22 because grounding is mostly good"
  Good: "Most claims grounded; revenue figure $96.5B cites query_fundamentals
  row 0 but the implicit YoY% appears computed, not cited"
- `reviewer_summary` is what a senior engineer would write back to the engineer
  who built this agent — a paragraph naming the headline takeaway AND the
  single most impactful change they should make next. Not a score restatement.
"""


# Note: parameters=frozenset() — pure system prompt with no substitutions.
# v3.0: BREAKING (PLAN-0110 W3) — DELETED the "PRESUME GROUNDED" instruction;
# numeric grounding is now cross-checked deterministically against the captured
# grounding_sample and the prompt defers value verification to it. The 4-dim
# schema + output keys (``feedback``/``reviewer_summary``) are unchanged from
# v2.0. Content hash flips automatically with the body change.
CHAT_QUALITY_JUDGE = PromptTemplate(
    name="chat_quality_judge",
    version="3.0",
    description=(
        "Strict 4-dim (tool_use/grounding/framing/refusal_judgment) chat-agent answer grader. "
        "v3.0 BREAKING: DELETED the 'PRESUME GROUNDED → 20-25' instruction; numeric grounding is "
        "now verified DETERMINISTICALLY against the captured grounding_sample (contradictions "
        "hard-fail), and the prompt grades grounding QUALITATIVELY (attribution + scope), with an "
        "explicit 'presumed' band when no sample is supplied."
    ),
    template=_TEMPLATE,
    parameters=frozenset(),
)
