"""Morning market briefing prompt template (PRD-0030 S16 row 16).

VERSION HISTORY
---------------
- 4.7 — PRD-0030 causal-attribution slice (P2, 2026-06-14): the prior brief
        DESCRIBED price moves the user can already see and filled the "why"
        gap with fabricated guesses ("TSLA +3.17% — no direct news;
        momentum-driven move"). Investigation (design report) found the root
        cause: the global /news/top feed carries NO entity attribution, so
        the LLM could never link a holding to a story, AND the prompt had no
        mechanism (or licence) to attribute drivers. v4.7 adds:
          (a) a per-holding DRIVER ATTRIBUTION ladder — entity news (cited) →
              sector/peer (hedged) → macro/event (cited) → else literally
              "idiosyncratic — no identifiable driver";
          (b) a FORBIDDEN list for speculative filler ("momentum-driven",
              "may be riding", "no catalyst confirmed", generic "tracking the
              broader market");
          (c) documentation of the new per-holding ``related: [cN]`` and
              ``sector:`` context lines the gatherer now feeds (PRD-0030
              P0/P1 in briefing_context.py + brief_context_formatter.py);
          (d) a marker-convention fix [N#] → [cN]: the backend resolver
              ``brief_parser._CN_CITATION_RE`` only matches [cN], so the
              prior [N#] markers were stripped as orphans and morning-brief
              per-bullet citations never resolved. Few-shot Examples A/B were
              re-shot to demonstrate the ladder + [cN] markers.
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
- 4.3 — PLAN-0103 W6 (2026-05-30): adds TWO few-shot examples (rich day +
        quiet day) and tightens the MANDATORY language above the examples.
        Motivation: the v4.2 live runs (audit
        ``docs/audits/2026-05-29-plan-0103-final-qa.md``) showed the LLM
        STILL dropping 2 of 6 sections AND silently skipping ``## Summary``
        even though the prompt explicitly required them. Length on those
        runs was ~150/919 tokens, so the failure was NOT a token-budget
        issue — the model was just not following the structural contract.
        v4.3 teaches the desired output SHAPE by example (Example A — rich
        day, Example B — quiet day with placeholder lines), since
        few-shot demonstration is more reliable than imperative rules for
        structural conformance. Parser-side defensive injection (see
        ``brief_parser.inject_missing_sections`` /
        ``inject_missing_summary``) is the belt-and-braces guarantee that
        the 6 sections + summary are present regardless of LLM compliance.
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
- 4.5 — PLAN-0103 W11 (2026-05-30): ADAPTIVE Summary length.  User feedback
        on the v4.4 50-word Summary cap: it is fine for a 10-position book
        on a quiet day, but a large portfolio (30+ positions) or a very
        active overnight session needs a denser synthesis to be useful.
        v4.5 replaces the fixed ``≤ 50 words`` cap with a target of
        ~100 words + explicit guidance bands:
          * Small portfolio (≤10 positions) + quiet day → 30-60 words.
          * Medium portfolio (10-30 positions) + normal day → 80-150 words.
          * Large portfolio (30+ positions) OR very active day
            (5+ material developments overnight) → up to 200 words.
        Hard cap stays at 200 words.  Example A's ``## Summary`` was
        re-shot at ~150 words mentioning the top 3 holdings by P&L impact
        (the new "lead with top-N holdings" guidance only fires when the
        summary exceeds 50 words; below that the original tight single-
        takeaway shape is preferred).  Example B's ~30-40 word summary
        is left unchanged — it is the canonical shape for the small-+-
        quiet case.  Parser ``split_summary_paragraph`` cap raised from
        300 chars → 1500 chars (200 words x ~7 chars/word + headroom).
- 4.4 — PLAN-0103 W9 (2026-05-30): SPLIT the single ``250 words`` cap into TWO
        explicit caps + per-section guidance. The v4.3 wording ``Cap total
        brief at 250 words`` was the WRONG design — 250 words is far too
        restrictive for a 6-section investor brief that must carry depth.
        v4.4 splits the budget into:
          * ``## Summary`` ≤ 50 words (1-3 sentences) — this is the
            collapsed dashboard surface the user reads at a glance.
          * ``## Details`` ≤ 700 words total with per-section guidance
            (Tape ≤ 25w; Your Portfolio Today 3-6 bullets ~20w each;
            Macro Today 1-4 bullets; News That Matters To You 3-5 bullets
            ~25w each; Risks + Opportunities 2-3 bullets ~20w each;
            Bonus context 1-2 bullets ~25w each). On quiet days the brief
            naturally lands ≤ 300 words; on busy days it can use the full
            ~700 word budget without bumping into a structural cap.
        Examples A and B were edited to fit the new ≤ 700 words details
        budget comfortably (no other shape change).  Parser unchanged —
        ``split_summary_paragraph`` still soft-caps the extracted summary
        at 300 chars for the schema field, which is a tighter constraint
        than the 50-word prompt directive (≈300 chars = 50 short words).
"""

