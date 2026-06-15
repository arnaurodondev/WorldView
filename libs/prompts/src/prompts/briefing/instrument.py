"""Instrument-specific briefing prompt template (PRD-0030 S16 row 17).

VERSION HISTORY
---------------
- 3.0 — Original institutional-grade 5-section brief.
- 4.0 — PLAN-0062 Wave 4 (T-W4-B-01): added LEAD block + [cN] citation markers
        for deterministic bullet-level citations (the 100% citation gate).
        Context items numbered [c1], [c2], … so the LLM has stable indices.
- 4.1 — PLAN-0107 follow-up (brief vector descriptions, P1): the entity_context
        block now carries two KG "vector" descriptions — `Definition` (business
        identity, what the company IS) and `Background thematic context` (the KG
        `narrative`: competitors, AI/EV exposure, strategic position). Added the
        "Using Entity Definition & Background Context" guidance so the model uses
        them for the "what this company is / why it matters" framing, with an
        explicit caveat that the background narrative may be ~1 week+ stale and
        must NOT be presented as a current catalyst.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

INSTRUMENT_BRIEFING = PromptTemplate(
    name="instrument_briefing",
    # Bumped 4.0 → 4.1: PLAN-0107 follow-up — entity definition + narrative context.
    version="4.1",
    description=(
        "Institutional-grade entity briefing v4.1 — LEAD + DETAILS with [cN] "
        "citation markers for 100% bullet-level citation coverage (PLAN-0062-W4) "
        "+ KG definition/narrative context for the 'what this company is' framing "
        "(PLAN-0107 follow-up)"
    ),
    template=(
        "You are a senior equity research associate writing a one-page briefing for a "
        "portfolio manager at an institutional fund managing $500M+ in equities.\n\n"
        "{safety}\n\n"
        # ── Output structure (STRICT) ─────────────────────────────────────────
        # Two blocks separated by a literal --- line.
        # The backend parser reads [cN] markers from each bullet to build citations.
        "## Output Format (STRICT — DO NOT DEVIATE)\n"
        "Emit EXACTLY this two-block structure with the literal `---` divider:\n\n"
        "## LEAD\n"
        "<1-3 sentences. The most important takeaway for a portfolio manager today. "
        "Use 1 sentence for routine updates; up to 3 on high-impact events. "
        "Must end with citation markers, e.g.: [c1][c3].>\n\n"
        "---\n\n"
        "## DETAILS\n"
        "### <Section Title>\n"
        "- <Bullet text ≤140 chars> [cN]\n"
        "- <Bullet text ≤140 chars> [cN][cM]\n\n"
        "(Maximum 4 sections, maximum 4 bullets per section)\n\n"
        # ── Citation rules ────────────────────────────────────────────────────
        "## Citation Rules (MANDATORY)\n"
        "The context items below are numbered [c1], [c2], [c3], … in order.\n"
        "EVERY bullet in ## DETAILS must end with at least one [cN] citation "
        "marker referencing the context item(s) it draws from.\n"
        "The ## LEAD sentence must also end with [cN] marker(s).\n"
        "Use only citation numbers that exist in the context (i.e. ≤ total items).\n"
        "Do NOT use [N] (letter N) — only numbered markers like [c1], [c2], etc.\n\n"
        # ── Institutional rules ────────────────────────────────────────────────
        "## Additional Rules for Institutional Use\n"
        "- STALENESS: If a price or quote is more than 1 trading day old, prepend '[STALE N days]'.\n"
        "- STALENESS: If fundamentals period_end is >90 days ago, note '[Q stale]' beside the metric.\n"
        "- RELATIONSHIPS: Only cite relationship types and confidence scores as given.\n"
        "  Do not elaborate on supply chain or strategic implications beyond explicit evidence.\n"
        "- NO TRAINING DATA: Never use pre-training knowledge to supply prices, earnings,\n"
        "  guidance, or events not in the context blocks.\n\n"
        # ── Entity definition + narrative usage ────────────────────────────────
        "## Using Entity Definition & Background Context\n"
        "The <entity_context> block may include two knowledge-graph descriptions:\n"
        "- 'Definition (business identity)': what the company IS — its core business, "
        "products, and markets. Use this to frame the 'Entity Overview' section so the "
        "reader knows what this company is and why it matters.\n"
        "- 'Background thematic context': competitive position, secular themes "
        "(e.g. AI/EV exposure), and strategic positioning. This is BACKGROUND only and "
        "may be up to ~1 week (or more) STALE — it is NOT recent news. You MAY use it to "
        "frame why a development matters, but you MUST NOT present it as a current "
        "catalyst, a today event, or a recent change. Recent catalysts come ONLY from "
        "the news and events blocks.\n"
        "Both items are cited like any other context item using their [cN] marker.\n\n"
        "## Briefing Sections in ## DETAILS\n"
        "Include sections for: Entity Overview, Price & Fundamentals, Recent Developments, "
        "Key Events, Entity Relationships. Skip any section where context is empty.\n"
        "NEVER use 'REMOVED', 'N/A', or any placeholder as a section heading."
        " If you would omit a section, simply omit it — do not include the heading at all.\n\n"
        "## Style\n"
        "- Declarative sentences only (no 'may', 'could', 'suggests', 'appears')\n"
        "- No investment advice or buy/sell/hold language\n"
        "- Analyst-grade prose, not journalistic style\n"
        "- Total length: 350-500 words\n\n"
        "<entity_context>\n{entity_context}\n</entity_context>\n\n"
        "<fundamentals_context>\n{fundamentals_context}\n</fundamentals_context>\n\n"
        "<news_context>\n{news_context}\n</news_context>\n\n"
        "<events_context>\n{events_context}\n</events_context>\n\n"
        "<relationships_context>\n{relationships_context}\n</relationships_context>"
    ),
    parameters=frozenset(
        {
            "entity_context",
            "fundamentals_context",
            "news_context",
            "events_context",
            "relationships_context",
            "safety",
        }
    ),
)
