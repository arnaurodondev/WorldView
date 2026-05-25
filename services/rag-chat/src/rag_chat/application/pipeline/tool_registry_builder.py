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
                "Fetches OHLCV (open/high/low/close/volume) bar history for a stock ticker "
                "over a specified date range. Use when the user asks about price movement, "
                "trend, range, or performance over a time period."
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
                    description="Start of date range (YYYY-MM-DD)",
                    required=True,
                ),
                ParameterSpec(
                    name="to_date",
                    type="date",
                    description="End of date range (YYYY-MM-DD)",
                    required=True,
                ),
                ParameterSpec(
                    name="interval",
                    type="string",
                    description="Bar granularity: day/week/month. Default 'week'.",
                    required=False,
                    enum=["day", "week", "month"],
                ),
            ],
            source_type="ohlcv",
            example_queries=[
                "How has AAPL performed over the last 3 months?",
                "What was NVDA's price range in Q1 2026?",
            ],
        ),
        handler=lambda **_: None,  # dispatch happens inside ToolExecutor.execute()
    )

    registry.register(
        ToolSpec(
            name="get_fundamentals_history",
            description=(
                "Fetches quarterly fundamental metrics (revenue, gross profit, net income, "
                "EPS, P/E ratio, market cap) for a ticker over N periods. Use when the user "
                "asks about revenue trends, EPS growth, or multi-quarter financial performance."
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
                    description="Number of quarters to return (1-20). Default 8.",
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
                "call transcripts, and analyst reports. Use for factual questions, news, company "
                "announcements, and any question requiring text evidence. This is the primary "
                "retrieval tool for unstructured information."
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
                "neighbours, relationships, and confidence scores. Use for questions about ONE entity "
                "like 'who are X's partners', 'what are X's subsidiaries', 'who does X compete with'. "
                "For questions about the relationship BETWEEN two entities (e.g. 'how is X connected to Y', "
                "'what is the relation between X and Y'), use traverse_graph instead — it is designed "
                "for cross-entity path finding and is more reliable for two-entity queries. "
                "If this tool returns empty or sparse results for a well-known entity, you may supplement "
                "with training knowledge but MUST label it 'Based on public knowledge: …' — never invent "
                "confidence scores or graph metadata."
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
                "Finds paths between two entities in the knowledge graph via multi-hop traversal. "
                "USE THIS TOOL when asked 'what is the relation between X and Y', 'how is X connected "
                "to Y', 'is X related to Y', or any question involving TWO named entities. "
                "Provide start_entity AND target_entity (e.g. start_entity='Apple', target_entity='Anthropic'). "
                "Also useful for indirect chains (shared investors, board-member chains, 3+ hops). "
                "Returns direct and indirect paths with relation types and confidence scores."
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
                "Use for listing what is known about an entity's relationships in structured form."
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
                "Searches for analyst claims and extracted assertions about an entity. Claims are "
                'LLM-extracted structured statements from financial documents (e.g., "AAPL will '
                'expand into India"). Use for opinion-type questions, target price questions, or '
                "when you need to contrast what analysts are saying."
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
                "M&A activity, leadership changes, product launches, regulatory filings. Use for "
                "timeline or event-based questions."
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
                        "UUID of the entity to retrieve the narrative for. "
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
                "Retrieves top-N pre-computed multi-hop relationship paths anchored on an entity, "
                "ranked by composite_score. Use when the user asks about indirect connections, "
                "how entities are linked through intermediaries, or wants to explore the entity's "
                "broader network relationships."
            ),
            parameters=[
                ParameterSpec(
                    name="entity_id",
                    type="string",
                    description=(
                        "UUID of the entity to retrieve paths for. Auto-injected from entity scope when available."
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
                        "UUID of the entity to retrieve health data for. "
                        "Auto-injected from entity scope when available."
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
                "Retrieves the full intelligence bundle for an entity — combining narrative, "
                "relationship paths, health score, and relations summary in a single call. "
                'Use when the user asks for a comprehensive overview or says "tell me everything '
                'about X". Prefer this over calling individual intelligence tools separately.'
            ),
            parameters=[
                ParameterSpec(
                    name="entity_id",
                    type="string",
                    description=(
                        "UUID of the entity to retrieve intelligence for. "
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
                "Side-by-side comparison of 2-4 financial entities: fundamentals highlights "
                "(market cap, P/E, revenue, EPS) and latest price quote. Use when the user "
                "asks to compare multiple stocks or companies against each other."
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
            ],
            source_type="fundamentals",
            example_queries=[
                "Screen for tech stocks with P/E under 20 and market cap over $10B",
                "Find large-cap US healthcare companies",
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
                "Returns earnings release dates for companies including EPS estimates and "
                "actuals. Use when the user asks about upcoming earnings, earnings season, or "
                "when a specific company reports."
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

    registry.register(
        ToolSpec(
            name="create_alert",
            description=(
                "Creates a user-initiated alert rule for a specific entity and condition. "
                'Use when the user explicitly asks to set, create, or add an alert (e.g. "alert '
                'me when AAPL drops below $200" or "set a price alert for NVDA"). IMPORTANT: '
                "this tool requires explicit user confirmation before execution "
                "(requires_confirmation: true). Do NOT call this tool unless the user has "
                "clearly and unambiguously asked to create an alert — never create alerts "
                "speculatively or as a follow-up to an unrelated question."
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
