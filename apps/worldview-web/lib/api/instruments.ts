/**
 * lib/api/instruments.ts — Instruments / Market Data domain.
 *
 * SCOPE: composite instrument bundle, OHLCV bars (single + batch), live quotes
 * (single + batch), and the full fundamentals surface (overview metrics,
 * timeseries, technicals, share statistics, insider transactions, earnings
 * history, splits/dividends, derived snapshot).
 *
 * WHY one file: every method here ultimately resolves through S3 (market-data)
 * or S6 (fundamentals enrichment) and shares the `instrumentId` argument shape.
 * Splitting by sub-domain (quotes vs OHLCV vs fundamentals) would multiply
 * imports without buying isolation — they're already tightly coupled at the
 * backend.
 */

import type {
  CompanyOverview,
  InstrumentPageBundle,
  OHLCVResponse,
  Quote,
  BatchQuoteResponse,
  Fundamentals,
  FundamentalsSnapshot,
  FundamentalsSectionResponse,
  FundamentalsTimeseriesResponse,
} from "@/types/api";
import { apiFetch, GatewayError } from "./_client";

/**
 * FinancialsBundleResponse — structural mirror of the S9
 * `FinancialsBundleResponse` Pydantic model (PLAN-0099 follow-up E).
 *
 * WHY structural (not from `@/types/api`): the generated OpenAPI types
 * have not been re-rolled since this endpoint landed; defining the shape
 * here unblocks callers immediately. Each leg is `unknown | null` because
 * downstream legs preserve their own per-endpoint shapes (`Fundamentals`,
 * `FundamentalsSnapshot`, section envelopes) — the bundle hook narrows
 * them when hydrating per-widget caches.
 *
 * All fields are nullable: a failed downstream leg degrades to `null` so
 * the page renders partial UIs rather than failing whole-tab.
 */
export interface FinancialsBundleResponse {
  fundamentals: unknown | null;
  fundamentals_snapshot: unknown | null;
  income_statement: unknown | null;
  earnings_history: unknown | null;
  share_statistics: unknown | null;
  splits_dividends: unknown | null;
  beat_miss_history: unknown | null;
  fundamentals_timeseries: unknown | null;
}

/**
 * RawFundamentalsSections — minimal structural type for the S3 all-sections
 * payload ({security_id, records:[{section, data, ingested_at}, …]}).
 *
 * WHY structural (not FundamentalsSectionResponse from types/api): the
 * transformer only touches these three fields; accepting the loosest shape
 * lets the financials-bundle hydrator (whose legs are typed `unknown`) call
 * it without lying through a cast to the full generated type.
 */
export interface RawFundamentalsSections {
  security_id?: string;
  records?: Array<Record<string, unknown>>;
}

/**
 * transformFundamentalsSections — S3 all-sections payload → flat Fundamentals.
 *
 * WHY EXPORTED (Round-2 fix, 2026-06-10): this transform used to live inline
 * in getFundamentals(). useFinancialsBundle then hydrated the
 * qk.instruments.fundamentals cache with the bundle's RAW all-sections leg
 * cast to `Fundamentals` — the exact BP-379 wrong-shape-seeding failure: every
 * consumer of that key (DenseMetricsGrid, MetricsTable, KeyStatsBar) read
 * `undefined` for all flat fields until the 1-hour staleTime expired.
 * Exporting the transformer lets the hydrator seed the CORRECT shape from the
 * same single source of truth (no duplicated mapping to drift).
 *
 * Mapping notes (unchanged from the original inline implementation):
 *   - extracts the singleton "highlights", "valuation_ratios",
 *     "technicals_snapshot" and "analyst_consensus" sections;
 *   - derives gross margin (GrossProfitTTM / RevenueTTM) and payout ratio
 *     (DividendShare / EarningsShare) when the inputs are positive;
 *   - balance-sheet ratios stay null (require the snapshot endpoint — BP-369).
 */