from __future__ import annotations

from prompts._base import PromptTemplate

MORNING_BRIEFING = PromptTemplate(
    name="morning_briefing",
    # Bumped 4.6 → 4.7 as part of PRD-0030 causal-attribution slice (P2).
    # v4.7 adds the per-holding DRIVER ATTRIBUTION ladder (entity news →
    # sector/peer → macro/event → "idiosyncratic — no identifiable driver"),
    # FORBIDS speculative filler ("momentum-driven", "may be riding", "no
    # catalyst confirmed"), teaches the new per-holding ``related:`` /
    # ``sector:`` context shape, and switches the citation marker convention
    # from the unresolvable [N#] form to [cN] (which the backend resolver
    # ``_CN_CITATION_RE`` actually maps to a source — the prior [N#] markers
    # were silently stripped as orphans, so morning-brief per-bullet
    # citations never resolved). Few-shot Examples A/B re-shot accordingly.
    version="4.7",
    description=(
        "Morning market briefing v4.7 — v4.6 contract (## Summary + 6 mandatory "
        "sections + few-shot Examples A/B + adaptive Summary length) plus the "
        "PRD-0030 causal-attribution ladder: every holding line explains the "
        "LIKELY DRIVER of its move (entity news → sector/peer → macro → "
        "idiosyncratic) grounded in fed ``related:``/``sector:`` context, with "
        "speculative filler forbidden and [cN] citation markers (resolvable) "
        "replacing the prior unresolvable [N#] form."
    ),
    template=(
        # ── Role + goal ───────────────────────────────────────────────────────
        "You are writing the 5-minute morning brief for an investor about to scan it "
        "before market open.\n"
        "Goal: tell them what changed overnight that affects their decisions today.\n\n"
        "You have:\n"
        "  - Portfolio: <holdings + overnight P&L>. Each holding may carry "
        "indented context lines directly beneath its price:\n"
        "      * ``related: [cN] <headline> (sentiment, rel%)`` — entity-specific "
        "news already attributed to THIS holding (the likely driver of its move).\n"
        "      * ``sector: <Sector> +X.XX%`` — the holding's sector and its "
        "overnight return (a grounded fallback driver when there is no direct news).\n"
        "  - Overnight tape: <SPY/QQQ/VIX>\n"
        "  - Macro calendar: <events today + tomorrow>\n"
        "  - News (pre-ranked by relevance x portfolio overlap): <list>\n\n"
        # ── Causal-attribution ladder (PRD-0030 P2) ───────────────────────────
        # WHY: the prior brief restated price moves the user can already see and
        # filled the gap with fabricated guesses ("momentum-driven move", "may be
        # riding broader tech rally", "no catalyst confirmed"). For EVERY holding
        # you MUST explain the LIKELY DRIVER of its move by walking this ladder
        # IN ORDER, stopping at the first rung that has data — and cite the fed
        # item you used.
        "## Driver Attribution (MANDATORY for every holding)\n"
        "For each holding, explain WHY it moved by walking this ladder in order, "
        "stopping at the first rung with supporting data IN THE CONTEXT:\n"
        "  1. ENTITY NEWS — if the holding has a ``related: [cN]`` line, attribute "
        "the move to that story and cite its [cN]. Lead with the driver.\n"
        "  2. SECTOR / PEER — else if the holding has a ``sector:`` line, attribute "
        "the move to the sector ('tracking <Sector> +X.XX%'), using hedged "
        "language (tracking, in line with) — sector co-movement is correlation, "
        "not proven causation.\n"
        "  3. MACRO / EVENT — else if a macro print or scheduled event in the "
        "context plausibly explains it, attribute to that and cite it.\n"
        "  4. IDIOSYNCRATIC — else, and ONLY when the holding has NEITHER a "
        "``related:`` line NOR a ``sector:`` line, write exactly: "
        "'idiosyncratic — no identifiable driver'.\n"
        "FORBIDDEN: never write speculative filler such as 'momentum-driven', "
        "'may be riding', 'no catalyst confirmed', 'tracking the broader market', "
        "or any guess not grounded in a fed item. If you cannot ground it, it is "
        "'idiosyncratic — no identifiable driver'.\n"
        "NEVER fabricate a driver or cite a [cN] that is not in the context.\n\n"
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
        "<Synthesised paragraph for an investor scanning this for 10 seconds. "
        "Lead with the implication for the portfolio. Length is ADAPTIVE — "
        "see ``## Summary block`` guidance below for size bands (target ~100 "
        "words; 30-200 word range depending on portfolio breadth and overnight "
        "activity). Cite [N#] for facts.>\n\n"
        "## Details\n"
        "All 6 sections below are MANDATORY. If a section has no data, emit the "
        "heading and a single placeholder line (e.g. ``- No notable risks "
        "identified today``); do NOT omit the heading. Empty sections still need "
        "their bullet line.\n\n"
        "  1. **Market Snapshot** — one sentence. Futures + VIX. If market data is missing, "
        "emit ``- Market data unavailable``.\n"
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
        "The context items below are numbered [c1], [c2], [c3], … in order.\n"
        "Every factual bullet (especially in **Your Portfolio Today**, **News That "
        "Matters To You** and **Macro Today**) must end with at least one [cN] "
        "citation referencing the context item(s) it draws from.\n"
        "When a holding has a ``related: [cN]`` line, REUSE that exact [cN] in the "
        "holding's bullet so the driver resolves to its source.\n"
        "Use ONLY citation numbers that exist in the context (i.e. ≤ total items).\n"
        "Use the [cN] form (e.g. [c1], [c2]) — do NOT use the bare [N#] form, "
        "which the backend cannot resolve into a source.\n"
        "Placeholder lines (when a section has no data) do NOT need a citation.\n\n"
        # ── Tightened MUST language (v4.3) + few-shot examples ────────────────
        # WHY tighten + show: v4.2 imperative language alone wasn't enough — live
        # runs (audit 2026-05-29-plan-0103-final-qa.md) showed the LLM dropping
        # 2 of 6 sections and skipping ``## Summary`` even though the prompt
        # required them. Few-shot examples are the most reliable lever for
        # teaching structural conformance: the LLM imitates the SHAPE of
        # Example A (rich day) on busy days and Example B (quiet day with
        # placeholders) on sparse days.
        "## Output Contract (READ BEFORE WRITING)\n"
        "You MUST emit ALL 6 section headers AND the ``## Summary`` block — "
        "even on quiet days. If a section has no specific items, emit ONE "
        "single placeholder line that names the situation (see Example B). "
        "The two examples below show exactly what to produce in a rich vs "
        "quiet day. Match their SHAPE, not their content.\n\n"
        # ── Example A — Rich day ──────────────────────────────────────────────
        "### Example A — Rich day (lots of holding news + macro + risks, larger book)\n"
        "## Summary\n"
        "AI-infrastructure rally extends overnight and tilts the book "
        "constructive: your top three by impact — **MSFT** (+1.1% on the "
        "Anthropic-Azure win [c3]), **AAPL** (+0.8% on the Vision Pro "
        "shipment beat [c2]) and **NVDA** (flat but Dell's +40% AI-server "
        "backlog [c6] re-confirms hyperscaler capex into next print) — "
        "should add to a strong open. Watch the 08:30 CPI print "
        "(consensus 3.1% YoY [c4]): a hot read would re-price the duration "
        "leg and amplify drawdown given top-3 concentration at 38% of the "
        "book. FOMC minutes at 14:00 ET could re-rate Q3-cut probability. "
        "VIX 13.8 keeps protective puts cheap if you want to hedge AAPL "
        "through earnings. Net: stay engaged into the open, size hedges "
        "around CPI, do not chase Dell/Palantir extension.\n"
        "\n"
        "## Details\n"
        "**Market Snapshot**\n"
        "- SPY +0.35%, QQQ +0.62%, VIX 13.8 — risk-on tone pre-mkt [c1]\n"
        # WHY this Portfolio block (PRD-0030): demonstrates the attribution
        # ladder per holding — rung 1 (entity news, cited), rung 2 (sector
        # fallback, hedged), rung 4 (idiosyncratic, only when no related/
        # sector line was fed). The LLM imitates this SHAPE.
        "**Your Portfolio Today**\n"
        "- AAPL +0.8% pre-mkt — driven by the Vision Pro shipment beat [c2]; tailwind for your 12% weight\n"
        "- MSFT +1.1% — Azure-AI win at Anthropic confirms the cloud capex thesis [c3]\n"
        "- JPM +0.4% — no stock-specific news; tracking Financial Services +0.30% [c10]\n"
        "- NVDA +0.1% — idiosyncratic — no identifiable driver\n"
        "**Macro Today**\n"
        "- CPI 08:30 ET, consensus 3.1% YoY (prev 3.2%); hot print would re-price your duration risk [c4]\n"
        "- FOMC minutes 14:00 ET — watch language on Q3 cuts [c5]\n"
        "**News That Matters To You**\n"
        "- Dell +40% on AI-server backlog — confirms hyperscaler capex; MSFT/AAPL beneficiaries [c6]\n"
        "- Palantir +12% on DoD contract — adjacent to your defence sleeve [c7]\n"
        "- Anthropic raises $65B at $965B — cloud demand tailwind for MSFT Azure [c8]\n"
        "**Risks + Opportunities**\n"
        "- Concentration: top-3 holdings = 38% of book; CPI surprise would amplify drawdown\n"
        "- Opportunity: VIX 13.8 makes protective AAPL puts cheap if you want hedge through earnings\n"
        "**Bonus context**\n"
        "- 10Y yield 4.21% (+3bps overnight) — duration drag on growth names if it breaks 4.30% [c9]\n"
        "\n"
        # ── Example B — Quiet day ─────────────────────────────────────────────
        "### Example B — Quiet day (sparse data, placeholder lines)\n"
        "## Summary\n"
        "Quiet pre-mkt session — no material developments overnight on your "
        "holdings; watch for tomorrow's CPI print at 08:30.\n"
        "\n"
        "## Details\n"
        "**Market Snapshot**\n"
        "- SPY closed 521.40, QQQ 445.10, VIX 12.6 — market data thin pre-mkt [c1]\n"
        # WHY: on a quiet day a holding with NO related: and NO sector: line
        # must read 'idiosyncratic — no identifiable driver' — never a guess.
        "**Your Portfolio Today**\n"
        "- AAPL flat pre-mkt — idiosyncratic — no identifiable driver\n"
        "- MSFT flat pre-mkt — idiosyncratic — no identifiable driver\n"
        "**Macro Today**\n"
        "- No major economic releases scheduled\n"
        "**News That Matters To You**\n"
        "- No holding-relevant news in the past 24h. See Bonus context for industry-level item.\n"
        "**Risks + Opportunities**\n"
        "- No notable risk signals identified today. Watch for tomorrow's CPI release.\n"
        "**Bonus context**\n"
        "- Anthropic raised $65B at $965B valuation — cloud capex tailwind "
        "for hyperscalers if you re-weight to AAPL/MSFT [c2]\n"
        "\n"
        # ── End examples ──────────────────────────────────────────────────────
        "Now produce the brief for the input below. Follow the shape of "
        "Example A on busy days and Example B on quiet days.\n\n"
        "{safety}\n\n"
        "As of: {current_date}\n\n"
        # ── Format / hard rules ───────────────────────────────────────────────
        # WHY two explicit caps (v4.4): the previous single ``250 words`` cap
        # was too restrictive for a 6-section brief — the LLM was forced to
        # truncate per-section signal. v4.4 budgets the two blocks
        # separately so the dashboard collapsed surface stays tight while
        # the expanded details view can carry real depth.
        "## Summary block: target ~100 words; adapt to portfolio breadth + market activity.\n"
        "Guidance:\n"
        "  - Small portfolio (≤10 positions) + quiet day: 30-60 words.\n"
        "  - Medium portfolio (10-30 positions) + normal day: 80-150 words.\n"
        "  - Large portfolio (30+ positions) OR very active day "
        "(5+ material developments overnight): up to 200 words.\n"
        "Hard cap: 200 words.\n"
        "Lead with the single most important takeaway. Mention top 1-3 holdings "
        "by P&L impact when summary > 50 words. Always cite [cN] for facts.\n"
        "## Details block: ≤ 1200 words across all 6 sections combined. "
        "Per-section guidance — bullet length is a SOFT target: aim for ~30-50 "
        "words per bullet, but EXPAND up to ~100 words when the data is complex, "
        "multi-step, or has non-obvious implications worth explaining. Do NOT "
        "truncate a useful causal chain just to stay short. Conversely, do not "
        "pad a simple fact past one sentence. "
        "Section caps: Market Snapshot ≤ 40 words (one line); "
        "Your Portfolio Today 3-6 bullets, ~30-60 words each (expand to ~100 "
        "when explaining why a holding moves and what it implies); "
        "Macro Today 1-4 bullets, ~30-60 words each; "
        "News That Matters To You 3-5 bullets, ~40-80 words each (lead with "
        "the implication, then fact, then citation; expand to ~100 when the "
        "second-order portfolio impact needs unpacking); "
        "Risks + Opportunities 2-3 bullets, ~40-80 words each; "
        "Bonus context 1-2 bullets, ~30-60 words each.\n"
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
