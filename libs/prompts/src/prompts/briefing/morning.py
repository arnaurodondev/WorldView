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
- 4.2 — PLAN-0103 W3 (2026-05-30): adds the ``## Summary`` paragraph block AND
        promotes all 6 sections to MANDATORY. Three independent FQA findings
        motivated the change:
          (a) FQA-01 — live briefs were rendering only 4 of 6 sections (Risks
              + Opportunities and Bonus context silently missing). The 4.1
              prompt allowed sections to be omitted; the LLM took the path of
              least resistance and produced a partial brief. v4.2 makes each
              of the 6 section headings MANDATORY — if a section has no data
              the LLM must still emit the heading + a single placeholder line.
          (b) FQA-02 — Tape section regularly says "Not available" when the
              upstream data layer is empty. The placeholder language is now
              standardised so the parser/completeness check can identify it.
          (c) Product ask — dashboard collapsed view should show a 1-3 line
              synthesised paragraph, not the first section's first bullet.
              v4.2 introduces a leading ``## Summary`` block (≤300 chars) so
              the frontend can render a clean collapsed surface and only
              expand to the full 6-section ``## Details`` view on "Read more".
        Parser changes live in ``brief_parser.py::split_summary_paragraph``.
        ``brief_parser.parse_sections_with_citations`` continues to work on
        the ``## Details`` block — no divider is required between Summary and
        Details (Summary is identified by its heading).
"""

from __future__ import annotations

from prompts._base import PromptTemplate

MORNING_BRIEFING = PromptTemplate(
    name="morning_briefing",
    # Bumped 4.1 → 4.2 as part of PLAN-0103 W3 (add Summary + make 6 sections MANDATORY).
    version="4.2",
    description=(
        "Morning market briefing v4.2 — adds the leading ``## Summary`` paragraph "
        "(1-3 sentences, ≤300 chars) used by the dashboard collapsed view AND "
        "promotes all 6 sections to MANDATORY (Tape / Your Portfolio Today / "
        "Macro Today / News That Matters To You / Risks + Opportunities / "
        "Bonus context) — empty sections emit a single placeholder line"
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
        # ── Output structure (Summary + 6 mandatory sections) ─────────────────
        # WHY a leading ``## Summary``: the dashboard renders only this block
        # in the collapsed card; the user clicks "Read more" to expand into
        # ``## Details``. Keeping the headings ``## Summary`` and ``## Details``
        # gives the parser a deterministic split-point without needing a
        # ``---`` divider (which conflicted with em-dash ranges in prose).
        # WHY 6 sections MANDATORY: FQA-01 surfaced the LLM dropping Risks +
        # Opportunities and Bonus context on quiet news days (the prompt said
        # they were "expected" but not "required"). Making the section headings
        # mandatory forces a single placeholder line on quiet days rather than
        # a partial brief that hides whole categories.
        "Output structure (in this exact order):\n\n"
        "## Summary\n"
        "<1-3 sentences synthesising the single most important takeaway for an "
        "investor scanning this for 10 seconds. Lead with the implication for the "
        "portfolio. ≤300 characters total. Cite [N#] if quoting a fact.>\n\n"
        "## Details\n"
        "All 6 sections below are MANDATORY. If a section has no data, emit the "
        "heading and a single placeholder line (e.g. ``- No notable risks "
        "identified today``); do NOT omit the heading. Empty sections still need "
        "their bullet line.\n\n"
        "  1. **Tape** — one sentence. Futures + VIX. If tape data is missing, "
        "emit ``- Tape data unavailable``.\n"
        "  2. **Your Portfolio Today** — bullet per material holding. Lead with "
        "implication. If portfolio is empty, emit ``- No material holdings to report``.\n"
        "  3. **Macro Today** — bullet list of today/tomorrow's prints. If empty, "
        "emit ``- No scheduled macro releases today``.\n"
        "  4. **News That Matters To You** — 3-5 items. Each leads with the "
        "implication for the investor, then the fact, then [N#] citation. If no "
        "relevant news, emit ``- No portfolio-relevant news in this cycle``.\n"
        "  5. **Risks + Opportunities** — 2-3 model-generated lines synthesising "
        "signal across the data. If nothing notable, emit ``- No notable risks "
        "or opportunities identified today``.\n"
        "  6. **Bonus context** — 1-2 generic high-impact items. If nothing to "
        "add, emit ``- No additional context to flag``.\n\n"
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
        "Do NOT use [c1]/[c2] (legacy v3.0 marker form) — only [N1]/[N2]/[N3].\n"
        "Placeholder lines (when a section has no data) do NOT need a citation.\n\n"
        "{safety}\n\n"
        "As of: {current_date}\n\n"
        # ── Format / hard rules ───────────────────────────────────────────────
        "## Format Rules\n"
        "- Cap total brief at 250 words (Summary + Details combined).\n"
        "- Output pure markdown (no HTML tags).\n"
        "- Emit the literal ``## Summary`` and ``## Details`` headings exactly\n"
        "  as written above. Inside ``## Details`` use ``**Section Name**``\n"
        "  bold headings exactly as listed; do NOT add an outer\n"
        "  ``# Morning Briefing`` / ``Date:`` header — the card chrome already\n"
        "  supplies them.\n"
        "- One bullet per line, prefixed with `- `.\n"
        "- NEVER include news that doesn't connect to a holding, sector, or macro event.\n"
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
