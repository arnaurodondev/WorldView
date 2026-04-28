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
"""

from __future__ import annotations

from prompts._base import PromptTemplate

MORNING_BRIEFING = PromptTemplate(
    name="morning_briefing",
    # Bumped 2.1 → 2.2 as part of PLAN-0048 Wave A two-tier redesign.
    version="2.2",
    description="Morning market briefing — two-tier (SUMMARY + DETAILS) for compact card UX",
    template=(
        "You are a financial intelligence analyst writing a morning market briefing.\n"
        "Synthesize the following data into a clear, actionable markdown narrative.\n\n"
        "{safety}\n\n"
        "As of: {current_date}\n\n"
        # ── Two-tier output contract ─────────────────────────────────────────
        # The frontend splits the output on the FIRST ``---`` line:
        #   - Everything before becomes the collapsed summary (1-2 sentences).
        #   - Everything after becomes the expanded narrative (the four sections).
        # If the LLM omits the divider, the summary is null and only narrative
        # is shown — the rendering code degrades gracefully.
        "## Output Format (STRICT)\n"
        "Emit EXACTLY this two-block structure, in this order, with the\n"
        "literal `---` divider between them:\n\n"
        "## SUMMARY\n"
        "<1-2 sentences capturing today's most important signal across portfolio,"
        " market, and alerts. Lead with the single most actionable item.>\n\n"
        "---\n\n"
        "## DETAILS\n"
        "### Market Overview\n"
        "<Sector performance, top movers, overall market tone>\n\n"
        "### Portfolio Impact\n"
        "<How market events affect the user's holdings>\n\n"
        "### Key News\n"
        "<Top news stories ranked by relevance and impact>\n\n"
        "### Active Alerts & Signals\n"
        "<Unacknowledged alerts requiring attention>\n\n"
        # ── Hard rules to keep the output card-friendly ──────────────────────
        "## Guidelines\n"
        "- Output pure markdown (no HTML tags)\n"
        "- Total length 500-1000 words across both blocks\n"
        "- The SUMMARY block must be 1-2 sentences MAX (used in a 3-line card preview)\n"
        # WHY forbid Date/header echoes: the card chrome already shows
        # "MORNING BRIEFING" + the date. Repeating them inside the body wastes
        # the limited vertical space allocated to the brief on the dashboard.
        "- NEVER emit a top-level `# Morning Briefing` / `# Morning Market Briefing`"
        " header or a `Date:` line in the body — the card chrome supplies them\n"
        "- Use numbered citations [N] when referencing specific data\n"
        "- Flag conflicting signals explicitly\n"
        "- If a context section is empty, skip the entire section (heading + body)."
        " Never write 'No data available', 'not available', or similar.\n"
        "- Do not compute portfolio P&L, percentage returns, or position values"
        " unless they appear verbatim in the portfolio context\n"
        "- Do not use phrases like 'consider', 'you should', 'it may be worth'\n"
        "- Append *(as of [date])* after every price, level, or rate mentioned\n\n"
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
