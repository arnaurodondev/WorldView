/**
 * lib/copy/empty-states.ts — centralised empty-state copy dictionary
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 + FU-10.10 — every empty-state across
 * the app reads from the same dictionary so we have one place to audit
 * tone, length, and finance-terminology accuracy.  Each entry maps a
 * stable key (e.g. "portfolio.no-holdings") to a {title, body, cta?}
 * triple so EmptyState can render any condition uniformly.
 *
 * Five canonical conditions (FU-10.11):
 *   - loading
 *   - empty-cold-start (user has account but no data yet)
 *   - empty-no-data (data source returned empty)
 *   - error
 *   - permission (user lacks access)
 *   - coming-soon (feature flagged off)
 *
 * Page agents extend this dictionary as new keys are needed.  The
 * empty-copy-dictionary arch test (plan §4) guarantees every
 * <EmptyState copyKey="X"> reference resolves to a key here.
 */

export interface EmptyCopy {
  readonly title: string;
  readonly body: string;
  readonly ctaLabel?: string;
}

export const EMPTY_COPY: Record<string, EmptyCopy> = {
  // Generic fallbacks — used when a page hasn't defined its own key yet.
  "generic.loading": {
    title: "Loading…",
    body: "Fetching the latest data from the platform.",
  },
  "generic.empty-cold-start": {
    title: "Nothing here yet",
    body: "Once data starts flowing through the platform you'll see it here.",
  },
  "generic.empty-no-data": {
    title: "No data",
    body: "This source returned an empty result for the current query.",
  },
  "generic.error": {
    title: "Couldn't load",
    body: "The platform returned an error. Retry, or check the status page.",
    ctaLabel: "Retry",
  },
  "generic.permission": {
    title: "Access required",
    body: "You don't have permission to view this resource.",
  },
  "generic.coming-soon": {
    title: "Coming soon",
    body: "This view is queued for a later wave of the roadmap.",
  },

  // Portfolio surface keys — extended by per-page agents.
  "portfolio.no-holdings": {
    title: "No holdings yet",
    body: "Connect a brokerage or enter a manual lot to populate this view.",
    ctaLabel: "Connect brokerage",
  },
  "portfolio.no-transactions": {
    title: "No transactions",
    body: "Transactions appear here after the first brokerage sync.",
  },

  // Portfolio Round-3 polish keys (EmptyState migration, DS §15.12).
  // WHY new keys instead of editing the two above: the existing keys are
  // pinned verbatim by components/primitives/__tests__/EmptyState.test.tsx,
  // while the portfolio call sites have THEIR copy pinned by older tests
  // (e.g. /No transactions yet\./ in portfolio-wave-f-polish). Distinct keys
  // let both sets of pinned strings coexist without weakening any test (R19).
  "portfolio.no-portfolio": {
    // Title matches the heading pinned by empty-portfolio.test.tsx exactly.
    title: "Select or create a portfolio",
    body:
      "Your portfolio is the P&L centre of Worldview — holdings, live quotes, " +
      "transactions and analytics all hang off it. Create your first portfolio " +
      "to start tracking positions.",
  },
  "portfolio.no-holdings-table": {
    // Trailing period intentional — older tests pin /No holdings yet\./.
    title: "No holdings yet.",
    body: "Connect a brokerage or use Add Position to start tracking your book.",
  },
  "portfolio.no-transactions-yet": {
    // Trailing period intentional — older tests pin /No transactions yet\./.
    title: "No transactions yet.",
    body: "Connect a brokerage to import activity, or use Add Position to record a trade manually.",
  },
  "portfolio.no-watchlists": {
    title: "No watchlists yet.",
    body: "Group tickers by thesis — earnings plays, long ideas, shorts — and track live quotes per list.",
  },
  "portfolio.watchlist-no-tickers": {
    title: "No tickers in this watchlist.",
    body: "Search above to add your first symbol — live quotes refresh every 30 seconds.",
  },
  "portfolio.analytics-insufficient": {
    title: "Not enough history",
    body: "Analytics need at least two daily snapshots — check back after the next market close.",
  },
  // Portfolio Round-4 hardening: page-level load failure (the deferred R3
  // item). WHY the title is exactly "Failed to load portfolio data": the e2e
  // suite (qa-exhaustive.spec.ts "Portfolio shows error state with retry
  // option") pins that text via page.locator — keeping it verbatim means the
  // R4 migration from InlineEmptyState to the named EmptyState + Retry action
  // changes structure without breaking the pinned copy (R19).
  "portfolio.load-error": {
    title: "Failed to load portfolio data",
    body: "The portfolio list could not be fetched. Check your connection, then retry.",
    ctaLabel: "Retry",
  },

  // Screener surface keys.
  "screener.no-matches": {
    title: "No matches",
    body: "Try widening the criteria or removing a filter.",
  },
  // Round-3 screener empty-state migration (item 5): the page distinguishes
  // THREE zero-row situations that used to share one DashboardEmptyState:
  //   cold-start          — default filters AND the server universe is empty
  //                         (nothing ingested yet; resetting filters is useless)
  //   no-filter-matches   — the SERVER returned zero rows for active filters
  //   no-loaded-matches   — the server returned rows but the CLIENT-side
  //                         technical/search filters excluded every loaded one
  // WHY both *-matches titles are identical: __tests__/screener.test.tsx pins
  // the user-facing headline "No results match your filters" for any
  // filtered-to-zero outcome; the BODY carries the actionable difference.
  // ("screener.no-matches" above stays untouched — its copy is pinned by
  // components/primitives/__tests__/EmptyState.test.tsx.)
  "screener.cold-start": {
    title: "No instruments yet",
    body: "The instrument universe is empty — instruments appear after the first market-data ingestion run.",
  },
  "screener.no-filter-matches": {
    title: "No results match your filters",
    body: "No instruments match the current filters. Adjust filters and apply.",
  },
  "screener.no-loaded-matches": {
    title: "No results match your filters",
    body: "The technical / search filters excluded all rows in the loaded page. Try widening them or loading more.",
  },

  // Watchlist surface keys.
  "watchlist.empty": {
    title: "Empty watchlist",
    body: "Add tickers from any instrument page to track them here.",
    ctaLabel: "Browse instruments",
  },

  // News / intelligence keys.
  "news.no-articles": {
    title: "No articles",
    body: "The pipeline hasn't surfaced any articles matching this query.",
  },
  "intelligence.no-brief": {
    title: "Brief unavailable",
    body: "Re-run the brief generator from the action menu.",
    ctaLabel: "Regenerate",
  },

  // Instrument surface keys — Round-2 reservation (cross-surface request,
  // item 4). Copy mirrors the headline/hint strings currently hardcoded in
  // components/instrument/shared/EmptyState.tsx call sites (NewsColumn,
  // GraphColumn, ContextPanel, ContradictionsBlock) so the Round-3
  // consolidation onto components/primitives/EmptyState.tsx is a pure
  // mechanical swap with zero copy changes. Dynamic fragments (the depth
  // number in the graph-timeout headline) are generalised — registry copy
  // must be static; surfaces needing interpolation keep a local string.
  "instrument.no-articles": {
    title: "No articles for this entity",
    body: "Articles appear here as the ingestion pipeline links coverage to this entity.",
  },
  "instrument.no-contradictions": {
    title: "No contradictions detected",
    body: "Conflicting claims between sources surface here when the KG pipeline flags them.",
  },
  "instrument.graph-timeout": {
    title: "Graph query timed out",
    body: "Deeper traversals are expensive. Try depth 1 or 2.",
    ctaLabel: "Reduce depth",
  },
  "instrument.graph-no-filter-matches": {
    title: "No entities match the type filter",
    body: "Clear or widen the entity-type filter in the toolbar above.",
  },
  "instrument.no-connections": {
    title: "No connections found",
    body: "The knowledge graph builds connections as news articles are ingested — check back later.",
  },
  "instrument.no-entity-context": {
    title: "No entity context",
    body: "This entity has not been enriched yet — the overnight enrichment worker populates name, type and description.",
  },
  // Round-3 additions (instrument surface agent): two call sites of the
  // retired components/instrument/shared/EmptyState.tsx fell OUTSIDE the six
  // Round-2 reserved keys (the reservation list mirrored the four
  // NewsColumn/GraphColumn/ContextPanel/ContradictionsBlock sites; these two
  // were Round-2 additions that also adopted the local component). Copy is
  // lifted verbatim from the previously hardcoded headline/hint strings so
  // the consolidation stays a zero-copy-change swap.
  "instrument.no-narrative-history": {
    title: "No narrative history",
    body: "Versions appear after the KG narrative worker (or a manual Refresh) generates a new interpretation of this entity.",
  },
  "instrument.no-financial-statements": {
    title: "No financial statements",
    body: "Statement records have not been ingested for this instrument — ETFs and newly listed tickers have none until the fundamentals backfill runs.",
  },

  // Chat surface keys — Round-3 polish sprint. The welcome title "Analyst
  // Intelligence" is PINNED by __tests__/chat.test.tsx ("shows welcome state")
  // and the no-threads title by the "/no conversations yet/i" assertion — do
  // not reword without updating both tests.
  "chat.welcome": {
    title: "Analyst Intelligence",
    // Wave-2 copy tune (frontend-rework sprint): lead with WHAT the analyst
    // can ask, close with the trust signal — capability first, grounding
    // second. Body assertion updated in __tests__/chat.test.tsx.
    body: "Ask about any company, your portfolio, or market events — answers cite the platform's market intelligence.",
  },
  "chat.no-threads": {
    title: "No conversations yet",
    body: "Click “New chat” to begin your first research thread.",
  },
  // Wave-2 (frontend-rework sprint): context-rail cold state. Shown in the
  // right rail while the conversation has no messages yet — names what the
  // rail WILL do so the empty panel reads as "waiting", not "broken".
  "chat.rail-empty": {
    title: "Context appears as you chat",
    body: "Entity cards, cited sources, and the tools behind each answer collect here as the conversation develops.",
  },

  // Dashboard surface keys — Round-3 polish sprint (2026-06-10).
  // WHY these exist: the Round-3 dashboard pass migrates every widget's
  // bespoke empty-state JSX onto the shared <EmptyState> primitive (§15.12),
  // which resolves copy through this registry. Titles intentionally mirror
  // the strings the pre-migration widgets rendered, because several are
  // pinned by existing tests (R19: never weaken tests — e.g.
  // "No upcoming earnings events scheduled." in earnings-calendar-widget,
  // "No watchlist yet" in WatchlistMoversWidget.insights, "AI brief
  // unavailable" in morning-brief-card, "No movers" greps in
  // e2e/qa-live-stack). Keys are namespaced `dashboard.*` and appended
  // additively — this file is the documented extension point for per-page
  // agents (see header) and the empty-copy-dictionary arch test requires
  // every literal copyKey to resolve here.
  "dashboard.no-signals": {
    title: "No signals yet",
    body: "AI price-impact signals appear here as new articles are processed.",
  },
  "dashboard.signals-error": {
    title: "Signals unavailable",
    body: "The signals feed failed to load — check the connection.",
  },
  "dashboard.no-sector-data": {
    title: "No sector data available",
    body: "Sector performance appears once market data is ingested.",
  },
  "dashboard.sector-error": {
    title: "Sector data unavailable",
    body: "The heatmap failed to load — check the connection.",
  },
  "dashboard.no-portfolio": {
    title: "No portfolio yet",
    body: "Create a portfolio to track totals, P&L and top holdings here.",
  },
  "dashboard.no-positions": {
    title: "Track your top positions here",
    body: "Live prices, day P&L and 5-day trends for your largest positions.",
  },
  "dashboard.no-holdings-movers": {
    title: "No holdings",
    body: "Add holdings or sync a brokerage to see daily movers here.",
  },
  "dashboard.no-watchlist": {
    title: "No watchlist yet",
    body: "Add instruments to your watchlist to see daily movers here.",
  },
  "dashboard.no-movers": {
    title: "No movers",
    body: "No price movement recorded for this view in the selected period.",
  },
  "dashboard.no-markets": {
    title: "No open prediction markets",
    body: "Prediction markets appear here once Polymarket data is ingested.",
  },
  "dashboard.no-economic-events": {
    title: "No upcoming economic events scheduled.",
    body: "Economic events populate as market calendar data is ingested.",
  },
  "dashboard.no-earnings": {
    title: "No upcoming earnings events scheduled.",
    body: "Earnings calendar data populates as company reporting schedules are ingested.",
  },
  "dashboard.no-news": {
    title: "No recent news",
    body: "Ranked portfolio news appears here as the pipeline ingests articles.",
  },
  "dashboard.news-filter-no-match": {
    title: "No articles match these filters.",
    body: "Clear the tier or ticker filter to see all ranked articles.",
  },
  "dashboard.no-alerts": {
    title: "No recent alerts.",
    body: "Create alert rules on the Alerts page to receive notifications here.",
  },
  "dashboard.brief-unavailable": {
    title: "AI brief unavailable",
    body: "No morning brief has been generated yet.",
  },

  // Round-4 hardening (2026-06-10): NAMED error states for the widgets that
  // previously rendered bespoke error text (or worse, fell through to a
  // misleading empty state on fetch failure — e.g. PortfolioSummary showed
  // "No portfolio yet" when /v1/portfolios 500'd). Each error key pairs with
  // a Retry action wired to the failing query's refetch() via
  // components/dashboard/WidgetErrorState. Copy follows the established
  // "<thing> unavailable" + "failed to load — check the connection" voice
  // set by dashboard.signals-error / dashboard.sector-error above.
  "dashboard.snapshot-error": {
    title: "Snapshot unavailable",
    body: "The market snapshot failed to load — check the connection.",
  },
  "dashboard.portfolio-error": {
    title: "Portfolio unavailable",
    body: "Portfolio data failed to load — check the connection.",
  },
  "dashboard.movers-error": {
    title: "Movers unavailable",
    body: "The market movers feed failed to load — check the connection.",
  },
  "dashboard.economic-error": {
    title: "Economic calendar unavailable",
    body: "Macro events failed to load — check the connection.",
  },
  "dashboard.alerts-error": {
    title: "Alerts unavailable",
    body: "The alert feed failed to load — check the connection.",
  },
};

export type EmptyCopyKey = keyof typeof EMPTY_COPY;