export function transformFundamentalsSections(
  raw: RawFundamentalsSections,
  instrumentId: string,
): Fundamentals {
  const num = (v: unknown): number | null => {
    if (v == null || v === "") return null;
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) ? n : null;
  };
  // Extract singleton sections (one record each)
  let hi: Record<string, unknown> = {};
  let vr: Record<string, unknown> = {};
  let ts: Record<string, unknown> = {};
  // Audit 2026-05-09: also extract analyst_consensus (Buy/Hold/Sell/StrongBuy/StrongSell/Rating/TargetPrice)
  // — previously dropped which forced AnalystConsensusStrip to render a hardcoded placeholder.
  let ac: Record<string, unknown> = {};
  let updatedAt: string | null = null;
  for (const rec of raw.records ?? []) {
    const data = (rec["data"] ?? {}) as Record<string, unknown>;
    const section = rec["section"] as string | undefined;
    if (section === "highlights" && !Object.keys(hi).length) { hi = data; updatedAt = rec["ingested_at"] as string ?? null; }
    else if (section === "valuation_ratios" && !Object.keys(vr).length) vr = data;
    else if (section === "technicals_snapshot" && !Object.keys(ts).length) ts = data;
    else if (section === "analyst_consensus" && !Object.keys(ac).length) ac = data;
  }
  const grossMarginTTM = (num(hi["GrossProfitTTM"]) != null && num(hi["RevenueTTM"]) != null && num(hi["RevenueTTM"])! > 0)
    ? num(hi["GrossProfitTTM"])! / num(hi["RevenueTTM"])!
    : null;
  const eps = num(hi["EarningsShare"]);
  const div = num(hi["DividendShare"]);
  const payoutRatio = eps != null && eps > 0 && div != null ? div / eps : null;
  return {
    instrument_id: raw.security_id ?? instrumentId,
    ticker: "",  // populated by overview; FundamentalsTab doesn't render this
    name: "",    // populated by overview
    market_cap:           num(hi["MarketCapitalization"]),
    pe_ratio:             num(hi["PERatio"]),
    forward_pe:           num(vr["ForwardPE"]),
    price_to_book:        num(vr["PriceBookMRQ"]),
    price_to_sales:       num(vr["PriceSalesTTM"]),
    ev_to_ebitda:         num(vr["EnterpriseValueEbitda"]),
    gross_margin:         grossMarginTTM,
    operating_margin:     num(hi["OperatingMarginTTM"]),
    net_margin:           num(hi["ProfitMargin"]),
    roe:                  num(hi["ReturnOnEquityTTM"]),
    roa:                  num(hi["ReturnOnAssetsTTM"]),
    revenue_growth_yoy:   num(hi["QuarterlyRevenueGrowthYOY"]),
    earnings_growth_yoy:  num(hi["QuarterlyEarningsGrowthYOY"]),
    dividend_yield:       num(hi["DividendYield"]),
    payout_ratio:         payoutRatio,
    debt_to_equity:       null, // requires balance-sheet join; populated by snapshot
    current_ratio:        null, // requires balance-sheet join; populated by snapshot
    quick_ratio:          null, // requires balance-sheet join; populated by snapshot
    week_52_high:         num(ts["52WeekHigh"]),
    week_52_low:          num(ts["52WeekLow"]),
    daily_return:         null, // derived from OHLCV; available in overview.fundamentals
    // Analyst consensus — see audit 2026-05-09. Field names match EODHD exactly.
    analyst_strong_buy_count:   num(ac["StrongBuy"]),
    analyst_buy_count:          num(ac["Buy"]),
    analyst_hold_count:         num(ac["Hold"]),
    analyst_sell_count:         num(ac["Sell"]),
    analyst_strong_sell_count:  num(ac["StrongSell"]),
    analyst_rating:             num(ac["Rating"]),
    analyst_target_price:       num(ac["TargetPrice"]),
    updated_at:           updatedAt,
  };
}

