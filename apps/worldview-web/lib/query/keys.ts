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
  },

  // ── Screener ─────────────────────────────────────────────────────────────
  screener: {
    all: ["screener"] as const,
    fields: () => ["screener", "fields"] as const,
    query: (request: Readonly<Record<string, unknown>>) =>
      ["screener", "query", request] as const,
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
  },

  // ── Chat / RAG threads ───────────────────────────────────────────────────
  chat: {
    all: ["chat"] as const,
    threads: () => ["chat", "threads"] as const,
    thread: (threadId: string) => ["chat", "threads", threadId] as const,
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
  },

  // ── Feedback / admin ─────────────────────────────────────────────────────
  feedback: {
    all: ["feedback"] as const,
    submissions: (filters?: Readonly<Record<string, unknown>>) =>
      filters
        ? (["feedback", "submissions", filters] as const)
        : (["feedback", "submissions"] as const),
    featureRequests: () => ["feedback", "feature-requests"] as const,
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
