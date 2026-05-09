/**
 * lib/query/keys.ts — Hierarchical TanStack Query key factory
 *
 * WHY THIS EXISTS: Before this module, ~153 components inlined query keys as
 * `queryKey: ["watchlists"]` or `queryKey: ["holdings", portfolioId]`. Two
 * components could pick different strings for the same logical query
 * ("morningBrief" vs "morning-brief"), defeating cache sharing. Worse, a
 * cache invalidation in one feature couldn't easily cascade to dependent
 * queries because nothing tied them together structurally.
 *
 * This factory:
 *  1. Centralises every query key the app uses.
 *  2. Encodes domain hierarchy so `invalidateQueries({ queryKey: qk.portfolios.detail(id) })`
 *     cascades to all child queries (holdings/transactions/value-history/...).
 *  3. Returns `as const` tuples so TypeScript infers literal types — this is
 *     what makes the keys structurally comparable for invalidation matching.
 *  4. Keeps every key string defined exactly once. New domains add one entry
 *     here, not 20 inlined string literals across the codebase.
 *
 * CASCADE BEHAVIOUR (TanStack Query partial-match):
 *   qc.invalidateQueries({ queryKey: qk.portfolios.detail(p) })
 *     → invalidates qk.portfolios.holdings(p), qk.portfolios.transactions(p), …
 *   qc.invalidateQueries({ queryKey: qk.portfolios.all })
 *     → invalidates EVERY portfolio-scoped query
 *
 * MIGRATION: 153 inline call sites are migrated incrementally. The ESLint rule
 * `no-inline-querykey` blocks NEW inline keys; existing sites are converted as
 * touched. See PLAN-0059-C C-2.
 *
 * USAGE:
 *   import { qk } from "@/lib/query/keys";
 *   useQuery({ queryKey: qk.portfolios.list(), queryFn: ... });
 *   useQuery({ queryKey: qk.instrument.ohlcv(id, "1D"), queryFn: ... });
 */

// ── Convention: every domain has `.all` for "invalidate everything in this
//    domain", and where applicable a `.list()` and `.detail(id)` pair so
//    detail-scoped sub-resources can nest under the detail key.

