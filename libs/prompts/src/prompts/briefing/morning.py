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
- 4.1 — PLAN-0103 W2 (2026-05-29): cleanup release. v4.0 carried TWO incompatible
        rubrics — the 6-section investor brief at the top AND the legacy v3.0
        ``## LEAD / --- / ## DETAILS`` "STRICT" template (with "Maximum 4 sections,
        maximum 4 bullets") at the bottom. The lower block contradicted the upper
        spec on EVERY axis (number of sections, section names, bullet caps,
        block structure). The live brief HAPPENED to follow the upper rubric,
        but the LLM was given conflicting instructions. v4.1 deletes the legacy
        ``## LEAD / --- / ## DETAILS`` template and the 4/4 caps; keeps the
        citation rules (now in a single block) and the format rules (≤250 words,
        markdown headers); the 6-section spec is the SINGLE source of truth.
        See ``docs/audits/2026-05-29-plan-0102-phase-d-code-review.md`` §1.
        The brief parser already degrades gracefully when the ``---`` divider
        is absent (``brief_parser.py::split_summary_and_details`` returns
        ``(None, full_content)`` → frontend renders the whole body as the
        expanded view) so removing the divider does not break rendering.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

MORNING_BRIEFING = PromptTemplate(
    name="morning_briefing",
    # Bumped 4.0 → 4.1 as part of PLAN-0103 W2 prompt cleanup (BP-623 sibling).
    version="4.1",
    description=(
        "Morning market briefing v4.1 — 5-minute investor brief with 6 named "
        "sections (Tape / Your Portfolio Today / Macro Today / News That Matters "
        "To You / Risks + Opportunities / Bonus context); v4.1 deletes the "
        "contradictory v3.0 LEAD/DETAILS template that v4.0 had retained"
    ),
    template=(
        # ── Role + goal ───────────────────────────────────────────────────────
        "You are writing the 5-minute morning brief for an investor about to scan it "
        "before market open.\n"
        "Goal: tell them what changed overnight that affects their decisions today.\n\n"
        "You have:\n"
        "  - Portfolio: <holdings + sector + last close>\n"
        "  - Overnight tape: <SPY/QQQ/VIX>\n"
        "  - Macro calendar: <events today + tomorrow>\n"
        "  - News (pre-ranked by relevance x portfolio overlap): <list>\n\n"
        # ── 6-section spec (SINGLE SOURCE OF TRUTH) ───────────────────────────
        # WHY this is the only rubric: v4.0 also carried a legacy v3.0
        # "## LEAD / --- / ## DETAILS" block with a "max 4 sections, max 4
        # bullets" cap. The two were incompatible — the LLM had to pick one.
        # v4.1 (PLAN-0103 W2) deletes the v3.0 block entirely; this section is
        # now the only structural mandate. The brief parser degrades
        # gracefully when the legacy --- divider is absent.
        "Output sections in this exact order:\n"
        "  1. **Tape** — one sentence. Futures + VIX.\n"
        "  2. **Your Portfolio Today** — bullet per material holding. Lead with implication.\n"
        "  3. **Macro Today** — bullet list of today/tomorrow's prints.\n"
        "  4. **News That Matters To You** — 3-5 items. Each leads with the implication "
        "for the investor, then the fact, then [N#] citation.\n"
        "  5. **Risks + Opportunities** — 2-3 model-generated lines synthesising signal "
        "across the data.\n"
        "  6. **Bonus context** — 1-2 generic high-impact items.\n\n"
        # ── Citation rules ────────────────────────────────────────────────────
        # WHY [N#] markers: the backend parser reads these markers to attach
        # the correct source document to each bullet. Citations are MANDATORY
        # on every factual assertion — the LLM is forbidden from citing a
        # number that is not in the supplied context block.
        "## Citation Rules (MANDATORY)\n"
        "The context items below are numbered [N1], [N2], [N3], … in order.\n"
        "Every factual bullet (especially in **News That Matters To You** and "
        "**Macro Today**) must end with at least one [N#] citation referencing "
        "the context item(s) it draws from.\n"
        "Use ONLY citation numbers that exist in the context (i.e. ≤ total items).\n"
        "Do NOT use [c1]/[c2] (legacy v3.0 marker form) — only [N1]/[N2]/[N3].\n\n"
        "{safety}\n\n"
        "As of: {current_date}\n\n"
        # ── Format / hard rules ───────────────────────────────────────────────
        "## Format Rules\n"
        "- Cap total at 250 words.\n"
        "- Output pure markdown (no HTML tags).\n"
        "- Use `**Section Name**` headings exactly as listed above; do NOT add an outer\n"
        "  `# Morning Briefing` / `Date:` header — the card chrome already supplies them.\n"
        "- One bullet per line, prefixed with `- `.\n"
        "- NEVER include news that doesn't connect to a holding, sector, or macro event.\n"
        "- On quiet days, surface 1 sector-relevant macro signal rather than padding with\n"
        "  irrelevant news.\n"
        "- If a context section is empty, skip the entire section. Never write 'No data\n"
        "  available' or 'not available' or 'REMOVED' / 'N/A' as a heading.\n"
        "- Do NOT compute portfolio P&L, percentage returns, or position values unless\n"
        "  they appear verbatim in the portfolio context.\n"
        "- Do NOT use phrases like 'consider', 'you should', 'it may be worth'.\n"
        "- Append *(as of {current_date})* after every price or rate mentioned.\n"
        "- Flag conflicting signals explicitly.\n\n"
        # ── Context blocks ────────────────────────────────────────────────────
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