export function createInstrumentsApi(t: string | undefined) {
  return {
    /**
     * getCompanyOverview — composite response: fundamentals + OHLCV + news
     * Used by Instrument Detail page for the initial page load
     */
    getCompanyOverview(instrumentId: string): Promise<CompanyOverview> {
      return apiFetch<CompanyOverview>(
        `/v1/companies/${encodeURIComponent(instrumentId)}/overview`,
        { token: t },
      );
    },

    /**
     * getCompanyOverviewsBatch — fan-in N company-overview lookups (FIX F-1).
     *
     * WHY THIS EXISTS: Dashboard widgets (PreMarketMoversWidget,
     * SectorHeatmapWidget, PortfolioSummary) used to spawn N parallel
     * `useQueries` calls — each one a /v1/companies/{id}/overview HTTP
     * round-trip. With 10-20 visible rows that's 10-20 sequential auth checks
     * + downstream fan-outs on the gateway. This batch endpoint POSTs the full
     * id list in a single request; S9 runs the legs in parallel server-side
     * and returns an id-keyed map.
     *
     * RESPONSE SHAPE: `{ overviews: { "<uuid>": CompanyOverview | null } }`.
     * `null` means "this leg failed downstream" — the caller should render a
     * placeholder rather than tripping a global error.
     *
     * WHY return a plain map (not the envelope): callers always immediately
     * `overviewsMap[id]` so unwrapping at the boundary saves boilerplate.
     */
    async getCompanyOverviewsBatch(
      instrumentIds: string[],
    ): Promise<Record<string, CompanyOverview | null>> {
      const resp = await apiFetch<{
        overviews: Record<string, CompanyOverview | null>;
      }>(`/v1/companies/overviews:batch`, {
        token: t,
        method: "POST",
        body: { instrument_ids: instrumentIds },
      });
      return resp.overviews ?? {};
    },

    /**
     * getInstrumentPageBundle — single-round-trip composite for /instruments/[id].
     *
     * PLAN-0059 I-5: collapses the overview-tab waterfall (overview + fundamentals
     * + technicals + insider + top-news) into one HTTP request. The S9 endpoint
     * fans out via asyncio.gather; failed sub-resources degrade to null in the
     * response so the FE can render partial UIs.
     *
     * Children of /instruments/[id] can keep their own per-feature useQuery calls
     * to populate tab-specific surfaces; this bundle covers the OVERVIEW tab's
     * initial paint without requiring those children to be migrated.
     */
    getInstrumentPageBundle(instrumentId: string): Promise<InstrumentPageBundle> {
      return apiFetch<InstrumentPageBundle>(
        `/v1/instruments/${encodeURIComponent(instrumentId)}/page-bundle`,
        { token: t },
      );
    },

    /**
     * getOHLCV — candlestick bars for lightweight-charts
     * timeframe: "5M" | "1H" | "1D" | "1W" | "1M" (frontend convention: uppercase)
     *
     * WHY transform: S3 market-data returns OHLCVListResponse with `items` (not `bars`),
     * `bar_date` (not `timestamp`), and string OHLCV values (not numbers). The frontend
     * OHLCVBar type expects `timestamp: string` and numeric open/high/low/close. Transform
     * here at the gateway boundary so components stay decoupled from S3's schema.
     *
     * WHY lowercase timeframe before sending: S3 accepts "1d"/"1h"/"5m"/"1w" (lowercase)
     * BUT "1M" (uppercase M) for monthly — S3's Timeframe.ONE_MONTH = "1M" is
     * case-sensitive. Simple toLowerCase() would produce "1m" which S3 rejects.
     * The chart sends "5M"/"1H"/"1D"/"1W"/"1M" (uppercase frontend convention).
     * Normalize here so S3 doesn't return 422.
     */
    async getOHLCV(
      instrumentId: string,
      // WHY `limit` (added Wave-4, 2026-06-12): S3's OHLCV endpoint caps the
      // result at 200 bars when no limit is given. The chart's default daily
      // view wants the full ~500-bar history (so panning back has data), so it
      // passes an explicit high limit. Other callers omit it and keep the
      // 200-bar default. The value is sent as a query-string `limit=`.
      params: { timeframe?: string; start?: string; end?: string; limit?: number } = {},
    ): Promise<OHLCVResponse> {
      // WHY special-case "1M": S3's Timeframe enum is case-sensitive.
      // All timeframes are lowercase EXCEPT ONE_MONTH which is "1M" (uppercase M).
      // Frontend sends "1M" (its own uppercase convention), which happens to match
      // S3's expected casing — so we preserve it. Everything else lowercases normally.
      const normalizeTimeframe = (tf: string): string =>
        tf === "1M" ? "1M" : tf.toLowerCase();

      const normalized = {
        ...params,
        ...(params.timeframe ? { timeframe: normalizeTimeframe(params.timeframe) } : {}),
      };
      const qs = new URLSearchParams(
        Object.entries(normalized).filter(([, v]) => v != null) as [string, string][],
      ).toString();

      // WHY raw type: apiFetch would cast to OHLCVResponse directly, bypassing transform
      const raw = await apiFetch<{
        items: Array<{
          bar_date: string;
          open: string;
          high: string;
          low: string;
          close: string;
          volume: number | null;
        }>;
        total: number;
        timeframe: string;
      }>(`/v1/ohlcv/${encodeURIComponent(instrumentId)}${qs ? `?${qs}` : ""}`, { token: t });

      return {
        instrument_id: instrumentId,
        ticker: "",
        // Keep the frontend's uppercase convention in the response
        timeframe: (params.timeframe ?? "1D").toUpperCase(),
        bars: (raw.items ?? []).map((item) => ({
          timestamp: item.bar_date,
          open: parseFloat(item.open),
          high: parseFloat(item.high),
          low: parseFloat(item.low),
          close: parseFloat(item.close),
          volume: item.volume ?? 0,
        })),
      };
    },

    /**
     * getQuote — live quote for a single instrument (5s Valkey cache on S9)
     */
    getQuote(instrumentId: string): Promise<Quote> {
      return apiFetch<Quote>(
        `/v1/quotes/${encodeURIComponent(instrumentId)}`,
        { token: t },
      );
    },

    /**
     * getBatchQuotes — prices for multiple instruments at once
     * Used by: Sidebar watchlist (30s refetch), Portfolio page, TopBar index tickers
     * Body: { instrument_ids: string[] } — field name matches BatchQuoteRequest Pydantic model
     *
     * WHY 404 fallback (INC-004 / FR-8.3): mirrors the getBatchOhlcvBars pattern.
     * If the batch endpoint is missing (deployment drift or old backend), we fall back
     * to per-instrument single-quote calls and merge results into the same
     * BatchQuoteResponse shape. This means callers never need to handle "no batch"
     * as a special case — the response shape is identical.
     *
     * WHY only 404: a missing endpoint is deployment drift; any other error (5xx, 401)
     * should propagate so the caller can surface it to the user.
     */
    async getBatchQuotes(ids: string[]): Promise<BatchQuoteResponse> {
      try {
        return await apiFetch<BatchQuoteResponse>("/v1/quotes/batch", {
          method: "POST",
          body: { instrument_ids: ids },
          token: t,
        });
      } catch (err) {
        // WHY only 404: missing endpoint → degrade gracefully. Other errors propagate.
        if (err instanceof GatewayError && err.status === 404) {
          // WHY Promise.allSettled: a per-instrument fetch may 404 for an individual
          // symbol (recently delisted) — we want the successes, not an all-or-nothing.
          const settled = await Promise.allSettled(
            ids.map((id) =>
              apiFetch<Quote>(`/v1/quotes/${encodeURIComponent(id)}`, { token: t }),
            ),
          );
          // WHY Record<string, Quote> accumulator: BatchQuoteResponse wraps quotes in
          // a { quotes: Record<string, Quote> } envelope — build the inner map first.
          const quotesMap: Record<string, Quote> = {};
          settled.forEach((result, idx) => {
            if (result.status === "fulfilled") {
              // WHY index into ids: the settled array preserves the same order as ids.
              const id = ids[idx];
              if (id !== undefined) {
                quotesMap[id] = result.value;
              }
            }
          });
          return { quotes: quotesMap };
        }
        throw err;
      }
    },

    /**
     * getBatchOhlcvBars — fetch recent OHLCV bars for many instruments at once.
     *
     * WHY THIS EXISTS (PLAN-0051 T-B-2-09): the screener renders an inline
     * 30-day sparkline per row. N parallel /v1/ohlcv calls would mean 50+
     * round-trips for a default page — way too slow. This batch endpoint is
     * one round-trip for up to ~100 instruments (PLAN-0049 T-A-1-05).
     *
     * WHY a 404 fallback to per-instrument calls: if a deployment drifts and
     * the batch endpoint is missing, the screener still works at degraded
     * performance instead of breaking entirely.
     *
     * RESPONSE SHAPE: { results: [{ instrument_id, bars: OHLCVBar[] }, ...] }
     */
    async getBatchOhlcvBars(params: {
      instrument_ids: string[];
      timeframe?: string;
      limit?: number;
    }): Promise<{ results: Array<{ instrument_id: string; bars: OHLCVResponse["bars"] }> }> {
      // WHY normalize lowercase: S3 enum values are lowercase ("1d"/"1h"). The
      // single-instrument getOHLCV does the same normalization.
      const tf = (params.timeframe ?? "1d").toLowerCase();
      const body = {
        requests: params.instrument_ids.map((id) => ({
          instrument_id: id,
          timeframe: tf,
          limit: params.limit ?? 30,
        })),
      };

      try {
        const raw = await apiFetch<{
          results: Array<{
            instrument_id: string;
            items: Array<{
              bar_date: string;
              open: string;
              high: string;
              low: string;
              close: string;
              volume: number | null;
            }>;
          }>;
        }>("/v1/ohlcv/batch", {
          method: "POST",
          body,
          token: t,
        });
        return {
          results: (raw.results ?? []).map((r) => ({
            instrument_id: r.instrument_id,
            bars: (r.items ?? []).map((item) => ({
              timestamp: item.bar_date,
              open: parseFloat(item.open),
              high: parseFloat(item.high),
              low: parseFloat(item.low),
              close: parseFloat(item.close),
              volume: item.volume ?? 0,
            })),
          })),
        };
      } catch (err) {
        // WHY only 404: missing endpoint → degrade. Other errors propagate.
        if (err instanceof GatewayError && err.status === 404) {
          // WHY inline (not this.getOHLCV): destructured calls would lose `this`.
          const limit = params.limit ?? 30;
          const tfNorm = params.timeframe ?? "1D";
          const tfPath = tfNorm === "1M" ? "1M" : tfNorm.toLowerCase();
          const results = await Promise.all(
            params.instrument_ids.map(async (id) => {
              try {
                const raw = await apiFetch<{
                  items: Array<{
                    bar_date: string;
                    open: string;
                    high: string;
                    low: string;
                    close: string;
                    volume: number | null;
                  }>;
                }>(`/v1/ohlcv/${encodeURIComponent(id)}?timeframe=${tfPath}`, { token: t });
                const bars = (raw.items ?? []).slice(-limit).map((item) => ({
                  timestamp: item.bar_date,
                  open: parseFloat(item.open),
                  high: parseFloat(item.high),
                  low: parseFloat(item.low),
                  close: parseFloat(item.close),
                  volume: item.volume ?? 0,
                }));
                return { instrument_id: id, bars };
              } catch {
                return { instrument_id: id, bars: [] };
              }
            }),
          );
          return { results };
        }
        throw err;
      }
    },

    /**
     * getFundamentals — all fundamental metrics for an instrument.
     * Used by Instrument Detail → Fundamentals tab.
     *
     * WHY transformer: S3 returns {security_id, records: [{section, data}]} but
     * FundamentalsTab expects a flat Fundamentals object (market_cap, pe_ratio…).
     * The transformer extracts the singleton "highlights", "valuation_ratios", and
     * "technicals_snapshot" sections and assembles the flat shape. Fields that
     * require time-series joins (debt_to_equity, current_ratio) return null until
     * the backfill populates the snapshot table. (BP-369)
     */
    async getFundamentals(instrumentId: string): Promise<Fundamentals> {
      const raw = await apiFetch<{ security_id: string; records: Array<Record<string, unknown>> }>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}`,
        { token: t },
      );
      // WHY delegate: the section→flat mapping is shared with the
      // financials-bundle cache hydrator (useFinancialsBundle) — see
      // transformFundamentalsSections above for the full mapping rationale.
      return transformFundamentalsSections(raw, instrumentId);
    },

    /**
     * getFundamentalsTimeseries — single-metric time series for sparklines
     *
     * WHY no auth: S9 route /v1/fundamentals/timeseries is a public endpoint —
     * it issues a system JWT internally (not a user JWT). No Bearer token sent.
     *
     * WHY instrument_id + metric as query params (not path): the S3 endpoint
     * is designed as a filter over the fundamentals_metrics table, not a
     * resource path. Multiple instruments or metrics could be fetched with the
     * same route shape.
     *
     * Used by: FundamentalSparkline (Overview sidebar panels + Fundamentals tab inline charts)
     * Default limit of 20 gives enough points for a sparkline without over-fetching.
     */
    getFundamentalsTimeseries(
      instrumentId: string,
      metric: string,
      params?: {
        start_date?: string;
        end_date?: string;
        period_type?: string;
        limit?: number;
        // order: 'asc' returns the oldest N rows, 'desc' returns the most recent N
        // (DESC is what UI charts almost always want — see audit 2026-04-28 / BP-261).
        // Returned data is always chronologically ascending regardless of order.
        order?: "asc" | "desc";
      },
    ): Promise<FundamentalsTimeseriesResponse> {
      // WHY URLSearchParams with conditional spread: filters out undefined values so
      // optional params don't appear as "undefined" strings in the query string.
      const qs = new URLSearchParams({
        instrument_id: instrumentId,
        metric,
        ...(params?.start_date ? { start_date: params.start_date } : {}),
        ...(params?.end_date ? { end_date: params.end_date } : {}),
        ...(params?.period_type ? { period_type: params.period_type } : {}),
        ...(params?.limit != null ? { limit: String(params.limit) } : {}),
        ...(params?.order ? { order: params.order } : {}),
      });
      return apiFetch<FundamentalsTimeseriesResponse>(
        `/v1/fundamentals/timeseries?${qs.toString()}`,
        {}, // no auth — public endpoint uses system JWT internally
      );
    },

    /**
     * getTechnicals — technical indicators snapshot from S3
     *
     * WHY /technicals (not /technicals-snapshot): S9 exposes the shortened path.
     * S3 internally stores this as "technicals_snapshot" section.
     * Used by: TechnicalSnapshot component (Wave D-3), OverviewSidebarMetrics (Wave C-1)
     */
    getTechnicals(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/technicals`,
        { token: t },
      );
    },

    /**
     * getShareStatistics — share count and ownership percentages from S3
     *
     * Data fields: shares_outstanding, shares_float, percent_insiders, percent_institutions.
     * Cast records[0].data to ShareStatisticsData for typed access.
     * Used by: OwnershipSnapshotPanel (Wave D-2)
     */
    getShareStatistics(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/share-statistics`,
        { token: t },
      );
    },

    /**
     * getInsiderTransactions — recent insider buys/sells from S3
     *
     * Returns records with section="insider_transactions_snapshot". Each record's
     * data array contains individual transactions (date, owner_name, type, shares, value).
     * Used by: InsiderTransactionsTable (Wave D-3)
     */
    getInsiderTransactions(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/insider-transactions`,
        { token: t },
      );
    },

    /**
     * getEarningsHistory — historical EPS actuals from S3 (ANNUAL records)
     *
     * WHY /earnings-annual-trend (not /earnings-trend): The S9 /earnings-trend
     * endpoint maps to EODHD's EarningsTrend section which contains FORWARD-LOOKING
     * analyst consensus estimates (period "+1q", "+1y") — not historical actuals.
     * The /earnings-annual-trend endpoint contains historical per-fiscal-year EPS
     * actuals stored as `{date: "YYYY-MM-DD", epsActual: N}` records. This is what
     * analysts need to see the multi-year EPS growth trajectory (the primary input
     * for P/E target valuation). Live data confirms: 33 historical annual EPS records
     * for AAPL from /earnings-annual-trend vs 0 records from the timeseries endpoint.
     * Used by: EarningsHistoryChart (Wave D-3)
     */
    getEarningsHistory(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/earnings-annual-trend`,
        { token: t },
      );
    },

    /**
     * getSplitsDividends — stock split and dividend history from S3
     *
     * Returns records with section="splits_dividends". Contains forward and
     * historical split ratios, dividend dates, and ex-dividend dates.
     * Used by: FundamentalsTab (Wave D-1 splits section), future D-3 enrichment
     */
    getSplitsDividends(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/splits-dividends`,
        { token: t },
      );
    },

    /**
     * getFundamentalsSnapshot — pre-computed derived metrics snapshot from S3
     *
     * WHY SEPARATE FROM getFundamentals: The main getFundamentals call returns
     * fields assembled from EODHD highlights/technicals JSONB sections (market cap,
     * P/E, margins). This snapshot contains 10 additional derived metrics that
     * require multi-section joins (FCF = operating_cf - |capex|, interest coverage
     * = ebit / interest_expense, net debt/EBITDA, beta, avg_volume_30d, eps_ttm).
     * Pre-computing these at backfill time keeps the API response fast and avoids
     * complex JSONB arithmetic in hot query paths.
     *
     * WHY NO 404: S3 always returns 200 for this endpoint — all fields are null
     * when the instrument hasn't been through the backfill yet (e.g. newly-listed
     * stocks, ETFs with no cash flow statements). The frontend shows "—" for nulls.
     *
     * Used by: InstrumentKeyMetrics (EPS TTM, Beta, Avg Volume rows),
     *          FundamentalsTab Cash Flow section + Debt & Credit section.
     * PLAN-0050 Wave D (T-D-4-04).
     */
    getFundamentalsSnapshot(instrumentId: string): Promise<FundamentalsSnapshot> {
      return apiFetch<FundamentalsSnapshot>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/snapshot`,
        { token: t },
      );
    },

    /**
     * getIncomeStatement — annual income-statement records from S3
     *
     * Returns FundamentalsResponse with period_type=ANNUAL records. Each record's
     * data dict contains income-statement fields: totalRevenue, grossProfit,
     * operatingIncome, netIncome, ebitda, eps, etc. (EODHD PascalCase keys).
     *
     * Used by: IncomeStatementFY (PLAN-0088 Wave G-1) — Finviz-style FY-column
     * table showing the last 4 fiscal years of key P&L metrics.
     *
     * WHY separate from getFundamentals: the main getFundamentals call returns
     * TTM point-in-time snapshots (highlights section). This endpoint returns
     * per-fiscal-year actuals from the income_statement section — a different
     * data shape (array of periods, not a single snapshot).
     */
    getIncomeStatement(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/income-statement`,
        { token: t },
      );
    },

    /**
     * getFinancialsBundle — PLAN-0099 follow-up E single-RTT composite for the
     * Financials tab.
     *
     * WHY THIS EXISTS: Opening the Financials tab cold previously fired ~8
     * unique S9 round-trips (fundamentals, snapshot, income-statement,
     * earnings history, technicals, share statistics, splits/dividends,
     * plus per-panel beat-miss-history + fundamentals-timeseries). Each
     * goes through S9 auth + internal-JWT issuance, so the page was
     * wave-serialized by the slowest leg.
     *
     * The bundle endpoint fans these legs out in parallel server-side and
     * returns a composite object. The matching `useFinancialsBundle` hook
     * (see ../../components/instrument/hooks/) pre-warms each per-widget
     * TanStack cache key via `queryClient.setQueryData(...)` so existing
     * child components (`BeatMissHistoryPanel`, `IncomeStatementTable`,
     * etc.) hit warm cache instead of refetching.
     *
     * WHY POST (not GET): symmetric with `/v1/companies/overviews:batch`.
     * The endpoint is resource-composition, not a simple resource fetch.
     *
     * WHY response typed as a structural interface (not generated types):
     * the generated types haven't been re-rolled for this endpoint yet —
     * keeping the structural interface here lets callers use the bundle
     * today without waiting for `pnpm generate-types`. Each leg is `unknown`
     * because the bundle simply forwards the underlying S3 response shapes
     * which the per-widget hooks already type at hydration time.
     */
    getFinancialsBundle(instrumentId: string): Promise<FinancialsBundleResponse> {
      return apiFetch<FinancialsBundleResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/financials-bundle`,
        { token: t, method: "POST" },
      );
    },

    // ── T-02 W3 additions ─────────────────────────────────────────────────

    /**
     * getInstitutionalHolders — top 10 institutional holders from S3
     *
     * WHY T-02: PLAN-0089 W3 adds an InstitutionalHoldersTable to the Financials
     * tab. The data lives in EODHD's InstitutionHolders section — Vanguard,
     * BlackRock, State Street etc. Analysts use this to gauge passive-vs-active
     * ownership concentration and predict sell-off behaviour (passive holders
     * can't exit quickly; concentrated hedge fund ownership amplifies moves).
     *
     * Returns FundamentalsSection with section="institutional_holders_snapshot".
     * The `data` dict is {"0": {name, currentShares, currentValue, ...}, "1": ...}.
     * S9 route added in T-S9-01 (PLAN-0089 W3).
     */
    getInstitutionalHolders(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/institutional-holders`,
        { token: t },
      );
    },

    /**
     * getFundHolders — top 10 mutual/ETF fund holders from S3
     *
     * WHY T-02: Mirrors getInstitutionalHolders but for fund-level holders
     * (e.g. Fidelity 500 Index Fund). Fund holders often indicate passive ETF
     * inflow; institutional holders are more likely to be active managers.
     * Knowing the split helps analysts model price-insensitive vs price-sensitive
     * flows (important for estimating liquidity around rebalancing dates).
     *
     * Returns FundamentalsSection with section="fund_holders_snapshot".
     * S9 route added in T-S9-02 (PLAN-0089 W3).
     */
    getFundHolders(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/fund-holders`,
        { token: t },
      );
    },

    /**
     * getPeers — 5 closest peers by market cap in the same GICS industry
     *
     * WHY T-02: PeerComparisonTable (T-12) lets analysts benchmark valuation
     * ratios (P/E, P/B, EV/EBITDA) against same-industry peers in one row.
     * This is the primary workflow for relative-value equity analysis:
     * "AAPL at 28× P/E vs MSFT at 35×; who is cheap?"
     *
     * WHY /v1/instruments/{id}/peers (not /v1/fundamentals): peers are derived
     * from the instruments table (gics_sector + market_cap ranking) not from
     * EODHD fundamentals. The S2 market-data service owns this query.
     *
     * Returns { instrument_id, peers: PeerInstrument[] } with 1Y return included.
     * S9 route T-S9-03 was shipped in W5 (feat(w5): T-S9-01).
     */
    getPeers(instrumentId: string, n = 5): Promise<PeersResponse> {
      return apiFetch<PeersResponse>(
        `/v1/instruments/${encodeURIComponent(instrumentId)}/peers?n=${n}`,
        { token: t },
      );
    },

    // ── Quote-tab Wave-1 endpoints (2026-06 backend; live-verified shapes) ──

    /**
     * getIntradayStats — current session O / H / L / VWAP / volume from the
     * intraday bar store (richer than the last OHLCV bar: includes prev_close,
     * VWAP with its source resolution, and volume vs 30-day-average ratio).
     *
     * UNITS: volume_vs_30d_ratio is a plain ratio (1.0 = exactly the 30-day
     * average partial-day volume). vwap_source tags the bar resolution VWAP
     * was computed from ("1m" / "5m" / "1h") — surfaced as a tooltip so the
     * analyst knows the precision of the number.
     */
    getIntradayStats(instrumentId: string): Promise<IntradayStatsResponse> {
      return apiFetch<IntradayStatsResponse>(
        `/v1/instruments/${encodeURIComponent(instrumentId)}/intraday-stats`,
        { token: t },
      );
    },

    /**
     * getMultiPeriodReturns — trailing returns for 1D…5Y in ONE round-trip.
     *
     * UNITS (live-verified 2026-06-10): values are PERCENT-FORM numbers
     * (-7.9289 means -7.93%), NOT decimals — render with formatPercentDirect.
     * Horizons with insufficient price history (e.g. 3Y/5Y for dev data that
     * only has ~1.5y of bars) come back null → the strip renders "—".
     */
    getMultiPeriodReturns(instrumentId: string): Promise<MultiPeriodReturnsResponse> {
      return apiFetch<MultiPeriodReturnsResponse>(
        `/v1/instruments/${encodeURIComponent(instrumentId)}/returns`,
        { token: t },
      );
    },

    /**
     * getPriceLevels — 52-week range position, MA50/MA200, prior-session
     * high/low and fractal swing-point support/resistance levels.
     *
     * UNITS: pct_from_52w_high / pct_from_52w_low are percent-form
     * (-7.93 = 7.93% below the high). support[]/resistance[] are price
     * arrays nearest-first; sr_method is a human-readable description of the
     * algorithm — surfaced as a tooltip on the S/R chips so the levels are
     * auditable rather than magic numbers.
     */
    getPriceLevels(instrumentId: string): Promise<PriceLevelsResponse> {
      return apiFetch<PriceLevelsResponse>(
        `/v1/instruments/${encodeURIComponent(instrumentId)}/price-levels`,
        { token: t },
      );
    },

    /**
     * triggerInstrumentBriefingGeneration — lazy-generate POST for AIBriefPanel
     *
     * WHY T-02: The AIBriefPanel (T-22) uses a GET→404→POST→poll flow (Δ16 / Δ19):
     * on 404 (brief not yet generated), fire this POST to queue generation.
     * The backend is idempotent (one brief per instrument per 60-min window).
     * After POST, the hook polls GET every 30s up to 5 times until the brief appears.
     *
     * WHY separate from getInstrumentBrief: the POST is not a read — it mutates
     * backend state (enqueues a generation job). Keeping it separate makes it
     * clear at the call site that this is a lazy mutation, not a standard query.
     *
     * S9 + S8 route shipped in W5 (T-S8-05).
     */
    triggerInstrumentBriefingGeneration(entityId: string): Promise<void> {
      return apiFetch<void>(
        `/v1/briefings/instrument/${encodeURIComponent(entityId)}/generate`,
        { token: t, method: "POST" },
      );
    },
  };
}

// ── W3 type additions ─────────────────────────────────────────────────────────

/**
 * PeerInstrument — one row in the peers response.
 *
 * WHY separate type (not in types/api.ts): peers are a new W3 shape; adding
 * to the generated-types file would require re-rolling the generation script.
 * This structural interface unblocks callers immediately and can be moved to
 * types/api.ts in a future cleanup pass.
 *
 * WHY return_1y optional: the S2 query computes it from OHLCV; if no bars
 * exist for a peer (newly listed, delisted) the field is omitted.
 */
export interface PeerInstrument {
  instrument_id: string;
  ticker: string;
  name: string;
  /** Trailing 12-month P/E; null = no earnings / not computed. */
  pe_ratio: number | null;
  market_cap: number | null;
  /** 1-year price return as a DECIMAL (0.18 = +18%). null = insufficient history. */
  return_1y: number | null;
  /**
   * Day change in PERCENT FORM (1.61 = +1.61%) — note the unit mismatch with
   * return_1y (decimal). Live-verified 2026-06-10; render with
   * formatPercentDirect, NOT formatPercent.
   */
  change_pct?: number | null;
  /** Last traded/close price in USD. */
  last_price?: number | null;
  gics_sector?: string | null;
}

export interface PeersResponse {
  instrument_id: string;
  /** GICS industry label the peer set was drawn from (e.g. "Technology"). */
  industry?: string | null;
  peers: PeerInstrument[];
}

// ── Quote-tab Wave-1 response shapes (structural; live-verified 2026-06-10) ──
//
// WHY structural interfaces here (not types/api.ts): same rationale as
// PeerInstrument above — these endpoints are new and the generated-types file
// hasn't been re-rolled. Keeping them next to their fetchers also documents
// the unit quirks (percent-form vs decimal) at the point of use.

/** GET /v1/instruments/{id}/intraday-stats */
export interface IntradayStatsResponse {
  instrument_id: string;
  session_date: string;            // ISO date of the session the stats cover
  open: number | null;
  prev_close: number | null;
  day_high: number | null;
  day_low: number | null;
  vwap: number | null;
  /** Bar resolution VWAP was computed from ("1m" / "5m" / "1h"). */
  vwap_source: string | null;
  volume: number | null;
  /** Session volume ÷ 30-day average (1.0 = average). */
  volume_vs_30d_ratio: number | null;
}

/** The 9 return horizons the backend computes, in display order. */
export const RETURN_HORIZONS = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y"] as const;
export type ReturnHorizon = (typeof RETURN_HORIZONS)[number];

/** GET /v1/instruments/{id}/returns — values are PERCENT-FORM, null = insufficient history. */
export interface MultiPeriodReturnsResponse {
  instrument_id: string;
  as_of: string;
  returns: Partial<Record<ReturnHorizon, number | null>>;
}

/** GET /v1/instruments/{id}/price-levels */
export interface PriceLevelsResponse {
  instrument_id: string;
  as_of: string;
  last_close: number | null;
  high_52w: number | null;
  low_52w: number | null;
  /** Percent-form distance from the 52w high (negative = below). */
  pct_from_52w_high: number | null;
  /** Percent-form distance from the 52w low (positive = above). */
  pct_from_52w_low: number | null;
  ma_50: number | null;
  ma_200: number | null;
  prior_session_high: number | null;
  prior_session_low: number | null;
  /** Nearest swing-low prices below last close (nearest first). */
  support: number[];
  /** Nearest swing-high prices above last close (nearest first). */
  resistance: number[];
  /** Human-readable description of the S/R algorithm — chip tooltip. */
  sr_method: string | null;
}
