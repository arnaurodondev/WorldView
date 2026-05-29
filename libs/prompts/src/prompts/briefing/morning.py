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
- 4.0 — PLAN-0102 W1 T-W1-05 (2026-05-28): "5-minute investor brief" rewrite.
        Replaces the generic "synthesize this data" wording with an explicit
        6-section spec (Tape, Your Portfolio Today, Macro Today, News That
        Matters To You, Risks + Opportunities, Bonus context). Every News bullet
        leads with the IMPLICATION for the investor, then the fact, then a
        citation. Total cap 250 words. Audit:
        docs/audits/2026-05-28-plan-0102-brief-redesign.md.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

MORNING_BRIEFING = PromptTemplate(
    name="morning_briefing",
    # Bumped 3.0 → 4.0 as part of PLAN-0102 W1 "5-minute investor brief" rewrite.
    version="4.0",
    description=(
        "Morning market briefing v4.0 — 5-minute investor brief with 6 named "
        "sections (Tape / Your Portfolio Today / Macro Today / News That Matters "
        "To You / Risks + Opportunities / Bonus context); every News bullet "
        "leads with the implication (PLAN-0102 W1)"
    ),
    template=(
        "You are writing the 5-minute morning brief for an investor about to scan it "
        "before market open.\n"
        "Goal: tell them what changed overnight that affects their decisions today.\n\n"
        "You have:\n"
        "  - Portfolio: <holdings + sector + last close>\n"
        "  - Overnight tape: <SPY/QQQ/VIX>\n"
        "  - Macro calendar: <events today + tomorrow>\n"
        "  - News (pre-ranked by relevance x portfolio overlap): <list>\n\n"
        "Output sections in this exact order:\n"
        "  1. **Tape** — one sentence. Futures + VIX.\n"
        "  2. **Your Portfolio Today** — bullet per material holding. Lead with implication.\n"
        "  3. **Macro Today** — bullet list of today/tomorrow's prints.\n"
        "  4. **News That Matters To You** — 3-5 items. Each leads with the implication "
        "for the investor, then the fact, then [N#] citation.\n"
        "  5. **Risks + Opportunities** — 2-3 model-generated lines synthesising signal "
        "across the data.\n"
        "  6. **Bonus context** — 1-2 generic high-impact items.\n\n"
        "Rules:\n"
        "  - Cap total at 250 words.\n"
        "  - Cite sources [N1] [N2].\n"
        "  - NEVER include news that doesn't connect to a holding, sector, or macro event.\n"
        "  - On quiet days, surface 1 sector-relevant macro signal rather than padding with "
        "irrelevant news.\n\n"
        "{safety}\n\n"
        "As of: {current_date}\n\n"
        # ── Output structure (STRICT) ─────────────────────────────────────────
        # Three blocks separated by literal --- lines.
        # The parser splits on the FIRST --- to extract the ## LEAD block.
        # If the LLM omits the divider, lead is null and only narrative is shown.
        "## Output Format (STRICT — DO NOT DEVIATE)\n"
        "Emit EXACTLY this two-block structure with the literal `---` divider:\n\n"
        "## LEAD\n"
        "<1-3 sentences. The single most actionable signal for today. "
        "Use 1 sentence on quiet days; up to 3 on high-activity days or "
        "large portfolios. Must end with citation markers, e.g.: [c1][c3].>\n\n"
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
        "- ## LEAD block: 1-3 sentences MAX (used in the collapsed card view)\n"
        "- ## DETAILS block: ≤4 sections, ≤4 bullets each, ≤140 chars per bullet\n"
        "- NEVER emit a top-level `# Morning Briefing` / `# Morning Market Briefing`"
        " header or a `Date:` line — the card chrome already supplies them\n"
        "- Flag conflicting signals explicitly\n"
        "- If a context section is empty, skip that entire section entirely."
        " Never write 'No data available' or 'not available'.\n"
        "- NEVER use 'REMOVED', 'N/A', or any placeholder as a section heading."
        " If you would omit a section, simply omit it — do not include the heading at all.\n"
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