export const qk = {
  // ── Portfolio domain ─────────────────────────────────────────────────────
  portfolios: {
    all: ["portfolios"] as const,
    list: () => ["portfolios", "list"] as const,
    detail: (portfolioId: string) =>
      ["portfolios", "detail", portfolioId] as const,
    holdings: (portfolioId: string) =>
      ["portfolios", "detail", portfolioId, "holdings"] as const,
    holdingsQuotes: (portfolioId: string) =>
      ["portfolios", "detail", portfolioId, "holdings-quotes"] as const,
    transactions: (
      portfolioId: string,
      filters?: Readonly<Record<string, unknown>>,
    ) =>
      filters
        ? (["portfolios", "detail", portfolioId, "transactions", filters] as const)
        : (["portfolios", "detail", portfolioId, "transactions"] as const),
    valueHistory: (portfolioId: string, period: string) =>
      ["portfolios", "detail", portfolioId, "value-history", period] as const,
    exposure: (portfolioId: string) =>
      ["portfolios", "detail", portfolioId, "exposure"] as const,
    riskMetrics: (portfolioId: string) =>
      ["portfolios", "detail", portfolioId, "risk-metrics"] as const,
    realizedPnL: (portfolioId: string, period: string) =>
      ["portfolios", "detail", portfolioId, "realized-pnl", period] as const,
    summary: (portfolioId: string) =>
      ["portfolios", "detail", portfolioId, "summary"] as const,
    // WHY bundle key: the portfolio page bundle endpoint (PLAN-0070 C-1) fetches
    // all sub-resources in one round-trip. This key is ONLY for the bundle fetch —
    // the dedicated hooks (holdingsByPortfolio, transactionsByPortfolio, etc.)
    // continue using their own keys for targeted invalidation after mutations.
    // Invalidating qk.portfolios.bundle(id) triggers a full-page refetch; use it
    // after mutations that affect multiple portfolio sub-resources at once.
    bundle: (portfolioId: string) =>
      ["portfolios", "bundle", portfolioId] as const,
    // ── Flat legacy-shape keys for usePortfolioData queries ─────────────
    // WHY different shape from holdings()/transactions() above: those keys nest
    // under ["portfolios","detail",id,...] for cascade-invalidation. The queries
    // in usePortfolioData.ts historically used the flat shapes below so we
    // preserve them here rather than silently changing the cache identity (which
    // would cause stale data until the old cache entry expires).
    holdingsByPortfolio: (portfolioId: string) =>
      ["holdings", portfolioId] as const,
    // F-045: root prefix key used for prefix-invalidation of all holdings-quotes
    // cache entries regardless of which instrument IDs were in the batch.
    holdingsQuotesAll: ["holdings-quotes"] as const,
    holdingsQuotesByIds: (ids: readonly string[]) =>
      ["holdings-quotes", [...ids].sort()] as const,
    transactionsByPortfolio: (portfolioId: string) =>
      ["transactions", portfolioId] as const,
    performance: (portfolioId: string, period: string) =>
      ["portfolio-performance", portfolioId, period] as const,
    holdingOverviews: (ids: readonly string[]) =>
      ["holdings-overviews", [...ids].sort()] as const,
    watchlistQuotes: (ids: readonly string[]) =>
      ["watchlist-quotes", [...ids].sort()] as const,
  },

  // ── Watchlists ───────────────────────────────────────────────────────────
  watchlists: {
    all: ["watchlists"] as const,
    list: () => ["watchlists", "list"] as const,
    sidebar: () => ["watchlists", "sidebar"] as const,
    detail: (watchlistId: string) =>
      ["watchlists", "detail", watchlistId] as const,
    members: (watchlistId: string) =>
      ["watchlists", "detail", watchlistId, "members"] as const,
    insights: (watchlistId: string) =>
      ["watchlists", "detail", watchlistId, "insights"] as const,
    quotes: (instrumentIds: readonly string[]) =>
      ["watchlists", "quotes", [...instrumentIds].sort()] as const,
  },

  // ── Brokerage ────────────────────────────────────────────────────────────
  brokerage: {
    all: ["brokerage"] as const,
    connections: () => ["brokerage", "connections"] as const,
    syncErrors: () => ["brokerage", "sync-errors"] as const,
  },

  // ── Instruments / market data ────────────────────────────────────────────
  instruments: {
    all: ["instruments"] as const,
    detail: (instrumentId: string) =>
      ["instruments", "detail", instrumentId] as const,
    overview: (instrumentId: string) =>
      ["instruments", "detail", instrumentId, "overview"] as const,
    brief: (instrumentId: string) =>
      ["instruments", "detail", instrumentId, "brief"] as const,
    ohlcv: (instrumentId: string, timeframe: string) =>
      ["instruments", "detail", instrumentId, "ohlcv", timeframe] as const,
    fundamentals: (instrumentId: string) =>
      ["instruments", "detail", instrumentId, "fundamentals"] as const,
    fundamentalsSnapshot: (instrumentId: string) =>
      ["instruments", "detail", instrumentId, "fundamentals-snapshot"] as const,
    fundamentalsTimeseries: (instrumentId: string, period: string) =>
      ["instruments", "detail", instrumentId, "fundamentals-ts", period] as const,
    technicals: (instrumentId: string) =>
      ["instruments", "detail", instrumentId, "technicals"] as const,
    entityGraph: (instrumentId: string, depth?: number) =>
      depth == null
        ? (["instruments", "detail", instrumentId, "entity-graph"] as const)
        : (["instruments", "detail", instrumentId, "entity-graph", depth] as const),
    contradictions: (instrumentId: string) =>
      ["instruments", "detail", instrumentId, "contradictions"] as const,
    ownership: (instrumentId: string) =>
      ["instruments", "detail", instrumentId, "ownership"] as const,
    // WHY pageBundle: the instrument detail page pre-fetches a bundle of all
    // sub-resources in one round-trip and seeds child-component caches. This
    // key is ONLY for the bundle fetch — child components continue using their
    // own keys (fundamentals, overview, etc.) so their invalidation semantics
    // stay correct.
    pageBundle: (entityId: string) =>
      ["instrument-page-bundle", entityId] as const,
    // WHY browse: the /instruments list page runs the screener with a simple
    // name_ticker filter. Keeping it under instruments.* lets
    // `qc.invalidateQueries({ queryKey: qk.instruments.all })` cascade.
    browse: (query: string) => ["instruments-browse", query] as const,
  },

  // ── Quotes (live prices) ─────────────────────────────────────────────────
  quotes: {
    all: ["quotes"] as const,
    single: (instrumentId: string) => ["quotes", "single", instrumentId] as const,
    batch: (instrumentIds: readonly string[]) =>
      ["quotes", "batch", [...instrumentIds].sort()] as const,
    batchOhlcv: (instrumentIds: readonly string[], timeframe: string) =>
      ["quotes", "batch-ohlcv", [...instrumentIds].sort(), timeframe] as const,
  },

  // ── News ─────────────────────────────────────────────────────────────────
  news: {
    all: ["news"] as const,
    top: (params?: Readonly<Record<string, unknown>>) =>
      params ? (["news", "top", params] as const) : (["news", "top"] as const),
    forEntity: (
      entityId: string,
      params?: Readonly<Record<string, unknown>>,
    ) =>
      params
        ? (["news", "entity", entityId, params] as const)
        : (["news", "entity", entityId] as const),
    // WHY separate key: relevance-ranked news (S6-scored) is a distinct
    // endpoint from the simple top-news list. Keeping it separate prevents
    // cache collisions with qk.news.top().
    relevant: () => ["news-relevant"] as const,
    // WHY topToday: the alerts/page.tsx TopTodayTab uses a flat key
    // ["news-top-today", { hours, limit }] for its paginated news query.
    // We preserve that exact shape so cache entries survive the migration.
    topToday: (params: Readonly<Record<string, unknown>>) =>
      ["news-top-today", params] as const,
  },

  // ── Screener ─────────────────────────────────────────────────────────────
  screener: {
    all: ["screener"] as const,
    fields: () => ["screener", "fields"] as const,
    query: (request: Readonly<Record<string, unknown>>) =>
      ["screener", "query", request] as const,
    // WHY filter+offset variant: the screener page uses a flat 3-element key
    // ["screener", filterSerialized, offset] for its paginated query so that
    // each page offset gets its own cache entry. We preserve that shape here
    // (rather than nesting under query()) so the cache identity doesn't change.
    page: (filterSerialized: string, offset: number) =>
      ["screener", filterSerialized, offset] as const,
    saved: () => ["screener", "saved-screens"] as const,
    sparklines: (instrumentIds: readonly string[]) =>
      ["screener", "sparklines", [...instrumentIds].sort()] as const,
  },

  // ── Alerts ───────────────────────────────────────────────────────────────
  alerts: {
    all: ["alerts"] as const,
    list: (params?: Readonly<Record<string, unknown>>) =>
      params ? (["alerts", "list", params] as const) : (["alerts", "list"] as const),
    history: (params?: Readonly<Record<string, unknown>>) =>
      params
        ? (["alerts", "history", params] as const)
        : (["alerts", "history"] as const),
    rules: () => ["alerts", "rules"] as const,
    // WHY pendingCount: layout.tsx polls a lightweight pending-count query every
    // 60s independently of the AlarmsPanel's full alert list. A dedicated key
    // avoids cache collisions with qk.alerts.list() which carries filters.
    pendingCount: () => ["layout-pending-alert-count"] as const,
  },

  // ── Chat / RAG threads ───────────────────────────────────────────────────
  chat: {
    all: ["chat"] as const,
    threads: () => ["chat", "threads"] as const,
    thread: (threadId: string) => ["chat", "threads", threadId] as const,
    // WHY entityResolve: the chat page resolves UUID entity_id URL params to
    // tickers via the company-overview endpoint. Keeping this under chat.* lets
    // `qc.invalidateQueries({ queryKey: qk.chat.all })` cascade to it on logout.
    entityResolve: (entityId: string) =>
      ["chat", "entity-resolve", entityId] as const,
  },

  // ── Dashboard widgets ────────────────────────────────────────────────────
  dashboard: {
    all: ["dashboard"] as const,
    morningBrief: () => ["dashboard", "morning-brief"] as const,
    topMovers: (params?: Readonly<Record<string, unknown>>) =>
      params
        ? (["dashboard", "top-movers", params] as const)
        : (["dashboard", "top-movers"] as const),
    predictionMarkets: (params?: Readonly<Record<string, unknown>>) =>
      params
        ? (["dashboard", "prediction-markets", params] as const)
        : (["dashboard", "prediction-markets"] as const),
    economicCalendar: (params?: Readonly<Record<string, unknown>>) =>
      params
        ? (["dashboard", "economic-calendar", params] as const)
        : (["dashboard", "economic-calendar"] as const),
    marketHeatmap: () => ["dashboard", "market-heatmap"] as const,
    aiSignals: () => ["dashboard", "ai-signals"] as const,
    // PLAN-0070 C-2: single-fetch key for the dashboard snapshot bundle.
    // WHY no params: the snapshot always fetches the same 6 legs with fixed
    // limits (news:8, markets:5, earnings:7d, alerts:10). No pagination or
    // filter variation — a single stable key covers all callers.
    snapshot: () => ["dashboard", "snapshot"] as const,
  },

  // ── Workspace widgets ────────────────────────────────────────────────────
  workspace: {
    all: ["workspace"] as const,
    chartOhlcv: (instrumentId: string, timeframe: string) =>
      ["workspace", "chart-ohlcv", instrumentId, timeframe] as const,
    fundamentals: (instrumentId: string) =>
      ["workspace", "fundamentals", instrumentId] as const,
    fundamentalsSnapshot: (instrumentId: string) =>
      ["workspace", "fundamentals-snapshot", instrumentId] as const,
    topNews: () => ["workspace", "top-news"] as const,
    screenerTop: () => ["workspace", "screener-top"] as const,
  },

  // ── Search ───────────────────────────────────────────────────────────────
  search: {
    all: ["search"] as const,
    query: (q: string, scope?: string) =>
      scope == null
        ? (["search", "query", q] as const)
        : (["search", "query", q, scope] as const),
    // WHY documents key: full-text document search (PLAN-0064 W6) needs a key
    // that is unique per query+filters+page combination so TanStack Query does
    // not serve stale results when the user changes any parameter. Including all
    // four dimensions in the key tuple enables:
    //  1. Cache sharing when the user re-types the same query with identical filters
    //  2. Independent invalidation per parameter change (no over-broad invalidation)
    //  3. Cascade invalidation via qk.search.all for logout / token refresh
    documents: (
      q: string,
      sourceType: string,
      facets: string[],
      page: number,
    ) =>
      // Sort facets for stable cache identity — [a, b] and [b, a] are the same filter.
      ["search", "documents", q, sourceType, [...facets].sort(), page] as const,
  },

  // ── Feedback / admin ─────────────────────────────────────────────────────
  feedback: {
    all: ["feedback"] as const,
    submissions: (filters?: Readonly<Record<string, unknown>>) =>
      filters
        ? (["feedback", "submissions", filters] as const)
        : (["feedback", "submissions"] as const),
    featureRequests: () => ["feedback", "feature-requests"] as const,
    // PLAN-0052 Wave E T-E-5-07. One row per user; no filters. Lives under
    // the feedback.* cascade so an admin-side mutation that bumps unrelated
    // feedback rows doesn't refetch enrollment, but invalidating
    // `qk.feedback.all` will still clear it (intentional — feedback-wide
    // refetch on admin actions).
    betaEnrollment: () => ["feedback", "beta-enrollment"] as const,
    // PLAN-0053 Wave G — admin NPS aggregate strip. Same shape as the
    // existing inline ["nps-aggregate", days] keys; centralising lets us
    // drop the bare top-level key once admin/feedback/page.tsx switches.
    npsAggregate: (days: number) =>
      ["feedback", "nps-aggregate", days] as const,
  },

  // ── Briefing (PLAN-0066 Wave F) ─────────────────────────────────────────
  // WHY a separate top-level domain: briefing queries (diff, history) are
  // independent of the dashboard.morningBrief key which is keyed to the
  // gateway.getMorningBrief() call. Having a dedicated briefing.* namespace
  // lets us invalidate diff/history caches separately after feedback mutations.
  briefing: {
    all: ["briefing"] as const,
    diff: (briefId?: string) =>
      briefId
        ? (["briefing", "diff", briefId] as const)
        : (["briefing", "diff"] as const),
    history: (params?: Readonly<Record<string, unknown>>) =>
      params
        ? (["briefing", "history", params] as const)
        : (["briefing", "history"] as const),
  },

  // ── User ─────────────────────────────────────────────────────────────────
  user: {
    all: ["user"] as const,
    profile: () => ["user", "profile"] as const,
    notificationPrefs: () => ["user", "notification-prefs"] as const,
  },
} as const;

/**
 * QueryKey — discriminated union of every key shape this app uses.
 *
 * Components that need a typed handle to a key (e.g., for `setQueryData`)
 * can write `qk.portfolios.detail(id)` and TS will infer the literal tuple.
 */
export type QueryKey = ReturnType<
  | typeof qk.portfolios.list
  | typeof qk.portfolios.detail
  | typeof qk.watchlists.list
  | typeof qk.instruments.detail
>;
