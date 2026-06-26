"""Tool registry builder — registers all 22 platform tools into a ToolRegistry.

Extracted from tool_executor.py (PLAN-0089 Wave C-1) to reduce dispatcher size.
All callers import build_default_registry from tool_executor (re-exported there).
"""

from __future__ import annotations

from typing import Any, cast

from tools.tool_registry import ToolRegistry  # type: ignore[import-untyped,import-not-found]


class ToolRegistryDriftError(RuntimeError):
    """Raised at startup when the YAML manifest and handler registry disagree.

    Fail-fast guard (PLAN-0093 QA P0-1, GraphEnricher dormant-tool follow-up):
    a tool that exists in the manifest with no registered handler — or vice
    versa — would otherwise only surface when the LLM tried to call it and
    the user saw an opaque "tool unavailable" message.  Raising at boot
    guarantees the orchestrator can never serve traffic while in this state.
    """


def validate_registry_parity(registry: ToolRegistry) -> dict[str, int]:
    """Compare the YAML manifest against the registered handler set.

    Returns the sizes ``{"manifest": N, "handled": M}`` for caller-side
    metric emission.  Raises :class:`ToolRegistryDriftError` if either side
    has an orphan — a tool in the manifest with no handler, or a registered
    handler with no manifest entry.

    The manifest is loaded via :meth:`ToolRegistry.load_manifest` (the same
    loader the architecture tests use), so a single source of truth is
    consulted both for parity here and for the R29 sync test.
    """
    manifest_doc = registry.load_manifest()
    # The manifest schema is ``{"version": str, "tools": [{"name": str, ...}, ...]}``.
    # We cast through Any because ``load_manifest`` returns ``dict[str, Any]`` and
    # the entries are heterogeneous dicts.
    tools_list = cast("list[dict[str, Any]]", manifest_doc.get("tools", []))
    manifest_tools = {entry["name"] for entry in tools_list}
    handled_tools = {spec.name for spec in registry.all_specs()}

    # Orphan in manifest = YAML advertises a tool that no handler is registered for.
    # Orphan in handlers = registry has a handler that the YAML manifest does not
    # describe (so the LLM would never be told it exists).
    orphan_in_manifest = manifest_tools - handled_tools
    orphan_in_handlers = handled_tools - manifest_tools

    if orphan_in_manifest or orphan_in_handlers:
        raise ToolRegistryDriftError(
            "Tool registry drift detected. "
            f"In manifest only: {sorted(orphan_in_manifest)}. "
            f"Handled only: {sorted(orphan_in_handlers)}."
        )
    return {"manifest": len(manifest_tools), "handled": len(handled_tools)}


