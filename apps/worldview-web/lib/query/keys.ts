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

import type { PathFilters } from "@/types/intelligence";

// ── Cache-namespace version ──────────────────────────────────────────────────
//
// WHY THIS CONSTANT EXISTS (PRD-0089 F2 step 11 / §6.3):
// F2 unified the parallel `entity_id` / `instrument_id` UUID namespaces into a
// single canonical `instrument_id` for tradable securities. Persisted TanStack
// caches (TanStack Query + browser persister) MAY carry entries keyed under the
// previous semantics — same string keys but the underlying UUIDs no longer mean
// the same thing. Prepending a version tag to every key creates a new cache
// namespace; old entries never collide with new ones.
//
// HOW TO USE:
//   - All `qk.*` factories below prepend `QK_VERSION` to their tuple.
//   - To force a global cache reset in a future migration, bump this constant
//     ("v2" → "v3"). No call sites need to change.
//   - Combined with `docker compose down -v` for dev (no_backfill), this is a
//     belt-and-suspenders safety net that keeps stale UUIDs from leaking
//     through partial cache rehydration.
export const QK_VERSION = "v2"; // post-F2 — UUID semantics changed (PRD-0089 F2)

// ── Convention: every domain has `.all` for "invalidate everything in this
//    domain", and where applicable a `.list()` and `.detail(id)` pair so
//    detail-scoped sub-resources can nest under the detail key.

