"""Morning market briefing prompt template (PRD-0030 S16 row 16).

VERSION HISTORY
---------------
- 2.1 — Original section-based prompt: ``Market Overview`` / ``Portfolio Impact`` / etc.
- 2.2 — PLAN-0048 Wave A: split output into a ``## SUMMARY`` block (1-2 sentences)
        and a ``## DETAILS`` block (the structured sections), separated by a literal
        ``---`` divider. The frontend MorningBriefCard uses the summary for the
        collapsed view and the details for the expanded view, so the redundant
        "Morning Briefing" / "Date:" preamble must NEVER appear in the body —
        the card chrome already supplies the title and timestamp.
- 3.0 — PLAN-0062 Wave 4 (T-W4-B-01): three-block structure (LEAD + --- + DETAILS).
        Context items are numbered [c1], [c2], … so the LLM can embed stable
        citation markers in every bullet (the 100% citation gate). Tightened to
        <=4 sections x <=4 bullets x <=140 chars per bullet.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

MORNING_BRIEFING = PromptTemplate(
    name="morning_briefing",
    # Bumped 2.2 → 3.0 as part of PLAN-0062 Wave 4 citation-first redesign.
    version="3.0",
    description=(
        "Morning market briefing v3.0 — LEAD + DETAILS with [cN] citation markers "
        "for deterministic bullet-level citations (PLAN-0062-W4)"
    ),
    template=(
        "You are a financial intelligence analyst writing a morning market briefing.\n"
        "Synthesize the following data into a clear, actionable structured brief.\n\n"
        "{safety}\n\n"
        "As of: {current_date}\n\n"
        # ── Output structure (STRICT) ─────────────────────────────────────────
        # Three blocks separated by literal --- lines.
        # The parser splits on the FIRST --- to extract the ## LEAD block.
        # If the LLM omits the divider, lead is null and only narrative is shown.
        "## Output Format (STRICT — DO NOT DEVIATE)\n"
        "Emit EXACTLY this two-block structure with the literal `---` divider:\n\n"
        "## LEAD\n"
        "<1-2 sentences. The single most actionable signal for today. "
        "Must end with citation markers, e.g.: [c1][c3].>\n\n"
        "---\n\n"
        "## DETAILS\n"
        "### <Section Title>\n"
        "- <Bullet text ≤140 chars> [cN]\n"
        "- <Bullet text ≤140 chars> [cN][cM]\n\n"
        "### <Section Title>\n"
        "- <Bullet text ≤140 chars> [cN]\n\n"
        "(Maximum 4 sections, maximum 4 bullets per section)\n\n"
        # ── Citation rules ────────────────────────────────────────────────────
        # WHY [cN] markers: the backend parser reads these markers to attach
        # the correct source document to each bullet. Every bullet MUST end
        # with at least one [cN] marker or it will be dropped from the output.
        "## Citation Rules (MANDATORY)\n"
        "The context items below are numbered [c1], [c2], [c3], … in order.\n"
        "EVERY bullet in ## DETAILS must end with at least one [cN] citation "
        "marker referencing the context item(s) it draws from.\n"
        "The ## LEAD sentence must also end with [cN] marker(s).\n"
        "Use only citation numbers that exist in the context (i.e. ≤ total items).\n"
        "Do NOT use [N] (letter N) — only numbered markers like [c1], [c2], etc.\n\n"
        # ── Hard rules ────────────────────────────────────────────────────────
        "## Guidelines\n"
        "- Output pure markdown (no HTML tags)\n"
        "- ## LEAD block: 1-2 sentences MAX (used in the collapsed card view)\n"
        "- ## DETAILS block: ≤4 sections, ≤4 bullets each, ≤140 chars per bullet\n"
        "- NEVER emit a top-level `# Morning Briefing` / `# Morning Market Briefing`"
        " header or a `Date:` line — the card chrome already supplies them\n"
        "- Flag conflicting signals explicitly\n"
        "- If a context section is empty, skip that entire section entirely."
        " Never write 'No data available' or 'not available'.\n"
        "- Do not compute portfolio P&L, percentage returns, or position values"
        " unless they appear verbatim in the portfolio context\n"
        "- Do not use phrases like 'consider', 'you should', 'it may be worth'\n"
        "- Append *(as of {current_date})* after every price or rate mentioned\n\n"
        "<portfolio_context>\n{portfolio_context}\n</portfolio_context>\n\n"
        "<news_context>\n{news_context}\n</news_context>\n\n"
        "<alerts_context>\n{alerts_context}\n</alerts_context>\n\n"
        "<market_overview>\n{market_overview}\n</market_overview>\n\n"
        "<events_context>\n{events_context}\n</events_context>"
    ),
    parameters=frozenset(
        {
            "portfolio_context",
            "news_context",
            "alerts_context",
            "market_overview",
            "events_context",
            "safety",
            "current_date",  # date context so the LLM knows what "today" is
        }
    ),
)