def build_default_registry() -> ToolRegistry:
    """Factory: create a ToolRegistry with all 22 tools registered.

    Breakdown: 10 v1 + 4 PLAN-0080 v2 + 6 PLAN-0081 v3 + 2 PLAN-0082 v4.

    Called by api/dependencies.py to wire the ToolExecutor at startup.
    The handlers registered here are placeholder stubs — the actual execution
    is dispatched inside ToolExecutor.execute() via name-based dispatch, not
    through the handler stored in the registry. The registry handler field is
    kept for future extension (e.g. PLAN-0067 full tool catalog).
    """
    from tools.tool_spec import ParameterSpec, ToolSpec  # type: ignore[import-untyped,import-not-found]

    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="get_price_history",
            description=(
                # PLAN-0109 B-3: teach the LLM the new flexible parameter
                # shape. The implicit 7d/1m fallback was removed in favour
                # of explicit ``last_n_bars`` / ``lookback_days`` knobs the
                # LLM can pick deliberately based on the user's question.
                "Fetches OHLCV (open/high/low/close/volume) bar history for a stock ticker. "
                "Only ``ticker`` is required. Provide ONE of the temporal patterns below:\n"
                "  - ``last_n_bars=1, interval='1m'`` for \"what is AAPL trading at?\" "
                "(works 24/7 — returns the most recent 1-minute bar).\n"
                "  - ``last_n_bars=7, interval='day'`` for \"the last week of daily prices\".\n"
                "  - ``lookback_days=30, interval='hour'`` for \"the last 30 days of hourly bars\".\n"
                "  - ``from_date`` + ``to_date`` (both required as a pair) for an explicit "
                'calendar window such as "Q1 2026".\n'
                "When no temporal parameter is supplied, defaults to ``last_n_bars=20`` "
                "(one screen of bars at the requested interval)."
            ),
            parameters=[
                ParameterSpec(
                    name="ticker",
                    type="string",
                    description="Stock ticker symbol (e.g. 'AAPL')",
                    required=True,
                ),
                ParameterSpec(
                    name="from_date",
                    type="date",
                    description=(
                        "Start of explicit date range (YYYY-MM-DD). Optional — pair with "
                        "``to_date`` for a calendar window. Ignored when ``last_n_bars`` or "
                        "``lookback_days`` is supplied."
                    ),
                    required=False,
                ),
                ParameterSpec(
                    name="to_date",
                    type="date",
                    description=(
                        "End of explicit date range (YYYY-MM-DD). Optional — pair with "
                        "``from_date``. Ignored when ``last_n_bars`` or ``lookback_days`` "
                        "is supplied."
                    ),
                    required=False,
                ),
                ParameterSpec(
                    name="last_n_bars",
                    type="integer",
                    description=(
                        "Return the N most-recent bars of the requested interval. "
                        "Use ``last_n_bars=1, interval='1m'`` for current-price queries."
                    ),
                    required=False,
                ),
                ParameterSpec(
                    name="lookback_days",
                    type="integer",
                    description=(
                        "Return bars from the last N calendar days ending today. "
                        "Pairs naturally with intra-day intervals (hour/1m)."
                    ),
                    required=False,
                ),
                ParameterSpec(
                    name="interval",
                    type="string",
                    # Chat-eval #5 NEW root cause A (2026-06-12): the backend
                    # ``/ohlcv/bars`` endpoint does NOT aggregate ``week``/
                    # ``month`` bars, so advertising them made the LLM pick them
                    # for "YTD high/low" and "P/E vs history" questions and burn
                    # iterations retrying on error. Drop them from the enum so the
                    # model only ever selects supported grains (intraday + day).
                    description="Bar granularity: 1m/hour/day. Default 'day'.",
                    required=False,
                    enum=["1m", "hour", "day"],
                ),
            ],
            source_type="ohlcv",
            example_queries=[
                "What is AAPL trading at?",
                "Show me the last week of daily prices for NVDA",
                "Plot the last 30 days of hourly bars for TSLA",
                "How has AAPL performed over the last 3 months?",
            ],
        ),
        handler=lambda **_: None,  # dispatch happens inside ToolExecutor.execute()
    )

    registry.register(
        ToolSpec(
            name="get_fundamentals_history",
            description=(
                # PLAN-0097 T-W3-03: reciprocal anti-pattern callout. Iter-9
                # chat-eval showed the LLM looping this singular tool for
                # multi-ticker comparisons; the warning routes those cases to
                # `get_fundamentals_history_batch` (5-10x faster).
                "Fetches quarterly fundamental metrics (revenue, gross profit, net income, "
                "EPS, P/E ratio, market cap) for a SINGLE ticker over N periods. Use when the "
                "user asks about revenue trends, EPS growth, or multi-quarter financial "
                "performance for ONE company. "
                "**Do NOT call this in a loop over multiple tickers — use "
                "`get_fundamentals_history_batch` instead.** Calling this tool N times in "
                "sequence is 5-10x slower than one batch call and is a tool-selection bug."
            ),
            parameters=[
                ParameterSpec(
                    name="ticker",
                    type="string",
                    description="Stock ticker symbol (e.g. 'MSFT')",
                    required=True,
                ),
                ParameterSpec(
                    name="periods",
                    type="integer",
                    description="Number of periods to return (1-20). Default 8.",
                    required=False,
                ),
                # F-LIVE-P (2026-05-26): explicit periodicity selector. The LLM
                # almost always wants quarterly, so we keep that as the default
                # and document the rare annual case in the description. The
                # handler validates and falls back to "quarterly" on anything
                # outside the allowlist.
                ParameterSpec(
                    name="period_type",
                    type="string",
                    description=(
                        'Periodicity of returned rows. Allowed values: "quarterly" '
                        '(default), "annual". Any other value falls back to "quarterly".'
                    ),
                    required=False,
                ),
            ],
            source_type="fundamentals",
            example_queries=[
                "Show me MSFT's revenue trend over 8 quarters",
                "What has AAPL's EPS been over the last 2 years?",
            ],
        ),
        handler=lambda **_: None,
    )

    # PLAN-0067 Wave W11-2: register remaining 8 tools (PLAN-0087 Wave F D-R1-002:
    # full ParameterSpec lists + descriptions mirrored from capability_manifest.yaml
    # so OpenAI tool definitions emitted by ``ToolRegistry.to_tool_definitions()``
    # carry the same schema the architecture sync test (R29) validates the YAML
    # against). Handlers are placeholder stubs — dispatch is inside
    # ToolExecutor.execute() via name-based routing, not via the registry handler.

    registry.register(
        ToolSpec(
            name="search_documents",
            description=(
                "Searches the platform's document corpus using hybrid BM25 + ANN embedding search. "
                "Returns text excerpts from news articles, SEC filings (10-K, 10-Q, 8-K), earnings "
                "call transcripts, and analyst reports. Use for open-ended factual questions that "
                "need free-text evidence from documents (e.g. 'what risks does AAPL cite in its "
                "10-K', 'what did analysts say about NVDA data-centre revenue'). This is a "
                "LAST-RESORT, broad retrieval tool — prefer the dedicated structured tool whenever "
                "the question shape matches one.\n"
                "DO NOT use this tool for — route to the named tool instead:\n"
                "  - earnings dates / who-reports-when / earnings season → get_earnings_calendar.\n"
                "  - macro / economic events (CPI, FOMC, GDP) → get_economic_calendar.\n"
                "  - latest news on ONE named company/ticker → get_entity_news.\n"
                "  - a company's relationships / partners / subsidiaries / board / 'before joining "
                "X' history → traverse_graph, search_entity_relations, or get_entity_intelligence.\n"
                "  - the relation BETWEEN two named entities → traverse_graph.\n"
                "  - numeric fundamentals (revenue, margins, P/E, EPS, growth) → query_fundamentals "
                "or get_fundamentals_history (single ticker) / get_fundamentals_history_batch "
                "(2+ tickers).\n"
                "  - side-by-side comparison of 2-4 tickers → compare_entities.\n"
                "  - corporate events (M&A, leadership change, product launch) for an entity → "
                "search_events.\n"
                "  - analyst claims / price targets / sector theses → search_claims.\n"
                "  - filtering the stock universe by criteria (sector, market cap, margin) → "
                "screen_universe.\n"
                "GUARDRAIL: if a search_documents call returns NO rows, do NOT re-issue the same or "
                "a near-identical query — either escalate to the matching structured tool above or "
                "answer that no documents were found."
            ),
            parameters=[
                ParameterSpec(name="query", type="string", description="Natural language search query", required=True),
                ParameterSpec(
                    name="entity_tickers",
                    type="array",
                    description='List of stock tickers to constrain results (e.g. ["AAPL", "MSFT"])',
                    required=False,
                ),
                ParameterSpec(
                    name="date_from",
                    type="date",
                    description="Earliest document date (YYYY-MM-DD). Optional.",
                    required=False,
                ),
                ParameterSpec(
                    name="date_to",
                    type="date",
                    description="Latest document date (YYYY-MM-DD). Optional.",
                    required=False,
                ),
                ParameterSpec(
                    name="source_types",
                    type="array",
                    description="Filter by source: ['sec_filing', 'earnings', 'news', 'analyst_report']",
                    required=False,
                ),
            ],
            source_type="mixed",
            example_queries=[
                "What risks does AAPL mention in their latest 10-K?",
                "What did analysts say about NVDA's data centre revenue?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="get_entity_graph",
            description=(
                "Retrieves the egocentric knowledge graph for a SINGLE named entity — its immediate "
                "neighbours, relationships, and confidence scores. Use ONLY for explicit structural "
                "questions about ONE entity's direct neighbours: 'who are X's partners', 'what are "
                "X's subsidiaries', 'what board seats does X hold'. "
                "DO NOT use for: (1) peer / competitor / 'who does X compete with' questions — the KG "
                "is sparse on competitor_of edges and will return empty; use get_entity_intelligence "
                "(returns relations_summary + narrative) or compare_entities for those. "
                "(2) biographical or career-history questions about people ('what did X do before Y') "
                "— use get_entity_intelligence for narrative. "
                "(3) the relationship BETWEEN two named entities — use traverse_graph or "
                "get_entity_paths for cross-entity path finding. "
                "If this tool returns empty or sparse results for a well-known entity, you may "
                "supplement with training knowledge but MUST label it 'Based on public knowledge: …' "
                "— never invent confidence scores or graph metadata."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_name",
                    type="string",
                    description="Name of the entity (company, person, fund) to build the graph around",
                    required=True,
                ),
                ParameterSpec(
                    name="depth",
                    type="integer",
                    description="Graph hop depth (1 or 2). Default 1. Use 2 for broader connectivity.",
                    required=False,
                ),
                ParameterSpec(
                    name="relation_types",
                    type="array",
                    description=(
                        "Filter by relation type: ['subsidiary_of', 'board_member_of', 'partnership', 'competitor_of']"
                    ),
                    required=False,
                ),
            ],
            source_type="knowledge_graph",
            example_queries=[
                "What companies is Elon Musk connected to?",
                "Who are AAPL's main subsidiaries?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="traverse_graph",
            description=(
                "Finds paths between TWO named entities in the knowledge graph via multi-hop "
                "traversal. USE THIS TOOL ONLY when the question names two entities explicitly: "
                "'what is the relation between X and Y', 'how is X connected to Y', 'is X related "
                "to Y', 'shared board members of X and Y', 'is X an investor in Y'. "
                "Provide BOTH start_entity AND target_entity (e.g. start_entity='Apple', "
                "target_entity='Anthropic'). Also useful for indirect chains (shared investors, "
                "board-member chains, 3+ hops). Returns direct and indirect paths with relation "
                "types and confidence scores. "
                "DO NOT use for: (1) single-entity peer / competitor / 'who are X's rivals' questions "
                "— there is no second entity to traverse toward; use get_entity_intelligence or "
                "compare_entities. (2) biographical / 'before joining Apple' questions — use "
                "get_entity_intelligence. (3) pre-ranked top-N paths anchored on one entity — use "
                "get_entity_paths (no target needed; cheaper and pre-computed)."
            ),
            parameters=[
                ParameterSpec(name="start_entity", type="string", description="Starting entity name", required=True),
                ParameterSpec(
                    name="target_entity",
                    type="string",
                    description="Target entity name to find paths to. Optional.",
                    required=False,
                ),
                ParameterSpec(
                    name="depth",
                    type="integer",
                    description="Maximum path depth (2-4). Default 3.",
                    required=False,
                ),
                ParameterSpec(
                    name="cypher_pattern",
                    type="string",
                    description='Optional Cypher relationship filter (e.g. "[:INVESTS_IN|:BOARD_MEMBER_OF]")',
                    required=False,
                ),
            ],
            source_type="knowledge_graph",
            example_queries=[
                "How is Sam Altman connected to Microsoft?",
                "Are AAPL and MSFT connected through any shared board members?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="search_entity_relations",
            description=(
                "Searches for relation triplets involving an entity in the knowledge graph. "
                "Returns structured (subject, relation_type, object) triples with confidence scores. "
                "**Use this — NOT search_documents — to list what is known about ONE entity's "
                "relationships** (who it invests in, competes with, acquired, partners with, "
                "supplies). Triggers: 'who does X invest in', 'list X's acquisitions', 'X's "
                "suppliers/partners'. For the relationship BETWEEN two named entities use "
                "traverse_graph instead; for narrative career/biographical history use "
                "get_entity_intelligence."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_name",
                    type="string",
                    description="Entity to find relations for",
                    required=True,
                ),
                ParameterSpec(
                    name="relation_type",
                    type="string",
                    description=("Specific relation type to filter: 'invests_in', 'competes_with', 'acquired', etc."),
                    required=False,
                ),
                ParameterSpec(
                    name="min_confidence",
                    type="number",
                    description="Minimum confidence threshold (0.0-1.0). Default 0.6.",
                    required=False,
                ),
                ParameterSpec(
                    name="limit",
                    type="integer",
                    description="Maximum number of relations to return. Default 15.",
                    required=False,
                ),
            ],
            source_type="knowledge_graph",
            example_queries=[
                "List all companies that Microsoft has acquired",
                "What companies compete with NVIDIA in the GPU market?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="search_claims",
            description=(
                "Searches for analyst claims and extracted assertions about an entity or theme. "
                "Claims are LLM-extracted structured statements from financial documents (e.g., "
                '"AAPL will expand into India"). **Use this — NOT search_documents — for '
                "opinion / thesis / target-price questions and for SECTOR or THEME claims** "
                "(e.g. 'what are analysts saying about AI-chip demand', 'bullish theses on "
                "semiconductors'). For a broad sector thesis, query by the theme rather than "
                "narrowing to a single company. Use when you need to contrast what analysts "
                "are saying."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_name",
                    type="string",
                    description="Entity the claims are about",
                    required=True,
                ),
                ParameterSpec(
                    name="claim_type",
                    type="string",
                    description=("Type of claim: 'price_target', 'revenue_forecast', 'risk_factor', 'strategic_move'"),
                    required=False,
                ),
                ParameterSpec(
                    name="date_from",
                    type="date",
                    description="Earliest claim extraction date (YYYY-MM-DD)",
                    required=False,
                ),
                ParameterSpec(
                    name="date_to",
                    type="date",
                    description="Latest claim extraction date (YYYY-MM-DD)",
                    required=False,
                ),
            ],
            source_type="knowledge_graph",
            example_queries=[
                "What are analysts saying about AAPL's AI strategy?",
                "What are analysts forecasting for MSFT's revenue next quarter?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="search_events",
            description=(
                "Retrieves structured corporate events involving an entity — earnings releases, "
                "M&A activity, leadership changes, product launches, regulatory filings. "
                "**Use this — NOT search_documents — for timeline / event-based questions** "
                "('when did X last acquire a company', 'what M&A happened in healthcare in 2024', "
                "'recent leadership changes at Tesla'). Filter by event_type and date range rather "
                "than free-text searching. For earnings DATES specifically, prefer "
                "get_earnings_calendar."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_name",
                    type="string",
                    description="Entity involved in the events",
                    required=True,
                ),
                ParameterSpec(
                    name="event_type",
                    type="string",
                    description=(
                        "Event type: 'earnings', 'merger', 'acquisition', 'ipo', 'leadership_change', 'product_launch'"
                    ),
                    required=False,
                ),
                ParameterSpec(name="date_from", type="date", description="Earliest event date", required=False),
                ParameterSpec(name="date_to", type="date", description="Latest event date", required=False),
            ],
            source_type="knowledge_graph",
            example_queries=[
                "When did AAPL last announce a major acquisition?",
                "What leadership changes happened at Tesla in 2025?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="get_contradictions",
            description=(
                "Retrieves cross-source contradictions detected in analyst claims about an entity. "
                "Returns pairs of conflicting statements with their strength and sources. "
                "Use when the question is about disagreement, uncertainty, or conflicting signals."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_name",
                    type="string",
                    description="Entity to find contradictions for",
                    required=True,
                ),
                ParameterSpec(
                    name="confidence_threshold",
                    type="number",
                    description="Minimum contradiction strength (0.0-1.0). Default 0.5.",
                    required=False,
                ),
            ],
            source_type="knowledge_graph",
            example_queries=[
                "Are there conflicting analyst views on TSLA's profitability?",
                "Are there contradictions between analysts about Amazon's profitability?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="get_portfolio_context",
            description=(
                "Retrieves the current user's portfolio holdings and watchlist. Use when the "
                "question references the user's own positions, portfolio P&L, or watchlisted "
                'stocks. Do NOT call this tool unless the question explicitly references "my '
                'portfolio", "my holdings", "my watchlist", or similar personal context.'
            ),
            # WHY parameters=[]: this tool has no inputs; user identity is auto-injected
            # from the authenticated request context, never supplied by the LLM.
            parameters=[],
            source_type="portfolio",
            example_queries=[
                "How is my portfolio performing today?",
                "Which of my holdings have the highest exposure to AI?",
            ],
        ),
        handler=lambda **_: None,
    )

    # PLAN-0080 Wave A: register 4 intelligence tools (get_entity_narrative, get_entity_paths,
    # get_entity_health, get_entity_intelligence). These are distinct from the S7 KG tools —
    # they call S9-proxied intelligence endpoints (R14 compliance).
    # PLAN-0087 Wave F D-R1-002: full schemas mirrored from capability_manifest.yaml.

    registry.register(
        ToolSpec(
            name="get_entity_narrative",
            description=(
                "Retrieves the current LLM-generated narrative for an entity — a curated markdown "
                "summary of the entity's recent developments, strategic position, and key signals. "
                "Use when the user asks for an overview, summary, or what's been happening with an "
                "entity. Returns the latest narrative version. High-authority source "
                "(platform-curated)."
            ),
            parameters=[
                # entity_id is required=False because the orchestrator auto-injects it from
                # the active EntityContext when the user does not supply one.  The handler
                # validates presence at execution time.
                ParameterSpec(
                    name="entity_id",
                    type="string",
                    description=(
                        "Entity identifier: UUID, ticker symbol (e.g. 'AAPL'), or company name "
                        "(e.g. 'Apple Inc.'). Tickers and names are resolved server-side (BP-661). "
                        "Auto-injected from entity scope when available."
                    ),
                    required=False,
                ),
            ],
            source_type="narrative",
            example_queries=[
                "Give me a summary of what's been happening with Apple",
                "What's the latest narrative on NVDA?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="get_entity_paths",
            description=(
                "Retrieves top-N PRE-COMPUTED multi-hop relationship paths anchored on a SINGLE "
                "entity, ranked by composite_score (S7 path-insight pipeline). Use when the user "
                "asks 'what are the most important relationships of X', 'show me X's network', "
                "'top connections for X' — one anchor, no specific target. "
                "DO NOT use for: (1) two-entity 'how is X connected to Y' questions — use "
                "traverse_graph (live AGE walk between the two names). (2) full intelligence "
                "bundles (narrative + relations + health) — use get_entity_intelligence which "
                "wraps this tool plus the others in one call. (3) direct neighbours / 'who are "
                "X's partners' structural lookups — use get_entity_graph."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_id",
                    type="string",
                    description=(
                        "Entity identifier: UUID, ticker symbol (e.g. 'AAPL'), or company name. "
                        "Resolved server-side. Auto-injected from entity scope when available."
                    ),
                    required=False,
                ),
                ParameterSpec(
                    name="top_n",
                    type="integer",
                    description="Number of top paths to return (1-20). Default 5.",
                    required=False,
                ),
            ],
            source_type="knowledge_graph",
            example_queries=[
                "What are the most significant connections in AAPL's network?",
                "Show me the top relationship paths for Microsoft",
            ],
        ),
        handler=lambda **_: None,
    )

    # PLAN-0112 W4: on-demand TWO-ENTITY pairwise pathfinding (FR-9). Distinct
    # from get_entity_paths (single anchor, pre-computed): this binds BOTH ends
    # and searches live via S9 /v1/paths/between (R14). Manifest bumped to v5.
    registry.register(
        ToolSpec(
            name="get_path_between",
            description=(
                "Performs an ON-DEMAND, live, bounded search for connection PATHS between TWO "
                "specific entities — 'is X connected to Y, and how are they linked?'. Returns "
                "whether a connection exists within max_hops, the shortest hop count, and the "
                "ranked intermediary paths (ranked by how surprising the connection is). Use "
                "this for ANY two-entity relationship question: 'how is Nvidia connected to "
                "SpaceX', 'is Apple linked to OpenAI', 'what connects Microsoft and Anthropic'. "
                "DO NOT use for single-entity network questions — use get_entity_paths "
                "(one anchor, pre-computed) instead."
            ),
            parameters=[
                ParameterSpec(
                    name="source_entity",
                    type="string",
                    description=(
                        "First entity — UUID, ticker symbol (e.g. 'NVDA'), or company name. Resolved server-side."
                    ),
                    required=True,
                ),
                ParameterSpec(
                    name="target_entity",
                    type="string",
                    description=(
                        "Second entity — UUID, ticker, or company name. Resolved server-side. "
                        "Must differ from source_entity."
                    ),
                    required=True,
                ),
                ParameterSpec(
                    name="max_hops",
                    type="integer",
                    description="Maximum path length to search (1-3). Default 3.",
                    required=False,
                ),
            ],
            source_type="knowledge_graph",
            example_queries=[
                "How is Nvidia connected to SpaceX?",
                "Is Apple linked to OpenAI, and how?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="get_entity_health",
            description=(
                "Retrieves the entity health score, key metrics, source distribution, and 90-day "
                "confidence trend. Use when the user asks about data quality, confidence in the "
                "entity's information, how well-covered the entity is, or signal health."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_id",
                    type="string",
                    description=(
                        "Entity identifier: UUID, ticker symbol (e.g. 'AAPL'), or company name. "
                        "Resolved server-side. Auto-injected from entity scope when available."
                    ),
                    required=False,
                ),
            ],
            source_type="narrative",
            example_queries=[
                "How confident are we in the data on Apple?",
                "What is TSLA's data health score?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="get_entity_intelligence",
            description=(
                "Retrieves the FULL intelligence bundle for a single entity — combining narrative "
                "summary, top relationship paths, health score, and relations_summary (peers, "
                "competitors, partners) in ONE call. PREFER this tool whenever the user asks: "
                "(1) for a comprehensive overview, 'tell me everything about X', 'what's going on "
                "with X'; (2) BIOGRAPHICAL or career-history questions about people / executives — "
                "'what did Tim Cook do before Apple', 'who is Sam Altman', 'background on Lisa Su' "
                "— the narrative section covers career timeline; (3) PEER / competitor / 'who does "
                "X compete with' questions — the relations_summary surfaces competitor / partner "
                "buckets even when KG competitor_of edges are sparse. "
                "DO NOT use for: (1) two-entity 'how is X connected to Y' — use traverse_graph. "
                "(2) raw structural neighbour lists with relation_type filters — use get_entity_graph. "
                "(3) side-by-side numeric comparison of 2+ tickers — use compare_entities."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_id",
                    type="string",
                    description=(
                        "Entity identifier: UUID, ticker symbol (e.g. 'AAPL'), or company name "
                        "(e.g. 'Apple Inc.'). Tickers and names are resolved server-side (BP-661). "
                        "Auto-injected from entity scope when available."
                    ),
                    required=False,
                ),
            ],
            source_type="narrative",
            example_queries=[
                "Tell me everything about Apple",
                "Give me the full intelligence report on NVDA",
            ],
        ),
        handler=lambda **_: None,
    )

    # PLAN-0081 Wave A: register 6 catalog tools (brief, compare, screener, movers, calendars).
    # These call S9-proxied endpoints or the DB archive (R14 compliance).
    # PLAN-0087 Wave F D-R1-002: full schemas mirrored from capability_manifest.yaml.

    registry.register(
        ToolSpec(
            name="get_morning_brief",
            description=(
                "Retrieves the user's latest morning brief — a curated daily summary of "
                "portfolio-relevant news, earnings, and macro events. Use when the user asks "
                "for their brief, today's brief, morning brief, or \"what's happening today\". "
                "Returns the brief headline, lead, and all sections."
            ),
            # WHY parameters=[]: brief is keyed on the authenticated user; no LLM inputs.
            parameters=[],
            source_type="narrative",
            example_queries=[
                "Show me my morning brief",
                "What's in my brief today?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="compare_entities",
            description=(
                "FINANCIAL side-by-side comparison of 2-4 stock tickers: fundamentals highlights "
                "(market cap, P/E, revenue, EPS) and latest price quote — one row per ticker. "
                "Use when the user asks 'compare AAPL and MSFT', 'how does NVDA stack up vs AMD', "
                "'which of {A, B, C} has the higher P/E'. This is a FINANCIAL tool — output is "
                "numeric metrics, not relationships or narrative. "
                "DO NOT use for: (1) relationship questions between the two tickers ('is X "
                "connected to Y', 'do they share board members') — use traverse_graph. "
                "(2) qualitative narrative / 'which is the better business' — use "
                "get_entity_intelligence per entity. (3) historical time-series for one entity — "
                "use get_fundamentals_history."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_tickers",
                    type="array",
                    description='List of 2-4 stock tickers to compare (e.g. ["AAPL", "MSFT"])',
                    required=True,
                ),
            ],
            source_type="fundamentals",
            example_queries=[
                "Compare AAPL and MSFT side by side",
                "Show me a comparison of NVDA, AMD, and INTC",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="screen_universe",
            description=(
                "Quantitative screener — filters the instrument universe by market cap, P/E ratio, "
                "sector, industry, and region. Use when the user asks to screen, filter, or find "
                "stocks that meet specific fundamental criteria. For AI-chip / semiconductor "
                "queries, set sector='Technology' AND industry='Semiconductors' (GICS taxonomy)."
            ),
            parameters=[
                ParameterSpec(
                    name="market_cap_min",
                    type="number",
                    description="Minimum market cap in USD (e.g. 1000000000 for $1B)",
                    required=False,
                ),
                ParameterSpec(
                    name="market_cap_max",
                    type="number",
                    description="Maximum market cap in USD",
                    required=False,
                ),
                ParameterSpec(
                    name="pe_ratio_max",
                    type="number",
                    description="Maximum P/E ratio (e.g. 25.0)",
                    required=False,
                ),
                ParameterSpec(
                    name="sector",
                    type="string",
                    description="Sector filter (e.g. 'Technology', 'Healthcare')",
                    required=False,
                ),
                # FIX-LIVE-M (2026-05-24): GICS industry filter — more specific than
                # sector. "AI chip" / "semiconductor" queries need industry='Semiconductors'
                # (sector='Technology' alone returns too many irrelevant SaaS/IT names).
                ParameterSpec(
                    name="industry",
                    type="string",
                    description="Industry filter (e.g. 'Semiconductors', 'Cloud Computing')",
                    required=False,
                ),
                ParameterSpec(
                    name="region",
                    type="string",
                    description="Region filter (e.g. 'US', 'EU')",
                    required=False,
                ),
                ParameterSpec(
                    name="limit",
                    type="integer",
                    description="Maximum number of results (1-100). Default 20.",
                    required=False,
                ),
                # PLAN-0103 W1 (BP-622): fundamentals-grade metric filters.
                # These map to columns in market-data's metric_extractor.
                ParameterSpec(
                    name="revenue_growth_yoy_min",
                    type="number",
                    description=(
                        "Minimum quarter-over-year-ago revenue growth, e.g. 0.0 for any "
                        "positive growth, 0.10 for >=10%."
                    ),
                    required=False,
                ),
                ParameterSpec(
                    name="revenue_growth_yoy_max",
                    type="number",
                    description="Maximum quarter-over-year-ago revenue growth.",
                    required=False,
                ),
                ParameterSpec(
                    name="gross_margin_min",
                    type="number",
                    description="Minimum gross margin as a decimal (e.g. 0.40 for >=40%).",
                    required=False,
                ),
                ParameterSpec(
                    name="gross_margin_max",
                    type="number",
                    description="Maximum gross margin as a decimal.",
                    required=False,
                ),
                ParameterSpec(
                    name="roe_min",
                    type="number",
                    description="Minimum return on equity as a decimal (e.g. 0.15 for >=15%).",
                    required=False,
                ),
                ParameterSpec(
                    name="dividend_yield_min",
                    type="number",
                    description="Minimum dividend yield as a decimal (e.g. 0.02 for >=2%).",
                    required=False,
                ),
                ParameterSpec(
                    name="dividend_yield_max",
                    type="number",
                    description="Maximum dividend yield as a decimal.",
                    required=False,
                ),
            ],
            source_type="fundamentals",
            example_queries=[
                "Screen for tech stocks with P/E under 20 and market cap over $10B",
                "Find large-cap US healthcare companies",
                "AI semiconductor companies with market cap > $50B and positive YoY revenue growth",
            ],
        ),
        handler=lambda **_: None,
    )

    # PLAN-0103 W2 — entity-anchored news feed (Q1 follow-up from the
    # 2026-05-29 real-user audit).  Routes through the per-entity
    # /briefing-articles endpoint so the LLM gets per-entity relevance
    # scoring instead of falling back to broad search_documents.
    registry.register(
        ToolSpec(
            name="get_entity_news",
            description=(
                "Latest news articles mentioning a specific entity (by entity_id OR ticker), "
                "filtered by date range. Use this for 'what's the latest on X' questions "
                "where the user names a single entity. PREFER over search_documents when "
                "the user asks about ONE specific company or ticker."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_id",
                    type="string",
                    description="Canonical entity UUID. Provide this OR ticker.",
                    required=False,
                ),
                ParameterSpec(
                    name="ticker",
                    type="string",
                    description="Ticker symbol (e.g. 'MSTR'). Resolved server-side.",
                    required=False,
                ),
                ParameterSpec(
                    name="days_back",
                    type="integer",
                    description="Look back N days (1-90). Default 14.",
                    required=False,
                ),
                ParameterSpec(
                    name="max_results",
                    type="integer",
                    description="Max articles to return (1-20). Default 10.",
                    required=False,
                ),
            ],
            source_type="news_article",
            example_queries=[
                "Show me the latest news on MSTR",
                "What's happening with NVDA this week?",
                "Any recent news about Tesla?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="get_market_movers",
            description=(
                "Returns the top gainers, losers, or most-active stocks over a time period. "
                "Use when the user asks about market movers, top performers, biggest "
                "gainers/losers, or most-active stocks."
            ),
            parameters=[
                ParameterSpec(
                    name="mover_type",
                    type="string",
                    description="Type of movers: 'gainers' or 'losers'. Default 'gainers'.",
                    required=False,
                    enum=["gainers", "losers"],
                ),
                ParameterSpec(
                    name="limit",
                    type="integer",
                    description="Number of results (1-50). Default 10.",
                    required=False,
                ),
                ParameterSpec(
                    name="period",
                    type="string",
                    description="Time period: '1D', '1W', '1M'. Default '1D'.",
                    required=False,
                ),
            ],
            source_type="market_data",
            example_queries=[
                "What are the top market movers today?",
                "Show me the biggest losers this week",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="get_economic_calendar",
            description=(
                "Retrieves upcoming and past macro economic events (CPI, FOMC, GDP releases, "
                "PMI data) with actual vs. forecast vs. prior values. Use when the user asks "
                "about economic events, macro calendar, upcoming data releases, or central bank "
                "decisions."
            ),
            parameters=[
                ParameterSpec(
                    name="from_date",
                    type="date",
                    description="Start of date range (YYYY-MM-DD). Optional.",
                    required=False,
                ),
                ParameterSpec(
                    name="to_date",
                    type="date",
                    description="End of date range (YYYY-MM-DD). Optional.",
                    required=False,
                ),
                ParameterSpec(
                    name="region",
                    type="string",
                    description="Region filter: 'US', 'EU', 'global'. Optional.",
                    required=False,
                ),
            ],
            source_type="market_data",
            example_queries=[
                "What economic events are coming up this week?",
                "When is the next FOMC meeting?",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="get_earnings_calendar",
            description=(
                "**Use this tool — NOT search_documents — for ANY question about earnings DATES "
                "or the earnings calendar.** Returns earnings release dates for companies "
                "including EPS estimates and actuals. Triggers: 'who reports earnings next week', "
                "'when does Apple next report', 'earnings season', 'upcoming earnings for my "
                "portfolio'. Free-text document search will NOT reliably surface a structured "
                "calendar — always come here first for earnings timing."
            ),
            parameters=[
                ParameterSpec(
                    name="from_date",
                    type="date",
                    description="Start of date range (YYYY-MM-DD). Optional.",
                    required=False,
                ),
                ParameterSpec(
                    name="to_date",
                    type="date",
                    description="End of date range (YYYY-MM-DD). Optional.",
                    required=False,
                ),
            ],
            source_type="market_data",
            example_queries=[
                "What companies are reporting earnings this week?",
                "When does Apple next report earnings?",
            ],
        ),
        handler=lambda **_: None,
    )

    # PLAN-0082 Wave A + Wave B: register 2 action tools (get_alerts, create_alert).
    # Calls S9-proxied S10 alert endpoints (R14 compliance).
    # create_alert requires user confirmation before execution (requires_confirmation=true).
    # PLAN-0087 Wave F D-R1-002: full schemas mirrored from capability_manifest.yaml.

    registry.register(
        ToolSpec(
            name="get_alerts",
            description=(
                "Retrieves the user's active (pending) alerts — price alerts, signal alerts, "
                'and watchlist triggers. Use when the user asks "show me my alerts", "what '
                'alerts do I have", or "are there any active alerts for my portfolio".'
            ),
            # WHY parameters=[]: alerts are keyed on the authenticated user; no LLM inputs.
            parameters=[],
            source_type="alert",
            example_queries=[
                "Show me my active alerts",
                "What alerts do I have set up?",
            ],
        ),
        handler=lambda **_: None,
    )

    # PLAN-0095 W2 T-W2-02: batched fundamentals fan-out tool.
    # WHY a separate tool (not an overload of get_fundamentals_history): tool
    # arguments cannot be array-OR-string in the OpenAI tool-calling schema
    # without forcing the LLM to wrap singletons in a list every time, which
    # ITER-7 evals showed it gets wrong ~30% of the time. A dedicated batch
    # tool lets the model keep using the singular tool for one-shot lookups
    # and the batch tool only when it has 2+ tickers — which matches its
    # actual reasoning pattern (deciding-up-front vs. exploring-one).
    registry.register(
        ToolSpec(
            name="get_fundamentals_history_batch",
            description=(
                # PLAN-0097 T-W3-03: strict imperative directive at the top.
                # Soft phrasing ("use this when comparing") was insufficient —
                # iter-9 chat-eval showed the LLM still iterated the singular
                # tool. Bold "**Use this tool — NOT ...**" forces tool selection
                # on the first turn.
                "**Use this tool — NOT `get_fundamentals_history` — when the user mentions "
                "2 or more tickers, OR when you have a list of tickers from a screener "
                "result, OR when comparing multiple companies.** Calling "
                "`get_fundamentals_history` in a loop is 5-10x slower and is a "
                "tool-selection bug. "
                "Fetches quarterly fundamental metrics (revenue, gross profit, net income, "
                "EPS, P/E, market cap) for MULTIPLE tickers in a single call. "
                "Returns a per-ticker dict {ticker: {status: ok|error, periods?, "
                "reason?}}; partial failures (unknown ticker, missing data) do not fail the "
                "whole batch. Cap: 25 tickers per call."
            ),
            parameters=[
                ParameterSpec(
                    name="tickers",
                    type="array",
                    description='List of stock tickers to fetch (e.g. ["AAPL", "MSFT", "NVDA"]). Max 25.',
                    required=True,
                ),
                ParameterSpec(
                    name="periods",
                    type="integer",
                    description="Number of quarters per ticker (1-20). Default 5.",
                    required=False,
                ),
            ],
            source_type="fundamentals",
            example_queries=[
                "Compare revenue growth of AAPL, MSFT, GOOG, AMZN, META",
                "Get the last 4 quarters of fundamentals for the top 5 AI chip stocks",
            ],
        ),
        handler=lambda **_: None,
    )

    # PLAN-0104 W32: unified parameterised fundamentals query.
    # WHY a SEPARATE tool (not a flag on get_fundamentals_history): the OpenAI
    # tool-calling schema cannot express "this method takes a metric list AND
    # returns a polymorphic shape" without confusing the LLM. Keeping the
    # legacy 6-column tool (revenue/eps/net_income/...) for simple lookups
    # and this rich tool for non-standard metrics matches how the LLM
    # actually reasons — it picks the tool whose advertised columns match
    # the user's question vocabulary.
    registry.register(
        ToolSpec(
            name="query_fundamentals",
            description=(
                "Parameterised fundamentals query for a SINGLE ticker. Use this — "
                "NOT `get_fundamentals_history` — when the user asks about metrics "
                "BEYOND the standard revenue/EPS/net-income/P-E triple. Examples: "
                "gross margin, operating margin, net margin, forward P/E, PEG ratio, "
                "EV/EBITDA, EV/Revenue, FCF yield, consensus EPS for current or "
                "next year, quarterly revenue/earnings growth YoY, ROE, dividend "
                "yield. You declare the metric list and the tool returns both a "
                "per-period series AND a TTM/live snapshot block, with a "
                "per-metric coverage flag (ok | partial | missing) so you know "
                "which values are safe to quote and which to caveat or refuse on. "
                "Always read the Coverage line before quoting a metric — if it "
                "says 'missing', refuse rather than fabricate."
            ),
            parameters=[
                ParameterSpec(
                    name="ticker",
                    type="string",
                    description="Stock ticker symbol (e.g. 'AAPL')",
                    required=True,
                ),
                ParameterSpec(
                    name="metrics",
                    type="array",
                    description=(
                        "List of canonical metric names to fetch. Supported: "
                        "revenue, gross_profit, operating_income, net_income, ebit, "
                        "ebitda, eps, cost_of_revenue, research_development, "
                        "operating_cash_flow, capital_expenditures, free_cash_flow, "
                        "gross_margin, operating_margin, net_margin, ebitda_margin, "
                        "pe_ratio, forward_pe, peg_ratio, ev_ebitda, ev_revenue, "
                        "price_to_book, price_to_sales_ttm, market_cap, ebitda_ttm, "
                        "revenue_ttm, gross_profit_ttm, eps_ttm, diluted_eps_ttm, "
                        "dividend_yield, dividend_share, book_value, roe_ttm, "
                        "roa_ttm, operating_margin_ttm, profit_margin_ttm, "
                        "quarterly_revenue_growth_yoy, quarterly_earnings_growth_yoy, "
                        "consensus_eps_curr_quarter, consensus_eps_next_quarter, "
                        "consensus_eps_curr_year, consensus_eps_next_year, "
                        "wall_street_target_price, fcf_yield. Unknown names are "
                        "flagged 'missing' in coverage rather than rejected."
                    ),
                    required=True,
                ),
                ParameterSpec(
                    name="periods",
                    type="integer",
                    description=(
                        "Number of per-period rows to return (0-20). Default 8. "
                        "Pass 0 to get the snapshot only (no historical series)."
                    ),
                    required=False,
                ),
                ParameterSpec(
                    name="period_type",
                    type="string",
                    description=(
                        'Periodicity: "quarterly" (default) or "annual". Anything else falls back to "quarterly".'
                    ),
                    required=False,
                ),
                ParameterSpec(
                    name="include_snapshot",
                    type="boolean",
                    description="Include the TTM/live snapshot block (default true).",
                    required=False,
                ),
            ],
            source_type="fundamentals",
            example_queries=[
                "What's AAPL's forward P/E and PEG ratio?",
                "Show TSLA's gross margin trend over the last 8 quarters",
                "Get NVDA's consensus EPS for current and next year",
                "Compare AMZN's operating margin and FCF yield",
            ],
        ),
        handler=lambda **_: None,
    )

    registry.register(
        ToolSpec(
            name="create_alert",
            description=(
                "Creates a user-initiated alert rule for a specific entity and condition. "
                "**You MUST call this tool — and call it IMMEDIATELY — whenever the user "
                'issues an alert imperative such as "alert me when AAPL drops below $200", '
                '"set a price alert for NVDA above $1000", "notify me when TSLA spikes", or '
                '"add an alert for ...". Calling this tool is how the alert gets set.** '
                "How the confirmation gate works (READ THIS — it is the #1 mistake on this "
                "tool): the system itself handles user confirmation. When you call this tool, "
                "it does NOT execute the write immediately — it returns a structured pending "
                "action that the application surfaces to the user as a confirm/cancel card, and "
                "the user confirms there. Your job is ONLY to call the tool with the parsed "
                "entity + condition + threshold. Do NOT ask the user to confirm in your text "
                "reply, do NOT write a prose sentence like 'I need your confirmation before I "
                "proceed', and do NOT claim the alert has been or will be created in prose "
                "INSTEAD of calling this tool — the confirmation step happens automatically "
                "AFTER you call it. Free-texting a confirmation request or a fake 'alert set' "
                "message without calling this tool is a failure: the alert is never registered. "
                "The ONLY thing you must NOT do is invent an alert the user did not ask for — "
                "never create alerts speculatively or as a follow-up to an unrelated question."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_id",
                    type="string",
                    description=("UUID of the entity to watch (auto-injected from entity scope when available)"),
                    required=True,
                ),
                ParameterSpec(
                    name="condition",
                    type="string",
                    description=("Alert trigger condition: price_below | price_above | volume_spike | percent_change"),
                    required=True,
                    enum=["price_below", "price_above", "volume_spike", "percent_change"],
                ),
                ParameterSpec(
                    name="threshold",
                    type="object",
                    description=(
                        'Condition parameters as a JSON object, e.g. {"value": 200.0} or '
                        '{"percent": 5.0, "window": "1d"}'
                    ),
                    required=True,
                ),
                ParameterSpec(
                    name="severity",
                    type="string",
                    description="Alert severity tier. Default: low.",
                    required=False,
                    enum=["low", "medium", "high", "critical"],
                ),
            ],
            source_type="alert",
            example_queries=[
                "Alert me when AAPL drops below $200",
                "Set a price alert for NVDA above $1000",
                "Notify me if there's a volume spike on TSLA",
            ],
        ),
        handler=lambda **_: None,
    )

    return registry