export const qk = {
  // ── Portfolio domain ─────────────────────────────────────────────────────
  portfolios: {
    all: [QK_VERSION, "portfolios"] as const,
    list: () => [QK_VERSION, "portfolios", "list"] as const,
    detail: (portfolioId: string) =>
      [QK_VERSION, "portfolios", "detail", portfolioId] as const,
    holdings: (portfolioId: string) =>
      [QK_VERSION, "portfolios", "detail", portfolioId, "holdings"] as const,
    holdingsQuotes: (portfolioId: string) =>
      [QK_VERSION, "portfolios", "detail", portfolioId, "holdings-quotes"] as const,
    transactions: (
      portfolioId: string,
      filters?: Readonly<Record<string, unknown>>,
    ) =>
      filters
        ? ([QK_VERSION, "portfolios", "detail", portfolioId, "transactions", filters] as const)
        : ([QK_VERSION, "portfolios", "detail", portfolioId, "transactions"] as const),
    valueHistory: (portfolioId: string, period: string) =>
      [QK_VERSION, "portfolios", "detail", portfolioId, "value-history", period] as const,
    exposure: (portfolioId: string) =>
      [QK_VERSION, "portfolios", "detail", portfolioId, "exposure"] as const,
    riskMetrics: (portfolioId: string) =>
      [QK_VERSION, "portfolios", "detail", portfolioId, "risk-metrics"] as const,
    realizedPnL: (portfolioId: string, period: string) =>
      [QK_VERSION, "portfolios", "detail", portfolioId, "realized-pnl", period] as const,
    summary: (portfolioId: string) =>
      [QK_VERSION, "portfolios", "detail", portfolioId, "summary"] as const,
    // WHY bundle key: the portfolio page bundle endpoint (PLAN-0070 C-1) fetches
    // all sub-resources in one round-trip. This key is ONLY for the bundle fetch —
    // the dedicated hooks (holdingsByPortfolio, transactionsByPortfolio, etc.)
    // continue using their own keys for targeted invalidation after mutations.
    // Invalidating qk.portfolios.bundle(id) triggers a full-page refetch; use it
    // after mutations that affect multiple portfolio sub-resources at once.
    bundle: (portfolioId: string) =>
      [QK_VERSION, "portfolios", "bundle", portfolioId] as const,
    // ── Flat legacy-shape keys for usePortfolioData queries ─────────────
    // WHY different shape from holdings()/transactions() above: those keys nest
    // under [QK_VERSION,"portfolios","detail",id,...] for cascade-invalidation. The queries
    // in usePortfolioData.ts historically used the flat shapes below so we
    // preserve them here rather than silently changing the cache identity (which
    // would cause stale data until the old cache entry expires).
    holdingsByPortfolio: (portfolioId: string) =>
      [QK_VERSION, "holdings", portfolioId] as const,
    // F-045: root prefix key used for prefix-invalidation of all holdings-quotes
    // cache entries regardless of which instrument IDs were in the batch.
    holdingsQuotesAll: [QK_VERSION, "holdings-quotes"] as const,
    holdingsQuotesByIds: (ids: readonly string[]) =>
      [QK_VERSION, "holdings-quotes", [...ids].sort()] as const,
    transactionsByPortfolio: (portfolioId: string) =>
      [QK_VERSION, "transactions", portfolioId] as const,
    performance: (portfolioId: string, period: string) =>
      [QK_VERSION, "portfolio-performance", portfolioId, period] as const,
    holdingOverviews: (ids: readonly string[]) =>
      [QK_VERSION, "holdings-overviews", [...ids].sort()] as const,
    watchlistQuotes: (ids: readonly string[]) =>
      [QK_VERSION, "watchlist-quotes", [...ids].sort()] as const,
  },

  // ── Watchlists ───────────────────────────────────────────────────────────
  watchlists: {
    all: [QK_VERSION, "watchlists"] as const,
    list: () => [QK_VERSION, "watchlists", "list"] as const,
    sidebar: () => [QK_VERSION, "watchlists", "sidebar"] as const,
    detail: (watchlistId: string) =>
      [QK_VERSION, "watchlists", "detail", watchlistId] as const,
    members: (watchlistId: string) =>
      [QK_VERSION, "watchlists", "detail", watchlistId, "members"] as const,
    insights: (watchlistId: string) =>
      [QK_VERSION, "watchlists", "detail", watchlistId, "insights"] as const,
    quotes: (instrumentIds: readonly string[]) =>
      [QK_VERSION, "watchlists", "quotes", [...instrumentIds].sort()] as const,
  },

  // ── Brokerage ────────────────────────────────────────────────────────────
  brokerage: {
    all: [QK_VERSION, "brokerage"] as const,
    connections: () => [QK_VERSION, "brokerage", "connections"] as const,
    syncErrors: () => [QK_VERSION, "brokerage", "sync-errors"] as const,
  },

  // ── Instruments / market data ────────────────────────────────────────────
  instruments: {
    all: [QK_VERSION, "instruments"] as const,
    detail: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId] as const,
    overview: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "overview"] as const,
    brief: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "brief"] as const,
    ohlcv: (instrumentId: string, timeframe: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "ohlcv", timeframe] as const,
    // PRD-0089 W1 (§4.5 / §5): batched intraday OHLCV used by WatchlistPanel
    // sparklines and potentially IndexStrip. One round trip per ticker set keeps
    // sidebar render cost flat regardless of how many watchlist members the user
    // tracks. Tickers are sorted in the key so [A,B] and [B,A] share one cache
    // entry; `timeframe` and `limit` participate in the key so different bar
    // widths (5m vs 1d) do not collide.
    ohlcvBatch: (
      tickers: readonly string[],
      timeframe: string,
      limit: number,
    ) =>
      [
        QK_VERSION,
        "instruments",
        "ohlcv-batch",
        [...tickers].sort(),
        timeframe,
        limit,
      ] as const,
    fundamentals: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "fundamentals"] as const,
    fundamentalsSnapshot: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "fundamentals-snapshot"] as const,
    fundamentalsTimeseries: (instrumentId: string, period: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "fundamentals-ts", period] as const,
    technicals: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "technicals"] as const,
    entityGraph: (instrumentId: string, depth?: number) =>
      depth == null
        ? ([QK_VERSION, "instruments", "detail", instrumentId, "entity-graph"] as const)
        : ([QK_VERSION, "instruments", "detail", instrumentId, "entity-graph", depth] as const),
    contradictions: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "contradictions"] as const,
    ownership: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "ownership"] as const,
    // PLAN-0090 T-A-01: dedicated keys for new fundamentals sub-resources used by
    // the redesigned instrument detail page (Quote/Financials/Intelligence tabs).
    // Each nests under QK_VERSION,"instruments","detail",id,... so the standard
    // cascade via qk.instruments.detail(id) still invalidates them in one shot.
    shareStatistics: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "share-statistics"] as const,
    incomeStatement: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "income-statement"] as const,
    earningsHistory: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "earnings-history"] as const,
    // WHY splitsDividends key: FlatMetricsGrid renders EX-DIV DATE / DIV PAY DATE
    // from the splits_dividends section returned by S9 /v1/fundamentals/{id}/splits-dividends.
    // Audit 2026-05-19 — previously hard-coded to null in FinancialsTab.
    splitsDividends: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "splits-dividends"] as const,
    // WHY pageBundle: the instrument detail page pre-fetches a bundle of all
    // sub-resources in one round-trip and seeds child-component caches. This
    // key is ONLY for the bundle fetch — child components continue using their
    // own keys (fundamentals, overview, etc.) so their invalidation semantics
    // stay correct.
    pageBundle: (instrumentId: string) =>
      [QK_VERSION, "instrument-page-bundle", instrumentId] as const,
    // ── W3 Financials-tab sidebar keys ────────────────────────────────────
    // WHY separate from shareStatistics: institutional/fund holders are slow-
    // changing data (quarterly 13F filings) and are only needed on the Financials
    // tab sidebar — keeping them under their own keys prevents unnecessary
    // cache eviction when the main fundamentals invalidation fires on the Quote tab.
    institutionalHolders: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "institutional-holders"] as const,
    fundHolders: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "fund-holders"] as const,
    // ── W5 Quote-tab keys ──────────────────────────────────────────────────
    // WHY all 4 nest under ["instruments","detail",id,...]:
    // qc.invalidateQueries({ queryKey: qk.instruments.detail(id) }) cascades to
    // all 4 in one shot (Δ38 / Shift+R cascade). "intraday-stats" includes an
    // optional lastBarTs parameter so a new 5m bar invalidates only that stale
    // entry without evicting the daily-close peers / returns / levels caches.
    peers: (instrumentId: string, limit?: number) =>
      limit == null
        ? ([QK_VERSION, "instruments", "detail", instrumentId, "peers"] as const)
        : ([QK_VERSION, "instruments", "detail", instrumentId, "peers", limit] as const),
    intradayStats: (instrumentId: string, lastBarTs?: string) =>
      [
        QK_VERSION,
        "instruments",
        "detail",
        instrumentId,
        "intraday-stats",
        // WHY "live" sentinel: when lastBarTs is unknown we still want a stable
        // key so the first render doesn't thrash. "live" is replaced on the next
        // bar-close once the bar timestamp is available from the OHLCV response.
        lastBarTs ?? "live",
      ] as const,
    multiPeriodReturns: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "multi-period-returns"] as const,
    priceLevels: (instrumentId: string) =>
      [QK_VERSION, "instruments", "detail", instrumentId, "price-levels"] as const,
    // WHY browse: the /instruments list page runs the screener with a simple
    // name_ticker filter. Keeping it under instruments.* lets
    // `qc.invalidateQueries({ queryKey: qk.instruments.all })` cascade.
    browse: (query: string) => [QK_VERSION, "instruments-browse", query] as const,
  },

  // ── Quotes (live prices) ─────────────────────────────────────────────────
  quotes: {
    all: [QK_VERSION, "quotes"] as const,
    single: (instrumentId: string) => [QK_VERSION, "quotes", "single", instrumentId] as const,
    batch: (instrumentIds: readonly string[]) =>
      [QK_VERSION, "quotes", "batch", [...instrumentIds].sort()] as const,
    batchOhlcv: (instrumentIds: readonly string[], timeframe: string) =>
      [QK_VERSION, "quotes", "batch-ohlcv", [...instrumentIds].sort(), timeframe] as const,
  },

  // ── News ─────────────────────────────────────────────────────────────────
  news: {
    all: [QK_VERSION, "news"] as const,
    top: (params?: Readonly<Record<string, unknown>>) =>
      params ? ([QK_VERSION, "news", "top", params] as const) : ([QK_VERSION, "news", "top"] as const),
    forEntity: (
      entityId: string,
      params?: Readonly<Record<string, unknown>>,
    ) =>
      params
        ? ([QK_VERSION, "news", "entity", entityId, params] as const)
        : ([QK_VERSION, "news", "entity", entityId] as const),
    // WHY separate key: relevance-ranked news (S6-scored) is a distinct
    // endpoint from the simple top-news list. Keeping it separate prevents
    // cache collisions with qk.news.top().
    relevant: () => [QK_VERSION, "news-relevant"] as const,
    // WHY topToday: the alerts/page.tsx TopTodayTab uses a flat key
    // [QK_VERSION, "news-top-today", { hours, limit }] for its paginated news query.
    // We preserve that exact shape so cache entries survive the migration.
    topToday: (params: Readonly<Record<string, unknown>>) =>
      [QK_VERSION, "news-top-today", params] as const,
    // P2-F: cluster key for the ClusterArticlesModal. Scoped to the cluster_id
    // so different clusters cache independently but share the "news" root for
    // future invalidation via qk.news.all.
    cluster: (clusterId: string) => [QK_VERSION, "news", "cluster", clusterId] as const,
  },

  // ── Screener ─────────────────────────────────────────────────────────────
  screener: {
    all: [QK_VERSION, "screener"] as const,
    fields: () => [QK_VERSION, "screener", "fields"] as const,
    query: (request: Readonly<Record<string, unknown>>) =>
      [QK_VERSION, "screener", "query", request] as const,
    // WHY filter+offset variant: the screener page uses a flat 3-element shape
    // [QK_VERSION, "screener", filterSerialized, offset] for its paginated query so that
    // each page offset gets its own cache entry. We preserve that shape here
    // (rather than nesting under query()) so the cache identity doesn't change.
    page: (filterSerialized: string, offset: number) =>
      [QK_VERSION, "screener", filterSerialized, offset] as const,
    saved: () => [QK_VERSION, "screener", "saved-screens"] as const,
    sparklines: (instrumentIds: readonly string[]) =>
      [QK_VERSION, "screener", "sparklines", [...instrumentIds].sort()] as const,
  },

  // ── Alerts ───────────────────────────────────────────────────────────────
  alerts: {
    all: [QK_VERSION, "alerts"] as const,
    list: (params?: Readonly<Record<string, unknown>>) =>
      params ? ([QK_VERSION, "alerts", "list", params] as const) : ([QK_VERSION, "alerts", "list"] as const),
    history: (params?: Readonly<Record<string, unknown>>) =>
      params
        ? ([QK_VERSION, "alerts", "history", params] as const)
        : ([QK_VERSION, "alerts", "history"] as const),
    rules: () => [QK_VERSION, "alerts", "rules"] as const,
    // WHY pendingCount: layout.tsx polls a lightweight pending-count query every
    // 60s independently of the AlarmsPanel's full alert list. A dedicated key
    // avoids cache collisions with qk.alerts.list() which carries filters.
    pendingCount: () => [QK_VERSION, "layout-pending-alert-count"] as const,
  },

  // ── Chat / RAG threads ───────────────────────────────────────────────────
  chat: {
    all: [QK_VERSION, "chat"] as const,
    threads: () => [QK_VERSION, "chat", "threads"] as const,
    thread: (threadId: string) => [QK_VERSION, "chat", "threads", threadId] as const,
    // WHY entityResolve: the chat page resolves UUID entity_id URL params to
    // tickers via the company-overview endpoint. Keeping this under chat.* lets
    // `qc.invalidateQueries({ queryKey: qk.chat.all })` cascade to it on logout.
    entityResolve: (entityId: string) =>
      [QK_VERSION, "chat", "entity-resolve", entityId] as const,
  },

  // ── Dashboard widgets ────────────────────────────────────────────────────
  dashboard: {
    all: [QK_VERSION, "dashboard"] as const,
    morningBrief: () => [QK_VERSION, "dashboard", "morning-brief"] as const,
    topMovers: (params?: Readonly<Record<string, unknown>>) =>
      params
        ? ([QK_VERSION, "dashboard", "top-movers", params] as const)
        : ([QK_VERSION, "dashboard", "top-movers"] as const),
    predictionMarkets: (params?: Readonly<Record<string, unknown>>) =>
      params
        ? ([QK_VERSION, "dashboard", "prediction-markets", params] as const)
        : ([QK_VERSION, "dashboard", "prediction-markets"] as const),
    economicCalendar: (params?: Readonly<Record<string, unknown>>) =>
      params
        ? ([QK_VERSION, "dashboard", "economic-calendar", params] as const)
        : ([QK_VERSION, "dashboard", "economic-calendar"] as const),
    marketHeatmap: () => [QK_VERSION, "dashboard", "market-heatmap"] as const,
    aiSignals: () => [QK_VERSION, "dashboard", "ai-signals"] as const,
    // PLAN-0070 C-2: single-fetch key for the dashboard snapshot bundle.
    // WHY no params: the snapshot always fetches the same 6 legs with fixed
    // limits (news:8, markets:5, earnings:7d, alerts:10). No pagination or
    // filter variation — a single stable key covers all callers.
    snapshot: () => [QK_VERSION, "dashboard", "snapshot"] as const,
  },

  // ── Workspace widgets ────────────────────────────────────────────────────
  workspace: {
    all: [QK_VERSION, "workspace"] as const,
    chartOhlcv: (instrumentId: string, timeframe: string) =>
      [QK_VERSION, "workspace", "chart-ohlcv", instrumentId, timeframe] as const,
    fundamentals: (instrumentId: string) =>
      [QK_VERSION, "workspace", "fundamentals", instrumentId] as const,
    fundamentalsSnapshot: (instrumentId: string) =>
      [QK_VERSION, "workspace", "fundamentals-snapshot", instrumentId] as const,
    topNews: () => [QK_VERSION, "workspace", "top-news"] as const,
    screenerTop: () => [QK_VERSION, "workspace", "screener-top"] as const,
  },

  // ── Search ───────────────────────────────────────────────────────────────
  search: {
    all: [QK_VERSION, "search"] as const,
    query: (q: string, scope?: string) =>
      scope == null
        ? ([QK_VERSION, "search", "query", q] as const)
        : ([QK_VERSION, "search", "query", q, scope] as const),
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
      [QK_VERSION, "search", "documents", q, sourceType, [...facets].sort(), page] as const,
  },

  // ── Feedback / admin ─────────────────────────────────────────────────────
  feedback: {
    all: [QK_VERSION, "feedback"] as const,
    submissions: (filters?: Readonly<Record<string, unknown>>) =>
      filters
        ? ([QK_VERSION, "feedback", "submissions", filters] as const)
        : ([QK_VERSION, "feedback", "submissions"] as const),
    featureRequests: () => [QK_VERSION, "feedback", "feature-requests"] as const,
    // PLAN-0052 Wave E T-E-5-07. One row per user; no filters. Lives under
    // the feedback.* cascade so an admin-side mutation that bumps unrelated
    // feedback rows doesn't refetch enrollment, but invalidating
    // `qk.feedback.all` will still clear it (intentional — feedback-wide
    // refetch on admin actions).
    betaEnrollment: () => [QK_VERSION, "feedback", "beta-enrollment"] as const,
    // PLAN-0053 Wave G — admin NPS aggregate strip. Same shape as the
    // existing inline ["nps-aggregate", days] keys; centralising lets us
    // drop the bare top-level key once admin/feedback/page.tsx switches.
    npsAggregate: (days: number) =>
      [QK_VERSION, "feedback", "nps-aggregate", days] as const,
  },

  // ── Briefing (PLAN-0066 Wave F) ─────────────────────────────────────────
  // WHY a separate top-level domain: briefing queries (diff, history) are
  // independent of the dashboard.morningBrief key which is keyed to the
  // gateway.getMorningBrief() call. Having a dedicated briefing.* namespace
  // lets us invalidate diff/history caches separately after feedback mutations.
  briefing: {
    all: [QK_VERSION, "briefing"] as const,
    diff: (briefId?: string) =>
      briefId
        ? ([QK_VERSION, "briefing", "diff", briefId] as const)
        : ([QK_VERSION, "briefing", "diff"] as const),
    history: (params?: Readonly<Record<string, unknown>>) =>
      params
        ? ([QK_VERSION, "briefing", "history", params] as const)
        : ([QK_VERSION, "briefing", "history"] as const),
  },

  // ── Market (PRD-0089 W2) ────────────────────────────────────────────────
  // Keys for market-level data that don't belong to a specific instrument
  // or portfolio. Namespaced here so qc.invalidateQueries({ queryKey: qk.market.all })
  // clears all market-level queries at once (e.g. on session reset).
  market: {
    all: [QK_VERSION, "market"] as const,
    // WHY benchmarkSeries: PerformanceChartPanel overlays SPY closes on the
    // portfolio line. Keeping the benchmark key in a dedicated market.* namespace
    // prevents cross-contamination with instrument-detail OHLCV invalidations
    // (which cascade via qk.instruments.detail(id), a different branch).
    // The ticker + period + startDate all participate so:
    //   - different periods cache independently
    //   - the date boundary is captured (prevents stale cache across midnight UTC
    //     — F-DATA-001, QA 2026-05-21)
    benchmarkSeries: (ticker: string, period: string, startDate?: string) =>
      [QK_VERSION, "market", "benchmark-series", ticker, period, startDate ?? ""] as const,
  },

  // ── Shell (PRD-0089 W1) ─────────────────────────────────────────────────
  // Keys owned by the global shell — the IndexStrip in the TopBar, alarm
  // cluster, etc. Kept under their own namespace so they do not pollute the
  // per-page domain namespaces and so a single `qc.invalidateQueries({queryKey:
  // qk.shell.all})` clears every shell-owned query at once (used by RefreshAll
  // and logout).
  shell: {
    all: [QK_VERSION, "shell"] as const,
    // IndexStrip resolves its 10-ticker manifest (SPY / QQQ / IWM / DIA / VIX /
    // TLT / ^TNX / GLD / USO / BTC-USD) to canonical instrument UUIDs once and
    // caches for 30min — entity IDs are immutable per ticker so frequent
    // refetch is wasted bandwidth.
    indexResolveIds: () => [QK_VERSION, "shell", "index", "resolve-ids"] as const,
    // Live batch quotes for the resolved index instrument IDs. 15s cadence
    // matches MarketStatusPill so a single S9 batch call can serve both.
    indexQuotes: (instrumentIds: readonly string[]) =>
      [QK_VERSION, "shell", "index", "quotes", [...instrumentIds].sort()] as const,
  },

  // ── Knowledge Graph entity keys (W7) ────────────────────────────────────
  // WHY separate from instruments.*: KG queries are entity-scoped (any entity
  // type), while instruments.* are instrument-scoped (tradable securities).
  // Keeping them in their own namespace lets a single
  // `qc.invalidateQueries({ queryKey: qk.kg.all })` flush all entity-level
  // detail, intelligence, path, contradiction, and narrative caches at once
  // (e.g., after a full KG pipeline run). The instruments.entityGraph key
  // is kept under instruments.* to preserve the existing cascade behaviour.
  kg: {
    all: [QK_VERSION, "kg"] as const,
    entityDetail: (id: string) =>
      [QK_VERSION, "kg", "entity", id, "detail"] as const,
    intelligence: (id: string) =>
      [QK_VERSION, "kg", "entity", id, "intelligence"] as const,
    // WHY filters in paths key: each unique filter set gets its own cache slot
    // so switching between filter combinations restores from cache instantly.
    paths: (id: string, filters?: PathFilters) =>
      filters
        ? ([QK_VERSION, "kg", "entity", id, "paths", filters] as const)
        : ([QK_VERSION, "kg", "entity", id, "paths"] as const),
    contradictions: (id: string) =>
      [QK_VERSION, "kg", "entity", id, "contradictions"] as const,
    narratives: (id: string) =>
      [QK_VERSION, "kg", "entity", id, "narratives"] as const,
  },

  // ── User ─────────────────────────────────────────────────────────────────
  user: {
    all: [QK_VERSION, "user"] as const,
    profile: () => [QK_VERSION, "user", "profile"] as const,
    notificationPrefs: () => [QK_VERSION, "user", "notification-prefs"] as const,
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
